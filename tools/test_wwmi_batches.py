"""Exercise actual WWMI methods without loading Blender.

AST loading deliberately preserves production method bodies.
The tiny coordinate objects implement only Blender's used API.
Synthetic buffers isolate sparse, component, and key-ID offsets.
A real existing fixture is checked when its directory is available.
These tests verify buffer generation, not in-game rendering.
"""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy

# Resolve production sources relative to this test, not the calling directory.
# This lets the same regression run after either repository is relocated.
# No temporary files or Blender installation are required by these probes.
ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    # Importing the plugin normally requires bpy and an initialized scene.
    # Extract only the requested function, leaving its implementation intact.
    # Strip annotations and decorators that depend on plugin-only classes.
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    function.decorator_list = []
    for argument in function.args.args:
        argument.annotation = None
    function.returns = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), path, 'exec'), namespace)
    return namespace[name]


class Coordinates:
    # Blender uses flat float arrays for bulk coordinate transfers.
    # Keep the exact same memory layout so wrong index arithmetic is visible.
    # Each generated key receives its own independent coordinate array.
    def __init__(self, count):
        self.co = numpy.zeros(count * 3, dtype=numpy.float32)

    def foreach_get(self, name, out):
        out[:] = self.co

    def foreach_set(self, name, values):
        self.co[:] = values


class KeyBlocks(list):
    # The importer finds Basis through Blender's named key-block lookup.
    # A list subclass also supports its fallback numeric index access.
    # Missing keys return None, matching Blender's collection API.
    def get(self, name):
        return next((key for key in self if key.name == name), None)


class Object(dict):
    # Object custom properties hold runtime export batch boundaries.
    # Shape key storage belongs to data, as it does on a Blender object.
    # Only the importer-facing methods are needed for these buffer probes.
    def __init__(self, count):
        super().__init__()
        self.data = SimpleNamespace(vertices=range(count), shape_keys=None)

    def shape_key_add(self, name):
        if self.data.shape_keys is None:
            self.data.shape_keys = SimpleNamespace(key_blocks=KeyBlocks())
        key = SimpleNamespace(name=name, data=Coordinates(len(self.data.vertices)))
        self.data.shape_keys.key_blocks.append(key)
        return key


IMPORT = load_function('common/mesh_create_helper.py', 'import_shapekeys_wwmi', {'numpy': numpy, 'Fatal': ValueError})
EXPORT = load_function('games/wwmi/shapekeys.py', 'get_wwmi_shapekey_batches', {'Fatal': ValueError})
PACK = load_function('utils/shapekey_utils.py', 'extract_shapekey_data', {'math': math})


def import_buffers(offsets, ids, deltas, origin=0, count=1, metadata=None):
    # Feed byte arrays exactly as parse_category_buffers loads them from disk.
    # Runtime metadata remains separate from all three binary resources.
    # This detects accidental slicing or interpreting metadata as buffer bytes.
    obj = Object(count)
    buffers = {
        'ShapeKeyOffset': numpy.asarray(offsets, dtype='<u4').view(numpy.uint8),
        'ShapeKeyVertexId': numpy.asarray(ids, dtype='<u4').view(numpy.uint8),
        'ShapeKeyVertexOffset': numpy.asarray(deltas, dtype='<f2').ravel().view(numpy.uint8),
        'metadata': metadata or {},
    }
    IMPORT(None, obj, buffers, origin, count)
    return obj


class BatchTests(unittest.TestCase):
    def test_raw_cb_sparse_origin_is_not_component_origin(self):
        # CB0[261] selects the second sparse entry, not a mesh vertex range.
        # Vertex 100 becomes local vertex zero in this one-vertex component.
        # Import must use its 0.5 delta rather than the earlier 0.25 delta.
        cb = numpy.zeros(262, dtype='<u4')
        cb[1:128] = 1
        cb[261] = 1
        deltas = numpy.zeros((2, 6), dtype='<f2')
        deltas[:, 0] = [0.25, 0.5]
        obj = import_buffers(cb, [0, 100], deltas, 100)
        self.assertEqual([key.name for key in obj.data.shape_keys.key_blocks], ['Basis', 'Deform 0'])
        self.assertEqual(obj.data.shape_keys.key_blocks[1].data.co[0], 0.5)

    def test_middle_empty_slot_and_second_batch(self):
        # First key is blank; slot one is populated and must retain ID one.
        # Legacy compact block two always begins at global key ID 127.
        # Its local entry zero actually refers to concatenated sparse entry one.
        first = [0, 0] + [1] * 126
        second = [0] + [1] * 127
        deltas = numpy.zeros((2, 6), dtype='<f2')
        deltas[:, 0] = [0.25, 0.75]
        obj = import_buffers(first + second, [0, 0], deltas)
        keys = obj.data.shape_keys.key_blocks
        self.assertEqual([key.name for key in keys], ['Basis', 'Deform 1', 'Deform 127'])
        self.assertEqual(keys[2].data.co[0], 0.75)

    def test_explicit_short_runtime_batch_boundaries(self):
        # Original runtime batches can contain only one key each.
        # Explicit metadata avoids assuming 127 IDs between those batches.
        # The exported buffers must keep one 128-offset block per dispatch.
        offsets = ([0] + [1] * 127) * 2
        metadata = {'buffer_layout': 'compact_batches', 'batches': [
            {'buffer_vertex_offset': 0, 'shapekey_offset': 0, 'shapekey_count': 1},
            {'buffer_vertex_offset': 1, 'shapekey_offset': 1, 'shapekey_count': 1},
        ]}
        obj = import_buffers(offsets, [0, 0], numpy.zeros((2, 6)), metadata=metadata)
        self.assertEqual([key.name for key in obj.data.shape_keys.key_blocks], ['Basis', 'Deform 0', 'Deform 1'])
        obj['wwmi_shapekey_batch_counts'] = [1, 1]
        helper = SimpleNamespace(get_shapekey_cache=lambda *args: {0: {0: [0.25, 0, 0]}, 1: {0: [0.75, 0, 0]}})
        packed, ids, deltas = PACK(helper, obj, {})
        self.assertEqual(len(packed), 256)
        self.assertEqual(packed[127], 1)
        self.assertEqual(packed[255], 1)
        self.assertEqual(ids, [0, 0])
        self.assertEqual(deltas[6], 0.75)

    def test_truncated_sparse_buffers_fail(self):
        # Previously the importer filtered invalid entries and silently lost keys.
        # Validate full batch bounds before creating any Blender shape keys.
        # A malformed sparse buffer must now surface an actionable exception.
        with self.assertRaises(ValueError):
            import_buffers([0] + [2] * 127, [0], numpy.zeros((1, 6)))

    def test_export_requires_real_dispatch_metadata(self):
        # Two offset blocks cannot reuse a single legacy runtime checksum.
        # Missing metadata must fail rather than return an empty setup list.
        # A recovered zero checksum is legal when early key slots are blank.
        shape = SimpleNamespace(batches=[], checksum=175, dispatch_y=1318)
        model = SimpleNamespace(obj_buffer_model_wwmi=SimpleNamespace(shapekey_offsets=([0] + [1] * 127) * 2), wwmi_info=SimpleNamespace(shapekeys=shape))
        with self.assertRaises(ValueError):
            EXPORT(model)
        shape.batches = [{'checksum': 175, 'vertex_offset': 0, 'dispatch_y': 7}, {'checksum': 0, 'vertex_offset': 99, 'dispatch_y': 3}]
        result = EXPORT(model)
        self.assertEqual(result[1]['original_vertex_offset'], 99)
        self.assertEqual(result[1]['custom_vertex_offset'], 1)
        self.assertEqual(result[1]['dispatch_y'], 3)
        self.assertEqual(result[1]['checksum'], 0)
        # Presence is explicit for newly recovered runtime metadata.
        # Dispatch Y alone must not hide a missing checksum or original base.
        # Legacy metadata without the marker remains backward compatible.
        shape.batches[1]['runtime_metadata_complete'] = False
        with self.assertRaises(ValueError):
            EXPORT(model)

    def test_real_two_batch_fixture_when_available(self):
        # The existing diagnosis fixture contains 127 plus 34 populated keys.
        # Check all 161 IDs and a later key's actual coordinate deltas.
        # Absence outside this developer workspace does not break synthetic tests.
        directory = ROOT.parent / 'SSMT5/tmp/wwmi-053-out-v2/46159a16'
        if not directory.exists():
            self.skipTest('Optional real reverse-output fixture is not available')
        offsets = numpy.fromfile(directory / '46159a16-ShapeKeyOffset.buf', dtype='<u4')
        ids = numpy.fromfile(directory / '46159a16-ShapeKeyVertexId.buf', dtype='<u4')
        deltas = numpy.fromfile(directory / '46159a16-ShapeKeyVertexOffset.buf', dtype='<f2')
        obj = import_buffers(offsets, ids, deltas, count=193092)
        keys = obj.data.shape_keys.key_blocks
        self.assertEqual(len(keys), 162)
        self.assertEqual(keys[-1].name, 'Deform 160')
        self.assertGreater(numpy.count_nonzero(keys[-1].data.co), 0)


if __name__ == '__main__':
    unittest.main()
