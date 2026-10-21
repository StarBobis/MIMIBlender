"""Headless regression checks for the shared skeleton import settings.

Run: blender -b --factory-startup --python-exit-code 1 -P tools/test_skeleton_settings_blender.py

The same settings drive the Mod Reverse import and the workspace import, so the
block must be drawn in both panels and the two panels must never disagree.
Coverage notes:

- The properties are registered by utils/skeleton_ui.py, not by the reverse
  panel any more: the workspace import does not depend on that panel.
- Files saved before the settings were split still carry the old single enum;
  the migration must map NONE and GROUP_TO_BONE and keep the new default for
  the old default value.
- Panel draw functions must not write Scene properties in Blender 5.2, so the
  read-only resolver is checked separately from the migrating one.
- ``Follow MMT`` resolves the naming mode from the sidecar after it is loaded.
- The shared draw helper is exercised with a fake layout for both panels: found
  sidecar, missing sidecar, disabled binding and the stored last report.
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

# Import only the shared settings module; the full add-on startup is not needed.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("MIMIBlender")
package.__path__ = [str(ROOT)]
sys.modules["MIMIBlender"] = package
skeleton_helper = importlib.import_module("MIMIBlender.utils.skeleton_helper")
skeleton_ui = importlib.import_module("MIMIBlender.utils.skeleton_ui")


def rest_matrix(position):
    """Row-major rest matrix with the translation in the fourth column."""
    return [
        1.0, 0.0, 0.0, position[0],
        0.0, 1.0, 0.0, position[1],
        0.0, 0.0, 1.0, position[2],
        0.0, 0.0, 0.0, 1.0,
    ]


def make_mesh(name, group_names):
    """Create a one-triangle mesh carrying the given numeric vertex groups."""
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for group_name in group_names:
        obj.vertex_groups.new(name=group_name)
    return obj


def write_sidecar(folder, naming_mode, characters=None):
    """Write a minimal sidecar with one character and one DrawIB entry."""
    payload = {
        "Format": "MMT-SkeletonBinding",
        "Version": 1,
        "GamePreset": "ZZMI",
        "NamingMode": naming_mode,
        "Space": {"UpAxis": "Z", "Scale": 1.0, "RotationZ": 0.0},
        "Characters": characters
        or [
            {
                "Id": "qingyi",
                "Name": "QingYi",
                "Bones": [
                    {"Name": "Root", "Parent": -1, "Rest": rest_matrix((0.0, 0.0, 0.0)), "Length": 0.2, "Deform": True},
                    {"Name": "Spine", "Parent": 0, "Rest": rest_matrix((0.0, 0.0, 0.2)), "Length": 0.2, "Deform": True},
                ],
                "BoneMap": {"0": "Root", "1": "Spine"},
            }
        ],
        "DrawIBs": [
            {
                "DrawIB": "100",
                "Folder": folder,
                "CharacterId": (characters or [{"Id": "qingyi"}])[0].get("Id", "qingyi"),
                "UsedBones": 2,
                "MappedBones": 2,
            }
        ],
    }
    path = os.path.join(folder, "skeleton.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path, payload


class FakeLayout:
    """Stand-in for a Blender layout that records what the block draws."""

    def __init__(self):
        self.labels = []
        self.properties = []

    def box(self):
        return self

    def row(self, align=True):
        return self

    def label(self, text='', icon=''):
        self.labels.append(text)

    def prop(self, data, name, text=''):
        self.properties.append(name)


class SkeletonSettingsTests(unittest.TestCase):
    """Property registration, migration, naming resolution and shared drawing."""

    def setUp(self):
        # Registration is per test: unregister proves that no property leaks
        # into the next test or into a later add-on reload.
        self.scene = bpy.context.scene
        skeleton_ui.register()
        # Blender restores the value of a property when it is registered again,
        # so every test starts from an explicit, known state instead of the
        # leftovers of the previous test.
        self.scene.mimi_sword_bind_skeleton = True
        self.scene.mimi_sword_skeleton_naming = skeleton_helper.NAMING_SIDECAR
        self.scene.mimi_sword_skeleton_cleanup = skeleton_helper.BONE_CLEANUP_NONE
        self.scene.mimi_sword_skeleton_last_report = ""
        # Mark the scene as migrated so the setup above is not overwritten by
        # the legacy values a previous test may have stored.
        self.scene[skeleton_ui.SETTINGS_VERSION_KEY] = skeleton_ui.SETTINGS_VERSION

    def tearDown(self):
        skeleton_ui.unregister()

    def reset_legacy(self, legacy_value):
        """Store a legacy value and clear the migration marker again."""
        self.scene.mimi_sword_skeleton_mode = legacy_value
        try:
            del self.scene[skeleton_ui.SETTINGS_VERSION_KEY]
        except KeyError:
            pass

    def test_shared_properties_register_and_unregister(self):
        for property_name in (
            skeleton_ui.BIND_PROPERTY,
            skeleton_ui.NAMING_PROPERTY,
            skeleton_ui.CLEANUP_PROPERTY,
            skeleton_ui.REPORT_PROPERTY,
        ):
            self.assertTrue(hasattr(bpy.types.Scene, property_name), property_name)
        # A fresh scene follows MMT and keeps every bone.
        self.assertTrue(self.scene.mimi_sword_bind_skeleton)
        self.assertEqual(self.scene.mimi_sword_skeleton_naming, skeleton_helper.NAMING_SIDECAR)
        self.assertEqual(self.scene.mimi_sword_skeleton_cleanup, skeleton_helper.BONE_CLEANUP_NONE)
        skeleton_ui.unregister()
        self.assertFalse(hasattr(bpy.types.Scene, skeleton_ui.BIND_PROPERTY))
        # tearDown unregisters again; both calls must stay safe.
        skeleton_ui.register()

    def test_extraction_entries_resolve_by_the_bare_drawib(self):
        # Extraction folders are named hash-indexcount-firstindex while the
        # workspace import keys its objects by the bare hash; comparing the
        # whole folder name would bind every group to the first entry.
        sidecar = {
            "Characters": [{"Id": "char-a"}, {"Id": "char-b"}],
            "DrawIBs": [
                {"DrawIB": "aaaa1111-100-0", "Folder": "", "CharacterId": "char-a"},
                {"DrawIB": "bbbb2222-100-0", "Folder": "", "CharacterId": "char-b"},
            ],
        }
        picker = skeleton_helper.SkeletonHelper.pick_drawib
        self.assertEqual(picker(sidecar, [], "aaaa1111"), sidecar["DrawIBs"][0])
        self.assertEqual(picker(sidecar, [], "bbbb2222"), sidecar["DrawIBs"][1])
        # Workspace meshes are named "LOD0.hash-component" and carry no folder.
        self.assertEqual(
            picker(sidecar, ["LOD0.bbbb2222-0"], ""),
            sidecar["DrawIBs"][1],
        )

    def test_extraction_sidecar_binds_each_drawib(self):
        # End to end: two DrawIBs of different characters in one sidecar must
        # get one armature each instead of sharing the first entry.
        with tempfile.TemporaryDirectory() as folder:
            characters = []
            entries = []
            for index, name in enumerate(("aaaa1111", "bbbb2222")):
                character_id = "char-" + name
                characters.append(
                    {
                        "Id": character_id,
                        "Name": name,
                        "Bones": [
                            {
                                "Name": "Bone" + name,
                                "Parent": -1,
                                "Rest": rest_matrix((0.0, 0.0, 0.1 * index)),
                                "Length": 0.1,
                                "Deform": True,
                            }
                        ],
                        "BoneMap": {"0": "Bone" + name},
                    }
                )
                entries.append(
                    {
                        "DrawIB": name + "-100-0",
                        "Folder": os.path.join(folder, "LOD0", name + "-100-0", "TYPE_GPU"),
                        "CharacterId": character_id,
                        "UsedBones": 1,
                        "MappedBones": 1,
                    }
                )
            payload = {"Characters": characters, "DrawIBs": entries}
            path = os.path.join(folder, "skeleton.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            first = make_mesh("LOD0.aaaa1111-0", ["0"])
            second = make_mesh("LOD0.bbbb2222-0", ["0"])
            summary = skeleton_helper.SkeletonHelper.apply_groups(
                skeleton_helper.NAMING_SIDECAR,
                {"aaaa1111": [first], "bbbb2222": [second]},
                path,
            )

        self.assertIn("aaaa1111", summary)
        self.assertIn("bbbb2222", summary)
        first_armature = next(
            modifier.object for modifier in first.modifiers if modifier.type == "ARMATURE"
        )
        second_armature = next(
            modifier.object for modifier in second.modifiers if modifier.type == "ARMATURE"
        )
        self.assertEqual(first_armature.name, "char-aaaa1111_Armature")
        self.assertEqual(second_armature.name, "char-bbbb2222_Armature")
        self.assertNotEqual(first_armature, second_armature)

    def test_legacy_values_are_migrated(self):
        cases = {
            "NONE": (False, skeleton_helper.NAMING_SIDECAR),
            "GROUP_TO_BONE": (True, skeleton_helper.NAMING_GROUP_TO_BONE),
            # The old default was BONE_TO_GROUP for everybody, so it becomes
            # the new default and lets the sidecar decide.
            "BONE_TO_GROUP": (True, skeleton_helper.NAMING_SIDECAR),
        }
        for legacy_value, expected in cases.items():
            self.reset_legacy(legacy_value)
            settings = skeleton_ui.ensure_bind_settings(self.scene)
            self.assertEqual(
                (settings.bind, settings.naming),
                expected,
                legacy_value,
            )
            # The migration marks the scene, so a second call is a no-op.
            self.assertFalse(skeleton_ui.ensure_scene_settings(self.scene))
            self.assertEqual(self.scene[skeleton_ui.SETTINGS_VERSION_KEY], skeleton_ui.SETTINGS_VERSION)

    def test_read_does_not_write_before_migration(self):
        self.reset_legacy("NONE")
        settings = skeleton_ui.read_bind_settings(self.scene)
        self.assertFalse(settings.bind)
        # Panel draw functions may not write: the marker must still be absent.
        self.assertNotIn(skeleton_ui.SETTINGS_VERSION_KEY, self.scene.keys())

    def test_sidecar_naming_mode_is_used(self):
        # Follow MMT: the sidecar asks for readable vertex groups.
        mesh = make_mesh("GroupModeBody", ["0", "1"])
        with tempfile.TemporaryDirectory() as folder:
            path, _payload = write_sidecar(folder, "groupToBone")
            summary = skeleton_helper.SkeletonHelper.apply_groups(
                skeleton_helper.NAMING_SIDECAR, {"100": [mesh]}, path
            )
        self.assertIn("QingYi", summary)
        self.assertEqual(sorted(group.name for group in mesh.vertex_groups), ["Root", "Spine"])

        # Follow MMT: the sidecar asks for numeric bones, the default mode.
        mesh = make_mesh("BoneModeBody", ["0", "1"])
        with tempfile.TemporaryDirectory() as folder:
            path, _payload = write_sidecar(folder, "boneToGroup")
            skeleton_helper.SkeletonHelper.apply_groups(
                skeleton_helper.NAMING_SIDECAR, {"100": [mesh]}, path
            )
        armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
        self.assertTrue(armatures)
        self.assertEqual(sorted(bone.name for bone in armatures[-1].data.bones), ["0", "1"])
        self.assertEqual(sorted(group.name for group in mesh.vertex_groups), ["0", "1"])

    def test_draw_block_reports_the_sidecar(self):
        layout = FakeLayout()
        with tempfile.TemporaryDirectory() as folder:
            write_sidecar(folder, "boneToGroup")
            skeleton_ui.draw_skeleton_binding(layout, self.scene, folder)
        self.assertIn("Skeleton Binding", layout.labels)
        self.assertIn("Skeleton file found: the import will bind the character armature", layout.labels)
        self.assertIn("Character: QingYi", layout.labels)
        self.assertIn(skeleton_ui.BIND_PROPERTY, layout.properties)
        self.assertIn(skeleton_ui.NAMING_PROPERTY, layout.properties)
        self.assertIn(skeleton_ui.CLEANUP_PROPERTY, layout.properties)

    def test_draw_block_hides_choices_when_unbound(self):
        self.scene.mimi_sword_bind_skeleton = False
        layout = FakeLayout()
        with tempfile.TemporaryDirectory() as folder:
            write_sidecar(folder, "boneToGroup")
            skeleton_ui.draw_skeleton_binding(layout, self.scene, folder)
        self.assertIn(skeleton_ui.BIND_PROPERTY, layout.properties)
        self.assertNotIn(skeleton_ui.NAMING_PROPERTY, layout.properties)
        self.assertNotIn(skeleton_ui.CLEANUP_PROPERTY, layout.properties)
        self.assertIn("Skeleton binding is off; the import creates no armature", layout.labels)

    def test_draw_block_shows_missing_sidecar_and_last_report(self):
        layout = FakeLayout()
        with tempfile.TemporaryDirectory() as folder:
            skeleton_ui.draw_skeleton_binding(layout, self.scene, folder)
        self.assertIn("No skeleton.json next to this folder; the import uses the skeleton embedded in each Json when it has one", layout.labels)
        skeleton_ui.remember_bind_report(self.scene, "QingYi (2 bones, 1 meshes)")
        layout = FakeLayout()
        skeleton_ui.draw_skeleton_binding(layout, self.scene, "")
        self.assertIn("Last bind: QingYi (2 bones, 1 meshes)", layout.labels)

    def test_draw_block_warns_only_before_a_numeric_split(self):
        # One palette per DrawIB is legal, and two disagreeing palettes force
        # one armature per palette only while the bones carry the numbers.
        # "Rename Vertex Groups" renames object-local groups, so it keeps one
        # armature and must not promise a split.
        with tempfile.TemporaryDirectory() as folder:
            payload = {
                "NamingMode": "boneToGroup",
                "Characters": [
                    {
                        "Id": "conflict",
                        "Name": "Conflict",
                        "Bones": [
                            {"Name": "Root", "Parent": -1, "Rest": rest_matrix((0.0, 0.0, 0.0)), "Length": 0.2},
                            {"Name": "Arm", "Parent": 0, "Rest": rest_matrix((0.0, 0.0, 0.2)), "Length": 0.2},
                        ],
                        "BoneMap": {"0": "Root", "1": "Arm"},
                    }
                ],
                "DrawIBs": [
                    {"DrawIB": "aaaa1111", "CharacterId": "conflict", "BoneMap": {"0": "Root", "1": "Arm"}},
                    {"DrawIB": "bbbb2222", "CharacterId": "conflict", "BoneMap": {"0": "Arm", "1": "Root"}},
                ],
            }
            with open(os.path.join(folder, "skeleton.json"), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            # The summary is cached per mtime, so a reused temp path must not
            # serve the payload of a previous test.
            skeleton_ui.clear_sidecar_cache()

            hint = skeleton_ui.tr(
                "DrawIBs of {names} number different bones; the import creates one armature per palette"
            ).format(names="Conflict")

            # "Follow MMT" resolves to the numeric mode this sidecar asks for.
            layout = FakeLayout()
            skeleton_ui.draw_skeleton_binding(layout, self.scene, folder)
            self.assertIn(hint, layout.labels)

            # The split is numeric-only, so readable bone names drop the hint:
            # the whole character stays on one armature.
            self.scene.mimi_sword_skeleton_naming = skeleton_helper.NAMING_GROUP_TO_BONE
            layout = FakeLayout()
            skeleton_ui.draw_skeleton_binding(layout, self.scene, folder)
            self.assertNotIn(hint, layout.labels)

    def test_draw_block_wraps_a_long_bind_report(self):
        # A long report used to be shortened in the middle, which hid the one
        # detail that explains why a character got several armatures.
        report = (
            "Skeleton: Jane Doe [ba4255a5], naming Rename Bones, "
            "armature janedoe_Armature_ba4255a5, confidence 0.42, palette 94/94, "
            "2 slot(s) without a bone (80, 82) -> 4 weights in bind pose"
        )
        skeleton_ui.remember_bind_report(self.scene, report)
        layout = FakeLayout()
        skeleton_ui.draw_skeleton_binding(layout, self.scene, "")
        self.assertTrue(layout.labels)
        # The report is the last block of the panel, so its first line is the
        # first label that carries the "Last bind" caption.
        start = next(
            index
            for index, label in enumerate(layout.labels)
            if label.startswith("Last bind: Skeleton: Jane Doe")
        )
        report_lines = [label.strip() for label in layout.labels[start:]]
        self.assertGreater(len(report_lines), 1)
        # Joining the lines restores the words the wrap split apart.
        self.assertIn("janedoe_Armature_ba4255a5", " ".join(report_lines))
        self.assertLessEqual(len(layout.labels[start]), skeleton_ui.REPORT_LINE_WIDTH)
        for label in layout.labels[start + 1:]:
            self.assertLessEqual(len(label), skeleton_ui.REPORT_LINE_WIDTH + 2)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SkeletonSettingsTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("RESULT " + json.dumps({"tests": result.testsRun, "success": result.wasSuccessful()}))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
