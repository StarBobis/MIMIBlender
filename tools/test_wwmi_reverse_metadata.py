"""Regression coverage for portable, validated reverse shape metadata.

These tests execute the production module without requiring Blender.
They cover matching and conflict checks, not in-game shader execution.
Source mesh data is intentionally absent: this path must never touch it.
Run with Python directly or together with the existing WWMI batch tests.
"""

from copy import deepcopy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / 'workspace/wwmi_reverse_metadata.py'))
CAPTURE = MODULE['capture_reverse_shape_metadata']
RESOLVE = MODULE['resolve_reverse_shape_metadata']
PROPERTY = MODULE['PROPERTY_NAME']


class Object(dict):
    # A dictionary mirrors the only Blender object API used by this module.
    # Names are separate from custom properties, matching bpy.types.Object.
    # No geometry or shape coordinate API is available to accidentally mutate.
    name = 'reverse_body'


class ReverseMetadataTests(unittest.TestCase):
    def setUp(self):
        # Keep the real failure's 127 + 49 boundaries and runtime identities.
        # Tiny draw ranges make target-association failures easy to understand.
        # Compact counts deliberately differ from the native sparse count.
        self.batches = [
            dict(vertex_offset=0, vertex_count=80286, shapekey_count=127,
                 dispatch_y=2360, checksum=1019, runtime_metadata_complete=True,
                 buffer_vertex_offset=0, shapekey_offset=0),
            dict(vertex_offset=75507, vertex_count=25506, shapekey_count=49,
                 dispatch_y=712, checksum=3465, runtime_metadata_complete=True,
                 buffer_vertex_offset=80286, shapekey_offset=127),
        ]
        self.ranges = [dict(ComponentIndex=0, MatchFirstIndex=0, MatchIndexCount=3),
                       dict(ComponentIndex=1, MatchFirstIndex=3, MatchIndexCount=6)]
        self.buffers = dict(source_match_components=self.ranges,
                            metadata=dict(offsets_hash='67b0a7f4', scale_hash='d87014b0',
                                          batches=self.batches, buffer_layout='compact_batches'))
        self.info = SimpleNamespace(
            components=[SimpleNamespace(index_offset=0, index_count=3, vg_count=121),
                        SimpleNamespace(index_offset=3, index_count=6, vg_count=108)],
            shapekeys=SimpleNamespace(offsets_hash='67b0a7f4', scale_hash='d87014b0',
                                     vertex_count=75507, checksum=1019, dispatch_y=2360,
                                     batches=[deepcopy(self.batches[0])]),
        )
        self.info.shapekeys.batches[0]['vertex_count'] = 75507

    def object(self, buffers=None):
        obj = Object()
        CAPTURE(obj, self.buffers if buffers is None else buffers)
        return obj

    def resolve(self, objects=None):
        RESOLVE(self.info, objects if objects is not None else [self.object()], 'e590b8d4_LOD0')

    def test_capture_keeps_a_portable_independent_snapshot(self):
        # Editing the parsed JSON later must not change an imported object.
        # Both original match ranges and runtime identities survive serialization.
        # No absolute source path is needed when the blend is moved elsewhere.
        obj = self.object()
        self.batches[1]['checksum'] = 7
        payload = json.loads(obj[PROPERTY])
        self.assertEqual(payload['shapekeys']['batches'][1]['checksum'], 3465)
        self.assertEqual(payload['components'], self.ranges)

    def test_normal_extraction_does_not_gain_reverse_metadata(self):
        # An ordinary submesh does not carry reverse MatchComponentList entries.
        # Its existing native metadata remains the sole authority.
        # The capture helper must also accept a component without shape buffers.
        self.assertNotIn(PROPERTY, self.object({'metadata': self.buffers['metadata']}))
        self.assertNotIn(PROPERTY, self.object({}))

    def test_extension_preserves_native_header_and_source(self):
        # Only batch runtime identities extend, never native skeleton/mesh counts.
        # Compact buffer addresses are discarded rather than exported as bases.
        # Source properties remain byte-for-byte unchanged after resolution.
        obj = self.object()
        source = deepcopy(obj)
        components = deepcopy(self.info.components)
        self.resolve([obj])
        self.assertEqual(len(self.info.shapekeys.batches), 2)
        self.assertEqual(self.info.shapekeys.batches[1]['vertex_offset'], 75507)
        self.assertNotIn('buffer_vertex_offset', self.info.shapekeys.batches[1])
        self.assertEqual(self.info.shapekeys.vertex_count, 75507)
        self.assertEqual(self.info.components, components)
        self.assertEqual(obj, source)

    def test_no_attached_metadata_does_not_change_batches(self):
        before = deepcopy(self.info.shapekeys.batches)
        self.resolve([Object(), None])
        self.assertEqual(self.info.shapekeys.batches, before)

    def test_target_draw_ranges_must_match(self):
        self.ranges[1]['MatchFirstIndex'] = 4
        with self.assertRaisesRegex(ValueError, 'e590b8d4_LOD0.*reverse_body.*draw ranges'):
            self.resolve()

    def test_target_hashes_must_match(self):
        # Matching component counts alone does not prove the same target model.
        # Both known resource hashes are checked independently.
        # Never compensate for mismatch by rewriting the target extraction.
        for key in ('offsets_hash', 'scale_hash'):
            with self.subTest(key=key):
                buffers = deepcopy(self.buffers)
                buffers['metadata'][key] = 'deadbeef'
                with self.assertRaisesRegex(ValueError, 'does not match.*hash'):
                    self.resolve([self.object(buffers)])

    def test_overlapping_runtime_identities_must_agree(self):
        # All four fields identify the original runtime dispatch and its slots.
        # Mod sparse vertex counts deliberately are not part of that identity.
        # A mismatch must fail before extending any other source's batches.
        for key in ('vertex_offset', 'dispatch_y', 'checksum', 'shapekey_count'):
            with self.subTest(key=key):
                buffers = deepcopy(self.buffers)
                buffers['metadata']['batches'][0][key] -= 1
                with self.assertRaises(ValueError):
                    self.resolve([self.object(buffers)])
                self.assertEqual(len(self.info.shapekeys.batches), 1)

    def test_incomplete_metadata_never_fabricates_checksum(self):
        for change in ({'checksum': None}, {'runtime_metadata_complete': False}, {'dispatch_y': 0}):
            with self.subTest(change=change):
                buffers = deepcopy(self.buffers)
                buffers['metadata']['batches'][1].update(change)
                with self.assertRaisesRegex(ValueError, 'runtime batch metadata'):
                    self.resolve([self.object(buffers)])

    def test_invalid_sizes_and_offsets_fail(self):
        for change in ({'shapekey_count': 128}, {'shapekey_count': -1}, {'vertex_offset': -1}, {'checksum': -1}):
            with self.subTest(change=change):
                buffers = deepcopy(self.buffers)
                buffers['metadata']['batches'][1].update(change)
                with self.assertRaisesRegex(ValueError, 'invalid original runtime'):
                    self.resolve([self.object(buffers)])

    def test_runtime_values_are_never_rounded(self):
        # A decimal or boolean is not a recoverable original runtime identity.
        # Strings from older JSON writers are accepted only when truly integral.
        # Invalid values must identify the source instead of leaking int errors.
        for value in (3465.5, True, 'bad', float('inf')):
            with self.subTest(value=value):
                buffers = deepcopy(self.buffers)
                buffers['metadata']['batches'][1]['checksum'] = value
                with self.assertRaisesRegex(ValueError, 'reverse_body.*non-integer'):
                    self.resolve([self.object(buffers)])

    def test_zero_checksum_is_valid(self):
        self.batches[1]['checksum'] = 0
        self.resolve()
        self.assertEqual(self.info.shapekeys.batches[1]['checksum'], 0)

    def test_nonconsecutive_key_boundaries_fail(self):
        self.batches[1]['shapekey_offset'] = 126
        with self.assertRaisesRegex(ValueError, 'nonconsecutive'):
            self.resolve()

    def test_duplicate_and_shorter_sources_do_not_truncate(self):
        # Object order is not a preference among independent runtime identities.
        # A matching prefix can coexist with a longer complete source.
        # Identical metadata repeated on many components is parsed only once.
        full = self.object()
        short_buffers = deepcopy(self.buffers)
        short_buffers['metadata']['batches'] = short_buffers['metadata']['batches'][:1]
        short = self.object(short_buffers)
        self.resolve([full, full, short])
        self.assertEqual(len(self.info.shapekeys.batches), 2)

    def test_conflicting_sources_fail_atomically(self):
        full = self.object()
        self.batches[1]['checksum'] += 1
        other = self.object()
        before = deepcopy(self.info.shapekeys.batches)
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.resolve([full, other])
        self.assertEqual(self.info.shapekeys.batches, before)

    def test_malformed_properties_fail_with_source_context(self):
        # Hand-edited or older custom properties must not bypass validation.
        # JSON array roots and missing schema fields are invalid records.
        # An unexpected property type is reported as a controlled ValueError.
        for text in ('{', '[]', '{}', {'wrong': 'type'}):
            with self.subTest(text=text):
                obj = Object({PROPERTY: text})
                with self.assertRaisesRegex(ValueError, 'e590b8d4_LOD0.*reverse_body'):
                    self.resolve([obj])


if __name__ == '__main__':
    unittest.main()
