"""Safely roundtrip an optional real WWMI workspace in factory-startup Blender.

Run with --background --factory-startup --python-exit-code 1 --python this_file.
MIMI_AUDIT_WORKSPACE selects a folder name under the local WWMI workspace root.
MIMI_AUDIT_IMPORT_MODE=PER_COMPONENT tests local import/export independently.
Default import tests MergedComponent, Merged, and UniComponent sequentially.
Source files and selection records are read-only; outputs stay under tmp.
These checks exercise Blender and generated resources, not in-game rendering.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
import bpy

# Use this repository rather than a possibly older installed release.
# This program must run in an isolated Blender process, never a user scene.
# All output paths are controlled below and never point into the fixture.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
from MIMIBlender.common.global_config import GlobalConfig
from MIMIBlender.games.wwmi.model import DrawIBModelWWMI
from MIMIBlender.ui.ui_func_import_mmt import ImprotFromWorkSpaceFull
from MIMIBlender.ui.ui_func_export import generate_mod_from_tree
from MIMIBlender.utils.json_utils import JsonUtils
from MIMIBlender.utils.command_utils import CommandUtils


class Reporter:
    # A cancelled or partially successful UI operation is a failed regression.
    # Raising also retains the precise report in Blender's diagnostic log.
    # Successful reports remain visible when troubleshooting a real fixture.
    def report(self, levels, message):
        print(sorted(levels), message)
        if 'ERROR' in levels:
            raise AssertionError(message)


def snapshot():
    # Hash source geometry, all weights, and every shape coordinate, not only
    # object counts. Export may create and remove copies but cannot modify any
    # of these data. Numeric group names are part of the identity contract.
    result = {}
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        values = [[list(v.co), [(g.group, g.weight) for g in v.groups]] for v in obj.data.vertices]
        shapes = []
        if obj.data.shape_keys:
            shapes = [(key.name, [list(v.co) for v in key.data]) for key in obj.data.shape_keys.key_blocks]
        data = [values, shapes, [g.name for g in obj.vertex_groups], [list(p.vertices) for p in obj.data.polygons]]
        result[obj.name] = hashlib.sha256(json.dumps(data).encode()).hexdigest()
    return result


# Each process imports exactly once. Architecture changes are valid between
# globally named modes; PerComponent must instead start from a local import.
# Missing optional fixtures skip explicitly rather than pretending to pass.
name = os.environ.get('MIMI_AUDIT_WORKSPACE', 'Xin')
workspace = Path(r'D:\MMTCacheFolder\WorkSpace\WWMI') / name
if not workspace.is_dir():
    print('SKIP: optional real workspace is unavailable:', name)
else:
    GlobalConfig.read_from_main_json()
    properties = bpy.context.scene.mimi_global_properties
    import_mode = os.environ.get('MIMI_AUDIT_IMPORT_MODE', 'MERGED_COMPONENT')
    properties.import_merged_vgmap = import_mode
    modes = ['PER_COMPONENT'] if import_mode == 'PER_COMPONENT' else ['MERGED_COMPONENT', 'MERGED', 'UNICOMPONENT']
    results = []
    with patch.object(GlobalConfig, 'path_workspace_folder', return_value=str(workspace)), patch.object(GlobalConfig, 'get_workspace_name', return_value=name), patch.object(JsonUtils, 'SaveToFile'):
        ImprotFromWorkSpaceFull(Reporter(), bpy.context)
        tree = bpy.data.node_groups[name]
        original = snapshot()
        original_objects = set(bpy.data.objects)
        original_meshes = set(bpy.data.meshes)
        # Default cube has no submesh binding and must not enter exported counts.
        # Imported objects use the LOD-qualified DrawIB component names.
        index_count = sum(len(obj.data.polygons) * 3 for obj in bpy.data.objects if obj.type == 'MESH' and obj.name.startswith('LOD'))
        for mode in modes:
            properties.import_merged_vgmap = mode
            folder = ROOT / 'tmp' / ('wwmi_roundtrip_' + name.lower() + '_' + mode.lower())
            folder.mkdir(exist_ok=True)
            exported = []
            original_write = DrawIBModelWWMI.write_buffer_files

            def record_write(model):
                # Check complete draw coverage before inspecting generated files.
                # A successful UniComponent split may still lose boundary faces;
                # exact source index coverage catches that silent data loss.
                exported.append({'draw_ib': model.draw_ib, 'indices': len(model.obj_buffer_model_wwmi.ib), 'stride': model.blend_remap_bone_count})
                return original_write(model)

            with patch.object(GlobalConfig, 'path_generate_mod_folder', return_value=str(folder)), patch.object(CommandUtils, 'OpenGeneratedModFolder'), patch.object(DrawIBModelWWMI, 'write_buffer_files', record_write):
                status = generate_mod_from_tree(tree, bpy.context, Reporter().report)
            assert status == {'FINISHED'}, status
            assert snapshot() == original, 'Export changed source geometry, groups, weights, or shapes'
            assert set(bpy.data.objects) == original_objects, 'Export left temporary objects'
            assert set(bpy.data.meshes) == original_meshes, 'Export left orphaned mesh copies'
            actual_indices = sum(item['indices'] for item in exported)
            assert actual_indices == index_count, (mode, actual_indices, index_count)
            results.append({'mode': mode, 'source_preserved': True, 'models': exported})
    print('AUDIT_RESULT ' + json.dumps({'workspace': name, 'results': results}))
addon.unregister()
