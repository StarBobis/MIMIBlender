"""Optional real WWMI export coverage for the three non-global-Hash nodes.

Run in factory-startup background Blender with --python-exit-code 1.
MIMI_AUDIT_WORKSPACE selects an existing workspace (default JinXi).
All fixture images and outputs remain under repository tmp.
The user scene, source workspace and installed Mods are never overwritten.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
import bpy

# Register the checkout before importing any workspace objects or RNA nodes.
# This is an isolated Blender process, not the user's running editor.
# Saved preferences are never modified by registration or fixture import.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
from MIMIBlender.common.global_config import GlobalConfig
from MIMIBlender.ui.ui_func_import_mmt import ImprotFromWorkSpaceFull
from MIMIBlender.ui.ui_func_export import generate_mod_from_tree
from MIMIBlender.utils.json_utils import JsonUtils
from MIMIBlender.utils.command_utils import CommandUtils
from MIMIBlender.workspace.texture_metadata_helper import TextureMetadataResolver
from MIMIBlender.blueprint import blueprint_node_global_slot as global_slot

class Reporter:
    # A cancelled operation is a failure even if it leaves some output files.
    # Preserve the concrete exporter diagnostic in the background-process log.
    def report(self, levels, message):
        if 'ERROR' in levels:
            raise AssertionError(message)

name = os.environ.get('MIMI_AUDIT_WORKSPACE', 'JinXi')
workspace = Path('D:/MMTCacheFolder/WorkSpace/WWMI') / name
if not workspace.is_dir():
    raise RuntimeError('Set MIMI_AUDIT_WORKSPACE to an installed WWMI workspace')
folder = ROOT / 'tmp' / ('wwmi_texture_nodes_' + str(time.time_ns()))
folder.mkdir(parents=True)
GlobalConfig.read_from_main_json()

# The optional capture fixture has Hash-style marks. Supply a Slot-style view
# in memory for Slot tests, keeping the original resource paths and registers.
# This tests node routing without rewriting the user's texture-mark JSON.
original_loader = TextureMetadataResolver.load_submesh_texture_markup_info_from_all_submeshes
def slot_marks(*args, **kwargs):
    result = original_loader(*args, **kwargs)
    for marks in result.values():
        for mark in marks:
            mark.mark_type = 'Slot'
    return result

with patch.object(GlobalConfig, 'path_workspace_folder', return_value=str(workspace)), \
     patch.object(GlobalConfig, 'get_workspace_name', return_value=name), \
     patch.object(JsonUtils, 'SaveToFile'), patch.object(CommandUtils, 'OpenGeneratedModFolder'):
    bpy.context.scene.mimi_global_properties.import_merged_vgmap = 'MERGED'
    ImprotFromWorkSpaceFull(Reporter(), bpy.context)
    tree = bpy.data.node_groups[name]
    output = next(n for n in tree.nodes if n.bl_idname == 'MIMINode_Result_Output')
    sources = next(n for n in tree.nodes if n.bl_idname == 'MIMINode_Object_List')
    # Component 3 owns this fixture's DiffuseMap at ps-t2. Other components
    # must not receive a global Slot default intended only for Component 3.
    index = next(i for i, item in enumerate(sources.object_items) if item.submesh_name.endswith('-3'))
    submesh = sources.object_items[index].submesh_name
    from MIMIBlender.workspace.mmt_workspace import MMTWorkSpace
    json_path = Path(MMTWorkSpace.check_and_get_submesh_json_path(submesh))
    data = json.loads(json_path.read_text(encoding='utf-8-sig'))
    mark = next(m for m in data['TextureMarkUpInfoList'] if m['MarkName'] == 'DiffuseMap')
    original = str(json_path.parent / mark['MarkFileName'])
    image = bpy.data.images.new('texture_fixture', width=8, height=8)
    image.generated_color = (1, 0, 1, 1)
    image.filepath_raw = str(folder / 'replacement.png')
    image.file_format = 'PNG'
    image.save()
    image_path = image.filepath_raw
    bpy.data.images.remove(image)

    # Export one node at a time through the real blueprint and WWMI writer.
    # File existence alone is insufficient: inspect draw-local instructions,
    # reference restoration and actual DDS bytes after conversion.
    for mode in ('target_slot', 'target_hash', 'global_slot'):
        node_id = {'target_slot':'MIMINode_Texture_Bind', 'target_hash':'MIMINode_Hash_Texture_Bind', 'global_slot':'MIMINode_Texture_Global'}[mode]
        node = tree.nodes.new(node_id)
        outdir = folder / mode
        outdir.mkdir()
        contexts = []
        if mode == 'global_slot':
            tree.links.new(sources.outputs[0], output.inputs[0])
            item = node.items.add()
            item.identity = 'fixture'
            item.file_path = image_path
            contexts.append(patch.object(global_slot, 'scan_slot_marks', return_value={'fixture':(submesh, {'slot':mark['MarkSlot'], 'name':'DiffuseMap'}, original)}))
        else:
            # Replace only the output link, leaving source objects unchanged.
            # A targeted node applies only to the selected Component output.
            for link in list(output.inputs[0].links):
                tree.links.remove(link)
            tree.links.new(sources.outputs[index + 1], node.inputs[0])
            tree.links.new(node.outputs[0], output.inputs[0])
            if mode == 'target_slot':
                item = node.texture_slot_items.add()
                item.source_type = 'FILE'
                item.slot = mark['MarkSlot']
            else:
                item = node.texture_hash_items.add()
                item.source_type = 'FILE'
                item.texture_hash = mark['MarkHash']
                item.mark_source_slot = mark['MarkSlot']
            item.file_path = image_path
        item.output_name = mode + '_fixture'
        # Slot defaults run after local resolution, inside guarded WWMI model
        # initialization. The model has no standard naming method to borrow.
        from contextlib import ExitStack
        with ExitStack() as stack:
            for context in contexts:
                stack.enter_context(context)
            if mode != 'target_hash':
                stack.enter_context(patch.object(TextureMetadataResolver, 'load_submesh_texture_markup_info_from_all_submeshes', side_effect=slot_marks))
            stack.enter_context(patch.object(GlobalConfig, 'path_generate_mod_folder', return_value=str(outdir)))
            assert generate_mod_from_tree(tree, bpy.context, Reporter().report) == {'FINISHED'}
        ini = (outdir / (name + '.ini')).read_text(encoding='utf-8-sig')
        assert mark['MarkSlot'] + ' = Resource' in ini, mode
        assert ' = ref ' + mark['MarkSlot'] in ini, mode
        target = outdir / 'Textures' / (mode + '_fixture.dds')
        assert target.read_bytes().startswith(b'DDS '), mode
        from MIMIBlender.texcomb.core.dds_match import read_dds_metadata
        assert read_dds_metadata(str(target)).storage_key == read_dds_metadata(original).storage_key, mode
        # Compare actual replacement bytes, not merely a valid DDS header.
        # The independent staging call uses the same captured format authority.
        from MIMIBlender.texcomb.core.dds_match import DDSReplacementStage
        with DDSReplacementStage() as stage:
            expected = stage.prepare(image_path, original, False, color_mode='AUTO', data_hint='DiffuseMap')
            assert target.read_bytes() == Path(expected).read_bytes(), mode
        if mode == 'global_slot':
            assert 'ResourceGlobalSlot_' in ini
        tree.nodes.remove(node)
    print('WWMI_TEXTURE_NODES_PASS', folder)
addon.unregister()
