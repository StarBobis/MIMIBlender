"""Blender acceptance tests for the generic merged sculpting feature.

Covers the core module (create / apply / discard / validate), the failure
guards (missing source, vertex count change, duplicated UID) and the UI
wiring (panel + operators registered, operator roundtrip via bpy.ops).

Run with:
    blender -b --factory-startup --python-exit-code 1 --python tools/test_merged_sculpt_blender.py
"""

import importlib
import json
import sys
import unittest
from pathlib import Path

import bpy
import numpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / "tools"))
# Importing the package executes __init__.py but does not register it;
# the __main__ block registers the addon explicitly for the UI tests.
addon = importlib.import_module(ROOT.name)

from MIMIBlender.utils.merged_sculpt_utils import (
    MERGED_NAME_PREFIX,
    PROP_SOURCE_UID,
    PROP_SOURCES,
    MergedSculptUtils,
)

# Shared cube geometry: 8 vertices, 6 quad faces, centered on the origin.
CUBE_VERTS = [
    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
]
CUBE_FACES = [
    (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
    (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7),
]


def make_cube(name, location=(0.0, 0.0, 0.0), scale=1.0, rotation=(0.0, 0.0, 0.0)):
    """Create a unit cube mesh object with an optional object transform."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(CUBE_VERTS, [], CUBE_FACES)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.scale = (scale, scale, scale)
    obj.rotation_euler = rotation
    return obj


def select_only(objects):
    """Replace the selection with the given objects (data API, headless safe).

    bpy.ops.object.select_all is avoided on purpose: its poll() needs a 3D
    viewport context and can fail in background mode.
    """
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def read_cos(points):
    """Read a flat float64 copy of a vertex/key-point collection."""
    flat = numpy.zeros(len(points) * 3, dtype=numpy.float32)
    points.foreach_get("co", flat)
    return flat.reshape((-1, 3)).astype(numpy.float64)


def offset_cos(points, delta):
    """Move every point of a vertex/key-point collection by one delta."""
    values = read_cos(points)
    values += numpy.asarray(delta, dtype=numpy.float64)
    flat = numpy.ascontiguousarray(values, dtype=numpy.float32).ravel()
    points.foreach_set("co", flat)


class MergedSculptTests(unittest.TestCase):
    """End-to-end tests of the merged sculpting session lifecycle."""

    def setUp(self):
        # Start every test from an empty scene for full isolation.
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh)
        bpy.context.view_layer.update()

    def create_merged(self, objects):
        """Select the given sources and run the merge (with a fresh depsgraph
        so matrix_world reflects every transform assigned just before)."""
        select_only(objects)
        bpy.context.view_layer.update()
        merged, warnings = MergedSculptUtils.create_merged_object(bpy.context)
        # No test in this suite intentionally produces a shape key mismatch.
        self.assertEqual([], warnings)
        return merged

    def sculpt_merged(self, merged, delta):
        """Simulate a sculpt stroke: offset every merged vertex by delta in
        merged local space (Basis key when the merged mesh has shape keys)."""
        shape_keys = merged.data.shape_keys
        if shape_keys is not None:
            offset_cos(shape_keys.key_blocks["Basis"].data, delta)
        else:
            offset_cos(merged.data.vertices, delta)

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------
    def test_roundtrip_three_objects(self):
        cubes = [make_cube("cube_a"), make_cube("cube_b"), make_cube("cube_c")]
        before = [read_cos(cube.data.vertices) for cube in cubes]

        merged = self.create_merged(cubes)
        merged_name = merged.name
        merged_mesh_name = merged.data.name

        # One merged object with the full vertex budget, schema v2 payload
        # and "<session>:<uid>" stamps on every source.
        self.assertTrue(merged_name.startswith(MERGED_NAME_PREFIX))
        self.assertEqual(24, len(merged.data.vertices))
        payload = json.loads(merged[PROP_SOURCES])
        self.assertEqual(2, payload["version"])
        self.assertEqual(3, len(payload["sources"]))
        for index, cube in enumerate(cubes):
            record = payload["sources"][index]
            self.assertEqual(payload["session"] + ":" + record["uid"],
                             cube[PROP_SOURCE_UID])

        # Sculpt a constant offset, then apply: identity transforms mean the
        # sources must receive exactly old_position + delta.
        delta = (0.1, 0.2, 0.3)
        self.sculpt_merged(merged, delta)
        self.assertEqual(3, MergedSculptUtils.apply_merged_sculpt(bpy.context))

        for cube, old in zip(cubes, before):
            numpy.testing.assert_allclose(
                read_cos(cube.data.vertices), old + numpy.asarray(delta),
                atol=1e-5)
            self.assertNotIn(PROP_SOURCE_UID, cube)
        # Applying is the end of the session: merged object and mesh are gone.
        self.assertNotIn(merged_name, bpy.data.objects)
        self.assertNotIn(merged_mesh_name, bpy.data.meshes)

    def test_single_object_rejected(self):
        cube = make_cube("solo")
        select_only([cube])
        with self.assertRaisesRegex(ValueError, "at least 2"):
            MergedSculptUtils.create_merged_object(bpy.context)

    def test_two_and_seven_objects(self):
        for count in (2, 7):
            cubes = [make_cube("n%d_c%d" % (count, i)) for i in range(count)]
            merged = self.create_merged(cubes)
            # The merged vertex count is exactly the sum of the sources.
            self.assertEqual(8 * count, len(merged.data.vertices))
            payload = json.loads(merged[PROP_SOURCES])
            self.assertEqual(count, len(payload["sources"]))
            MergedSculptUtils.discard_merged_sculpt(bpy.context)
            for cube in cubes:
                self.assertNotIn(PROP_SOURCE_UID, cube)

    def test_transforms_world_invariant(self):
        # The second source has a non-trivial transform; the first keeps the
        # identity, so merged space equals world space in this test.
        cube_a = make_cube("base")
        cube_b = make_cube("moved", location=(5, 1, -2), scale=2.0,
                           rotation=(0.3, 0.2, 0.1))
        merged = self.create_merged([cube_a, cube_b])
        merged_before = read_cos(merged.data.vertices)

        delta = (0.25, -0.5, 0.75)
        self.sculpt_merged(merged, delta)
        self.assertEqual(2, MergedSculptUtils.apply_merged_sculpt(bpy.context))
        bpy.context.view_layer.update()

        # World-space invariant (the actual contract): for every vertex,
        # M_src @ co_src == old merged position + delta. The merged old
        # positions were captured before sculpting, so this is not circular.
        expected = merged_before + numpy.asarray(delta)
        got_a = numpy.array(
            [cube_a.matrix_world @ Vector(co) for co in read_cos(cube_a.data.vertices)])
        got_b = numpy.array(
            [cube_b.matrix_world @ Vector(co) for co in read_cos(cube_b.data.vertices)])
        numpy.testing.assert_allclose(got_a, expected[0:8], atol=1e-4)
        numpy.testing.assert_allclose(got_b, expected[8:16], atol=1e-4)

    def test_rename_during_sculpting_is_safe(self):
        cubes = [make_cube("name_one"), make_cube("name_two")]
        merged = self.create_merged(cubes)
        # Renaming must not break the UID-based source resolution.
        cubes[0].name = "completely_different_a"
        cubes[1].name = "completely_different_b"

        before = [read_cos(cube.data.vertices) for cube in cubes]
        delta = (0.0, 0.0, 0.5)
        self.sculpt_merged(merged, delta)
        self.assertEqual(2, MergedSculptUtils.apply_merged_sculpt(bpy.context))
        for cube, old in zip(cubes, before):
            numpy.testing.assert_allclose(
                read_cos(cube.data.vertices), old + numpy.asarray(delta),
                atol=1e-5)

    def _make_shape_key_cubes(self):
        """Two cubes sharing identical shape keys: Basis plus a deform key
        whose points are offset by (1, 0, 0) so it is distinguishable."""
        cubes = [make_cube("sk_a"), make_cube("sk_b")]
        for cube in cubes:
            cube.shape_key_add(name="Basis")
            deform = cube.shape_key_add(name="deform")
            offset_cos(deform.data, (1.0, 0.0, 0.0))
        return cubes

    def test_shape_keys_apply_deltas_to_all_keys(self):
        cubes = self._make_shape_key_cubes()
        merged = self.create_merged(cubes)
        # The join keeps the shared key set on the merged object.
        self.assertIsNotNone(merged.data.shape_keys)

        old_basis = [read_cos(c.data.shape_keys.key_blocks["Basis"].data) for c in cubes]
        old_deform = [read_cos(c.data.shape_keys.key_blocks["deform"].data) for c in cubes]

        delta = (0.0, 0.4, 0.0)
        self.sculpt_merged(merged, delta)
        self.assertEqual(2, MergedSculptUtils.apply_merged_sculpt(
            bpy.context, apply_deltas_to_shapekeys=True))

        for index, cube in enumerate(cubes):
            keys = cube.data.shape_keys.key_blocks
            numpy.testing.assert_allclose(
                read_cos(keys["Basis"].data), old_basis[index] + delta, atol=1e-5)
            # With deltas enabled every key moves by the same sculpt delta.
            numpy.testing.assert_allclose(
                read_cos(keys["deform"].data), old_deform[index] + delta, atol=1e-5)

    def test_shape_keys_default_touches_basis_only(self):
        cubes = self._make_shape_key_cubes()
        merged = self.create_merged(cubes)
        old_deform = [read_cos(c.data.shape_keys.key_blocks["deform"].data) for c in cubes]

        delta = (0.0, 0.4, 0.0)
        self.sculpt_merged(merged, delta)
        self.assertEqual(2, MergedSculptUtils.apply_merged_sculpt(bpy.context))

        for index, cube in enumerate(cubes):
            keys = cube.data.shape_keys.key_blocks
            # The non-Basis keys stay untouched without the deltas option.
            numpy.testing.assert_allclose(
                read_cos(keys["deform"].data), old_deform[index], atol=1e-6)

    # ------------------------------------------------------------------
    # Failure guards (all-or-nothing: nothing may be written on failure)
    # ------------------------------------------------------------------
    def test_missing_source_aborts_everything(self):
        cubes = [make_cube("keep_a"), make_cube("doomed"), make_cube("keep_b")]
        before = [read_cos(cube.data.vertices) for cube in cubes]
        merged = self.create_merged(cubes)
        merged_name = merged.name
        self.sculpt_merged(merged, (0.1, 0.1, 0.1))

        doomed_mesh = cubes[1].data
        bpy.data.objects.remove(cubes[1], do_unlink=True)
        bpy.data.meshes.remove(doomed_mesh)

        with self.assertRaisesRegex(ValueError, "Missing source objects"):
            MergedSculptUtils.apply_merged_sculpt(bpy.context)
        # Survivors untouched, stamps kept, merged object still there.
        numpy.testing.assert_allclose(
            read_cos(cubes[0].data.vertices), before[0], atol=1e-6)
        numpy.testing.assert_allclose(
            read_cos(cubes[2].data.vertices), before[2], atol=1e-6)
        self.assertIn(PROP_SOURCE_UID, cubes[0])
        self.assertIn(merged_name, bpy.data.objects)
        MergedSculptUtils.discard_merged_sculpt(bpy.context)

    def test_vertex_count_change_aborts(self):
        cubes = [make_cube("vc_a"), make_cube("vc_b")]
        merged = self.create_merged(cubes)

        # Rebuild the merged mesh with one extra vertex (a remesh stand-in).
        # Note: in Blender 5.2 from_pydata() updates an existing mesh IN
        # PLACE and fails on a different vertex count, so the rebuild needs
        # a brand new mesh datablock assigned to the merged object.
        data = merged.data
        verts = [tuple(co) for co in read_cos(data.vertices)] + [(0.0, 0.0, 0.0)]
        faces = [tuple(polygon.vertices) for polygon in data.polygons]
        new_mesh = bpy.data.meshes.new("remeshed_stand_in")
        new_mesh.from_pydata(verts, [], faces)
        merged.data = new_mesh
        self.assertEqual(17, len(merged.data.vertices))

        with self.assertRaisesRegex(ValueError, "vertex count changed"):
            MergedSculptUtils.apply_merged_sculpt(bpy.context)
        # The session is still alive; discard cleans it up (and removes the
        # stand-in mesh together with the merged object).
        MergedSculptUtils.discard_merged_sculpt(bpy.context)
        bpy.data.meshes.remove(data)  # the orphaned pre-remesh mesh
        for cube in cubes:
            self.assertNotIn(PROP_SOURCE_UID, cube)

    def test_duplicated_source_uid_aborts(self):
        cubes = [make_cube("dup_a"), make_cube("dup_b")]
        self.create_merged(cubes)
        # obj.copy() inherits custom properties, so the copy carries the same
        # session UID stamp: the resolution must refuse to guess.
        rogue = cubes[0].copy()
        bpy.context.scene.collection.objects.link(rogue)
        with self.assertRaisesRegex(ValueError, "same session UID"):
            MergedSculptUtils.apply_merged_sculpt(bpy.context)
        bpy.data.objects.remove(rogue, do_unlink=True)
        MergedSculptUtils.discard_merged_sculpt(bpy.context)

    # ------------------------------------------------------------------
    # Multi-session, validate, discard
    # ------------------------------------------------------------------
    def test_two_concurrent_sessions_stay_separate(self):
        group_a = [make_cube("ga_1"), make_cube("ga_2")]
        group_b = [make_cube("gb_1"), make_cube("gb_2")]
        merged_a = self.create_merged(group_a)
        merged_a_name = merged_a.name
        merged_b = self.create_merged(group_b)

        # The newest merged object is active, so apply targets session B.
        before_b = [read_cos(cube.data.vertices) for cube in group_b]
        delta = (0.0, 0.0, 1.0)
        self.sculpt_merged(merged_b, delta)
        self.assertEqual(2, MergedSculptUtils.apply_merged_sculpt(bpy.context))

        for cube, old in zip(group_b, before_b):
            numpy.testing.assert_allclose(
                read_cos(cube.data.vertices), old + numpy.asarray(delta),
                atol=1e-5)
        # Session A is completely untouched by session B's apply.
        for cube in group_a:
            self.assertIn(PROP_SOURCE_UID, cube)
        self.assertIn(merged_a_name, bpy.data.objects)

        # Clean session A explicitly by selecting its merged object.
        select_only([bpy.data.objects[merged_a_name]])
        MergedSculptUtils.discard_merged_sculpt(bpy.context)
        for cube in group_a:
            self.assertNotIn(PROP_SOURCE_UID, cube)
        self.assertNotIn(merged_a_name, bpy.data.objects)

    def test_validate_reports_moved_source(self):
        cubes = [make_cube("val_a"), make_cube("val_b")]
        self.create_merged(cubes)
        # A fresh session has no issues.
        self.assertEqual([], MergedSculptUtils.validate_merged_sculpt(bpy.context))

        cubes[1].location = (3.0, 0.0, 0.0)
        bpy.context.view_layer.update()
        issues = MergedSculptUtils.validate_merged_sculpt(bpy.context)
        self.assertTrue(any("moved during sculpting" in issue for issue in issues))
        MergedSculptUtils.discard_merged_sculpt(bpy.context)

    def test_discard_without_sculpting(self):
        cubes = [make_cube("dis_a"), make_cube("dis_b")]
        before = [read_cos(cube.data.vertices) for cube in cubes]
        merged = self.create_merged(cubes)
        merged_name = merged.name
        MergedSculptUtils.discard_merged_sculpt(bpy.context)
        # Sources unchanged, stamps and merged object removed.
        for cube, old in zip(cubes, before):
            numpy.testing.assert_allclose(
                read_cos(cube.data.vertices), old, atol=1e-6)
            self.assertNotIn(PROP_SOURCE_UID, cube)
        self.assertNotIn(merged_name, bpy.data.objects)

    # ------------------------------------------------------------------
    # UI wiring (the addon is registered by the __main__ block)
    # ------------------------------------------------------------------
    def test_ui_classes_registered(self):
        # Registration is fault-tolerant per module, so a silently failed
        # step would only surface here.
        # Panels are verified through Panel.__subclasses__() on purpose:
        # hasattr(bpy.types, <panel class>) is False even for the shipped
        # Model Processing panel (probed on Blender 5.2 headless), while
        # operators are reachable through bpy.types attribute lookup.
        panel_names = [cls.__name__ for cls in bpy.types.Panel.__subclasses__()]
        self.assertIn("MIMIPanelMergedSculpt", panel_names)
        for class_name in (
                "MIMI_OT_merged_sculpt_create",
                "MIMI_OT_merged_sculpt_apply",
                "MIMI_OT_merged_sculpt_discard",
                "MIMI_OT_merged_sculpt_validate"):
            self.assertTrue(hasattr(bpy.types, class_name))
        # The scene-level option of the panel exists as an RNA property.
        self.assertTrue(
            hasattr(bpy.types.Scene, "mimi_merged_sculpt_apply_deltas"))

    def test_operator_roundtrip(self):
        cubes = [make_cube("op_a"), make_cube("op_b")]
        select_only(cubes)
        bpy.context.view_layer.update()

        result = bpy.ops.mimi.merged_sculpt_create()
        self.assertEqual({"FINISHED"}, result)
        merged = bpy.context.view_layer.objects.active
        self.assertIsNotNone(merged)
        self.assertIn(PROP_SOURCES, merged)

        # The create operator may have switched to sculpt mode; return to
        # object mode so later selection changes behave predictably.
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass

        before = [read_cos(cube.data.vertices) for cube in cubes]
        delta = (0.0, 0.3, 0.0)
        self.sculpt_merged(merged, delta)
        result = bpy.ops.mimi.merged_sculpt_apply()
        self.assertEqual({"FINISHED"}, result)
        for cube, old in zip(cubes, before):
            numpy.testing.assert_allclose(
                read_cos(cube.data.vertices), old + numpy.asarray(delta),
                atol=1e-5)


if __name__ == "__main__":
    # The suite targets the installed 5.2 LTS API and emits a compact CI result.
    print("RESULT_VERSION " + json.dumps({"blender": list(bpy.app.version)}))
    addon.register()
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(MergedSculptTests))
    finally:
        addon.unregister()
    print("RESULT " + json.dumps({"tests": result.testsRun, "passed": result.wasSuccessful()}))
    if not result.wasSuccessful():
        raise AssertionError("Merged sculpt tests failed")
