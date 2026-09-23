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

    def row(self, **kwargs):
        return self

    column = row
    box = row

    def label(self, **kwargs):
        pass

    def prop(self, data, name, **kwargs):
        self.properties.append(name)

    def operator(self, name, **kwargs):
        self.operators.append(name)
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
            self.assertIn('[TextureOverride_Texture_6077b727_Global]', text)
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
