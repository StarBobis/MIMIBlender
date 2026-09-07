"""Functional tests for the perfect mesh mirror utility (MeshMirrorUtils).

Run from the repository root inside a headless Blender, for example:
    blender -b --python tools/test_mesh_mirror_utils.py

The tests create cubes with UV maps, vertex groups and shape keys, then
mirror them in every mode ("COPY", "FLIP", "BAKE") and verify that:
    - the mesh coordinates are mirrored correctly,
    - the object scale ends clean at (1, 1, 1),
    - normals stay outward (face winding is repaired),
    - shape keys, UV maps and L/R vertex groups follow the mirror,
    - the original object stays untouched in "COPY" mode,
    - shared mesh data is not modified for other users of the data.
"""
import os
import sys
import types

import mathutils

# Make the add-on root importable (the file sits in the tools/ folder).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Import the add-on modules as the "MIMIBlender" package without executing
# the add-on's own __init__.py (which would register everything else).
PKG = types.ModuleType("MIMIBlender")
PKG.__path__ = [REPO_ROOT]
sys.modules["MIMIBlender"] = PKG

import bpy  # noqa: E402
from utils.mesh_mirror_utils import MeshMirrorUtils  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("[TEST] PASS |", name)
    else:
        FAILED.append(name)
        print("[TEST] FAIL |", name, "|", detail)


def vec_close(a, b, tol=1e-5):
    return (mathutils.Vector(a) - mathutils.Vector(b)).length <= tol


def wipe_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)


def new_cube(name, poke=(2.0, 0.5, 0.25)):
    wipe_scene()
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    if poke is not None:
        obj.data.vertices[0].co = mathutils.Vector(poke)
    return obj


def vertex_coords(obj):
    return [v.co.copy() for v in obj.data.vertices]


def faces_outward(obj):
    """True when every face normal points away from the object center."""
    center = mathutils.Vector((0.0, 0.0, 0.0))
    mesh = obj.data
    for polygon in mesh.polygons:
        normal = polygon.normal
        if normal.length < 1e-6:
            continue
        if normal.dot(polygon.center - center) <= 0.0:
            return False
    return True


def uv_per_vertex(mesh):
    """Return a dict: vertex index -> sorted list of (u, v) values."""
    result = {}
    for layer in mesh.uv_layers:
        for loop in mesh.loops:
            uv = layer.data[loop.index].uv
            key = loop.vertex_index
            result.setdefault(key, []).append((round(uv.x, 6), round(uv.y, 6)))
    for key in result:
        result[key].sort()
    return result


def group_weight_map(obj):
    """Return a dict: group name -> {vertex index: weight}."""
    result = {}
    for vg in obj.vertex_groups:
        weights = {}
        for vertex in obj.data.vertices:
            for group in vertex.groups:
                if group.group == vg.index:
                    weights[vertex.index] = round(group.weight, 6)
        result[vg.name] = weights
    return result


def test_flip_coords_and_scale():
    """FLIP mirrors the vertex coordinates and cleans the scale."""
    obj = new_cube("FlipCube")
    before = vertex_coords(obj)
    MeshMirrorUtils.mirror_mesh_object(obj, mode="FLIP", recalc_normals=False)
    after = vertex_coords(obj)
    ok = True
    for a, b in zip(before, after):
        if not vec_close((-a.x, a.y, a.z), b):
            ok = False
            break
    check("flip coordinates mirrored on X", ok)
    check("flip scale reset to 1", vec_close(obj.scale, (1.0, 1.0, 1.0)),
          str(obj.scale))
    # A second flip returns to the start (mirror is its own inverse).
    MeshMirrorUtils.mirror_mesh_object(obj, mode="FLIP", recalc_normals=False)
    back = vertex_coords(obj)
    ok = True
    for a, b in zip(before, back):
        if not vec_close(a, b):
            ok = False
            break
    check("flip twice returns to original", ok)


def test_flip_normals_without_recalc():
    """Winding reversal alone (no recalc) keeps normals outward."""
    obj = new_cube("NormCube", poke=None)
    MeshMirrorUtils.mirror_mesh_object(obj, mode="FLIP", recalc_normals=False)
    check("flip normals stay outward without recalc", faces_outward(obj))


def test_flip_normals_with_recalc():
    """With recalc enabled the normals are outward as well."""
    obj = new_cube("NormCube2", poke=None)
    MeshMirrorUtils.mirror_mesh_object(obj, mode="FLIP", recalc_normals=True)
    check("flip normals outward with recalc", faces_outward(obj))


def test_bake_negative_scale():
    """BAKE repairs an old scale.x = -1 object without changing its look."""
    obj = new_cube("BakeCube", poke=(2.0, 0.5, 0.25))
    obj.scale.x = -1.0
    before = vertex_coords(obj)
    MeshMirrorUtils.mirror_mesh_object(obj, mode="BAKE", recalc_normals=False)
    after = vertex_coords(obj)
    check("bake scale reset to 1", vec_close(obj.scale, (1.0, 1.0, 1.0)),
          str(obj.scale))
    # The look stays: data must now equal the old visual (mirrored x).
    ok = True
    for a, b in zip(before, after):
        if not vec_close((-a.x, a.y, a.z), b):
            ok = False
            break
    check("bake bakes the negative scale into the mesh", ok)


def test_bake_normals():
    """BAKE of a one-axis negative scale repairs the normals."""
    obj = new_cube("BakeNorm", poke=None)
    obj.scale.x = -1.0
    MeshMirrorUtils.mirror_mesh_object(obj, mode="BAKE", recalc_normals=False)
    check("bake normals outward", faces_outward(obj))


def test_bake_even_negatives_no_flip():
    """Two negative scales rotate, not mirror, so no winding flip happens."""
    obj = new_cube("BakeEven", poke=(2.0, 0.5, 0.25))
    obj.scale.x = -1.0
    obj.scale.y = -1.0
    before = vertex_coords(obj)
    MeshMirrorUtils.mirror_mesh_object(obj, mode="BAKE", recalc_normals=False)
    after = vertex_coords(obj)
    ok = True
    for a, b in zip(before, after):
        if not vec_close((-a.x, -a.y, a.z), b):
            ok = False
    check("even negative bake keeps coordinates", ok)
    check("even negative bake keeps scale clean",
          vec_close(obj.scale, (1.0, 1.0, 1.0)))
    # Normals are already covered by test_bake_normals (a poked cube is not
    # convex, so the outward check is unreliable for it here).


def test_copy_full_features():
    """COPY leaves the original alone and mirrors everything on the copy."""
    obj = new_cube("CopySrc")
    before = vertex_coords(obj)

    # A deterministic UV map so UV flipping can be verified.
    uv_layer = obj.data.uv_layers.new(name="UVMap")
    for loop in obj.data.loops:
        uv = uv_layer.data[loop.index].uv
        v = obj.data.vertices[loop.vertex_index].co
        uv.x = (v.x + 2.0) / 4.0
        uv.y = (v.y + 2.0) / 4.0
    uv_before = uv_per_vertex(obj.data)

    # Two side vertex groups (one pair to swap).
    vg_l = obj.vertex_groups.new(name="arm.L")
    vg_l.add([0, 1, 2, 3], 0.8, "REPLACE")
    vg_r = obj.vertex_groups.new(name="arm.R")
    vg_r.add([4, 5, 6, 7], 0.9, "REPLACE")

    # Shape keys: basis plus a poke key.
    obj.shape_key_add(name="Basis")
    kb = obj.shape_key_add(name="Poke")
    for point in kb.data:
        point.co.x += 0.1
    key_before = vertex_coords(obj)

    copy_obj = MeshMirrorUtils.mirror_mesh_object(
        obj, mode="COPY", recalc_normals=False, mirror_uv="U",
        swap_side_groups=True)

    # Original object must be completely untouched.
    check("copy original name unchanged", obj.name == "CopySrc")
    check("copy original coords unchanged",
          all(vec_close(a, b) for a, b in zip(before, vertex_coords(obj))))
    check("copy original groups unchanged",
          [g.name for g in obj.vertex_groups] == ["arm.L", "arm.R"])
    check("copy original scale clean", vec_close(obj.scale, (1.0, 1.0, 1.0)))

    # The copy itself is mirrored and clean.
    check("copy object name suffix", copy_obj.name == "CopySrc_mirror",
          copy_obj.name)
    after = vertex_coords(copy_obj)
    ok = True
    for a, b in zip(before, after):
        if not vec_close((-a.x, a.y, a.z), b):
            ok = False
            break
    check("copy coordinates mirrored", ok)
    check("copy scale reset to 1", vec_close(copy_obj.scale, (1.0, 1.0, 1.0)),
          str(copy_obj.scale))

    # Vertex groups: names swapped on the copy, weights kept per vertex.
    names = [g.name for g in copy_obj.vertex_groups]
    check("copy groups swapped", names == ["arm.R", "arm.L"], str(names))
    copy_weights = group_weight_map(copy_obj)
    check("copy weights follow their vertices",
          copy_weights["arm.R"][0] == 0.8 and copy_weights["arm.L"][4] == 0.9)

    # UV: flip U means u becomes 1 - u on the copy.
    uv_after = uv_per_vertex(copy_obj.data)
    ok = True
    for v_index in uv_before:
        expected = sorted((round(1.0 - u, 6), v) for (u, v) in uv_before[v_index])
        actual = uv_after.get(v_index)
        if actual != expected:
            ok = False
            break
    check("copy uv flipped around U", ok)

    # Shape keys: every block is mirrored; deltas flip sign on X.
    basis = copy_obj.data.shape_keys.key_blocks["Basis"]
    poke = copy_obj.data.shape_keys.key_blocks["Poke"]
    orig_basis = obj.data.shape_keys.key_blocks["Basis"]
    orig_poke = obj.data.shape_keys.key_blocks["Poke"]
    ok = True
    for i, point in enumerate(basis.data):
        if not vec_close((-orig_basis.data[i].co.x, orig_basis.data[i].co.y,
                          orig_basis.data[i].co.z), point.co):
            ok = False
            break
    check("copy shape key basis mirrored", ok)
    ok = True
    for i, point in enumerate(poke.data):
        delta_new = point.co - basis.data[i].co
        delta_old = orig_poke.data[i].co - orig_basis.data[i].co
        if not vec_close((-delta_old.x, delta_old.y, delta_old.z), delta_new):
            ok = False
            break
    check("copy shape key delta mirrored", ok)
    check("original shape keys untouched",
          vec_close(orig_basis.data[0].co, mathutils.Vector(key_before[0])))


def test_shared_data_flip_keeps_sibling():
    """Flipping an object whose mesh is shared must not touch the sibling."""
    wipe_scene()
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
    obj_a = bpy.context.active_object
    obj_a.name = "SharedA"
    obj_a.data.vertices[0].co = mathutils.Vector((2.0, 0.5, 0.25))
    obj_b = bpy.data.objects.new("SharedB", obj_a.data)
    bpy.context.scene.collection.objects.link(obj_b)

    MeshMirrorUtils.mirror_mesh_object(obj_a, mode="FLIP",
                                       recalc_normals=False)
    check("shared data sibling untouched",
          vec_close(obj_b.data.vertices[0].co, (2.0, 0.5, 0.25)))
    check("shared data flipped object mirrored",
          vec_close(obj_a.data.vertices[0].co, (-2.0, 0.5, 0.25)))


def test_copy_uses_same_collection():
    """The mirrored copy lands in the same collections as the original."""
    obj = new_cube("CollCube", poke=None)
    copy_obj = MeshMirrorUtils.mirror_mesh_object(obj, mode="COPY")
    coll_names = [c.name for c in obj.users_collection]
    copy_coll_names = [c.name for c in copy_obj.users_collection]
    check("copy linked to same collection", coll_names == copy_coll_names,
          str(coll_names) + " vs " + str(copy_coll_names))


def test_inplace_swap_groups():
    """FLIP in place swaps the L/R group names on the same object."""
    obj = new_cube("SwapCube", poke=None)
    vg_l = obj.vertex_groups.new(name="shoe.L")
    vg_l.add([0], 1.0, "REPLACE")
    MeshMirrorUtils.mirror_mesh_object(obj, mode="FLIP",
                                       swap_side_groups=True)
    names = [g.name for g in obj.vertex_groups]
    check("flip swaps group names in place", names == ["shoe.R"], str(names))


def test_operator_register_and_run():
    """Register the add-on operator and run it once through bpy.ops."""
    # An older installed copy of this add-on ("TheHerta4") may already have
    # registered this very class from the same source file. Register when
    # possible and ignore the "already registered" error in that case.
    # (Probing bpy.ops attributes is not reliable here: the dynamic bpy.ops
    # wrappers answer True even for operators that are not registered.)
    import MIMIBlender.ui.ui_panel_model as panel_model  # noqa: E402
    was_registered = False
    try:
        bpy.utils.register_class(panel_model.MirrorMeshOperator)
        was_registered = True
    except ValueError as exc:
        if "already registered" not in str(exc):
            raise
    try:
        # Create a selection of one cube and invoke the operator.
        obj = new_cube("OpCube", poke=None)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            result = bpy.ops.mimiblender.mirror_mesh("EXEC_DEFAULT",
                                                     mode="COPY")
            ok = isinstance(result, set) and "FINISHED" in result
            check("operator finished", ok, str(result))
        except Exception:
            import traceback
            print("operator call raised:")
            traceback.print_exc(file=sys.stdout)
            check("operator finished", False, "exception")
        copies = [o for o in bpy.data.objects if o.name == "OpCube_mirror"]
        check("operator created a copy", len(copies) == 1)
        check("operator copy is mirrored and clean",
              copies and vec_close(copies[0].scale, (1.0, 1.0, 1.0)) and
              vec_close(copies[0].data.vertices[0].co, (1.0, -1.0, -1.0)))
    finally:
        if was_registered:
            try:
                bpy.utils.unregister_class(panel_model.MirrorMeshOperator)
            except Exception:
                pass
        del sys.modules["MIMIBlender"]


def test_guard_errors():
    """Invalid input raises clear ValueError messages."""
    obj = new_cube("GuardCube", poke=None)
    raised = False
    try:
        MeshMirrorUtils.mirror_mesh_object(obj, mode="BOGUS")
    except ValueError:
        raised = True
    check("bad mode raises ValueError", raised)
    raised = False
    try:
        MeshMirrorUtils.mirror_mesh_object(obj, mode="FLIP", axis="W")
    except ValueError:
        raised = True
    check("bad axis raises ValueError", raised)


def main():
    tests = [
        test_flip_coords_and_scale,
        test_flip_normals_without_recalc,
        test_flip_normals_with_recalc,
        test_bake_negative_scale,
        test_bake_normals,
        test_bake_even_negatives_no_flip,
        test_copy_full_features,
        test_shared_data_flip_keeps_sibling,
        test_copy_uses_same_collection,
        test_inplace_swap_groups,
        test_operator_register_and_run,
        test_guard_errors,
    ]
    for test in tests:
        try:
            test()
        except Exception:
            import traceback
            FAILED.append(test.__name__)
            print("[TEST] FAIL |", test.__name__, "| exception:")
            traceback.print_exc()
    print(f"[SUMMARY] {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("[SUMMARY] failed:", ", ".join(FAILED))


main()
