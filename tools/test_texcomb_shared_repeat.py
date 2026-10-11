"""Regress automatic sizing and shared images with unequal UV coverage.

Run in Blender with --background --factory-startup --python-exit-code 1.
Pass -- --blend PATH to audit a real scene instead of creating fixtures.
Neither mode saves a blend file or overwrites a user's source texture.
The real-scene mode follows the same selection refresh as the UI button.
Synthetic mode additionally composes an atlas and measures remapped UVs.

Acceptance boundaries:
- Preview generation never changes mesh coordinates.
- All unlocked rows preserve original image proportions exactly.
- Both dimensions must be powers of two, even with external spacing.
- Two materials sharing an image but not UV bounds consume one region.
- Cross-tile polygons remain continuous; their corners are never modulo-wrapped.
- Negative UV tiles are normalized only during the actual merge.
- Tint and alpha variants remain distinct outputs (covered by the peer suite).
- Regeneration discards old fixed values before reading the sources.
- Recalculation of an unlocked plan is deterministic.
- Atlas pixel probes use a patterned source, not a constant-color shortcut.
- Pixel-space UV scale is identical along the two source axes.
- The original source Image datablock is not resized or repacked by planning.
- The desktop model's two named rope materials must share a visible row.
- Source pointers, not material names, define the actual shared-image family.
- Invalid non-dyadic source ratios are checked separately by the pure suite.
- Manual size overrides keep their existing semantics in the peer suite.
"""
import argparse
import json
import os
import sys
import tempfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def check_plan(planner, scene):
    """Validate the dimensions actually displayed to users.

    Return a primitive snapshot, because Blender RNA rows are replaced on
    recalculation and retaining old row wrappers would invalidate comparisons.
    A readable texture supplies the ratio; plain colors have no source aspect.
    """
    # Compare exact integer ratios so rounding cannot mask a distortion.
    rows = list(scene.mimi_smc_distribution)
    assert rows and not any(row.locked for row in rows)
    for row in rows:
        assert all(axis > 0 and axis & (axis - 1) == 0 for axis in (row.width, row.height))
        image = planner.get_image_from_material(row.mat)
        if image and planner.get_packed_file(image):
            assert row.width * image.size[1] == row.height * image.size[0], row.mat.name
    return [(row.mat.name, row.width, row.height, row.x, row.y) for row in rows]


def verify_real_scene(planner, path):
    """Reproduce the desktop scene's entirely unlocked generate action.

    Retain its real materials, source images, selection and sizing settings.
    Check both visible deduplication and the merge adapter's compacted data.
    Export only a temporary atlas; the input scene stays untouched on disk.
    """
    # Opening in this isolated process cannot change the user's open GUI scene.
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(path))
    scene = bpy.context.scene
    bpy.ops.mimi.refresh_ob_data()
    before = planner.prepare_sources(scene)[1]
    snapshot = {name: {mat: [tuple(uv) for uv in uvs] for mat, uvs in mats.items()}
                for name, mats in before.items()}
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    baseline = check_plan(planner, scene)
    rows = planner.distribution_entries(scene)
    # Unicode escapes keep this test's source portable across Windows consoles.
    hook = bpy.data.materials["\u94a9\u5b50\u7ef3.001"]
    hand = bpy.data.materials["\u624b\u7ef3.001"]
    assert planner.get_image_from_material(hook) == planner.get_image_from_material(hand)
    assert rows[hook] == rows[hand]
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    assert check_plan(planner, scene) == baseline
    _, after, structure = planner.prepare_sources(scene)
    assert snapshot == {name: {mat: [tuple(uv) for uv in uvs] for mat, uvs in mats.items()}
                        for name, mats in after.items()}
    # The merge adapter must reuse both the placement and common sampling grid.
    assert structure[hook]["gfx"]["uv_size"] == structure[hand]["gfx"]["uv_size"]
    planner.apply_distribution(scene, structure)
    assert hand.name in structure[hook]["dup"]
    assert hand not in structure
    members = len(planner.distribution_entries(scene)[hook].members)
    canvas = (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height)
    # Exercise the real composition path as well, writing only to a fresh temp
    # directory. Never save the changed mesh or replace the input blend file.
    scene.mimi_smc_image_format = "PNG"
    output = tempfile.mkdtemp(prefix="mimi_real_distribution_")
    assert bpy.ops.mimi.combiner(directory=output) == {"FINISHED"}
    from PIL import Image
    atlas_path = next(os.path.join(output, name) for name in os.listdir(output) if name.endswith(".png"))
    with Image.open(atlas_path) as atlas:
        assert atlas.size == canvas
    print("RESULT " + json.dumps({"status": "passed", "mode": "real_scene", "rows": baseline,
                                  "rope_members": members, "atlas": atlas_path, "canvas": canvas}))


def verify_synthetic(planner):
    """Isolate unequal repetition from shading and source identity.

    The long face and the negative-tile face use the same patterned image.
    A nearest-neighbor export makes texel-center probes deterministic.
    Cross-face interpolation catches incorrect modulo wrapping of vertices.
    The reduced-budget pass also verifies that releasing pressure restores
    native preferences rather than reusing the previous reduced allocation.
    """
    from test_texcomb_distribution import make_quad, snapshot
    from test_texcomb_uv_regression import sample
    from PIL import Image
    # Factory primitives belong to this disposable test process only.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    objects = [make_quad(index) for index in range(2)]
    first, second = [mat for obj, mat in objects]
    image = planner.get_image_from_material(first)
    image.scale(16, 16)
    image.pixels = [c for y in range(16) for x in range(16) for c in (x / 15, y / 15, 0.5, 1)]
    image.pack()
    next(node for node in second.node_tree.nodes if node.type == "TEX_IMAGE").image = image
    # One face crosses six vertical repeats while its peer samples one tile.
    # Keep endpoints on texel centers for exact nearest-neighbor pixel checks.
    corners = [(0.28125, 0.28125), (0.78125, 0.28125), (0.78125, 6.78125), (0.28125, 6.78125)]
    for loop, uv in zip(objects[0][0].data.uv_layers.active.data, corners):
        loop.uv = uv
    # Place the peer's corners and midpoint on texel centers as well; an exact
    # half-texel boundary would make float32 UV rounding choose either neighbor.
    peer_corners = [(-0.71875, -0.71875), (-0.21875, -0.71875),
                    (-0.21875, -0.21875), (-0.71875, -0.21875)]
    for loop, uv in zip(objects[1][0].data.uv_layers.active.data, peer_corners):
        loop.uv = uv
    before = snapshot(objects)
    scene = bpy.context.scene
    scene.mimi_smc_uniform_size = True
    scene.mimi_smc_uniform_size_value = 128
    scene.mimi_smc_total_size = True
    scene.mimi_smc_total_width = scene.mimi_smc_total_height = 256
    scene.mimi_smc_gaps = 5
    scene.mimi_smc_pixel_art = True
    scene.mimi_smc_image_format = "PNG"
    bpy.context.view_layer.objects.active = objects[0][0]
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    baseline = check_plan(planner, scene)
    assert len(baseline) == 1
    assert baseline[0][1:3] == (128, 128)
    assert len(scene.mimi_smc_distribution[0].members) == 2
    # Automatic updates must reset callback-induced locks before returning.
    scene.mimi_smc_distribution[0].width = 65
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    assert check_plan(planner, scene) == baseline
    assert snapshot(objects) == before
    assert tuple(image.size) == (16, 16)
    # Recalculation starts from native preferences, not the last reduced plan.
    scene.mimi_smc_total_width = scene.mimi_smc_total_height = 128
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    check_plan(planner, scene)
    assert scene.mimi_smc_distribution[0].width == 64
    scene.mimi_smc_total_width = scene.mimi_smc_total_height = 256
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    assert check_plan(planner, scene) == baseline
    _, _, structure = planner.prepare_sources(scene)
    assert structure[first]["gfx"]["uv_size"] == structure[second]["gfx"]["uv_size"] == (8, 8)
    planner.apply_distribution(scene, structure)
    assert len(structure) == 1
    # Compare packed source bytes to real final atlas samples, including a face
    # interior across tile boundaries; endpoint-only checks would miss wrapping.
    import io
    source = Image.open(io.BytesIO(bytes(image.packed_file.data))).convert("RGBA")
    output = tempfile.mkdtemp(prefix="mimi_shared_repeat_")
    assert bpy.ops.mimi.combiner(directory=output) == {"FINISHED"}
    atlas_path = next(os.path.join(output, name) for name in os.listdir(output) if name.endswith(".png"))
    checks = 0
    with Image.open(atlas_path).convert("RGBA") as atlas:
        for index, (obj, mat) in enumerate(objects):
            after = [tuple(loop.uv) for loop in obj.data.uv_layers.active.data]
            for weights in ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0.25,) * 4):
                old = [sum(w * uv[axis] for w, uv in zip(weights, before[index])) for axis in (0, 1)]
                new = [sum(w * uv[axis] for w, uv in zip(weights, after)) for axis in (0, 1)]
                expected = sample(source, tuple(axis % 1 for axis in old))
                actual = sample(atlas, new)
                assert max(abs(a - b) for a, b in zip(expected, actual)) <= 2, (old, expected, actual)
                checks += 1
            scales = [(max(uv[axis] for uv in after) - min(uv[axis] for uv in after)) * atlas.size[axis]
                      / (max(uv[axis] for uv in before[index]) - min(uv[axis] for uv in before[index]))
                      for axis in (0, 1)]
            assert abs(scales[0] - scales[1]) < 0.001
    print("RESULT " + json.dumps({"status": "passed", "mode": "synthetic", "rows": 1, "pixel_checks": checks}))


def main():
    """Register the repository addon only in this isolated test process.

    Arguments after Blender's separator select the optional real-scene case.
    Without that switch, no external model or source image is required.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    if args.blend:
        verify_real_scene(planner, args.blend)
    else:
        verify_synthetic(planner)


if __name__ == "__main__":
    main()
