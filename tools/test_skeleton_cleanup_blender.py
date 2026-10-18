"""Headless regression checks for reverse-skeleton bone cleanup.

Run: blender -b --factory-startup --python-exit-code 1 -P tools/test_skeleton_cleanup_blender.py

The Mod Reverse panel keeps the whole character skeleton by default. Its new
cleanup dropdown can instead delete or hide every bone that no imported mesh
actually deforms. A reverse skeleton belongs to the whole character, while one
mod usually uses only a small part of it.

Coverage notes:
- Only a non-zero vertex weight keeps a bone alive; the importer creates many
  empty numeric groups for palette gaps, and empty groups must not do it.
- Deleting a chain of invalid bones must keep usable children, reattach them to
  the nearest usable ancestor, and preserve their rest head position.
- A connected child used to snap onto the new parent's tail when the parent was
  changed before use_connect was cleared; the rest position check catches that.
- Hiding marks the invalid bones in both Edit Mode and Pose Mode while leaving
  every bone and every parent relationship in place.
- Zero-weight data must not delete a whole skeleton by accident.
- The complete sidecar path is exercised as well: build, rename, bind, clean.
- The default cleanup value must keep all bones for existing saved scenes.
- Every fixture lives in the factory-startup scene and never opens a user file.
- All temporary sidecars are written inside a temporary directory.
- The runner raises on failure so --python-exit-code reports a failing job.
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

# Import only the skeleton helper; no unrelated add-on startup work is needed.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("MIMIBlender")
package.__path__ = [str(ROOT)]
sys.modules["MIMIBlender"] = package
skeleton = importlib.import_module("MIMIBlender.utils.skeleton_helper")
SkeletonHelper = skeleton.SkeletonHelper


def new_armature(name, bones):
    """Create a test armature from (bone_name, parent_name) pairs.

    Head and tail are placed one unit apart on a chain, so a connected child
    starts exactly at its parent's tail and any snapping becomes measurable.
    """
    armature = bpy.data.armatures.new(name)
    armature_obj = bpy.data.objects.new(name, armature)
    bpy.context.scene.collection.objects.link(armature_obj)
    bpy.context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for index, (bone_name, parent_name) in enumerate(bones):
        edit_bone = armature.edit_bones.new(bone_name)
        # The index gives every bone a unique, easy to compare rest position.
        edit_bone.head = (0.0, 0.0, float(index))
        edit_bone.tail = (0.0, 0.0, float(index) + 1.0)
        edit_bone.parent = armature.edit_bones.get(parent_name) if parent_name else None
        # Start disconnected; individual tests connect the bones they need.
        edit_bone.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    armature_obj.select_set(False)
    return armature_obj


def new_mesh(name, weights):
    """Create a small mesh and assign (group_name, vertex_index, weight) rows."""
    mesh = bpy.data.meshes.new(name)
    # Two vertices are enough: one can carry a weight and one can stay empty.
    mesh.from_pydata([(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)], [], [])
    mesh.update()
    mesh_obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(mesh_obj)
    for group_name, vertex_index, weight in weights:
        group = mesh_obj.vertex_groups.get(group_name)
        if group is None:
            group = mesh_obj.vertex_groups.new(name=group_name)
        group.add([vertex_index], weight, "REPLACE")
    return mesh_obj


def set_connected(armature_obj, bone_names):
    """Mark selected bones as connected without touching their rest position."""
    bpy.context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name in bone_names:
        edit_bone = armature_obj.data.edit_bones.get(bone_name)
        if edit_bone is not None:
            edit_bone.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")


def write_sidecar(folder_path):
    """Write the smallest skeleton.json that drives the real binding path."""
    # The first bone is the parent of the second; both use explicit lengths so
    # the helper does not need to infer display sizes from the rest matrices.
    sidecar = {
        "Space": {"Scale": 1.0, "RotationZ": 0.0},
        "Characters": [
            {
                "Id": "test-character",
                "Name": "Test Character",
                "Bones": [
                    {
                        "Name": "root",
                        "Parent": -1,
                        "Rest": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                        "Length": 0.2,
                    },
                    {
                        "Name": "body",
                        "Parent": 0,
                        "Rest": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1],
                        "Length": 0.2,
                    },
                ],
                "BoneMap": {"0": "root", "1": "body"},
            }
        ],
        "DrawIBs": [{"DrawIB": "drawib1", "CharacterId": "test-character"}],
    }
    sidecar_path = os.path.join(folder_path, "skeleton.json")
    with open(sidecar_path, "w", encoding="utf-8") as handle:
        json.dump(sidecar, handle)
    return sidecar_path


class SkeletonCleanupTests(unittest.TestCase):
    def setUp(self):
        # This scene is factory-startup data owned by the test process.
        bpy.data.batch_remove(ids=list(bpy.data.objects))
        bpy.context.view_layer.objects.active = None

    def tearDown(self):
        # A failed assertion must not leave the next test inside Edit Mode.
        active_object = bpy.context.object
        if active_object is not None and active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

    def test_weighted_groups_ignore_empty_and_zero_weight_slots(self):
        # Group "0" is weighted, "1" stores a zero weight and "2" is empty.
        armature_obj = new_armature("Weights", [("0", None), ("1", "0"), ("2", "1")])
        mesh_obj = new_mesh("WeightsMesh", [("0", 0, 1.0), ("1", 1, 0.0)])
        mesh_obj.vertex_groups.new(name="2")

        weighted_names = SkeletonHelper.collect_weighted_group_names([mesh_obj])
        self.assertEqual(weighted_names, {"0"})
        # The armature itself is not a mesh and must be ignored safely.
        self.assertEqual(
            SkeletonHelper.collect_weighted_group_names([armature_obj]),
            set(),
        )

    def test_keep_mode_changes_nothing(self):
        armature_obj = new_armature("Keep", [("root", None), ("unused", "root")])
        mesh_obj = new_mesh("KeepMesh", [("root", 0, 1.0)])

        removed_count, hidden_count = SkeletonHelper.cleanup_bones(
            armature_obj, [mesh_obj], skeleton.BONE_CLEANUP_NONE
        )
        self.assertEqual((removed_count, hidden_count), (0, 0))
        self.assertIsNotNone(armature_obj.data.bones.get("unused"))
        self.assertFalse(armature_obj.data.bones["unused"].hide)

    def test_hide_mode_hides_only_invalid_bones(self):
        armature_obj = new_armature(
            "Hide",
            [("root", None), ("used", "root"), ("unused", "used")],
        )
        mesh_obj = new_mesh("HideMesh", [("root", 0, 1.0), ("used", 1, 1.0)])

        removed_count, hidden_count = SkeletonHelper.cleanup_bones(
            armature_obj, [mesh_obj], skeleton.BONE_CLEANUP_HIDE
        )
        self.assertEqual((removed_count, hidden_count), (0, 1))
        # Hiding must not remove or reparent anything.
        self.assertEqual(
            {bone.name for bone in armature_obj.data.bones},
            {"root", "used", "unused"},
        )
        self.assertEqual(armature_obj.data.bones["unused"].parent.name, "used")
        # Bone.hide covers Edit Mode, PoseBone.hide covers Pose Mode.
        self.assertTrue(armature_obj.data.bones["unused"].hide)
        self.assertTrue(armature_obj.pose.bones["unused"].hide)
        self.assertFalse(armature_obj.data.bones["used"].hide)
        self.assertFalse(armature_obj.pose.bones["used"].hide)

    def test_delete_mode_reattaches_valid_child_and_keeps_rest_position(self):
        armature_obj = new_armature(
            "Delete",
            [
                ("root", None),
                ("bad_a", "root"),
                ("bad_b", "bad_a"),
                ("tip", "bad_b"),
                ("side", "root"),
            ],
        )
        mesh_obj = new_mesh("DeleteMesh", [("root", 0, 1.0), ("tip", 1, 1.0)])
        # A connected tip would snap onto root's tail if use_connect were
        # cleared after the parent assignment inside the cleanup helper.
        set_connected(armature_obj, ["tip"])
        tip_head_before = armature_obj.data.bones["tip"].head_local.copy()

        removed_count, hidden_count = SkeletonHelper.cleanup_bones(
            armature_obj, [mesh_obj], skeleton.BONE_CLEANUP_DELETE
        )
        self.assertEqual((removed_count, hidden_count), (3, 0))
        self.assertEqual(
            {bone.name for bone in armature_obj.data.bones},
            {"root", "tip"},
        )
        tip_bone = armature_obj.data.bones["tip"]
        # The nearest usable ancestor is root: both invalid bones are skipped.
        self.assertEqual(tip_bone.parent.name, "root")
        self.assertFalse(tip_bone.use_connect)
        self.assertAlmostEqual(tip_bone.head_local.z, tip_head_before.z, places=6)
        self.assertIsNone(armature_obj.data.bones.get("bad_a"))
        self.assertIsNone(armature_obj.data.bones.get("bad_b"))
        self.assertIsNone(armature_obj.data.bones.get("side"))

    def test_delete_mode_does_nothing_without_any_weight(self):
        # No mesh carries a weight: deleting every bone would destroy data the
        # user may still need, so the helper leaves the skeleton untouched.
        armature_obj = new_armature("NoWeights", [("root", None), ("unused", "root")])
        mesh_obj = new_mesh("NoWeightMesh", [])
        mesh_obj.vertex_groups.new(name="root")

        removed_count, hidden_count = SkeletonHelper.cleanup_bones(
            armature_obj, [mesh_obj], skeleton.BONE_CLEANUP_DELETE
        )
        self.assertEqual((removed_count, hidden_count), (0, 0))
        self.assertEqual(
            {bone.name for bone in armature_obj.data.bones},
            {"root", "unused"},
        )

    def test_delete_mode_does_nothing_when_every_bone_is_used(self):
        armature_obj = new_armature("AllUsed", [("root", None), ("body", "root")])
        mesh_obj = new_mesh("AllUsedMesh", [("root", 0, 1.0), ("body", 1, 1.0)])

        removed_count, hidden_count = SkeletonHelper.cleanup_bones(
            armature_obj, [mesh_obj], skeleton.BONE_CLEANUP_DELETE
        )
        self.assertEqual((removed_count, hidden_count), (0, 0))
        self.assertEqual(
            {bone.name for bone in armature_obj.data.bones},
            {"root", "body"},
        )

    def test_apply_groups_runs_cleanup_after_binding(self):
        with tempfile.TemporaryDirectory() as folder_path:
            sidecar_path = write_sidecar(folder_path)
            mesh_obj = new_mesh("BoundMesh", [("0", 0, 1.0)])

            # The real path builds the armature from skeleton.json, renames its
            # bones to the numeric groups and then applies the cleanup choice.
            summary = SkeletonHelper.apply_groups(
                skeleton.NAMING_BONE_TO_GROUP,
                {"drawib1": [mesh_obj]},
                sidecar_path,
                skeleton.BONE_CLEANUP_DELETE,
            )

        self.assertIn("invalid bone(s) removed", summary)
        armature_objects = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
        self.assertEqual(len(armature_objects), 1)
        armature_obj = armature_objects[0]
        # Bone "0" is weighted, bone "1" is not, so only "0" may survive.
        self.assertEqual({bone.name for bone in armature_obj.data.bones}, {"0"})
        # The mesh must stay bound to the same armature after the deletion.
        armature_modifiers = [
            modifier for modifier in mesh_obj.modifiers if modifier.type == "ARMATURE"
        ]
        self.assertEqual(len(armature_modifiers), 1)
        self.assertIs(armature_modifiers[0].object, armature_obj)

    def test_apply_groups_default_keeps_every_bone(self):
        with tempfile.TemporaryDirectory() as folder_path:
            sidecar_path = write_sidecar(folder_path)
            mesh_obj = new_mesh("DefaultMesh", [("0", 0, 1.0)])
            # Existing callers do not pass a cleanup mode; the default must stay
            # non-destructive for scenes saved before this option existed.
            SkeletonHelper.apply_groups(
                skeleton.NAMING_BONE_TO_GROUP,
                {"drawib1": [mesh_obj]},
                sidecar_path,
            )

        armature_objects = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
        self.assertEqual(len(armature_objects), 1)
        self.assertEqual(
            {bone.name for bone in armature_objects[0].data.bones},
            {"0", "1"},
        )


def main():
    print("Blender version:", bpy.app.version_string)
    # Helper functions are pure Blender data, so registration is not required.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SkeletonCleanupTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("RESULT " + json.dumps({"tests": result.testsRun, "success": result.wasSuccessful()}))
    if not result.wasSuccessful():
        raise RuntimeError("Skeleton cleanup integration checks failed")


if __name__ == "__main__":
    main()
