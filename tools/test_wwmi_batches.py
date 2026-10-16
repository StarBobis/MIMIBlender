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

    def test_legacy_full_size_raw_cb(self):
        # Xin's legacy MMT extraction stores the whole 4096-byte shader CB.
        # The extra words include float bit patterns and are not offset blocks.
        # Keep CB[261]'s sparse origin independent of the component vertex origin.
        cb = numpy.zeros(1024, dtype='<u4')
        cb[1:128] = 1
        cb[256:261] = [1255466176, 1257630588, 1255483664, 1266679808, 1266679808]
        cb[261] = 1
        deltas = numpy.zeros((2, 6), dtype='<f2')
        deltas[:, 0] = [0.25, 0.5]
        obj = import_buffers(cb, [0, 100], deltas, origin=100)
        keys = obj.data.shape_keys.key_blocks
        self.assertEqual([key.name for key in keys], ['Basis', 'Deform 0'])
        self.assertEqual(keys[1].data.co[0], 0.5)

    def test_eight_compact_batches_are_not_a_raw_cb(self):
        # Eight valid compact batches have exactly the same size as a raw CB.
        # Structural validation preserves all eight blocks and their key IDs.
        # This guards against fixing Xin with an unconditional file-size guess.
        offsets = ([0] + [1] * 127) * 8
        deltas = numpy.zeros((8, 6), dtype='<f2')
        deltas[:, 0] = numpy.arange(1, 9) / 8
        obj = import_buffers(offsets, [0] * 8, deltas)
        keys = obj.data.shape_keys.key_blocks
        self.assertEqual([key.name for key in keys[1:]], [f'Deform {127 * batch}' for batch in range(8)])
        self.assertEqual(keys[-1].data.co[0], 1.0)

    def test_explicit_compact_layout_is_not_reinterpreted(self):
        # Declared compact buffers must not hide corrupt offsets as raw state.
        # Only legacy captures with no layout marker use the detection fallback.
        # The existing strict validation must continue to reject bad batches.
        offsets = numpy.zeros(1024, dtype='<u4')
        offsets[1:128] = 1
        offsets[256] = 123
        with self.assertRaisesRegex(ValueError, 'monotonic'):
            import_buffers(offsets, [0], numpy.zeros((1, 6)), metadata={'buffer_layout': 'compact_batches'})

    def test_explicit_full_size_raw_cb(self):
        # Modern metadata disambiguates even an all-zero shader-state tail.
        # CB[261] remains a sparse origin, not the first offset of batch two.
        # Test the explicit branch alongside the no-metadata legacy fallback.
        offsets = numpy.zeros(1024, dtype='<u4')
        offsets[1:128] = 1
        offsets[261] = 1
        deltas = numpy.zeros((2, 6), dtype='<f2')
        deltas[1, 0] = 0.75
        obj = import_buffers(offsets, [0, 0], deltas, metadata={'buffer_layout': 'raw_cb'})
        self.assertEqual(obj.data.shape_keys.key_blocks[1].data.co[0], 0.75)

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


class ShapeKeyHookTests(unittest.TestCase):
    # Use the actual INI writer without importing Blender-dependent modules.
    # A list implements the append/new_line API used by this one section.
    # Scoped names remain real enough to verify every callback reference.
    def write_sections(self, offsets_hash, scale_hash, offsets=None, batches=None):
        class Section(list):
            # Section type does not affect this writer's generated lines.
            # Keep blank lines visible, just like the production INI builder.
            def __init__(self, section_type):
                super().__init__()

            def new_line(self):
                self.append('')

        sections = []
        namespace = {
            'Fatal': ValueError, 'get_wwmi_shapekey_batches': EXPORT,
            'M_IniSection': Section,
            'M_SectionType': SimpleNamespace(TextureOverrideShapeKeys=0),
            'MIMIGlobalProperties': SimpleNamespace(import_merged_vgmap=lambda: 'MERGED'),
            'scoped_section': lambda name, draw_ib: '[' + name + '_' + draw_ib + ']',
            'scoped_name': lambda name, draw_ib: name + '_' + draw_ib,
            'scoped_global': lambda name, draw_ib: '$' + name + '_' + draw_ib,
        }
        # Valid runtime metadata isolates hash validation from batch validation.
        # Explicit empty offsets represent a genuinely shape-less model.
        # Missing offset hashes must still fail even when a scale hash exists.
        shape = SimpleNamespace(offsets_hash=offsets_hash, scale_hash=scale_hash,
                                batches=batches or [{'checksum': 1104, 'vertex_offset': 0, 'dispatch_y': 912}],
                                checksum=1104, dispatch_y=912)
        model = SimpleNamespace(draw_ib='94517393_LOD0', wwmi_info=SimpleNamespace(shapekeys=shape),
                                obj_buffer_model_wwmi=SimpleNamespace(shapekey_offsets=[0] + [1] * 127 if offsets is None else offsets))
        writer = load_function('games/wwmi/shapekeys.py', 'add_texture_override_shapekeys', namespace)
        writer(SimpleNamespace(append_section=sections.append), model)
        return '\n'.join(line for section in sections for line in section)

    def test_missing_scale_keeps_runtime_callbacks(self):
        # This is the live failing character's exact pair of resource hashes.
        # Both runtime callbacks must remain hooked through the offsets hash.
        # Do not emit an empty scale override or silently drop all shape keys.
        text = self.write_sections('15791c57', '')
        self.assertNotIn('[TextureOverrideShapeKeyScale_', text)
        self.assertEqual(text.count('hash = 15791c57'), 3)
        for name in ('TextureOverrideShapeKeyOffsets', 'TextureOverrideShapeKeyLoaderCallback',
                     'TextureOverrideShapeKeyMultiplierCallback', 'CommandListSetupShapeKeysBatch',
                     'CommandListLoadShapeKeysBatch', 'CommandListMultiplyShapeKeys'):
            self.assertIn('[' + name + '_94517393_LOD0]', text)
        self.assertIn('shapekey_checksum_batch0 = 1104', text)
        self.assertIn('shapekey_dispatch_size_y_original_batch0 = 912', text)

    def test_present_scale_still_gets_size_override(self):
        # Older captures with a separate scale resource keep identical behavior.
        # The resource hash and stride must belong to that optional section.
        # Loader callbacks still use the offsets resource, not the scale hash.
        text = self.write_sections('15791c57', '12345678')
        self.assertIn('[TextureOverrideShapeKeyScale_94517393_LOD0]\nhash = 12345678', text)
        self.assertIn('override_byte_stride = 4', text)
        self.assertEqual(text.count('hash = 15791c57'), 3)

    def test_missing_offsets_still_fails(self):
        # Scale metadata alone cannot hook either runtime callback.
        # Keep strict validation for genuinely unusable capture metadata.
        # Test both absent hashes and the scale-only variant independently.
        for scale in ('', '12345678'):
            with self.subTest(scale=scale), self.assertRaisesRegex(ValueError, 'offsets hash is missing'):
                self.write_sections('', scale)

    def test_no_shape_buffers_need_no_hashes(self):
        # Static models never run the original shape key pipeline.
        # Missing hashes on such models must not prevent ordinary export.
        # No orphaned setup commands should be emitted in this case either.
        self.assertEqual(self.write_sections('', '', offsets=[]), '')

    def test_missing_scale_preserves_multiple_batches(self):
        # Optional scale resources are independent of runtime batch count.
        # Keep distinct dispatch sizes and original sparse offsets per batch.
        # Reusing batch zero would break characters with more than 127 keys.
        batches = [{'checksum': 1104, 'vertex_offset': 0, 'dispatch_y': 912},
                   {'checksum': 7, 'vertex_offset': 29161, 'dispatch_y': 3}]
        text = self.write_sections('15791c57', '', offsets=([0] + [1] * 127) * 2, batches=batches)
        self.assertIn('shapekey_checksum_batch1 = 7', text)
        self.assertIn('shapekey_vertex_offset_original_batch1 = 29161', text)
        self.assertIn('shapekey_dispatch_size_y_original_batch1 = 3', text)


if __name__ == '__main__':
    unittest.main()
