"""Check imported blueprint positions with real Blender frame parenting.

Run with Blender --background --factory-startup --python-exit-code 1
--python tools/test_import_blueprint_layout_blender.py.
"""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy

# Load this checkout instead of a possibly outdated installed add-on.
# Factory startup ensures no interactive scene or user file is changed.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
importer = importlib.import_module(ROOT.name + '.ui.ui_func_import_mmt')


def absolute_position(node):
    # Child locations are relative to their frame, not to the node editor.
    # Walk all parents so nested frames cannot hide a backwards connection.
    x, y = node.location
    parent = node.parent
    while parent is not None:
        x += parent.location.x
        y += parent.location.y
        parent = parent.parent
    return x, y


class ImportLayoutTests(unittest.TestCase):
    def setUp(self):
        # Use real RNA nodes: mocks cannot reproduce frame coordinate changes.
        self.tree = bpy.data.node_groups.new('import_layout', 'MIMIBlueprintTreeType')
        # Production import retains trees with a fake user for later exports.
        self.tree.use_fake_user = True
        self.objects = []

    def tearDown(self):
        # Delete only data created by this isolated factory-process test.
        bpy.data.node_groups.remove(self.tree)
        for obj in self.objects:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)

    def make_import(self, count):
        # Socket count must not affect the horizontal order of the graph.
        # Include a large import matching the tall list in the reported image.
        imported = {}
        for index in range(count):
            mesh = bpy.data.meshes.new('layout_mesh')
            obj = bpy.data.objects.new('layout_object', mesh)
            self.objects.append(obj)
            imported[str(index)] = (obj, 'submesh_' + str(index))
        model = SimpleNamespace(parse_new_format_name=lambda name: None)
        group = self.tree.nodes.new('MIMINode_Object_Group')
        with patch.object(importer.GlobalConfig, 'get_workspace_name', return_value='layout_workspace'):
            _, _, right = importer._create_and_layout_obj_info_nodes(self.tree, group, imported, model)
        output = self.tree.nodes.new('MIMINode_Result_Output')
        output.location = (right + 480.0, -200.0)
        importer._link_group_to_output(self.tree, group, output)
        importer._layout_imported_blueprint(self.tree)
        return group, output

    def assert_forward_links(self):
        # Every connected source must end before its target begins.
        # Testing world coordinates catches regressions caused by NodeFrame.
        for link in self.tree.links:
            source_x, _ = absolute_position(link.from_node)
            target_x, _ = absolute_position(link.to_node)
            self.assertGreaterEqual(target_x - source_x - link.from_node.width, 80.0,
                                    (link.from_node.name, link.to_node.name, source_x, target_x))

    def test_layout_ignores_creation_order_and_old_positions(self):
        # Reproduce the reported result node on the left of its own sources.
        # Keep the list and group parented to exercise absolute coordinates.
        group, output = self.make_import(29)
        output.location = (-900.0, 0.0)
        group.location.x = -400.0
        importer._layout_imported_blueprint(self.tree)
        self.assert_forward_links()

    def test_face_export_precedes_final_output(self):
        # Face export is an intermediate node, not a sibling of Generate Mod.
        # Both the regular group and the face branch must feed forward.
        group, output = self.make_import(2)
        source = next(node for node in self.tree.nodes if node.bl_idname == 'MIMINode_Object_List')
        face = self.tree.nodes.new('MIMINode_Face_Mod_Export')
        face.location = output.location
        self.tree.links.new(source.outputs[1], face.inputs[0])
        importer._link_group_to_output(self.tree, face, output)
        importer._layout_imported_blueprint(self.tree)
        self.assert_forward_links()
        # Same-layer siblings must not overlap, even with large input lists.
        self.assertEqual(absolute_position(group)[0], absolute_position(face)[0])
        self.assertGreater(abs(absolute_position(group)[1] - absolute_position(face)[1]), 200.0)

    def test_refresh_import_uses_dependency_layout(self):
        # Exercise the production refresh entry point, not just its helper.
        # Workspace discovery is mocked; node creation and positioning stay real.
        group, output = self.make_import(2)
        imported = {str(index): (obj, 'submesh_' + str(index))
                    for index, obj in enumerate(self.objects)}
        model = SimpleNamespace(parse_new_format_name=lambda name: None)
        with patch.object(importer.GlobalConfig, 'get_workspace_name', return_value=self.tree.name), \
                patch.object(importer, 'WorkSpaceModel', return_value=model), \
                patch.object(importer.BlueprintExportHelper, 'reveal_tree_in_node_editors'), \
                patch.object(importer, '_layout_imported_blueprint', wraps=importer._layout_imported_blueprint) as layout:
            importer._generate_blueprint_for_imported_objects(bpy.context, imported, ['submesh_0', 'submesh_1'])
        layout.assert_called_once_with(self.tree)
        self.assert_forward_links()
        # The final pass must also preserve the importer's deselected state.
        self.assertFalse(any(node.select for node in self.tree.nodes))

    def test_cycle_leaves_positions_unchanged(self):
        # Imported graphs are acyclic; malformed data must not hang the editor.
        # Planning before moving avoids half-rearranged graphs on failure.
        group, output = self.make_import(1)
        other = self.tree.nodes.new('MIMINode_Object_Group')
        self.tree.links.new(group.outputs[0], other.inputs[0])
        self.tree.links.new(other.outputs[0], group.inputs[-1])
        before = {node.name: tuple(node.location) for node in self.tree.nodes}
        self.assertFalse(importer._layout_imported_blueprint(self.tree))
        self.assertEqual(before, {node.name: tuple(node.location) for node in self.tree.nodes})

    def test_large_import_flows_left_to_right(self):
        # Verify the exact import helper before any editor has drawn the tree.
        # Blender must not need a redraw to obtain correct node coordinates.
        self.make_import(29)
        self.assert_forward_links()

    def test_single_object_flows_left_to_right(self):
        # A minimal graph still needs the same source/group/output ordering.
        self.make_import(1)
        self.assert_forward_links()


# Ignore Blender's own command-line arguments when invoking unittest.
if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
