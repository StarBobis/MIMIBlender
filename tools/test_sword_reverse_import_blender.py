"""Headless regression checks for the Mod Reverse one-click import.

Run: blender -b --factory-startup --python-exit-code 1 -P this_file

The Mod Reverse panel can import from the folder MMT recorded, from one
workspace under Reversed, or from a folder the user picked by hand. A hand
picked folder used to be imported blindly: a wrong level, an empty folder or a
copy without buffers produced an empty collection and no explanation.

Coverage notes:
- The folder check is pure file inspection, so it runs without any real reverse
  output and never touches the user's own MMT cache folder.
- Every fixture lives in a temporary directory that the test removes again.
- All mesh fixtures follow the real ssmt_fmt layout written by MMT (one folder
  per DrawIB holding the data types plus their .buf / .ib buffers).
- The good fixture is a two triangle quad with Position and Texcoord, which is
  the smallest layout the importer accepts end to end.
- A broken data type points at a buffer file that does not exist, which is what
  a half copied reverse folder looks like.
- Refused folders must create neither a mesh object nor a collection: the empty
  reverse collection is exactly the reported bug.
- The recorded global format is patched so a stale configuration cannot decide
  the import format any more; the folder content must win.
- The panel hint is drawn through the real drawing function with a fake layout,
  because a headless run has no sidebar area to draw into.
- Both interface languages are checked, so the yes / no verdict stays
  translated.
- Registration runs register/unregister/register again, because the add-on
  updater reloads the add-on in a running Blender.
- The runner raises on failure so --python-exit-code reports a failing job.
"""
import importlib
import json
import os
import shutil
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import bpy

# Import only this feature and i18n, avoiding unrelated add-on startup work.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('MIMIBlender')
package.__path__ = [str(ROOT)]
sys.modules['MIMIBlender'] = package
probe = importlib.import_module('MIMIBlender.sword.reverse_source_probe')
panel = importlib.import_module('MIMIBlender.sword.ui_panel_sword')
global_config = importlib.import_module('MIMIBlender.common.global_config')
# The importer builds materials through the scene level add-on properties, so
# that property group must be registered like it is in a normal add-on start.
global_properties = importlib.import_module('MIMIBlender.common.mimi_global_properties')
i18n = importlib.import_module('MIMIBlender.i18n.i18n')
# Skeleton settings live in their own shared module now, because the same
# properties drive the workspace import too.
skeleton_ui = importlib.import_module('MIMIBlender.utils.skeleton_ui')

# Smallest importable quad: four vertices, six indices, two triangles.
_QUAD_POSITIONS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
_QUAD_TEXCOORDS = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
_QUAD_INDICES = [0, 1, 2, 2, 1, 3]


def _write_bytes(file_path, data):
    """Write raw vertex or index bytes, creating missing folders."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'wb') as handle:
        handle.write(data)


def _data_type_json(drawib, index_file_name, position_file_name, texcoord_file_name):
    """Build one data type description in the MMT ssmt_fmt Json shape."""
    return {
        'GamePreset': 'GIMI',
        'WorkGameType': 'Position-Texcoord',
        'IndexOffset': 0,
        'IndexCount': len(_QUAD_INDICES),
        'IndexBufferList': [
            {
                'DXGI_FORMAT': 'DXGI_FORMAT_R16_UINT',
                'FileName': index_file_name,
                'IndexOffset': 0,
                'IndexCount': len(_QUAD_INDICES),
            }
        ],
        'CategoryBufferList': [
            {
                'FileName': position_file_name,
                'Type': 'Normal',
                'D3D11ElementList': [
                    {
                        'SemanticName': 'POSITION',
                        'SemanticIndex': '0',
                        'Format': 'R32G32B32_FLOAT',
                        'ByteWidth': '12',
                        'ExtractSlot': 'vb0',
                        'ExtractTechnique': 'trianglelist',
                        'Category': 'Position',
                        'DrawCategory': 'Position',
                    }
                ],
            },
            {
                'FileName': texcoord_file_name,
                'Type': 'Normal',
                'D3D11ElementList': [
                    {
                        'SemanticName': 'TEXCOORD',
                        'SemanticIndex': '0',
                        'Format': 'R32G32_FLOAT',
                        'ByteWidth': '8',
                        'ExtractSlot': 'vb0',
                        'ExtractTechnique': 'trianglelist',
                        'Category': 'Texcoord',
                        'DrawCategory': 'Texcoord',
                    }
                ],
            },
        ],
    }


def build_importable_group(group_path, drawib='a1b2c3d4', broken_type=False):
    """Write one importable DrawIB folder; optionally add a broken data type."""
    os.makedirs(group_path, exist_ok=True)
    index_name = drawib + '.ib'
    position_name = drawib + '-Position.buf'
    texcoord_name = drawib + '-Texcoord.buf'

    index_data = struct.pack('<%dH' % len(_QUAD_INDICES), *_QUAD_INDICES)
    position_data = struct.pack('<%df' % (len(_QUAD_POSITIONS) * 3),
                                *[value for vertex in _QUAD_POSITIONS for value in vertex])
    texcoord_data = struct.pack('<%df' % (len(_QUAD_TEXCOORDS) * 2),
                                *[value for vertex in _QUAD_TEXCOORDS for value in vertex])
    _write_bytes(os.path.join(group_path, index_name), index_data)
    _write_bytes(os.path.join(group_path, position_name), position_data)
    _write_bytes(os.path.join(group_path, texcoord_name), texcoord_data)

    good_json = _data_type_json(drawib, index_name, position_name, texcoord_name)
    with open(os.path.join(group_path, 'GoodType.json'), 'w', encoding='utf-8') as handle:
        json.dump(good_json, handle)

    if broken_type:
        # A data type whose buffer files were lost during a copy.
        broken_json = _data_type_json(drawib, 'missing_buffer.ib', position_name, texcoord_name)
        with open(os.path.join(group_path, 'BrokenType.json'), 'w', encoding='utf-8') as handle:
            json.dump(broken_json, handle)
    return group_path


def build_blend16_group(group_path, drawib='c0ffee16'):
    """Write one reverse DrawIB folder whose Blend buffer holds 16-bit bone ids.

    MMT writes this layout when the original WWMI mod remaps bone ids above 255
    (Blend.buf keeps component-local 8-bit ids, BlendRemapVertexVG.buf holds the
    real ones). The importer must read BLENDINDICES as 16-bit values, otherwise
    every id collapses into the low range and weights land on wrong bones.
    """
    os.makedirs(group_path, exist_ok=True)
    index_name = drawib + '.ib'
    position_name = drawib + '-Position.buf'
    blend_name = drawib + '-Blend.buf'

    # Index buffer: one quad, two triangles, 16-bit indices like the reverse.
    index_data = struct.pack('<%dH' % len(_QUAD_INDICES), *_QUAD_INDICES)
    position_data = struct.pack('<%df' % (len(_QUAD_POSITIONS) * 3),
                                *[value for vertex in _QUAD_POSITIONS for value in vertex])

    # Per vertex: four 16-bit ids followed by four 16-bit UNORM weights.
    # The first vertex carries ids far above 255 with a normalized 40000/25535
    # split, the remaining vertices keep a single id 7 at full weight.
    blend_data = struct.pack('<8H', 300, 301, 302, 0, 40000, 25535, 0, 0)
    for _ in range(len(_QUAD_POSITIONS) - 1):
        blend_data += struct.pack('<8H', 7, 0, 0, 0, 65535, 0, 0, 0)

    _write_bytes(os.path.join(group_path, index_name), index_data)
    _write_bytes(os.path.join(group_path, position_name), position_data)
    _write_bytes(os.path.join(group_path, blend_name), blend_data)

    data_type = {
        'GamePreset': 'WWMI',
        'WorkGameType': 'GPU_P12_TA4_N4_C4_C1-4_BI16x4_BW16x4_T4_T1-4_T2-4_',
        'IndexOffset': 0,
        'IndexCount': len(_QUAD_INDICES),
        'IndexBufferList': [
            {
                'DXGI_FORMAT': 'DXGI_FORMAT_R16_UINT',
                'FileName': index_name,
                'IndexOffset': 0,
                'IndexCount': len(_QUAD_INDICES),
            }
        ],
        'CategoryBufferList': [
            {
                'FileName': position_name,
                'Type': 'Normal',
                'D3D11ElementList': [
                    {
                        'SemanticName': 'POSITION',
                        'SemanticIndex': '0',
                        'Format': 'R32G32B32_FLOAT',
                        'ByteWidth': '12',
                        'ExtractSlot': 'vb0',
                        'ExtractTechnique': 'trianglelist',
                        'Category': 'Position',
                        'DrawCategory': 'Position',
                    }
                ],
            },
            {
                'FileName': blend_name,
                'Type': 'Normal',
                'D3D11ElementList': [
                    {
                        'SemanticName': 'BLENDINDICES',
                        'SemanticIndex': '0',
                        'Format': 'R16G16B16A16_UINT',
                        'ByteWidth': '8',
                        'ExtractSlot': 'vb4',
                        'ExtractTechnique': 'trianglelist',
                        'Category': 'Blend',
                        'DrawCategory': 'Blend',
                    },
                    {
                        'SemanticName': 'BLENDWEIGHT',
                        'SemanticIndex': '0',
                        'Format': 'R16G16B16A16_UNORM',
                        'ByteWidth': '8',
                        'ExtractSlot': 'vb4',
                        'ExtractTechnique': 'trianglelist',
                        'Category': 'Blend',
                        'DrawCategory': 'Blend',
                    },
                ],
            },
        ],
    }
    with open(os.path.join(group_path, 'Blend16.json'), 'w', encoding='utf-8') as handle:
        json.dump(data_type, handle)
    return group_path


class FakeLayout:
    """Stand-in for a Blender UI layout that records the drawn text."""

    def __init__(self):
        self.labels = []
        self.operators = []

    def box(self):
        return self

    def row(self, align=True):
        return self

    def column(self, align=True):
        return self

    def label(self, text='', icon=''):
        self.labels.append(text)

    def operator(self, idname, text='', icon=''):
        self.operators.append(idname)

    def prop(self, data, name, text=''):
        pass


class ReverseImportTests(unittest.TestCase):
    """Folder check, import rollback and panel hint behavior."""

    def setUp(self):
        # Every test gets its own folder tree, removed again in tearDown.
        self.temp_root = tempfile.mkdtemp(prefix='mimi_reverse_check_')
        self.scene = bpy.context.scene
        self.scene.mimi_sword_reverse_source_mode = 'CUSTOM'
        self.scene.mimi_sword_custom_reverse_output_folder_path = ''
        panel.clear_sword_reverse_probe_cache()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)
        panel.clear_sword_reverse_probe_cache()
        # Keep test order independent: the forwarding test changes the choice.
        self.scene.mimi_sword_skeleton_cleanup = 'NONE'

    def folder(self, name):
        """Return a fresh sub folder of the temporary root."""
        path = os.path.join(self.temp_root, name)
        os.makedirs(path, exist_ok=True)
        return path

    def run_import(self, folder_path):
        """Run the real operator and report what it created / reported.

        Only names are returned: the created data is removed again right away,
        and a removed Blender data block cannot be inspected any more.
        """
        self.scene.mimi_sword_reverse_source_mode = 'CUSTOM'
        self.scene.mimi_sword_custom_reverse_output_folder_path = folder_path
        panel.clear_sword_reverse_probe_cache()

        objects_before = set(bpy.data.objects)
        collections_before = set(bpy.data.collections)
        message = ''
        try:
            bpy.ops.mimi.import_all_reverse()
        except Exception as error:
            # Blender turns an operator error report into an exception here.
            message = str(error)

        new_objects = [obj for obj in bpy.data.objects if obj not in objects_before]
        new_collections = [col for col in bpy.data.collections if col not in collections_before]
        result = {
            'object_names': [obj.name for obj in new_objects],
            'collection_names': [col.name for col in new_collections],
            # A parent collection is meant to stay empty (its meshes live in the
            # leaf collections), so only empty leaves are a bug.
            'empty_leaf_names': [
                col.name for col in new_collections
                if len(col.objects) == 0 and len(col.children) == 0
            ],
            # Numeric vertex group names are the bone ids of the reversed mesh;
            # keeping them here proves 16-bit ids survived the import.
            'vertex_group_ids': {
                obj.name: sorted(int(group.name) for group in obj.vertex_groups
                                 if group.name.isdigit())
                for obj in new_objects if obj.type == 'MESH'
            },
            # The one-click import must follow the mirror workflow mode: the
            # default keeps the game's mirrored orientation, the non-mirrored
            # workflow bakes an X reflection into the mesh.
            'x_ranges': {
                obj.name: (min(vertex.co.x for vertex in obj.data.vertices),
                           max(vertex.co.x for vertex in obj.data.vertices))
                for obj in new_objects if obj.type == 'MESH'
            },
            'mirror_markers': {
                obj.name: bool(obj.get('MIMI:MirrorWorkflowApplied', False))
                for obj in new_objects if obj.type == 'MESH'
            },
            'message': message,
        }
        # Clean up whatever the import created, so tests stay independent.
        for obj in new_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for collection in new_collections:
            if collection.name in bpy.data.collections:
                bpy.data.collections.remove(collection)
        return result

    def draw_hint(self, folder_path):
        """Draw the panel hint for one folder and return the fake layout."""
        self.scene.mimi_sword_reverse_source_mode = 'CUSTOM'
        self.scene.mimi_sword_custom_reverse_output_folder_path = folder_path
        panel.clear_sword_reverse_probe_cache()
        layout = FakeLayout()
        panel.draw_sword_reverse_source_status(layout, bpy.context)
        return layout

    # ------------------------------------------------------------ folder check
    def test_probe_accepts_real_layout(self):
        # One DrawIB folder with a data type and its buffers is importable.
        root = self.folder('good')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        result = probe.probe_reverse_folder(root)
        self.assertEqual(result['status'], probe.STATUS_OK)
        self.assertEqual(result['format'], probe.SSMT_FMT)
        self.assertEqual(result['group_count'], 1)
        self.assertEqual(result['data_type_count'], 1)
        self.assertEqual(result['incomplete_groups'], [])

    def test_probe_ignores_folders_without_data(self):
        # A textures folder or an empty leftover folder must not become a group.
        root = self.folder('with_textures')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        os.makedirs(os.path.join(root, 'Textures'))
        result = probe.probe_reverse_folder(root)
        self.assertEqual(result['status'], probe.STATUS_OK)
        self.assertEqual(result['group_count'], 1)

    def test_probe_reports_wrong_level(self):
        # Selecting one DrawIB folder itself is reported as too deep.
        deep_root = self.folder('too_deep')
        group_path = build_importable_group(os.path.join(deep_root, 'a1b2c3d4'))
        self.assertEqual(probe.probe_reverse_folder(group_path)['status'], probe.STATUS_TOO_DEEP)

        # Selecting a folder that holds workspaces is reported as too shallow.
        shallow_root = self.folder('too_shallow')
        build_importable_group(os.path.join(shallow_root, 'WorkspaceA', 'a1b2c3d4'))
        shallow = probe.probe_reverse_folder(shallow_root)
        self.assertEqual(shallow['status'], probe.STATUS_TOO_SHALLOW)
        self.assertIn('WorkspaceA', shallow['suggested_folders'])

    def test_probe_reports_missing_folder_and_buffers(self):
        # A path that does not exist and a folder without data are told apart.
        missing = probe.probe_reverse_folder(os.path.join(self.temp_root, 'nope'))
        self.assertEqual(missing['status'], probe.STATUS_MISSING)

        empty = self.folder('empty')
        self.assertEqual(probe.probe_reverse_folder(empty)['status'], probe.STATUS_NO_DATA)

        # Data files without any buffer file can never be imported.
        no_buffer = self.folder('no_buffer')
        group_path = os.path.join(no_buffer, 'a1b2c3d4')
        os.makedirs(group_path)
        with open(os.path.join(group_path, 'GoodType.json'), 'w', encoding='utf-8') as handle:
            json.dump({'IndexBufferList': [], 'CategoryBufferList': []}, handle)
        result = probe.probe_reverse_folder(no_buffer)
        self.assertEqual(result['status'], probe.STATUS_NO_BUFFER)

    def test_probe_normalizes_typed_paths(self):
        # Explorer's "Copy as path" adds quotes that used to break the import.
        root = self.folder('quoted')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        self.assertEqual(probe.probe_reverse_folder('"' + root + '"')['status'], probe.STATUS_OK)
        self.assertEqual(probe.normalize_folder_path(''), '')

    def test_probe_detects_legacy_format(self):
        # A legacy ib_vb_fmt folder is recognised, but it is no longer imported:
        # the check must refuse it with a reason instead of saying "ok".
        root = self.folder('legacy')
        group_path = os.path.join(root, 'Body')
        os.makedirs(group_path)
        for name in ('Body.fmt', 'Body.ib', 'Body.vb'):
            with open(os.path.join(group_path, name), 'w', encoding='utf-8') as handle:
                handle.write('x')
        result = probe.probe_reverse_folder(root)
        self.assertEqual(result['status'], probe.STATUS_LEGACY_FORMAT)
        self.assertEqual(result['format'], '')
        self.assertEqual(result['fmt_count'], 1)

    # --------------------------------------------------------------- importing
    def test_import_imports_valid_folder(self):
        # The good fixture must still import meshes into DrawIB collections.
        root = self.folder('import_ok')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        result = self.run_import(root)
        self.assertTrue(result['object_names'], result['message'])
        self.assertTrue(any(name.startswith('a1b2c3d4') for name in result['collection_names']),
                        result['collection_names'])
        self.assertEqual(result['message'], '')

    def test_import_refuses_unusable_folder_without_collections(self):
        # Every refused folder must leave the outliner untouched: the reported
        # bug was an empty collection that looked like a successful import.
        cases = {
            'empty_folder': self.folder('refuse_empty'),
            'drawib_folder': build_importable_group(
                os.path.join(self.folder('refuse_deep'), 'a1b2c3d4')
            ),
        }
        # A folder whose sub folders are workspaces instead of DrawIB folders.
        shallow_root = self.folder('refuse_shallow')
        build_importable_group(os.path.join(shallow_root, 'WorkspaceA', 'a1b2c3d4'))
        cases['workspace_root'] = shallow_root

        for case_name, folder_path in cases.items():
            result = self.run_import(folder_path)
            self.assertEqual(result['object_names'], [], case_name)
            self.assertEqual(result['collection_names'], [], case_name)
            self.assertTrue(result['message'], case_name)

    def test_import_uses_folder_content(self):
        # The folder content decides which layout is imported; there is no
        # global format marker any more, so one valid ssmt_fmt folder imports.
        root = self.folder('folder_content')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        result = self.run_import(root)
        self.assertTrue(result['object_names'], result['message'])
        self.assertTrue(any(name.startswith('a1b2c3d4') for name in result['collection_names']),
                        result['collection_names'])

    def test_import_rolls_back_broken_data_type(self):
        # One broken data type is skipped, the good one still imports, and no
        # empty collection of the broken type stays behind.
        root = self.folder('partial')
        build_importable_group(os.path.join(root, 'a1b2c3d4'), broken_type=True)
        result = self.run_import(root)
        self.assertTrue(result['object_names'], result['message'])
        self.assertTrue(any(name.startswith('GoodType') for name in result['collection_names']),
                        result['collection_names'])
        self.assertFalse(any(name.startswith('BrokenType') for name in result['collection_names']),
                         result['collection_names'])
        self.assertEqual(result['empty_leaf_names'], [])

    def test_import_rolls_back_fully_broken_folder(self):
        # When every data type fails, the whole empty collection tree is removed.
        root = self.folder('all_broken')
        group_path = build_importable_group(os.path.join(root, 'a1b2c3d4'), broken_type=True)
        # Keep only the data type whose buffer file is missing.
        os.remove(os.path.join(group_path, 'GoodType.json'))
        result = self.run_import(root)
        self.assertEqual(result['object_names'], [])
        self.assertEqual(result['collection_names'], [])
        # Referenced-file preflight rejects this before collection creation.
        self.assertIn('No usable reverse descriptors', result['message'])

    # ------------------------------------------------------------- panel hint
    def test_panel_hint_reports_both_verdicts(self):
        root = self.folder('hint')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))

        hint = self.draw_hint(root)
        self.assertEqual(hint.labels[0], 'This folder can be imported normally')
        self.assertIn('1 DrawIB', hint.labels[1])
        self.assertIn('mimi.sword_check_reverse_source', hint.operators)

        hint = self.draw_hint('')
        self.assertEqual(hint.labels[0], 'This folder cannot be imported normally')
        self.assertIn('Custom folder is empty', ' '.join(hint.labels))

        # A too shallow pick names the workspaces worth selecting instead.
        shallow_root = self.folder('hint_shallow')
        build_importable_group(os.path.join(shallow_root, 'WorkspaceA', 'a1b2c3d4'))
        hint = self.draw_hint(shallow_root)
        self.assertEqual(hint.labels[0], 'This folder cannot be imported normally')
        self.assertIn('    WorkspaceA', hint.labels)

        # Groups without buffers are listed as unusable next to a good verdict.
        mixed_root = self.folder('hint_mixed')
        build_importable_group(os.path.join(mixed_root, 'a1b2c3d4'))
        bufferless = os.path.join(mixed_root, 'deadbeef')
        os.makedirs(bufferless)
        with open(os.path.join(bufferless, 'GoodType.json'), 'w', encoding='utf-8') as handle:
            json.dump({'IndexBufferList': [], 'CategoryBufferList': []}, handle)
        hint = self.draw_hint(mixed_root)
        self.assertEqual(hint.labels[0], 'This folder can be imported normally')
        self.assertIn('invalid descriptors', ' '.join(hint.labels))

    def test_panel_hint_is_translated(self):
        # The verdict must exist in Simplified Chinese as well.
        root = self.folder('hint_zh')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        i18n.apply_language('zh')
        try:
            self.assertEqual(self.draw_hint(root).labels[0], '该目录可以正常导入')
            self.assertEqual(self.draw_hint('').labels[0], '该目录不可以正常导入')
        finally:
            i18n.apply_language('en')

    def test_check_operator_accepts_and_rejects(self):
        # The re-check button reports the verdict without changing the scene.
        root = self.folder('check_button')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        self.scene.mimi_sword_reverse_source_mode = 'CUSTOM'
        self.scene.mimi_sword_custom_reverse_output_folder_path = root
        panel.clear_sword_reverse_probe_cache()
        self.assertEqual(bpy.ops.mimi.sword_check_reverse_source(), {'FINISHED'})

        self.scene.mimi_sword_custom_reverse_output_folder_path = self.folder('check_empty')
        panel.clear_sword_reverse_probe_cache()
        with self.assertRaises(RuntimeError):
            bpy.ops.mimi.sword_check_reverse_source()

    def test_probe_result_is_cached_per_folder(self):
        # The panel draws constantly, so the check must not re-read the folder
        # while the selected path stays the same.
        root = self.folder('cache')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        first = panel.get_sword_reverse_probe(root)
        second = panel.get_sword_reverse_probe(root)
        self.assertIs(first, second)

        # Deleting the content is invisible until the cache is cleared, which is
        # exactly what the update callbacks and the re-check button do.
        shutil.rmtree(root)
        self.assertIs(panel.get_sword_reverse_probe(root), first)
        panel.clear_sword_reverse_probe_cache()
        self.assertEqual(panel.get_sword_reverse_probe(root)['status'], probe.STATUS_MISSING)

    def test_invalid_json_and_missing_single_buffer_are_rejected(self):
        # A random sibling IB must not make malformed JSON importable.
        root = self.folder('invalid_reference')
        group = build_importable_group(os.path.join(root, 'a1b2c3d4'))
        os.remove(os.path.join(group, 'a1b2c3d4-Texcoord.buf'))
        self.assertEqual(probe.probe_reverse_folder(root)['status'], probe.STATUS_NO_BUFFER)
        with open(os.path.join(group, 'GoodType.json'), 'w') as handle:
            handle.write('{broken')
        self.assertEqual(probe.probe_reverse_folder(root)['status'], probe.STATUS_NO_BUFFER)

    def test_all_directories_are_checked(self):
        # Valid data after 200 empty folders was silently omitted by the cap.
        root = self.folder('large_root')
        for index in range(205):
            os.makedirs(os.path.join(root, 'empty_%03d' % index))
        build_importable_group(os.path.join(root, 'zz_valid'))
        result = probe.probe_reverse_folder(root)
        self.assertEqual(result['status'], probe.STATUS_OK)
        self.assertEqual(result['group_count'], 1)

    def test_mixed_formats_import_the_json_type(self):
        # A leftover .fmt next to a valid .json must not hide the JSON type.
        root = self.folder('mixed_format')
        group = build_importable_group(os.path.join(root, 'a1b2c3d4'))
        with open(os.path.join(group, 'Bad.fmt'), 'w') as handle:
            handle.write('prefix: missing')
        result = self.run_import(root)
        self.assertTrue(result['object_names'], result['message'])

    def test_language_cache_and_blender_relative_paths(self):
        # Cached error strings must follow language changes without reselecting.
        self.scene.mimi_sword_custom_reverse_output_folder_path = ''
        panel.clear_sword_reverse_probe_cache()
        self.assertIn('Custom folder', panel.get_sword_reverse_source(self.scene)[1])
        i18n.apply_language('zh')
        try:
            self.assertIn('自定义', panel.get_sword_reverse_source(self.scene)[1])
        finally:
            i18n.apply_language('en')
        # Blender owns // resolution; normpath must not reinterpret it as UNC.
        self.scene.mimi_sword_custom_reverse_output_folder_path = '//review_relative'
        path, _error = panel.resolve_sword_reverse_source_folder(self.scene)
        self.assertEqual(path, os.path.normpath(bpy.path.abspath('//review_relative')))

    def test_skeleton_cleanup_choices_are_translated(self):
        # The bone cleanup dropdown keeps stable identifiers for saved scenes
        # while both interface languages show their own captions.
        self.assertEqual(self.scene.mimi_sword_skeleton_cleanup, 'NONE')
        self.assertEqual(
            [item[0] for item in skeleton_ui.get_cleanup_items(None, None)],
            ['NONE', 'DELETE', 'HIDE'],
        )
        self.assertEqual(
            [item[1] for item in skeleton_ui.get_cleanup_items(None, None)],
            ['Keep All Bones', 'Delete Invalid Bones', 'Hide Invalid Bones'],
        )
        i18n.apply_language('zh')
        try:
            chinese_labels = [
                item[1] for item in skeleton_ui.get_cleanup_items(None, None)
            ]
        finally:
            i18n.apply_language('en')
        self.assertEqual(chinese_labels, ['不清理骨骼', '删除无效骨骼', '隐藏无效骨骼'])

    def test_bone_cleanup_choice_reaches_skeleton_helper(self):
        # The import operator hands the scene dropdown to the helper that owns
        # the actual bone cleanup logic; no real armature is needed here.
        folder = self.folder('bind_forward')
        with open(os.path.join(folder, 'skeleton.json'), 'w', encoding='utf-8') as handle:
            handle.write('{}')
        self.scene.mimi_sword_bind_skeleton = True
        self.scene.mimi_sword_skeleton_naming = 'BONE_TO_GROUP'
        self.scene.mimi_sword_skeleton_cleanup = 'DELETE'
        fake_operator = types.SimpleNamespace(report=lambda *args: None)
        with mock.patch.object(
            panel.SkeletonHelper, 'apply_groups', return_value='ok'
        ) as apply_groups:
            panel.SwordImportAllReversed._bind_skeleton(
                fake_operator,
                bpy.context,
                folder,
                {'drawib1': [object()]},
            )
        apply_groups.assert_called_once()
        call_arguments = apply_groups.call_args.args
        # Positional signature: naming mode, groups, sidecar path, cleanup mode.
        self.assertEqual(call_arguments[0], 'BONE_TO_GROUP')
        self.assertEqual(call_arguments[3], 'DELETE')

    def test_failed_import_removes_unlinked_objects(self):
        # Mesh creation can throw before linking an object to its collection.
        # Collection-only rollback left such orphan objects in bpy.data.objects.
        root = self.folder('unlinked_failure')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        original = panel.MMTImportHelper.create_mesh_from_json
        def fail_before_link(**kwargs):
            bpy.data.objects.new('review_orphan', None)
            raise RuntimeError('synthetic pre-link failure')
        panel.MMTImportHelper.create_mesh_from_json = staticmethod(fail_before_link)
        try:
            result = self.run_import(root)
        finally:
            panel.MMTImportHelper.create_mesh_from_json = original
        self.assertEqual(result['object_names'], [])
        self.assertEqual(result['collection_names'], [])

    def test_legacy_folder_is_refused_without_collections(self):
        # The old ib_vb_fmt importer is gone. Picking such a folder must still be
        # explained, and it must leave the outliner untouched.
        root = self.folder('legacy_real')
        group = os.path.join(root, 'Body')
        os.makedirs(group)
        with open(os.path.join(group, 'Body.fmt'), 'w', encoding='utf-8') as handle:
            handle.write('prefix: Body\n')
        result = self.run_import(root)
        self.assertEqual(result['object_names'], [])
        self.assertEqual(result['collection_names'], [])
        self.assertIn('ib_vb_fmt', result['message'])

    def test_reverse_import_follows_mirror_workflow(self):
        # The workspace import already honored the mirror workflow; the reverse
        # import must produce the same orientation for the same mode, because
        # the skeleton armature is placed relative to that orientation.
        root = self.folder('mirror_workflow')
        build_importable_group(os.path.join(root, 'a1b2c3d4'))
        properties = self.scene.mimi_global_properties
        original_mode = properties.mirror_workflow_mode
        try:
            properties.mirror_workflow_mode = 'MIRRORED'
            mirrored = self.run_import(root)
            properties.mirror_workflow_mode = 'NON_MIRRORED'
            non_mirrored = self.run_import(root)
        finally:
            properties.mirror_workflow_mode = original_mode

        self.assertTrue(mirrored['object_names'], mirrored['message'])
        self.assertTrue(non_mirrored['object_names'], non_mirrored['message'])
        for name, x_range in mirrored['x_ranges'].items():
            # The fixture quad spans X 0..1 in game space.
            self.assertAlmostEqual(x_range[0], 0.0, places=5, msg=name)
            self.assertAlmostEqual(x_range[1], 1.0, places=5, msg=name)
            self.assertFalse(mirrored['mirror_markers'][name], name)
        for name, x_range in non_mirrored['x_ranges'].items():
            self.assertAlmostEqual(x_range[0], -1.0, places=5, msg=name)
            self.assertAlmostEqual(x_range[1], 0.0, places=5, msg=name)
            self.assertTrue(non_mirrored['mirror_markers'][name], name)

    def test_reverse_import_keeps_16_bit_bone_ids(self):
        # Regression: MMT reverse output can now carry a 16-bit Blend layout
        # (BLENDINDICES R16G16B16A16_UINT). Reading it as bytes truncates every
        # id, so the imported vertex groups must still be named 300 / 301 / 302
        # and the 8-bit ids of the same buffer must not leak in.
        root = self.folder('blend16')
        drawib = 'c0ffee16'
        build_blend16_group(os.path.join(root, drawib), drawib)
        result = self.run_import(root)

        self.assertEqual(len(result['object_names']), 1, result['message'])
        self.assertEqual(result['empty_leaf_names'], [])
        # The importer allocates one group per id up to the mesh maximum, so the
        # contract is the highest id and the presence of the 16-bit ids, not the
        # exact group count.
        group_ids = result['vertex_group_ids'][result['object_names'][0]]
        self.assertEqual(max(group_ids), 302,
                         'vertex groups must keep the real 16-bit bone ids')
        for expected_id in (300, 301, 302):
            self.assertIn(expected_id, group_ids,
                          'bone id %d must survive the import' % expected_id)


def main():
    # Exercise register/unregister/re-register so add-on reload remains safe.
    print('Blender version:', bpy.app.version_string)
    global_properties.register()
    skeleton_ui.register()
    panel.register()
    panel.unregister()
    panel.register()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReverseImportTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print('RESULT ' + json.dumps({'tests': result.testsRun, 'success': result.wasSuccessful()}))
        if not result.wasSuccessful():
            raise RuntimeError('Mod Reverse import integration checks failed')
    finally:
        panel.unregister()
        skeleton_ui.unregister()
        global_properties.unregister()


if __name__ == '__main__':
    main()
