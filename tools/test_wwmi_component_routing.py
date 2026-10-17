"""Pure regression coverage for lossless, conservative component routing.

Run with Python; neither Blender nor a user's project is loaded.
Fixtures explicitly distinguish whole-triangle and per-vertex incompatibility.
No test grants permission to delete weights or infer material equivalence.

Safety matrix
-------------
A valid blueprint assignment takes precedence over any alternative candidate.
A unique alternative remains blocked until the caller supplies draw-state consent.
Consent never resolves multiple equally compatible alternative palettes.
A triangle needs one palette for all corners, not one palette per corner.
One mixed vertex cannot be repaired by duplicating that vertex at a boundary.
Tiny positive influences still constrain a draw before any later quantization.
Zero weights and unused helpers do not constrain an otherwise compatible face.
An active nonnumeric helper is reported rather than silently losing its influence.
Numeric Blender suffixes are accepted without confusing names and group indices.
Runtime aliases need metadata evidence and canonical matches retain priority.
Alias cycles terminate without making an unrelated bone magically compatible.
Sparse native maps retain their documented offset fallback for missing entries.
Integer layout bounds exclude slots which cannot fit in the exported field.
All failures are collected even when earlier faces have valid proposed moves.
Invalid provenance and non-triangle input are rejected before any mutation.

Fixture conventions
-------------------
Component numbers are zero-based positions in the native metadata sequence.
Group indices are arbitrary collection positions; their names identify bones.
Each vertex stores every input group, just as a Blender mesh vertex does.
Weights are deliberately not normalized by this module or its fixture helper.
The planner returns assignments but never edits the supplied objects in place.
The Blender integration suite is responsible for committing complete plans.
It separately checks buffers, face selection, shape duplicates and draw branches.
These tests prove skeleton feasibility, not visual equivalence of game materials.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('component_routing', ROOT / 'games/wwmi/component_routing.py')
routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing)


def component(bones, offset=0):
    # Explicit maps make fixture identities independent of runtime slot numbers.
    # Duplicate canonical entries are intentionally legal, just like native maps.
    return NS(vg_map=dict(enumerate(bones)), vg_offset=offset, vg_count=len(bones))


def vertices(weights):
    # Keep every positive input influence, including values below quantization.
    # The planner reads the same group/weight fields as Blender's mesh vertices.
    return [NS(groups=[NS(group=group, weight=weight) for group, weight in row]) for row in weights]


class RoutingTests(unittest.TestCase):
    def plan(self, weights, palettes=None, source=0, consent=False, names=None):
        # One triangle is enough to expose dominant-bone and palette-union bugs.
        # Reusing the same vertex is not required; all three corners participate.
        return routing.plan_faces(vertices(weights), [NS(vertices=(0, 1, 2))],
                                  names or {0: '10', 1: '20', 2: '30'}, [source],
                                  palettes or [component([10]), component([20], 100)], consent)

    def test_current_valid_assignment_wins_shared_candidates(self):
        # Shared bones must not force an arbitrary move away from the blueprint.
        result = self.plan([[(0, 1)]] * 3, [component([10]), component([10], 100)])
        self.assertEqual(result['assignments'], [0])
        self.assertFalse(result['issues'])

    def test_unique_candidate_requires_draw_state_consent(self):
        result = self.plan([[(1, 1)]] * 3)
        self.assertEqual(result['issues'][0]['candidates'], [1])
        self.assertEqual(result['issues'][0]['kind'], 'draw_state')
        self.assertEqual(result['assignments'], [0])

    def test_unique_candidate_can_route_after_consent(self):
        result = self.plan([[(1, 1)]] * 3, consent=True)
        self.assertEqual(result['assignments'], [1])
        self.assertFalse(result['issues'])

    def test_ambiguous_candidate_never_guessed(self):
        # Consent to native destination state does not choose between materials.
        result = self.plan([[(1, 1)]] * 3, [component([10]), component([20]), component([20])], consent=True)
        self.assertEqual(result['issues'][0]['kind'], 'ambiguous')
        self.assertEqual(result['issues'][0]['candidates'], [1, 2])

    def test_triangle_only_conflict(self):
        # Every vertex fits some palette, but no single draw can render the face.
        result = self.plan([[(0, 1)], [(1, 1)], [(0, 1)]], consent=True)
        self.assertEqual(result['issues'][0]['kind'], 'incompatible')
        self.assertEqual(result['issues'][0]['unassignable_vertices'], [])

    def test_mixed_vertex_cannot_be_fixed_by_duplication(self):
        result = self.plan([[(0, .7), (1, .3)]] * 3, consent=True)
        self.assertEqual(result['issues'][0]['unassignable_vertices'], [0, 1, 2])
        self.assertEqual(result['issues'][0]['groups'], ['10', '20'])

    def test_tiny_positive_weight_still_constrains_target(self):
        # A later R8 quantizer must not make the safety decision for the planner.
        result = self.plan([[(0, 1), (1, 1e-12)]] * 3, consent=True)
        self.assertEqual(result['counts']['incompatible'], 1)

    def test_zero_weight_and_unused_named_helper_do_not_constrain(self):
        result = self.plan([[(0, 1), (1, 0)]] * 3, names={0: '10', 1: 'helper'})
        self.assertFalse(result['issues'])

    def test_active_unnamed_group_is_reported(self):
        result = self.plan([[(0, 1)]] * 3, names={0: 'helper'})
        self.assertEqual(result['issues'][0]['groups'], ['helper'])
        self.assertEqual(result['counts']['incompatible'], 1)

    def test_numeric_suffix_and_runtime_alias(self):
        # A legacy slot may alias a canonical ID, but only when metadata says so.
        palettes = [component([68], 223)]
        result = self.plan([[(0, 1)]] * 3, palettes, names={0: '223.001'})
        self.assertFalse(result['issues'])

    def test_exact_canonical_identity_precedes_alias(self):
        maps, aliases = routing.build_bone_maps([component([20, 10], 10)])
        self.assertEqual(routing.resolve_local(10, maps[0], aliases), 1)
        self.assertIsNone(routing.resolve_local(999, maps[0], aliases))

    def test_alias_cycle_does_not_hang(self):
        self.assertIsNone(routing.resolve_local(1, {3: 0}, {1: 2, 2: 1}))

    def test_sparse_map_fallback_and_integer_width(self):
        palette = NS(vg_map={1: 10}, vg_offset=100, vg_count=3)
        maps, aliases = routing.build_bone_maps([palette], maximum_local=1)
        self.assertEqual(maps, [{100: 0, 10: 1}])
        self.assertEqual(routing.resolve_local(101, maps[0], aliases), 1)
        self.assertIsNone(routing.resolve_local(102, maps[0], aliases))

    def test_all_failures_are_collected_and_inputs_unchanged(self):
        # A valid proposed move must not hide a later impossible triangle.
        # The caller rejects the whole plan; this pure stage never applies it.
        mesh_vertices = vertices([[(1, 1)]] * 3 + [[(0, .5), (1, .5)]] * 3)
        before = repr(mesh_vertices)
        result = routing.plan_faces(mesh_vertices, [NS(vertices=(0, 1, 2)), NS(vertices=(3, 4, 5))],
                                    {0: '10', 1: '20'}, [0, 0], [component([10]), component([20])], True)
        self.assertEqual(result['assignments'], [1, 0])
        self.assertEqual(len(result['issues']), 1)
        self.assertEqual(repr(mesh_vertices), before)

    def test_invalid_ownership_and_nontriangles_rejected(self):
        # Lost modifier provenance must not silently become component zero.
        with self.assertRaisesRegex(ValueError, 'ownership'):
            self.plan([[(0, 1)]] * 3, source=-1)
        with self.assertRaisesRegex(ValueError, 'count'):
            routing.plan_faces([], [], {}, [0], [])
        with self.assertRaisesRegex(ValueError, 'triangle'):
            routing.plan_faces(vertices([[(0, 1)]] * 4), [NS(vertices=(0, 1, 2, 3))],
                               {0: '10'}, [0], [component([10])])


if __name__ == '__main__':
    unittest.main(verbosity=2)
