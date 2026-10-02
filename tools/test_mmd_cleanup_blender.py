"""Headless integration checks for the MMD cleanup sidebar feature.

Run: blender -b --factory-startup --python-exit-code 1 -P this_file
Tests create synthetic imports only, never open or modify a user scene.

Coverage notes:
- Physics groups contain hidden mesh descendants, as real MMD imports do.
- Duplicate group names exercise Blender's numeric naming suffixes.
- Character names have no special meaning to the cleanup algorithm.
- A second selected model stays intact when the first model is cleaned.
- Retained helpers and clothing exercise non-skeleton child preservation.
- Root translation, rotation and scale exercise world-matrix preservation.
- An external parent exercises reconnecting rather than simple unparenting.
- Armature modifiers and shape keys remain bound to their original data.
- Root metadata permits cleanup after the physics groups are already gone.
- Renamed physics containers exercise metadata-based group identification.
- Main-mesh selection is required; root and physics selections are rejected.
- A nested skeleton proves validation happens before destructive mutation.
- Edit Mode is rejected without forcing the user into a different mode.
- Registration can be reversed and repeated in the same Blender process.
- Sidebar placement and Chinese captions are checked without stealing focus.
- No optional MMD importer is needed to execute these regression checks.

Test fixture ownership:
- All fixtures live in the process's fresh default scene.
- Removing default objects cannot affect the user's live Blender session.
- Mesh fixtures need no rendered topology to verify parenting semantics.
- Shape keys exercise preservation of attached mesh data blocks.
- Armature objects exercise the hierarchy even without creating pose bones.
- Hidden children reproduce objects users cannot easily select manually.
- Every object is linked to the default collection for valid selection.
- Object references are retained instead of assuming requested names survive.
- The first cleanup test invokes the registered Blender operator itself.
- Direct helper tests expose validation failures as Python exceptions.
- Matrix comparisons are made after the cleanup updates the view layer.
- Numeric tolerance allows normal floating-point decomposition differences.
- The external parent is itself included in the transform comparisons.
- The second model's root, skeleton, mesh and containers are all checked.
- Failed cleanup compares complete object sets, not only object counts.
- Language changes are restored to English within their isolated test.
- Repeated registration is checked before running the functional suite.
- The runner raises on failure so --python-exit-code reports a failing job.
- A final JSON result line provides a compact automated-test summary.
- Temporary test classes are unregistered even after failed assertions.
- No saved blend file or installation preferences are written by the tests.
"""
import importlib
import json
from pathlib import Path
import sys
import types
import unittest

import bpy

# Import only this feature and i18n, avoiding unrelated add-on startup work.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('MIMIBlender')
package.__path__ = [str(ROOT)]
sys.modules['MIMIBlender'] = package
panel = importlib.import_module('MIMIBlender.ui.ui_panel_mmd')
i18n = importlib.import_module('MIMIBlender.i18n.i18n')


def new_object(name, kind='EMPTY', parent=None):
    # Keep Blender's returned reference when duplicate names gain suffixes.
    data = None
    if kind == 'MESH':
        data = bpy.data.meshes.new(name)
    elif kind == 'ARMATURE':
        data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def model(name, metadata=False, physics=True, outer=None):
    # Mirror the screenshot: root -> skeleton -> main mesh, with physics
    # containers beside the skeleton. A second model gains numeric suffixes.
    root = new_object(name, parent=outer)
    arm = new_object(name + '_arm', 'ARMATURE', root)
    mesh = new_object(name + '_mesh', 'MESH', arm)
    groups = []
    if metadata:
        root['mmd_type'] = 'ROOT'
    if physics:
        for name, tag in [('joints', 'JOINT_GRP'), ('rigidbodies', 'RIGID_GRP')]:
            group = new_object(name, parent=root)
            if metadata:
                group.name = 'renamed_' + name
                group['mmd_type'] = tag
            # Hidden descendants must be deleted even when not selectable.
            item = new_object(name + '_item', 'MESH', group)
            item.hide_set(True)
            groups.append(group)
    return root, arm, mesh, groups


class CleanupTests(unittest.TestCase):
    def setUp(self):
        # This scene is factory-startup data owned by the test process.
        bpy.data.batch_remove(ids=list(bpy.data.objects))

    def activate(self, mesh):
        # Multiple selected objects must not broaden the deletion scope.
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh

    def test_isolation_and_transforms(self):
        # Give the root a surviving external parent with nontrivial transforms.
        outer = new_object('external')
        outer.location = (2, -1, 3)
        root, arm, mesh, groups = model('character', outer=outer)
        other = model('second')
        root.location = (5, 2, -3)
        root.rotation_euler = (0.2, -0.4, 0.7)
        root.scale = (1.5, 1.5, 1.5)
        arm.location = (0.3, 0.2, 0.1)
        # Keep a second mesh and an unrelated helper in the retained branch.
        sibling = new_object('clothing', 'MESH', arm)
        helper = new_object('helper', parent=root)
        modifier = mesh.modifiers.new('skeleton', 'ARMATURE')
        modifier.object = arm
        mesh.shape_key_add(name='Basis')
        mesh.shape_key_add(name='expression')
        self.activate(mesh)
        other[2].select_set(True)
        bpy.context.view_layer.update()
        kept = [outer, arm, mesh, sibling, helper] + list(other[:3]) + other[3]
        matrices = {obj: obj.matrix_world.copy() for obj in kept}
        removed_names = [root.name] + [obj.name for group in groups for obj in [group, *group.children]]
        # Run the real registered operator, not a mocked deletion function.
        self.assertEqual(bpy.ops.mimi.remove_mmd_redundant_parts(), {'FINISHED'})
        for name in removed_names:
            self.assertNotIn(name, bpy.data.objects)
        for obj, matrix in matrices.items():
            delta = max(abs(obj.matrix_world[row][col] - matrix[row][col]) for row in range(4) for col in range(4))
            self.assertLess(delta, 1e-5, obj.name)
        # Skeleton binding, selection, shape keys and external parent survive.
        self.assertEqual(arm.parent, outer)
        self.assertEqual(helper.parent, outer)
        self.assertEqual(mesh.parent, arm)
        self.assertEqual(modifier.object, arm)
        self.assertEqual(len(mesh.data.shape_keys.key_blocks), 2)
        self.assertEqual(bpy.context.active_object, mesh)
        self.assertFalse(panel.MIMI_OT_remove_mmd_redundant_parts.poll(bpy.context))

    def test_metadata_and_missing_groups(self):
        # Metadata permits renamed containers and roots with no physics left.
        for physics in [True, False]:
            root, arm, mesh, groups = model('metadata', metadata=True, physics=physics)
            self.activate(mesh)
            self.assertEqual(panel.find_mmd_root(mesh), root)
            self.assertEqual(panel.remove_redundant_parts(bpy.context, mesh), 5 if physics else 1)
            self.assertIsNone(arm.parent)

    def test_invalid_selection_and_nested_model(self):
        # Ordinary objects and physics descendants must never enable cleanup.
        ordinary = new_object('ordinary', 'MESH', new_object('ordinary_root'))
        self.assertIsNone(panel.find_mmd_root(ordinary))
        root, arm, mesh, groups = model('valid')
        self.assertIsNone(panel.find_mmd_root(groups[0].children[0]))
        self.activate(root)
        self.assertFalse(panel.MIMI_OT_remove_mmd_redundant_parts.poll(bpy.context))
        self.activate(mesh)
        # A suspicious skeleton inside physics cancels before changing anything.
        new_object('unexpected_arm', 'ARMATURE', groups[0])
        before = set(bpy.data.objects)
        with self.assertRaises(ValueError):
            panel.remove_redundant_parts(bpy.context, mesh)
        self.assertEqual(before, set(bpy.data.objects))
        self.assertEqual(arm.parent, root)
        # Edit mode is rejected even when the main-model hierarchy is valid.
        bpy.ops.object.mode_set(mode='EDIT')
        self.assertFalse(panel.MIMI_OT_remove_mmd_redundant_parts.poll(bpy.context))
        bpy.ops.object.mode_set(mode='OBJECT')

    def test_panel_and_translation(self):
        # Check panel placement and captions without opening a GUI window.
        self.assertEqual(panel.MIMI_PT_mmd_model.bl_order, 11)
        self.assertEqual(panel.MIMI_PT_mmd_model.bl_category, 'MIMITools')
        i18n.apply_language('zh')
        self.assertEqual(panel.MIMI_PT_mmd_model.bl_label, 'MMD模型处理')
        self.assertEqual(i18n.tr('Delete Redundant Parts'), '删除冗余部件')
        i18n.apply_language('en')


def main():
    # Exercise register/unregister/re-register so add-on reload remains safe.
    print('Blender version:', bpy.app.version_string)
    panel.register()
    panel.unregister()
    panel.register()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CleanupTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print('RESULT ' + json.dumps({'tests': result.testsRun, 'success': result.wasSuccessful()}))
        if not result.wasSuccessful():
            raise RuntimeError('MMD cleanup integration checks failed')
    finally:
        # Remove test-only classes even when a check fails.
        panel.unregister()


if __name__ == '__main__':
    main()
