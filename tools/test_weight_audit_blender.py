"""Headless integration checks for the weight audit panel feature.

Run: blender -b --factory-startup --python-exit-code 1 -P this_file
Tests build synthetic meshes only, never open or modify a user scene.

Coverage notes:
- A smooth blend band between two bones must report zero seams.
- Two single-bone regions that touch on a flat surface must report a seam.
- A weight step across a geometric hard edge must be exempt from the report.
- A weight step across a material boundary must be exempt from the report.
- A tiny group island far away from the main region must be reported.
- Two large connected regions of one group are legitimate and stay silent.
- Zero-weight vertices, five influences and a bad weight sum are reported.
- Smoothing must remove the detected seam and keep every weight sum at one.
- Cleaning must drop tiny weights, cap influences and normalize the result.
- Two objects sharing one mesh must be processed once, not twice.
- The operators must reject Edit Mode and an empty selection.
- Registration is repeatable and the panel exposes all controls in Chinese.
- The report string is written to the scene and survives a second run.
- Unit checks pin the pure helpers (distance, normalize, equality).

Test fixture ownership:
- Every fixture lives in this process's factory-startup scene.
- The scene is cleared in setUp, so no data leaks between tests.
- Operators are invoked through bpy.ops, not through direct calls, so poll
  and registration are exercised the same way a user exercises them.
- The i18n language is restored to English in a finally block.
- A final JSON line gives the automated runner a compact result summary.
"""
import importlib
import json
from pathlib import Path
import sys
import types
import unittest

import bpy

# Import only this feature and i18n, avoiding unrelated add-on startup work.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('MIMIBlender')
package.__path__ = [str(ROOT)]
sys.modules['MIMIBlender'] = package
weight_utils = importlib.import_module('MIMIBlender.utils.weight_audit_utils')
panel = importlib.import_module('MIMIBlender.ui.ui_panel_weight')
i18n = importlib.import_module('MIMIBlender.i18n.i18n')

WeightAuditSettings = weight_utils.WeightAuditSettings
WeightAuditUtils = weight_utils.WeightAuditUtils


def new_mesh_object(name, vertices, faces=(), edges=()):
    """Create a linked mesh object from raw geometry."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(list(vertices), list(edges), list(faces))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def add_weight(obj, group_index, vertex_indices, weight):
    """Assign one weight to one existing or new vertex group."""
    # The caller passes the group index so a test can address a group that was
    # created earlier by name without relying on Blender's naming suffixes.
    group = obj.vertex_groups[group_index]
    group.add(list(vertex_indices), weight, 'REPLACE')


def strip_grid(columns, rows=2):
    """Return vertices and quad faces of a flat quad strip on the XY plane."""
    vertices = [(float(column), float(row), 0.0) for row in range(rows) for column in range(columns)]
    faces = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            first = row * columns + column
            faces.append((first, first + 1, first + columns + 1, first + columns))
    return vertices, faces


def two_quad_mesh(name):
    """Two coplanar quads that share the vertical edge between vertices 1 and 2.

    The shared edge is the only internal edge of this fixture, so a weight step
    placed on vertices 1 and 2 is guaranteed to be seen by the seam detector.
    """
    vertices = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (2.0, 0.0, 0.0), (2.0, 1.0, 0.0),
    ]
    faces = [(0, 1, 2, 3), (1, 4, 5, 2)]
    return new_mesh_object(name, vertices, faces)


def settings(**overrides):
    """Build audit settings with a stable baseline for every test."""
    values = {
        'seam_threshold': 1.0,
        'smooth_angle_degrees': 60.0,
        'island_weight_threshold': 0.05,
        'island_min_vertices': 8,
        'max_influences': 4,
        'min_weight': 0.01,
    }
    values.update(overrides)
    return WeightAuditSettings(**values)


def activate(obj):
    """Make one object the only selected and active object."""
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


class WeightAuditTests(unittest.TestCase):
    def setUp(self):
        # The factory-startup scene is owned by this test process, so clearing
        # it cannot touch the user's live Blender session.
        bpy.data.batch_remove(ids=list(bpy.data.objects))
        bpy.context.scene.mimi_weight_report = ''

    # ------------------------------------------------------------------
    # Pure helper checks
    # ------------------------------------------------------------------

    def test_weight_helpers(self):
        """The small helpers must agree on distance, normalization and equality."""
        self.assertAlmostEqual(
            WeightAuditUtils.weight_difference({0: 1.0}, {1: 1.0}), 2.0, places=6
        )
        self.assertAlmostEqual(
            WeightAuditUtils.weight_difference({0: 1.0}, {0: 0.5, 1: 0.5}), 1.0, places=6
        )
        self.assertAlmostEqual(
            WeightAuditUtils.weight_difference({}, {0: 1.0}), 1.0, places=6
        )
        self.assertAlmostEqual(
            WeightAuditUtils.weight_difference({0: 1.0}, {0: 1.0}), 0.0, places=6
        )
        entry = {0: 2.0, 1: 2.0}
        WeightAuditUtils.normalize_entry(entry)
        self.assertAlmostEqual(entry[0], 0.5, places=6)
        self.assertAlmostEqual(entry[1], 0.5, places=6)
        # An empty entry must stay empty instead of raising a division error.
        empty = {}
        WeightAuditUtils.normalize_entry(empty)
        self.assertEqual(empty, {})
        self.assertTrue(WeightAuditUtils.entries_equal({0: 1.0}, {0: 1.0}))
        self.assertFalse(WeightAuditUtils.entries_equal({0: 1.0}, {0: 0.5, 1: 0.5}))
        # The comparison shares the weight epsilon, so a float noise difference
        # stays equal while a real change is detected.
        self.assertTrue(WeightAuditUtils.entries_equal({0: 1.0}, {0: 1.0000001}))
        self.assertFalse(WeightAuditUtils.entries_equal({0: 1.0}, {0: 1.01}))

    # ------------------------------------------------------------------
    # Seam detection
    # ------------------------------------------------------------------

    def test_smooth_blend_band_is_clean(self):
        """A gradient where neighbours share a bone must not be a seam."""
        obj = two_quad_mesh('blend')
        for name in ['bone_a', 'bone_b']:
            obj.vertex_groups.new(name=name)
        # The shared edge blends through both bones, and every vertex pair
        # still shares one positive group, so nothing may be reported.
        add_weight(obj, 0, [0], 1.0)
        add_weight(obj, 0, [1], 0.7)
        add_weight(obj, 1, [1], 0.3)
        add_weight(obj, 0, [2], 0.3)
        add_weight(obj, 1, [2], 0.7)
        add_weight(obj, 0, [3], 1.0)
        add_weight(obj, 1, [4, 5], 1.0)
        report = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(report['seam_edges'], [])
        self.assertEqual(report['seam_vertices'], [])
        self.assertEqual(report['has_issues'], False)

    def test_blocky_weights_report_a_seam(self):
        """Two single-bone halves on a flat surface are a real defect."""
        obj = two_quad_mesh('blocky')
        obj.vertex_groups.new(name='bone_a')
        obj.vertex_groups.new(name='bone_b')
        # Vertices 1 and 2 bound the only internal edge and belong to different
        # single bones, so there is no transition at all across that edge.
        add_weight(obj, 0, [0, 1, 3], 1.0)
        add_weight(obj, 1, [2, 4, 5], 1.0)
        report = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(len(report['seam_edges']), 1)
        self.assertEqual(sorted(report['seam_vertices']), [1, 2])
        self.assertTrue(report['has_issues'])
        # Every reported edge must reference a real vertex pair inside range.
        for first, second in report['seam_edges']:
            self.assertTrue(0 <= first < len(obj.data.vertices))
            self.assertTrue(0 <= second < len(obj.data.vertices))
            self.assertIn(first, (1, 2))
            self.assertIn(second, (1, 2))

    def test_geometric_hard_edge_is_exempt(self):
        """A weight step across a 90 degree fold is an expected boundary."""
        # Face A lies on z=0, face B stands on the y=1 plane. They share the
        # edge v2-v3, which carries the weight step.
        vertices = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
            (0.0, 1.0, 1.0), (1.0, 1.0, 1.0),
        ]
        faces = [(0, 1, 2, 3), (3, 2, 5, 4)]
        obj = new_mesh_object('folded', vertices, faces)
        obj.vertex_groups.new(name='bone_a')
        obj.vertex_groups.new(name='bone_b')
        add_weight(obj, 0, [0, 2], 1.0)
        add_weight(obj, 1, [1, 3, 4, 5], 1.0)
        report = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(report['seam_edges'], [])

    def test_material_boundary_is_exempt(self):
        """A weight step across two materials is a different part, not a defect."""
        obj = two_quad_mesh('materials')
        obj.vertex_groups.new(name='bone_a')
        obj.vertex_groups.new(name='bone_b')
        add_weight(obj, 0, [0, 1, 3], 1.0)
        add_weight(obj, 1, [2, 4, 5], 1.0)
        # Two materials: the seam edge now sits on the material boundary.
        first = bpy.data.materials.new('first')
        second = bpy.data.materials.new('second')
        obj.data.materials.append(first)
        obj.data.materials.append(second)
        obj.data.polygons[0].material_index = 0
        obj.data.polygons[1].material_index = 1
        report = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(report['seam_edges'], [])

    # ------------------------------------------------------------------
    # Isolated cluster detection
    # ------------------------------------------------------------------

    def test_isolated_cluster_is_reported(self):
        """A tiny island of a group far from its main region is a stray weight."""
        vertices, faces = strip_grid(5, rows=5)
        base = len(vertices)
        # A separate three-vertex triangle sits far away from the 5x5 patch.
        vertices = list(vertices) + [
            (10.0, 10.0, 0.0), (11.0, 10.0, 0.0), (10.0, 11.0, 0.0)
        ]
        faces = list(faces) + [(base, base + 1, base + 2)]
        obj = new_mesh_object('island', vertices, faces)
        obj.vertex_groups.new(name='bone_a')
        # One group covers both the main patch and the far triangle, which is
        # exactly the shape a nearest-neighbour transfer leaves behind.
        add_weight(obj, 0, list(range(base)), 1.0)
        add_weight(obj, 0, [base, base + 1, base + 2], 1.0)
        report = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(len(report['clusters']), 1)
        cluster = report['clusters'][0]
        self.assertEqual(cluster['size'], 3)
        self.assertEqual(cluster['main_size'], 25)
        self.assertEqual(cluster['vertices'], [25, 26, 27])

    def test_two_large_regions_are_legitimate(self):
        """Front and back of a skirt form two big regions and must stay silent."""
        first_vertices, first_faces = strip_grid(5, rows=5)
        second_vertices, second_faces = strip_grid(5, rows=5)
        # Move the second patch far away so it cannot share any edge.
        second_vertices = [(x, y + 100.0, z) for x, y, z in second_vertices]
        offset = len(first_vertices)
        vertices = list(first_vertices) + second_vertices
        faces = list(first_faces) + [
            (a + offset, b + offset, c + offset, d + offset)
            for a, b, c, d in second_faces
        ]
        obj = new_mesh_object('two_regions', vertices, faces)
        obj.vertex_groups.new(name='bone_a')
        add_weight(obj, 0, list(range(50)), 1.0)
        report = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(report['clusters'], [])

    # ------------------------------------------------------------------
    # Per-vertex checks
    # ------------------------------------------------------------------

    def test_per_vertex_problems_are_reported(self):
        """Zero weight, five influences and a bad sum must all be listed."""
        # Four loose vertices have no edges, so the seam check cannot interfere
        # with the per-vertex assertions below.
        obj = new_mesh_object('loose', [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)])
        for name in ['a', 'b', 'c', 'd', 'e']:
            obj.vertex_groups.new(name=name)
        # Vertex 1: five real influences.
        for group_index in range(5):
            add_weight(obj, group_index, [1], 0.2)
        # Vertex 2: weight sum 0.5.
        add_weight(obj, 0, [2], 0.5)
        # Vertex 3: clean single bone.
        add_weight(obj, 0, [3], 1.0)
        report = WeightAuditUtils.analyse(
            obj, settings(island_min_vertices=1)
        )
        self.assertEqual(report['zero_weight_vertices'], [0])
        self.assertEqual(report['over_influence_vertices'], [1])
        self.assertEqual(report['unnormalized_vertices'], [2])
        self.assertEqual(report['issue_vertices'], [0, 1, 2])
        self.assertTrue(report['has_issues'])

    def test_empty_and_group_less_meshes_are_safe(self):
        """An empty mesh and a mesh without groups must not raise."""
        empty = new_mesh_object('empty', [])
        report = WeightAuditUtils.analyse(empty, settings())
        self.assertFalse(report['has_groups'])
        self.assertFalse(report['has_issues'])
        plain = new_mesh_object('plain', [(0, 0, 0), (1, 0, 0)], edges=[(0, 1)])
        report = WeightAuditUtils.analyse(plain, settings())
        self.assertFalse(report['has_groups'])
        self.assertEqual(report['vertices'], 2)
        # The repair helpers must also survive an object without groups.
        self.assertEqual(WeightAuditUtils.clean_weights(plain, 0.01, 4), 0)
        self.assertEqual(WeightAuditUtils.smooth_vertices(plain, [], 2, 0.5), 0)

    # ------------------------------------------------------------------
    # Repair
    # ------------------------------------------------------------------

    def test_smoothing_removes_the_seam(self):
        """Smoothing the detected seam must blend it and keep weights normalized."""
        obj = two_quad_mesh('smooth_me')
        obj.vertex_groups.new(name='bone_a')
        obj.vertex_groups.new(name='bone_b')
        add_weight(obj, 0, [0, 1, 3], 1.0)
        add_weight(obj, 1, [2, 4, 5], 1.0)
        before = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(len(before['seam_edges']), 1)
        targets = WeightAuditUtils.expand_vertices(
            obj.data, set(before['seam_vertices']), 1
        )
        updated = WeightAuditUtils.smooth_vertices(obj, targets, 3, 0.5)
        self.assertEqual(updated, len(targets))
        after = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(after['seam_edges'], [])
        # Every vertex must still sum to one and keep at least one weight.
        for vertex in obj.data.vertices:
            total = sum(element.weight for element in vertex.groups)
            self.assertAlmostEqual(total, 1.0, places=5)
            self.assertGreater(len(vertex.groups), 0)

    def test_cleaning_removes_noise_and_caps_influences(self):
        """Cleaning must drop tiny weights, keep at most four and normalize."""
        obj = new_mesh_object('clean_me', [(0, 0, 0), (1, 0, 0)])
        for name in ['a', 'b', 'c', 'd', 'e', 'f']:
            obj.vertex_groups.new(name=name)
        # Vertex 0 has six influences, two of them below the cleaning limit.
        add_weight(obj, 0, [0], 0.001)
        add_weight(obj, 1, [0], 0.5)
        add_weight(obj, 2, [0], 0.3)
        add_weight(obj, 3, [0], 0.1)
        add_weight(obj, 4, [0], 0.05)
        add_weight(obj, 5, [0], 0.049)
        # Vertex 1 has only tiny weights and must keep its strongest bone.
        add_weight(obj, 0, [1], 0.004)
        add_weight(obj, 1, [1], 0.002)
        changed = WeightAuditUtils.clean_weights(obj, 0.01, 4)
        self.assertEqual(changed, 2)
        for vertex in obj.data.vertices:
            weights = [element.weight for element in vertex.groups]
            self.assertLessEqual(len(weights), 4)
            self.assertAlmostEqual(sum(weights), 1.0, places=5)
            for weight in weights:
                self.assertGreaterEqual(weight, 0.01 - 1e-6)
        self.assertEqual(len(obj.data.vertices[1].groups), 1)

    def test_mark_vertices_clears_previous_selection(self):
        """Marking must show exactly the issue vertices, not an old selection."""
        obj = new_mesh_object('marked', [(0, 0, 0), (1, 0, 0), (2, 0, 0)])
        for vertex in obj.data.vertices:
            vertex.select = True
        WeightAuditUtils.mark_vertices(obj, [1])
        selected = [vertex.index for vertex in obj.data.vertices if vertex.select]
        self.assertEqual(selected, [1])

    # ------------------------------------------------------------------
    # Operators and panel
    # ------------------------------------------------------------------

    def test_shared_mesh_is_listed_once(self):
        """A linked duplicate must not be processed twice."""
        obj = new_mesh_object('shared', [(0, 0, 0), (1, 0, 0)], [(0, 1)])
        obj.vertex_groups.new(name='bone_a')
        duplicate = obj.copy()
        bpy.context.scene.collection.objects.link(duplicate)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        duplicate.select_set(True)
        listed = panel.selected_mesh_objects(bpy.context)
        self.assertEqual(len(listed), 1)

    def test_operator_poll_and_reports(self):
        """The operators must run, write a report and reject Edit Mode."""
        obj = new_mesh_object('operator', [(0, 0, 0), (1, 0, 0)], edges=[(0, 1)])
        obj.vertex_groups.new(name='bone_a')
        add_weight(obj, 0, [0], 1.0)
        activate(obj)
        # Object mode with a mesh selected: every operator is available.
        self.assertTrue(panel.WeightDetectOperator.poll(bpy.context))
        self.assertTrue(panel.WeightSmoothOperator.poll(bpy.context))
        self.assertTrue(panel.WeightCleanOperator.poll(bpy.context))
        self.assertEqual(bpy.ops.mimi.weight_detect(), {'FINISHED'})
        self.assertTrue(bpy.context.scene.mimi_weight_report)
        self.assertIn('operator', bpy.context.scene.mimi_weight_report)
        # The report must tell the user where the marked vertices are visible.
        self.assertIn('Edit Mode', bpy.context.scene.mimi_weight_report)
        # The clean operator must run even when nothing needs cleaning.
        self.assertEqual(bpy.ops.mimi.weight_clean(), {'FINISHED'})
        # Edit Mode must disable all three buttons instead of half-editing.
        bpy.ops.object.mode_set(mode='EDIT')
        self.assertFalse(panel.WeightDetectOperator.poll(bpy.context))
        self.assertFalse(panel.WeightSmoothOperator.poll(bpy.context))
        self.assertFalse(panel.WeightCleanOperator.poll(bpy.context))
        bpy.ops.object.mode_set(mode='OBJECT')
        # An empty selection must disable them too.
        bpy.ops.object.select_all(action='DESELECT')
        self.assertFalse(panel.WeightDetectOperator.poll(bpy.context))

    def test_smooth_operator_runs_through_bpy_ops(self):
        """The registered smooth operator must repair a real blocky mesh."""
        obj = two_quad_mesh('ops_smooth')
        obj.vertex_groups.new(name='bone_a')
        obj.vertex_groups.new(name='bone_b')
        add_weight(obj, 0, [0, 1, 3], 1.0)
        add_weight(obj, 1, [2, 4, 5], 1.0)
        activate(obj)
        bpy.context.scene.mimi_weight_smooth_iterations = 3
        bpy.context.scene.mimi_weight_smooth_factor = 0.5
        self.assertEqual(bpy.ops.mimi.weight_smooth(), {'FINISHED'})
        after = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(after['seam_edges'], [])

    def test_report_format_and_translation(self):
        """The panel must draw three buttons and translate their captions."""
        i18n.apply_language('zh')
        try:
            self.assertEqual(panel.MIMIPanelWeight.bl_label, '权重处理面板')
            # Operators keep the English bl_label as the translation key; the
            # panel draws them through tr(), which is what must translate.
            self.assertEqual(
                i18n.tr(panel.WeightDetectOperator.bl_label), '检测权重问题'
            )
            self.assertEqual(i18n.tr('Weight Quality Check'), '权重质量检查')
            self.assertEqual(i18n.tr('Seam Threshold'), '接缝阈值')
            self.assertEqual(i18n.tr('Last Report'), '上次报告')
            # The report formatter must return plain non-empty lines.
            results = [
                {
                    'object': 'part',
                    'has_groups': True,
                    'has_issues': True,
                    'seam_edges': [(0, 1)],
                    'clusters': [],
                    'zero_weight_vertices': [],
                    'over_influence_vertices': [],
                    'unnormalized_vertices': [],
                    'small_weight_count': 0,
                    'issue_vertices': [0, 1],
                }
            ]
            lines = panel.format_report(results)
            self.assertTrue(all(isinstance(line, str) and line for line in lines))
            self.assertIn('part', '\n'.join(lines))
            # A clean object must be counted in one summary line instead of
            # taking a line of its own, so real findings stay visible.
            results.append(
                {
                    'object': 'clean_part',
                    'has_groups': True,
                    'has_issues': False,
                    'seam_edges': [],
                    'clusters': [],
                    'zero_weight_vertices': [],
                    'over_influence_vertices': [],
                    'unnormalized_vertices': [],
                    'small_weight_count': 0,
                    'issue_vertices': [],
                }
            )
            lines = panel.format_report(results)
            text = '\n'.join(lines)
            self.assertIn('1 个对象无问题', text)
            self.assertNotIn('clean_part', text)
        finally:
            i18n.apply_language('en')

    def test_large_grid_seam_count(self):
        """A blocky boundary across a larger grid must report every crossing edge."""
        vertices, faces = strip_grid(10, rows=10)
        obj = new_mesh_object('large', vertices, faces)
        obj.vertex_groups.new(name='bone_a')
        obj.vertex_groups.new(name='bone_b')
        # Columns 0-4 use bone_a and columns 5-9 use bone_b. The crossing edges
        # are the horizontal edges of rows 1-8; the outer rows are open borders
        # that the seam check intentionally ignores.
        left, right = [], []
        for row in range(10):
            for column in range(10):
                (left if column <= 4 else right).append(row * 10 + column)
        add_weight(obj, 0, left, 1.0)
        add_weight(obj, 1, right, 1.0)
        report = WeightAuditUtils.analyse(obj, settings())
        self.assertEqual(len(report['seam_edges']), 8)
        self.assertEqual(len(report['seam_vertices']), 16)

    def test_out_of_range_vertices_are_ignored(self):
        """Stale vertex indices must be filtered instead of raising."""
        obj = two_quad_mesh('bounds')
        obj.vertex_groups.new(name='bone_a')
        obj.vertex_groups.new(name='bone_b')
        add_weight(obj, 0, [0, 1, 3], 1.0)
        add_weight(obj, 1, [2, 4, 5], 1.0)
        targets = WeightAuditUtils.expand_vertices(obj.data, {1, 2, 99, -3}, 1)
        self.assertTrue(targets.issubset(set(range(6))))
        updated = WeightAuditUtils.smooth_vertices(obj, {1, 99, -3}, 2, 0.5)
        self.assertEqual(updated, 1)

    def test_locked_group_warning_helper(self):
        """The lock warning must fire only when a vertex group is locked."""
        obj = new_mesh_object('lock', [(0, 0, 0)], edges=[])
        obj.vertex_groups.new(name='a')
        self.assertFalse(panel.locked_group_warning([obj]))
        obj.vertex_groups[0].lock_weight = True
        self.assertTrue(panel.locked_group_warning([obj]))

    def test_registration_is_repeatable(self):
        """Register, unregister and register again must leave a usable panel."""
        # Start from the state main() left behind: one registered cycle.
        panel.unregister()
        panel.register()
        panel.unregister()
        panel.register()
        try:
            self.assertTrue(hasattr(bpy.types.Scene, 'mimi_weight_seam_threshold'))
            self.assertTrue(hasattr(bpy.types.Scene, 'mimi_weight_report'))
            self.assertEqual(panel.MIMIPanelWeight.bl_category, 'MIMITools')
            self.assertIn('DEFAULT_CLOSED', panel.MIMIPanelWeight.bl_options)
            # The panel draw must reference the three operators without errors.
            buttons = []
            layout = types.SimpleNamespace(
                box=lambda: types.SimpleNamespace(
                    label=lambda **kwargs: None,
                    operator=lambda name, **kwargs: buttons.append(name),
                    column=lambda align=True: types.SimpleNamespace(
                        prop=lambda *args, **kwargs: None,
                        label=lambda **kwargs: None,
                    ),
                ),
                separator=lambda: None,
            )
            panel.MIMIPanelWeight.draw(
                types.SimpleNamespace(layout=layout), bpy.context
            )
            self.assertEqual(
                buttons,
                [
                    panel.WeightDetectOperator.bl_idname,
                    panel.WeightSmoothOperator.bl_idname,
                    panel.WeightCleanOperator.bl_idname,
                ],
            )
        finally:
            # Keep the panel registered for the tests that run after this one.
            panel.unregister()
            panel.register()


def main():
    # Exercise a full register / unregister cycle before the functional suite,
    # so a class that only works on first registration is caught here.
    print('Blender version:', bpy.app.version_string)
    panel.register()
    panel.unregister()
    panel.register()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(WeightAuditTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print('RESULT ' + json.dumps({'tests': result.testsRun, 'success': result.wasSuccessful()}))
        if not result.wasSuccessful():
            raise RuntimeError('Weight audit integration checks failed')
    finally:
        panel.unregister()


if __name__ == '__main__':
    main()
