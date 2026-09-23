"""Blender integration tests for refresh-driven global Hash replacements.

Run with blender -b --factory-startup --python-exit-code 1 --python this_file.
All workspace metadata, previews and generated textures live in a temp folder.
"""
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
from MIMIBlender.blueprint import blueprint_node_hash_texture as nodes
from MIMIBlender.blueprint import hash_texture_preview as previews
from MIMIBlender.model.blueprint_model import BluePrintModel
from MIMIBlender.common.global_config import GlobalConfig
from MIMIBlender.common.m_ini_builder import M_IniBuilder
from MIMIBlender.common.m_ini_helper import M_IniHelper


class LayoutRecorder:
    """Record the node controls without requiring a live editor area."""
    def __init__(self):
        self.properties = []
        self.operators = []
        self.icons = []
        self.labels = []
        self.button_texts = []

    def row(self, **kwargs):
        return self

    column = row
    box = row

    def label(self, **kwargs):
        self.labels.append(kwargs.get('text', ''))

    def prop(self, data, name, **kwargs):
        self.properties.append(name)

    def operator(self, name, **kwargs):
        self.operators.append(name)
        self.button_texts.append(kwargs.get('text', ''))
        return SimpleNamespace()

    def template_list(self, *args, **kwargs):
        pass

    def template_icon(self, **kwargs):
        self.icons.append(kwargs['icon_value'])


class GlobalHashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree = bpy.data.node_groups.new('global_test', 'MIMIBlueprintTreeType')
        self.node = self.tree.nodes.new('MIMINode_Hash_Texture_Global')
        self.addCleanup(bpy.data.node_groups.remove, self.tree)
        self.addCleanup(previews.clear_previews)
        self.workspace = patch.object(GlobalConfig, 'path_workspace_folder', return_value=str(self.root))
        self.workspace.start()
        self.addCleanup(self.workspace.stop)

        # Use genuine small PNG images for both native preview loading and
        # byte-for-byte export verification. No user's Image is reloaded.
        self.image_path = self.root / 'replacement.png'
        image = bpy.data.images.new('test_preview', width=8, height=8)
        image.generated_color = (1, 0, 0, 1)
        image.filepath_raw = str(self.image_path)
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)
        self.image_count = len(bpy.data.images)

    def mark_json(self, lod, folder, marks):
        # This is the real extracted workspace layout; do not mock discovery
        # or the SubmeshJson parser, which are the purpose of Refresh.
        directory = self.root / lod / folder / 'TYPE_test'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'original.png').write_bytes(self.image_path.read_bytes())
        path = directory / (folder + '.json')
        path.write_text(json.dumps({'TextureMarkUpInfoList': marks}), encoding='utf-8')
        return path

    @staticmethod
    def mark(texture_hash, name='DiffuseMap', mark_type='Hash'):
        return {'MarkName': name, 'MarkType': mark_type, 'MarkHash': texture_hash,
                'MarkSlot': 'ps-t0', 'MarkFileName': 'original.png'}

    def refresh(self):
        result = bpy.ops.mimi.global_hash_refresh(node_name=self.node.name, tree_name=self.tree.name)
        self.assertIn('FINISHED', result)

    def test_scan_preserve_preview_and_export(self):
        first = self.mark_json('LOD0', '94517393-10-0', [
            self.mark('6077b727'), self.mark('10d9df5f', 'LightMap'),
            self.mark('aaaaaaaa', 'SlotOnly', 'Slot'),
        ])
        # The duplicate from another LOD must not create a second override.
        self.mark_json('LOD1', '94517393-10-0', [self.mark('6077b727')])
        self.refresh()
        self.assertEqual(len(self.node.texture_hash_items), 2)
        self.assertEqual(BluePrintModel._collect_global_hash_texture_bindings(self.tree), [])
        rows = {item.texture_hash: item for item in self.node.texture_hash_items}
        item = rows['6077b727']
        original = item.mark_source_file_path
        self.assertTrue(Path(original).is_file())
        self.assertEqual(item.mark_source_name, 'DiffuseMap')
        index = list(rows).index('6077b727')
        self.node.texture_hash_index = index
        bpy.ops.mimi.texhashbind_select_file(node_name=self.node.name, tree_name=self.tree.name,
                                            item_index=index, filepath=str(self.image_path))
        self.assertEqual(item.mark_source_file_path, original)

        # Selecting a file must leave the original preview intact. Repeated
        # drawing reuses the cache rather than adding Image datablocks.
        original_icon = previews.texture_icon(original)
        # Background Blender decodes thumbnails but has no GUI icon IDs.
        # Validate real image dimensions, then supply an ID only for the UI
        # branch assertion; the decoder and its cache remain unmocked above.
        self.assertEqual(tuple(next(iter(previews._collection.values())).image_size), (8, 8))
        self.assertEqual(original_icon, previews.texture_icon(original))
        layout = LayoutRecorder()
        with patch.object(nodes, 'texture_icon', return_value=1):
            self.node.draw_buttons(bpy.context, layout)
        self.assertEqual(len(layout.icons), 2)
        self.assertIn('mimi.global_hash_refresh', layout.operators)
        self.assertNotIn('mimi.texhashbind_add_item', layout.operators)
        self.assertNotIn('mimi.texhashbind_remove_item', layout.operators)
        for hidden_input in ('source_type', 'texture_hash', 'mark_name', 'resource_name'):
            self.assertNotIn(hidden_input, layout.properties)
        self.assertEqual(len(bpy.data.images), self.image_count)

        # Add a mark which changes sorted row indices. The replacement and
        # selection must follow the hash, not remain attached to an index.
        first.write_text(json.dumps({'TextureMarkUpInfoList': [
            self.mark('6077b727'), self.mark('00000001', 'NormalMap'),
        ]}), encoding='utf-8')
        self.refresh()
        item = self.node.texture_hash_items[self.node.texture_hash_index]
        self.assertEqual(item.texture_hash, '6077b727')
        self.assertEqual(item.file_path, str(self.image_path))
        bindings = BluePrintModel._collect_global_hash_texture_bindings(self.tree)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]['source_type'], 'FILE')

        output = self.root / 'Textures'
        with patch.object(GlobalConfig, 'path_generatemod_texture_folder', return_value=str(output)):
            builder = M_IniBuilder()
            M_IniHelper.generate_hash_style_global_texture_ini(builder, bindings)
            text = '\n'.join(line for section in builder.ini_section_list for line in section.SectionLineList)
            self.assertIn('filename = Textures\\6077b727_DiffuseMap.png', text)
            self.assertIn('[TextureOverride_Texture_6077b727]', text)
            self.assertEqual((output / '6077b727_DiffuseMap.png').read_bytes(), self.image_path.read_bytes())
            # Same output name, changed source bytes: refresh the exported copy.
            self.image_path.write_bytes(b'updated replacement bytes')
            M_IniHelper.generate_hash_style_global_texture_ini(M_IniBuilder(), bindings)
            self.assertEqual((output / '6077b727_DiffuseMap.png').read_bytes(), b'updated replacement bytes')

        # DDS replacements use the original marked DDS filename, not a
        # ResourceTex name or a source basename chosen by the file browser.
        dds_source = ROOT / 'resources' / 'DisplayMatalMap.dds'
        item.file_path = str(dds_source)
        bindings = BluePrintModel._collect_global_hash_texture_bindings(self.tree)
        with patch.object(GlobalConfig, 'path_generatemod_texture_folder', return_value=str(output)):
            M_IniHelper.generate_hash_style_global_texture_ini(M_IniBuilder(), bindings)
        self.assertEqual((output / '6077b727_DiffuseMap.dds').read_bytes(), dds_source.read_bytes())

        # Clear means no override; the original mark is still available.
        bpy.ops.mimi.texhashbind_clear_file(node_name=self.node.name, tree_name=self.tree.name,
                                           item_index=self.node.texture_hash_index)
        self.assertEqual(item.mark_source_file_path, original)
        restoration = BluePrintModel._collect_global_hash_texture_bindings(self.tree)
        self.assertTrue(restoration[0]['restore_original'])
        self.assertEqual(M_IniHelper._collect_hash_binding_managed_hashes({}, restoration), set())
        # Automatic export preserves existing files. Restore an edited row's
        # original bytes explicitly, or clearing would leave the old replacement.
        with patch.object(GlobalConfig, 'path_generatemod_texture_folder', return_value=str(output)):
            builder = M_IniBuilder()
            M_IniHelper.generate_hash_style_global_texture_ini(builder, restoration)
        self.assertEqual((output / '6077b727_DiffuseMap.png').read_bytes(), Path(original).read_bytes())
        self.assertFalse(any(section.SectionLineList for section in builder.ini_section_list))

    def test_same_name_different_hash_and_clone(self):
        # Semantic labels are not identities: two DiffuseMap marks with
        # distinct hashes must both be listed, even within one SubmeshJson.
        self.mark_json('LOD0', '94517393-10-0', [
            self.mark('6077b727'), self.mark('0cefa11c'),
        ])
        self.refresh()
        self.assertEqual(len(self.node.texture_hash_items), 2)
        original = self.node.texture_hash_items[0]
        original.file_path = str(self.image_path)
        original.enabled = False
        child = bpy.data.node_groups.new('global_clone', self.tree.bl_idname)
        self.addCleanup(bpy.data.node_groups.remove, child)
        clone = addon.blueprint_node_group._clone_node(self.node, child)
        copied = clone.texture_hash_items[0]
        self.assertTrue(copied.global_detected)
        self.assertFalse(copied.enabled)
        self.assertEqual(copied.file_path, original.file_path)
        self.assertEqual(copied.mark_source_file_path, original.mark_source_file_path)

    def test_dds_preview_and_cache_cleanup(self):
        # DDS is the common case for game textures. Exercise Blender's native
        # decoder as well as the PNG fixture, without creating Image blocks.
        texture = ROOT / 'resources' / 'DisplayMatalMap.dds'
        previews.texture_icon(str(texture))
        preview = next(iter(previews._collection.values()))
        self.assertGreater(preview.image_size[0], 0)
        self.assertGreater(preview.image_size[1], 0)
        self.assertEqual(len(bpy.data.images), self.image_count)
        previews.clear_previews()
        self.assertIsNone(previews._collection)
        self.assertEqual(len(previews._stamps), 0)

    def test_connected_scope_ports_refresh_and_export(self):
        from MIMIBlender.model.drawib_model import DrawIBModel
        lists = addon.blueprint_node_object_list
        groups = addon.blueprint_node_group
        # Workspace discovery sees both components, but the connected node
        # must only follow the selected Object List/custom group output port.
        self.mark_json('LOD0', '94517393-10-0', [self.mark('6077b727')])
        self.mark_json('LOD0', '94517393-10-10', [self.mark('0cefa11c')])
        connected = self.tree.nodes.new('MIMINode_Hash_Texture_Bind')
        child = bpy.data.node_groups.new('scope_group', self.tree.bl_idname)
        self.addCleanup(bpy.data.node_groups.remove, child)
        for name in ('one', 'two'):
            child.interface.new_socket(name=name, in_out='OUTPUT', socket_type='MIMISocketObject')
        output = child.nodes.new(groups.GROUP_OUTPUT_IDNAME)
        source = child.nodes.new('MIMINode_Object_List')
        for index, name in enumerate(('mesh_a', 'mesh_b')):
            lists._append_object_list_item(source, name)
            source.object_items[index].submesh_name = 'LOD0.94517393-' + str(index)
            child.links.new(source.outputs[index + 1], output.inputs[index])
        group = self.tree.nodes.new(groups.GROUP_NODE_IDNAME)
        group.node_tree = child
        self.tree.links.new(group.outputs[0], connected.inputs[0])
        self.refresh()
        self.assertEqual(len(self.node.texture_hash_items), 2)
        bpy.ops.mimi.global_hash_refresh(node_name=connected.name, tree_name=self.tree.name)
        self.assertEqual([item.texture_hash for item in connected.texture_hash_items], ['6077b727'])
        self.assertEqual(BluePrintModel._collect_hash_texture_bindings(connected), [])
        item = connected.texture_hash_items[0]
        item.file_path = str(self.image_path)
        original_path = item.mark_source_file_path
        bindings = BluePrintModel._collect_hash_texture_bindings(connected)
        self.assertEqual(bindings[0]['mark_name'], 'DiffuseMap')

        # Use the same adapter used by WWMI. An object elsewhere in this scope
        # need not have the selected mark name in its own Submesh metadata.
        call = SimpleNamespace(obj_name='mesh_a', hash_texture_binding_list=bindings,
                               get_condition_str=lambda: '')
        submesh = SimpleNamespace(submesh_name='LOD0.94517393-0', drawcall_model_list=[call])
        model = SimpleNamespace(draw_ib='94517393', d3d11_game_type=None,
                                submesh_model_list=[submesh], submesh_texturemarkinfolist_dict={})
        DrawIBModel.resolve_texture_bindings_for_model(model)
        # The scanned row carries the mark slot, so it binds inside this
        # object's draw section instead of replacing the hash globally.
        self.assertEqual(call.resolved_hash_texture_binding_list, [])
        self.assertEqual(call.resolved_hash_slot_binding_list[0]['texture_hash'], '6077b727')
        self.assertEqual(call.resolved_hash_slot_binding_list[0]['slot'], 'ps-t0')
        self.assertEqual(len(call.resolved_texture_slot_lines), 1)
        self.assertTrue(call.resolved_texture_slot_lines[0].startswith('ps-t0 = ResourceTex_'))
        output_path = self.root / 'Textures'
        object_target = output_path / '6077b727_DiffuseMap_94517393.png'
        with patch.object(GlobalConfig, 'path_generatemod_texture_folder', return_value=str(output_path)):
            M_IniHelper.move_object_texture_binding_files(model)
        self.assertEqual(object_target.read_bytes(), self.image_path.read_bytes())

        # Clearing a scanned row drops the local replacement, so the object
        # falls back to the global replacement of that hash.
        item.file_path = ''
        call.hash_texture_binding_list = BluePrintModel._collect_hash_texture_bindings(connected)
        self.assertTrue(call.hash_texture_binding_list[0]['restore_original'])
        DrawIBModel.resolve_texture_bindings_for_model(model)
        self.assertEqual(call.resolved_hash_slot_binding_list, [])
        self.assertEqual(call.resolved_texture_slot_lines, [])
        item.file_path = str(self.image_path)

        # Replacing the wire changes discovery, not just the displayed list.
        # Keep the old configured entry visibly stale rather than losing it.
        self.tree.links.new(group.outputs[1], connected.inputs[0])
        bpy.ops.mimi.global_hash_refresh(node_name=connected.name, tree_name=self.tree.name)
        by_hash = {row.texture_hash: row for row in connected.texture_hash_items}
        self.assertTrue(by_hash['6077b727'].mark_missing)
        self.assertFalse(by_hash['0cefa11c'].mark_missing)
        self.assertEqual(by_hash['6077b727'].mark_source_file_path, original_path)
        with self.assertRaisesRegex(ValueError, 'connected scope'):
            BluePrintModel._collect_hash_texture_bindings(connected)
        by_hash['6077b727'].file_path = ''
        for link in list(connected.inputs[0].links):
            self.tree.links.remove(link)
        bpy.ops.mimi.global_hash_refresh(node_name=connected.name, tree_name=self.tree.name)
        self.assertEqual(len(connected.texture_hash_items), 0)

    def test_conditional_states_keep_distinct_image_files(self):
        from MIMIBlender.model.drawib_model import DrawIBModel
        # Two states of the same hash must not overwrite one shared basename.
        # This exercises scanned rows, not the retained legacy source enums.
        alternate = self.root / 'alternate.png'
        alternate.write_bytes(b'alternate texture bytes')
        calls = []
        for state, path in enumerate((self.image_path, alternate)):
            binding = {'enabled': True, 'texture_hash': '6077b727', 'source_type': 'FILE',
                       'file_path': str(path), 'mark_name': 'DiffuseMap', 'preserve_mark_filename': True}
            calls.append(SimpleNamespace(obj_name='mesh', hash_texture_binding_list=[binding],
                                         get_condition_str=lambda state=state: '$state == ' + str(state)))
        submesh = SimpleNamespace(submesh_name='LOD0.94517393-0', drawcall_model_list=calls)
        model = SimpleNamespace(draw_ib='94517393', d3d11_game_type=None,
                                submesh_model_list=[submesh], submesh_texturemarkinfolist_dict={})
        DrawIBModel.resolve_texture_bindings_for_model(model)
        self.assertEqual(len({job[2] for job in model.object_texture_binding_file_list}), 2)
        builder = M_IniBuilder()
        M_IniHelper.generate_hash_style_object_texture_ini(builder, {'94517393': model})
        text = '\n'.join(line for section in builder.ini_section_list for line in section.SectionLineList)
        self.assertIn('if $state == 0', text)
        self.assertIn('if $state == 1', text)
        with patch.object(GlobalConfig, 'path_generatemod_texture_folder', return_value=str(self.root / 'Textures')):
            M_IniHelper.move_object_texture_binding_files(model)
        for _, source, target in model.object_texture_binding_file_list:
            self.assertEqual((self.root / 'Textures' / target).read_bytes(), Path(source).read_bytes())

    def test_hash_ui_live_chinese_and_one_file_chooser(self):
        from MIMIBlender.i18n import i18n
        base = addon.blueprint_node_base
        previous = i18n.get_language()
        self.addCleanup(i18n.apply_language, previous)
        i18n.apply_language('en')
        connected = self.tree.nodes.new('MIMINode_Hash_Texture_Bind')
        custom = self.tree.nodes.new('MIMINode_Hash_Texture_Global')
        custom.label = 'User custom title'
        # Simulate existing English labels loaded from an older blueprint.
        self.node.label = 'Global Hash Texture Bind'
        connected.label = 'Hash Texture Bind'
        for node in (self.node, connected):
            item = node.texture_hash_items.add()
            item.global_detected = True
            item.texture_hash = '6077b727'
            item.mark_source_name = 'DiffuseMap'
            item.mark_source_file_path = str(self.image_path)
            item.file_path = str(self.image_path)
        i18n.apply_language('zh')
        self.assertEqual(self.node.label, '全局Hash贴图绑定')
        self.assertEqual(connected.label, 'Hash贴图绑定')
        self.assertEqual(custom.label, 'User custom title')
        for node in (self.node, connected):
            layout = LayoutRecorder()
            with patch.object(nodes, 'texture_icon', return_value=1):
                node.draw_buttons(bpy.context, layout)
            self.assertIn('刷新检测Hash标记贴图', layout.button_texts)
            self.assertIn('选择替换贴图', layout.button_texts)
            self.assertIn('原标记贴图', layout.labels)
            self.assertIn('替换贴图', layout.labels)
            self.assertEqual(layout.operators.count('mimi.texhashbind_select_file'), 1)
            # A FILE_PATH property adds its own folder icon; forbid it here.
            self.assertNotIn('file_path', layout.properties)
            self.assertNotIn('source_type', layout.properties)
            self.assertNotIn('mimi.texhashbind_add_item', layout.operators)
            self.assertEqual(len(layout.icons), 2)
        layout = LayoutRecorder()
        base.MIMISocketObject.draw(connected.outputs[0], bpy.context, layout, connected, 'Output')
        self.assertIn('输出', layout.labels)
        i18n.apply_language('en')
        self.assertEqual(connected.label, 'Hash Texture Bind')
        self.assertEqual(self.node.label, 'Global Hash Texture Bind')

    def test_removed_mark_keeps_choice_but_blocks_export(self):
        metadata = self.mark_json('LOD0', '94517393-10-0', [self.mark('6077b727')])
        self.refresh()
        self.node.texture_hash_items[0].file_path = str(self.image_path)
        metadata.write_text(json.dumps({'TextureMarkUpInfoList': []}), encoding='utf-8')
        self.refresh()
        item = self.node.texture_hash_items[0]
        self.assertTrue(item.mark_missing)
        self.assertEqual(item.file_path, str(self.image_path))
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            BluePrintModel._collect_global_hash_texture_bindings(self.tree)
        item.enabled = False
        self.assertEqual(BluePrintModel._collect_global_hash_texture_bindings(self.tree), [])
        item.file_path = ''
        self.refresh()
        self.assertEqual(len(self.node.texture_hash_items), 0)


if __name__ == '__main__':
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GlobalHashTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError('Global Hash replacement tests failed')
