"""Optional real-data check for the skeleton binding.

Run: blender -b --factory-startup --python-exit-code 1 -P tools/test_skeleton_real_pack_blender.py

The fixture is the reverse output that exposed the original defects. The test is
skipped when the folder is unavailable, so it never blocks a machine that does
not have the user's MMT cache. Set MIMI_REAL_REVERSE to point at another pack.

What it pins down:

- the pack writes ``Length: 0.004`` for bones that are 25-45 cm long, so the
  helper must fall back to the geometric child distance;
- a single DrawIB has one palette, so the app's camelCase "boneToGroup" must
  produce numeric bones and keep the vertex groups numeric;
- one palette slot of the body has no bone, which must be reported together
  with the number of weights that stay in bind pose;
- the rig must still deform the mesh, so a silently unbound model cannot pass.

The scene is never saved and no file of the pack is modified.
"""
import importlib
import json
import os
import sys
import unittest
from pathlib import Path

import bpy
import numpy

# Load the repository under test, never an installed add-on copy.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()

from MIMIBlender.common.mmt_import_helper import MMTImportHelper
from MIMIBlender.utils.skeleton_helper import SkeletonHelper

# Development pack: Aether Gazer Jane Maid. Overridable for other machines.
REAL_REVERSE = Path(os.environ.get(
    "MIMI_REAL_REVERSE",
    r"D:\MMTCacheFolder\Reversed\Jane Maid(Aether Gazer-Parvati)",
))


def clear_scene():
    """Remove the data a previous test created, so tests never share state."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for armature in list(bpy.data.armatures):
        if armature.users == 0:
            bpy.data.armatures.remove(armature)


def import_drawib(folder_name, collection):
    """Import the first data type folder of one DrawIB and return its data.

    Only one candidate data type is imported: every candidate carries the same
    skeleton and geometry, and importing all of them would triple the runtime.
    """
    folder = REAL_REVERSE / folder_name
    json_names = sorted(name for name in os.listdir(str(folder)) if name.lower().endswith(".json"))
    before = set(bpy.data.objects)
    MMTImportHelper.create_mesh_from_json(
        json_file_path=str(folder / json_names[0]),
        import_collection=collection,
        submesh_name_prefix=folder_name,
    )
    objects = [obj for obj in bpy.data.objects if obj not in before]
    with open(str(folder / json_names[0]), encoding="utf-8") as handle:
        block = json.load(handle).get("Skeleton")
    return objects, block


@unittest.skipUnless(REAL_REVERSE.is_dir(), "optional real reverse output is unavailable")
class RealPackTests(unittest.TestCase):
    """Bind the real pack and check lengths, naming, report and deformation."""

    def setUp(self):
        clear_scene()

    def tearDown(self):
        clear_scene()

    def test_body_binds_with_geometric_lengths(self):
        collection = bpy.data.collections.new("real_pack")
        bpy.context.scene.collection.children.link(collection)
        objects, block = import_drawib("ba4255a5", collection)

        warnings = []
        summary = SkeletonHelper.apply_groups(
            "SIDECAR",
            {"ba4255a5": objects},
            str(REAL_REVERSE / "skeleton.json"),
            "NONE",
            import_mirror=False,
            skeletons={"ba4255a5": block},
            collection=collection,
            warnings=warnings,
        )
        print("SUMMARY:", summary)

        armature = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE")
        # The armature belongs to the collection the import created.
        self.assertIn(armature.name, collection.objects)

        # The pack writes a 4 mm placeholder for these bones, so the display
        # length must come from the geometry instead of the sidecar value.
        bone_names = [bone["Name"] for bone in block["Bones"]]
        lengths = SkeletonHelper._bone_lengths(block["Bones"])
        for name, minimum in (
            ("Bip001 L Thigh", 0.2),
            ("Bip001 L Calf", 0.35),
            ("Bip001 L Forearm", 0.15),
        ):
            self.assertIn(name, bone_names)
            self.assertGreater(lengths[bone_names.index(name)], minimum, name)

        # One DrawIB, one palette: the app asks for numeric bones. The expected
        # count follows the palette the pack wrote, because a hard-coded number
        # goes stale as soon as the pack gains or loses a slot.
        palette_names = {str(name) for name in (block["BoneMap"] or {}).values()}
        expected_numeric = {name for name in palette_names if name in bone_names}
        numeric = [bone.name for bone in armature.data.bones if bone.name.isdigit()]
        self.assertTrue(expected_numeric)
        self.assertEqual(len(numeric), len(expected_numeric))
        self.assertTrue(all(group.name.isdigit() for obj in objects for group in obj.vertex_groups))
        # The longest bone proves the placeholder did not win in the armature
        # either: before the fix every bone stayed below 0.15.
        self.assertGreater(max(bone.length for bone in armature.data.bones), 0.35)

        # The body palette has a slot without a bone, which must be reported.
        self.assertIn("without a bone", summary)
        self.assertTrue(warnings)

        # A rig that silently lost its weights would still pass the checks above,
        # so one posed bone must move the geometry.
        thigh = armature.data.bones.get("2")
        self.assertIsNotNone(thigh)
        meshes = [obj for obj in objects if obj.type == "MESH"
                  and any(mod.type == "ARMATURE" and mod.object == armature for mod in obj.modifiers)]
        self.assertTrue(meshes)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        before = {}
        for obj in meshes:
            evaluated = obj.evaluated_get(depsgraph)
            coords = numpy.empty(len(evaluated.data.vertices) * 3, dtype=numpy.float32)
            evaluated.data.vertices.foreach_get("co", coords)
            before[obj.name] = coords.reshape(-1, 3).copy()

        pose_bone = armature.pose.bones.get(thigh.name)
        pose_bone.rotation_mode = "XYZ"
        pose_bone.rotation_euler = (0.7, 0.0, 0.0)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        moved = 0
        for obj in meshes:
            evaluated = obj.evaluated_get(depsgraph)
            coords = numpy.empty(len(evaluated.data.vertices) * 3, dtype=numpy.float32)
            evaluated.data.vertices.foreach_get("co", coords)
            delta = numpy.linalg.norm(coords.reshape(-1, 3) - before[obj.name], axis=1)
            moved += int((delta > 1e-5).sum())
        self.assertGreater(moved, 100)


def main():
    """Run the real pack test and fail the Blender process when it breaks."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RealPackTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("RESULT " + json.dumps({"tests": result.testsRun, "success": result.wasSuccessful()}))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
