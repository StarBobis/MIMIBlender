"""Exercise blueprint menu callbacks in factory-startup Blender.

Run with --background --factory-startup --python-exit-code 1 --python this_file.
No user scene or preferences are opened, saved, or changed.
"""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy

# Load the checkout through the shipped registration entry point.
# Menu-only imports would hide missing node/operator registration.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
menus = addon.blueprint_node_menu
from MIMIBlender.common.global_config import GlobalConfig, LogicName


class MenuLayout:
    # Capture operator properties as well as labels: a label alone does not
    # prove that the entry creates a valid, registered blueprint node.
    def __init__(self):
        self.operators = []
        self.menus = []

    def operator(self, identifier, **kwargs):
        # Real RNA lookup rejects entries pointing to unregistered operators.
        namespace, name = identifier.split('.')
        getattr(getattr(bpy.ops, namespace), name).get_rna_type()
        properties = SimpleNamespace()
        self.operators.append((identifier, properties))
        return properties

    def menu(self, identifier, **kwargs):
        # Submenus must also exist after the complete add-on registers.
        assert bpy.types.Menu.bl_rna_get_subclass_py(identifier) is not None
        self.menus.append(identifier)

    def separator(self):
        pass


class BlueprintMenuTests(unittest.TestCase):
    def setUp(self):
        # Use a real SpaceNodeEditor so the production context guard runs.
        # All temporary data belongs to this isolated Blender process.
        self.area = bpy.context.screen.areas[0]
        self.old_area_type = self.area.type
        self.area.type = 'NODE_EDITOR'
        self.area.spaces.active.tree_type = 'MIMIBlueprintTreeType'
        self.tree = bpy.data.node_groups.new('menu_regression', 'MIMIBlueprintTreeType')
        self.area.spaces.active.node_tree = self.tree

    def tearDown(self):
        # Restore the factory editor before disposing of its test tree.
        self.area.type = self.old_area_type
        bpy.data.node_groups.remove(self.tree)

    def draw(self, callback):
        # Invoke the actual callback without Blender swallowing exceptions
        # as it does when a popup partially draws on screen.
        layout = MenuLayout()
        with bpy.context.temp_override(area=self.area):
            callback(SimpleNamespace(layout=layout), bpy.context)
        return layout

    def test_add_menu_for_every_preset(self):
        # The missing LogicName import used to truncate every preset at
        # Generate Mod, before textures, timelines, Switch Key, and Frame.
        presets = [value for key, value in vars(LogicName).items()
                   if not key.startswith('_') and isinstance(value, str)]
        for preset in ['', *presets]:
            with self.subTest(preset=preset), patch.object(GlobalConfig, 'logic_name', preset):
                layout = self.draw(menus.draw_node_add_menu)
                nodes = {properties.type for _, properties in layout.operators}
                self.assertTrue({
                    'MIMINode_Object_Info', 'MIMINode_Object_List',
                    'MIMINode_Object_Group', 'MIMINode_Result_Output',
                    'MIMINode_Face_Mod_Export', 'MIMINode_SwitchKey', 'NodeFrame',
                }.issubset(nodes))
                self.assertEqual(set(layout.menus), {'MIMI_MT_texture_assign', 'MIMI_MT_dynamic_mod'})
                # Keep preset-specific capabilities confined to their games.
                # Explicit expectations avoid testing a helper against itself.
                self.assertEqual('MIMINode_WWMI_Mod_Info' in nodes, preset == 'WWMI')
                self.assertEqual('MIMINode_NarakaCrossIBRender' in nodes, preset in {'Naraka', 'GF2', 'PGR'})
                for node_type in nodes:
                    node = self.tree.nodes.new(node_type)
                    self.tree.nodes.remove(node)

    def test_texture_and_dynamic_submenus(self):
        # Every restored submenu must lead to usable nodes, not empty entries.
        expected = (
            (menus.MIMIMT_TextureAssignMenu, {
                'MIMINode_Texture_Bind', 'MIMINode_Hash_Texture_Bind',
                'MIMINode_Texture_Global', 'MIMINode_Hash_Texture_Global'}),
            (menus.MIMIMT_DynamicModMenu, {
                'MIMINode_TimeSwitch', 'MIMINode_TimePosSwitch', 'MIMINode_TimeShapeKey'}),
        )
        for menu, node_types in expected:
            layout = self.draw(menu.draw)
            self.assertEqual({props.type for _, props in layout.operators}, node_types)
            for node_type in node_types:
                node = self.tree.nodes.new(node_type)
                self.tree.nodes.remove(node)

    def test_context_menu_actions(self):
        # These commands are appended to the same right-click popup that
        # exposes NODE_MT_add when the blueprint selection is empty.
        layout = self.draw(menus.draw_node_context_menu)
        self.assertEqual({name for name, _ in layout.operators}, {
            'mimi.make_group', 'mimi.align_nodes', 'mimi.batch_connect_nodes',
            'mimi.refresh_blueprint', 'mimi.batch_set_selected_object_node_submesh',
        })

    def test_other_editors_stay_unchanged(self):
        # Shared Blender menu hooks must not leak blueprint commands into
        # shader editors or ordinary object-selection contexts.
        self.area.spaces.active.tree_type = 'ShaderNodeTree'
        for callback in (menus.draw_node_add_menu, menus.draw_node_context_menu):
            layout = self.draw(callback)
            self.assertEqual((layout.operators, layout.menus), ([], []))
        self.area.type = 'VIEW_3D'
        for callback in (menus.draw_node_add_menu, menus.draw_node_context_menu):
            layout = self.draw(callback)
            self.assertEqual((layout.operators, layout.menus), ([], []))


if __name__ == '__main__':
    # Keep a nonzero exit code on assertion failures for automated runners.
    # Unregistering also exercises the lifecycle of both restored submenus.
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(BlueprintMenuTests))
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError('Blueprint menu regression failed')
