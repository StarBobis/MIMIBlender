"""Regression checks for the repaired skeleton binding.

Run: blender -b --factory-startup --python-exit-code 1 -P tools/test_skeleton_bind_repair_blender.py

Every case locks one defect that used to fail silently on real reverse output:

- the desktop app writes ``NamingMode`` in camelCase, which never met the
  upper-case helper constants, so "Follow MMT" always renamed the vertex groups;
- packs write a 4 mm placeholder ``Length`` for bones that are 40 cm long, and
  ``min()`` over the children also counted helper bones sitting on the parent,
  which turned every main bone into an invisible dot;
- a palette slot without a bone used to freeze its weights without a word;
- a workspace object is named ``LOD0.<DrawIB>-<N>``, so the "Component N" text
  the binder used to parse is gone and every mesh was skipped from the binding;
- two DrawIBs of one character can carry completely different palettes, which
  used to force silent group renaming; each palette now gets its own armature.

The fixtures are synthetic so this file runs on every machine; the optional real
pack test at the end is skipped when the folder is unavailable.
"""
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

import bpy

# Load just the helper module, so the test does not need the updater or the UI.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("MIMIBlender")
package.__path__ = [str(ROOT)]
sys.modules["MIMIBlender"] = package
helper_module = importlib.import_module("MIMIBlender.utils.skeleton_helper")
SkeletonHelper = helper_module.SkeletonHelper


def rest_matrix(x=0.0, z=0.0):
    """Row-major rest matrix with the translation in the fourth column."""
    return [
        1.0, 0.0, 0.0, x,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, z,
        0.0, 0.0, 0.0, 1.0,
    ]


def make_mesh(name, group_weights):
    """Create a one-triangle mesh whose vertices carry the given group weights.

    group_weights: [(group name, [vertex index, ...]), ...]; each listed vertex
    receives weight 1.0 in that group.
    """
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for group_name, indices in group_weights:
        obj.vertex_groups.new(name=group_name).add(indices, 1.0, "REPLACE")
    return obj


def bound_armature(obj):
    """Return the armature of one mesh.

    The tests share one scene, so looking up "the first armature" would return
    the rig of an earlier test instead of the one this case created.
    """
    return next(modifier.object for modifier in obj.modifiers if modifier.type == "ARMATURE")


def drawib_block(bones, bone_map, naming="boneToGroup", components=None, hash_value="h1"):
    """Build one embedded skeleton block in the shape the desktop app writes."""
    block = {
        "Version": 1,
        "Hash": hash_value,
        "CharacterId": "char_" + hash_value,
        "CharacterName": "Character " + hash_value,
        "NamingMode": naming,
        "Space": {"Scale": 1.0, "RotationZ": 0.0, "MatchMirrorX": False},
        "Bones": bones,
        "BoneMap": bone_map,
    }
    if components is not None:
        block["Components"] = components
    return block


def sidecar_file(folder, payload):
    """Write a sidecar payload into folder and return its path."""
    path = os.path.join(folder, "skeleton.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


class NamingModeTests(unittest.TestCase):
    """The app writes camelCase, the helper compares constants."""

    def test_camel_case_bone_to_group_renames_bones(self):
        # One DrawIB means no palette conflict can mask the naming bug.
        mesh = make_mesh("naming-Component 0", [("0", [0, 1, 2]), ("1", [0])])
        block = drawib_block(
            [
                {"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
                {"Name": "Spine", "Parent": 0, "Rest": rest_matrix(z=0.2), "Length": 0.2},
            ],
            {"0": "Root", "1": "Spine"},
            naming="boneToGroup",
        )
        summary = SkeletonHelper.apply_groups(
            "SIDECAR", {"naming": [mesh]}, "", "NONE",
            import_mirror=False, skeletons={"naming": block},
        )
        armature = bound_armature(mesh)
        self.assertEqual(sorted(bone.name for bone in armature.data.bones), ["0", "1"])
        self.assertIn("naming Rename Bones", summary)

    def test_camel_case_group_to_bone_renames_groups(self):
        mesh = make_mesh("groupmode-Component 0", [("0", [0, 1, 2])])
        block = drawib_block(
            [{"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2}],
            {"0": "Root"},
            naming="groupToBone",
            hash_value="h2",
        )
        SkeletonHelper.apply_groups(
            "SIDECAR", {"group": [mesh]}, "", "NONE",
            import_mirror=False, skeletons={"group": block},
        )
        self.assertEqual([group.name for group in mesh.vertex_groups], ["Root"])

    def test_normalize_accepts_both_spellings(self):
        for value, expected in (
            ("boneToGroup", helper_module.NAMING_BONE_TO_GROUP),
            ("BONE_TO_GROUP", helper_module.NAMING_BONE_TO_GROUP),
            ("groupToBone", helper_module.NAMING_GROUP_TO_BONE),
            ("GROUP_TO_BONE", helper_module.NAMING_GROUP_TO_BONE),
            ("", ""),
            ("unknown", ""),
        ):
            self.assertEqual(SkeletonHelper.normalize_naming_mode(value), expected, value)


class BoneLengthTests(unittest.TestCase):
    """Display lengths must follow geometry, not placeholder values."""

    def test_placeholder_length_is_replaced_by_geometry(self):
        bones = [
            {"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.004},
            # A helper bone sits exactly on its parent and must not define the
            # parent length; the real child is 0.4 away.
            {"Name": "Root Twist", "Parent": 0, "Rest": rest_matrix(), "Length": 0.004},
            {"Name": "Limb", "Parent": 0, "Rest": rest_matrix(z=0.4), "Length": 0.004},
        ]
        lengths = SkeletonHelper._bone_lengths(bones)
        self.assertAlmostEqual(lengths[0], 0.4, places=5)
        self.assertAlmostEqual(lengths[1], 0.004, places=5)

    def test_consistent_length_is_kept(self):
        bones = [
            {"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
            {"Name": "Child", "Parent": 0, "Rest": rest_matrix(z=0.4), "Length": 0.4},
        ]
        lengths = SkeletonHelper._bone_lengths(bones)
        # 0.2 is within the accepted band around 0.4, so the pack value wins.
        self.assertAlmostEqual(lengths[0], 0.2, places=5)

    def test_leaf_keeps_its_explicit_length(self):
        bones = [{"Name": "Leaf", "Parent": -1, "Rest": rest_matrix(), "Length": 0.075}]
        lengths = SkeletonHelper._bone_lengths(bones)
        self.assertAlmostEqual(lengths[0], 0.075, places=5)

    def test_child_before_parent_inherits_in_any_order(self):
        # Some packs list a child before its parent, so the fallback length must
        # not depend on the order of the bone array.
        bones = [
            {"Name": "Leaf", "Parent": 1, "Rest": rest_matrix()},
            {"Name": "Parent", "Parent": -1, "Rest": rest_matrix(), "Length": 0.3},
        ]
        lengths = SkeletonHelper._bone_lengths(bones)
        self.assertAlmostEqual(lengths[0], 0.18, places=5)
        self.assertAlmostEqual(lengths[1], 0.3, places=5)


class BindingReportTests(unittest.TestCase):
    """Problems must be named instead of silently freezing weights."""

    def test_orphan_palette_slot_is_reported(self):
        # Group "5" carries weights but the palette only names "0".
        mesh = make_mesh("orphan-Component 0", [("0", [0]), ("5", [1, 2])])
        block = drawib_block(
            [{"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2}],
            {"0": "Root"},
            hash_value="h3",
        )
        warnings = []
        summary = SkeletonHelper.apply_groups(
            "SIDECAR", {"orphan": [mesh]}, "", "NONE",
            import_mirror=False, skeletons={"orphan": block}, warnings=warnings,
        )
        self.assertIn("without a bone", summary)
        self.assertIn("5", summary)
        self.assertTrue(any("without a bone" in message for message in warnings), warnings)

    def test_low_confidence_raises_a_warning(self):
        mesh = make_mesh("confidence-Component 0", [("0", [0, 1, 2])])
        block = drawib_block(
            [{"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2}],
            {"0": "Root"},
            hash_value="h4",
        )
        with tempfile.TemporaryDirectory() as folder:
            path = sidecar_file(
                folder,
                {
                    "NamingMode": "boneToGroup",
                    "Space": {"Scale": 1.0, "RotationZ": 0.0},
                    "Characters": [
                        {
                            "Id": "char_h4",
                            "Name": "Character h4",
                            "Bones": block["Bones"],
                            "BoneMap": block["BoneMap"],
                        }
                    ],
                    "DrawIBs": [
                        {
                            "DrawIB": "confidence",
                            "CharacterId": "char_h4",
                            "Confidence": 0.12,
                            "UsedBones": 4,
                            "MappedBones": 2,
                        }
                    ],
                },
            )
            warnings = []
            summary = SkeletonHelper.apply_groups(
                "SIDECAR", {"confidence": [mesh]}, path, "NONE",
                import_mirror=False, skeletons={"confidence": block}, warnings=warnings,
            )
        self.assertIn("confidence 0.12", summary)
        self.assertIn("palette 2/4", summary)
        self.assertTrue(any("low confidence" in message for message in warnings), warnings)


class ComponentIdentityTests(unittest.TestCase):
    """The component number must survive an object rename."""

    def test_property_wins_over_the_object_name(self):
        components = [{"ComponentIndex": 3, "BoneMap": {"0": "Root"}}]
        mesh = make_mesh("LOD0.abcdef12-3", [("0", [0])])
        mesh[helper_module.COMPONENT_INDEX_PROPERTY] = 3
        entry = SkeletonHelper.pick_component(
            components, mesh.name, SkeletonHelper.read_component_index(mesh)
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["ComponentIndex"], 3)

    def test_workspace_name_needs_the_property(self):
        components = [{"ComponentIndex": 0, "BoneMap": {"0": "Root"}}]
        # The workspace display name carries no "Component" text at all.
        self.assertIsNone(SkeletonHelper.pick_component(components, "LOD0.abcdef12-0", -1))
        self.assertIsNotNone(SkeletonHelper.pick_component(components, "LOD0.abcdef12-0", 0))

    def test_reverse_name_still_parses(self):
        components = [{"ComponentIndex": 2, "BoneMap": {"0": "Root"}}]
        entry = SkeletonHelper.pick_component(components, "abcdef12-Component 2.body", -1)
        self.assertEqual(entry["ComponentIndex"], 2)


class PaletteConflictTests(unittest.TestCase):
    """One rig cannot carry two numberings, so each palette gets its own rig."""

    def test_conflicting_palettes_get_one_armature_each(self):
        first = make_mesh("conflictA-Component 0", [("0", [0, 1, 2])])
        second = make_mesh("conflictB-Component 0", [("0", [0, 1, 2])])
        first_block = drawib_block(
            [{"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
             {"Name": "Arm", "Parent": 0, "Rest": rest_matrix(x=0.3), "Length": 0.2}],
            {"0": "Root", "1": "Arm"},
            hash_value="shared",
        )
        second_block = drawib_block(
            [{"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
             {"Name": "Arm", "Parent": 0, "Rest": rest_matrix(x=0.3), "Length": 0.2}],
            # Same numbers, different bones: the palettes disagree.
            {"0": "Arm", "1": "Root"},
            hash_value="shared",
        )
        summary = SkeletonHelper.apply_groups(
            "SIDECAR", {"conflictA": [first], "conflictB": [second]}, "", "NONE",
            import_mirror=False,
            skeletons={"conflictA": first_block, "conflictB": second_block},
        )
        # Numeric naming, because each mesh keeps its own palette on its own rig.
        self.assertIn("naming Rename Bones", summary)
        # Groups stay numeric: they are the export identity of the DrawIB.
        self.assertEqual([group.name for group in first.vertex_groups], ["0"])
        self.assertEqual([group.name for group in second.vertex_groups], ["0"])
        first_rig = bound_armature(first)
        second_rig = bound_armature(second)
        self.assertIsNot(first_rig, second_rig)
        self.assertEqual(sorted(bone.name for bone in first_rig.data.bones), ["0", "1"])
        self.assertEqual(sorted(bone.name for bone in second_rig.data.bones), ["0", "1"])
        # Slot 0 is Root in the first palette and Arm in the second one, which
        # the rest height makes visible.
        self.assertAlmostEqual(first_rig.data.bones["0"].head_local.x, 0.0, places=5)
        self.assertAlmostEqual(second_rig.data.bones["0"].head_local.x, 0.3, places=5)

    def test_group_naming_also_splits_the_armature(self):
        # Renaming the vertex groups makes both rigs use the same bone names,
        # but each part must still be a unit of its own: one rig per palette, so
        # a part can be posed and cleaned without touching the others.
        bones = [
            {"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
            {"Name": "Arm", "Parent": 0, "Rest": rest_matrix(x=0.3), "Length": 0.2},
        ]
        first = make_mesh("groupA-Component 0", [("0", [0, 1, 2])])
        second = make_mesh("groupB-Component 0", [("0", [0, 1, 2])])
        summary = SkeletonHelper.apply_groups(
            "GROUP_TO_BONE",
            {"groupA": [first], "groupB": [second]},
            "",
            "NONE",
            import_mirror=False,
            skeletons={
                "groupA": drawib_block(bones, {"0": "Root", "1": "Arm"}, hash_value="g"),
                "groupB": drawib_block(bones, {"0": "Arm", "1": "Root"}, hash_value="g"),
            },
        )
        self.assertIn("naming Rename Vertex Groups", summary)
        self.assertIn("groupA", summary)
        self.assertIn("groupB", summary)
        self.assertEqual([group.name for group in first.vertex_groups], ["Root"])
        self.assertEqual([group.name for group in second.vertex_groups], ["Arm"])
        first_rig = bound_armature(first)
        second_rig = bound_armature(second)
        self.assertIsNot(first_rig, second_rig)
        self.assertEqual(sorted(bone.name for bone in first_rig.data.bones), ["Arm", "Root"])
        self.assertEqual(sorted(bone.name for bone in second_rig.data.bones), ["Arm", "Root"])

    def test_split_warns_once_and_names_the_drawibs(self):
        # Several rigs are a workflow change, so it must never be silent: one
        # warning per character names the DrawIBs that disagree.
        bones = [
            {"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
            {"Name": "Arm", "Parent": 0, "Rest": rest_matrix(x=0.3), "Length": 0.2},
        ]
        first = make_mesh("warningA-Component 0", [("0", [0, 1, 2])])
        second = make_mesh("warningB-Component 0", [("0", [0, 1, 2])])
        warnings = []
        SkeletonHelper.apply_groups(
            "BONE_TO_GROUP",
            {"warningA": [first], "warningB": [second]},
            "",
            "NONE",
            import_mirror=False,
            skeletons={
                # Same skeleton hash, two palettes: the rig has to split.
                "warningA": drawib_block(bones, {"0": "Root", "1": "Arm"}, hash_value="warn"),
                "warningB": drawib_block(bones, {"0": "Arm", "1": "Root"}, hash_value="warn"),
            },
            warnings=warnings,
        )
        split = [message for message in warnings if "armature" in message]
        self.assertEqual(len(split), 1, warnings)
        self.assertIn("warningA", split[0])
        self.assertIn("warningB", split[0])
        self.assertIn("pose them together", split[0])


class BoneStructureTests(unittest.TestCase):
    """Bone collections and the Deform flag must reach the armature."""

    def test_deform_flag_and_bone_collections(self):
        mesh = make_mesh("structure-Component 0", [("0", [0, 1, 2])])
        block = drawib_block(
            [
                {"Name": "Bip001 Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
                {
                    "Name": "Bip001 Helper",
                    "Parent": 0,
                    "Rest": rest_matrix(x=0.2),
                    "Length": 0.2,
                    "Deform": False,
                },
            ],
            {"0": "Bip001 Root"},
            hash_value="h5",
        )
        SkeletonHelper.apply_groups(
            "SIDECAR", {"structure": [mesh]}, "", "NONE",
            import_mirror=False, skeletons={"structure": block},
        )
        armature = bound_armature(mesh)
        helper = armature.data.bones.get("Bip001 Helper")
        self.assertIsNotNone(helper)
        self.assertFalse(helper.use_deform)
        collection_names = {collection.name for collection in armature.data.collections}
        self.assertIn("Bip001", collection_names)


class PaletteUnionTests(unittest.TestCase):
    """Bone renaming must cover every palette that shares one armature."""

    def test_second_drawib_extends_the_numbering(self):
        # Both DrawIBs share one skeleton. The first one uses only slot 0, the
        # second one also uses slot 1; renaming with the first map alone would
        # leave the second mesh with a numeric group that answers to no bone.
        bones = [
            {"Name": "Root", "Parent": -1, "Rest": rest_matrix(), "Length": 0.2},
            {"Name": "Arm", "Parent": 0, "Rest": rest_matrix(x=0.3), "Length": 0.2},
        ]
        first = make_mesh("unionA-Component 0", [("0", [0, 1, 2])])
        second = make_mesh("unionB-Component 0", [("0", [0]), ("1", [1, 2])])
        summary = SkeletonHelper.apply_groups(
            "SIDECAR",
            {"unionA": [first], "unionB": [second]},
            "",
            "NONE",
            import_mirror=False,
            skeletons={
                "unionA": drawib_block(bones, {"0": "Root"}, hash_value="union"),
                "unionB": drawib_block(bones, {"0": "Root", "1": "Arm"}, hash_value="union"),
            },
        )
        armature = bound_armature(second)
        self.assertEqual(sorted(bone.name for bone in armature.data.bones), ["0", "1"])
        self.assertIn("naming Rename Bones", summary)


def main():
    """Run every test and fail the Blender process when one breaks."""
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("RESULT " + json.dumps({"tests": result.testsRun, "success": result.wasSuccessful()}))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
