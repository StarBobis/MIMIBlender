"""Run with Blender --background --factory-startup --python-exit-code 1 -P.

Use packed source pixels as the oracle, avoiding color-space assumptions.
Exercise the real operator and sample face interiors as well as corners.
"""

import json
import math
import os
import sys
import tempfile

import bpy

# The repository is the Blender addon package, not its parent directory.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
# Blender can use the addon's vendored Pillow after addon registration.
Image = None


def make_object(name, corners):
    # Encode UV coordinates in source pixels so flips and stretching fail.
    image = bpy.data.images.new(name, 16, 16, alpha=True)
    image.pixels = [c for y in range(16) for x in range(16)
                    for c in (x / 15, y / 15, 0.5, 1)]
    image.pack()
    mat = bpy.data.materials.new(name)
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    shader = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    mat.node_tree.links.new(tex.outputs["Color"], shader.inputs["Base Color"])
    # Disable optional diffuse multiplication to isolate the UV transform.
    mat.mimi_smc_diffuse = False
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(mat)
    layer = mesh.uv_layers.new(name="uvmap")
    for loop, uv in zip(layer.data, corners):
        loop.uv = uv
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    # Read the packed bytes, exactly as the production decoder does.
    import io
    source = Image.open(io.BytesIO(bytes(image.packed_file.data))).convert("RGBA")
    return obj, source, corners


def sample(image, uv):
    # PIL rows grow downward, unlike Blender's UV V axis.
    w, h = image.size
    x = min(w - 1, max(0, int(uv[0] * w)))
    y = min(h - 1, max(0, int((1 - uv[1]) * h)))
    return image.getpixel((x, y))


def run_case(crop, strategy, limited=False, uniform=False, pixel_art=False, custom=(256, 128), tall=False, budget=False):
    # Remove only this synthetic factory-startup test scene's objects.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    cases = []
    # Cell centers avoid ambiguous texels right on boundaries.
    for index, (u, v, du, dv) in enumerate([
        (0.28125, 0.28125, 0.5, 0.5),
        (0.28125, 0.28125, 1.5, 0.5),
        (-0.71875, -0.71875, 1.5, 1.5),
    ]):
        # A tall UV repeat forces portrait packing before final rotation.
        if tall:
            du, dv = 0.5, 7.5
        corners = [(u, v), (u + du, v), (u + du, v + dv), (u, v + dv)]
        obj, source, original = make_object("test_{}".format(index), corners)
        if limited:
            # This used to thumbnail an already packed repeated image again.
            obj.data.materials[0].mimi_smc_size = True
            obj.data.materials[0].mimi_smc_size_width = 16
            obj.data.materials[0].mimi_smc_size_height = 16
        cases.append((obj, source, original))
    # Match imported game models: render UVs differ from the selected mask.
    auxiliary_snapshots = {}
    for obj, source, original in cases:
        layer = obj.data.uv_layers.new(name="auxiliary")
        for index, loop in enumerate(layer.data):
            loop.uv = (0, index % 2)
        obj.data.uv_layers.active_index = 1
        auxiliary_snapshots[obj.name] = [tuple(loop.uv) for loop in layer.data]
    scene = bpy.context.scene
    # Tiny 16px fixtures cannot lose five texels when maximum-size mode
    # correctly avoids enlarging them; gap coverage remains in legacy cases.
    scene.mimi_smc_gaps = 0 if uniform else 5
    scene.mimi_smc_crop = crop
    scene.mimi_smc_size = strategy
    # Strict canvas bounds must be dyadic too: 192 cannot be both a rounded-up
    # minimum and a rounded-down maximum for the same approved distribution.
    scene.mimi_smc_size_width, scene.mimi_smc_size_height = custom
    scene.mimi_smc_uniform_size = uniform
    scene.mimi_smc_original_size = False
    scene.mimi_smc_total_size = budget
    if budget:
        # Exact-crop envelopes are far smaller than the old square grids, so
        # this ceiling verifies a tall plan stays inside the budget. Forced
        # reduction itself is covered by the dedicated distribution suite.
        scene.mimi_smc_total_width = 128
        scene.mimi_smc_total_height = 128
    scene.mimi_smc_uniform_size_value = 128
    scene.mimi_smc_pixel_art = pixel_art
    scene.mimi_smc_include_extra_textures = False
    scene.mimi_smc_image_format = "PNG"
    # Visible objects, not selection, determine the combine list.
    directory = tempfile.mkdtemp(prefix="texcomb_regression_")
    # The production operator now requires approval for every sizing mode.
    # Exercise that public workflow rather than bypassing its stale-plan guard.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    assert bpy.ops.mimi.combiner(directory=directory) == {"FINISHED"}
    path = next(os.path.join(directory, n) for n in os.listdir(directory) if n.endswith(".png"))
    atlas = Image.open(path).convert("RGBA")
    if uniform:
        # Exact-crop regions reserve only the UV extent, so a vertical tiling
        # may legitimately produce a portrait canvas. Whole-tile mode still
        # needs three 128 x 128 squares. Bound the area instead of the shape:
        # 256 x 256 fits every fixture and rejects a duplicated-tile blowup.
        assert atlas.width * atlas.height <= 256 * 256, (
            crop, strategy, limited, pixel_art, tall, budget, atlas.size)
    checks = 0
    for obj, source, original in cases:
        assert len(obj.data.materials) == 1
        # The atlas must edit the texture UVs, not the collapsed mask layer.
        assert obj.data.uv_layers.active.name == "uvmap"
        assert [tuple(loop.uv) for loop in obj.data.uv_layers["auxiliary"].data] == auxiliary_snapshots[obj.name]
        mapped = [tuple(loop.uv) for loop in obj.data.uv_layers.active.data]
        # Interior points catch changes to interpolation, not just vertices.
        weights = [(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1),
                   (0.4, 0.2, 0.2, 0.2), (0.2, 0.4, 0.2, 0.2)]
        for weight in weights:
            old = [sum(weight[i] * original[i][axis] for i in range(4)) for axis in range(2)]
            new = [sum(weight[i] * mapped[i][axis] for i in range(4)) for axis in range(2)]
            expected = sample(source, [x - math.floor(x) for x in old])
            actual = sample(atlas, new)
            # Resizing allows small filtering differences, but not wrong tiles.
            assert max(abs(a - b) for a, b in zip(actual, expected)) < 22, (
                crop, strategy, limited, uniform, obj.name, old, new, expected, actual)
            assert all(0 <= x <= 1 for x in new)
            checks += 1
    print("UV_CASE", crop, strategy, limited, uniform, pixel_art, checks)
    return checks


def check_extra_maps():
    # Test the Blender adapter directly with matching base and alpha tiles.
    from importlib import import_module
    planes = import_module(os.path.basename(ROOT) + ".texcomb.blender.planes")
    import numpy as np
    obj, source, corners = make_object("extra_test", [(0, 0)] * 4)
    mat = obj.data.materials[0]
    image = next(n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")
    packed = image.packed_file
    mat.mimi_smc_alpha_mode = "SEPARATE"
    mat.mimi_smc_alpha_image = image
    mat.mimi_smc_alpha_channel = "R"
    item = {"gfx": {"img_or_color": packed, "uv_size": (1.5, 1.25)}}
    base = planes.build_base_plane(mat, item, (24, 20), {})
    extra = planes.build_extra_plane(packed, (24, 20), "roughness", {}, uv_repeat=(1.5, 1.25))
    # Alpha is data; its values must repeat in lockstep with the raw R map.
    np.testing.assert_allclose(base[:, :, 3], extra[:, :, 0], atol=1e-6)
    # Cropping V must keep the bottom rows, not the top of the tiled array.
    np.testing.assert_allclose(extra[-1, :16], extra[-17, :16], atol=1e-6)
    np.testing.assert_allclose(extra[:, :8], extra[:, 16:24], atol=1e-6)
    print("PBR_ALPHA_REPEAT passed")


def main():
    print("BLENDER_VERSION", bpy.app.version_string)
    bpy.ops.preferences.addon_enable(module=os.path.basename(ROOT))
    global Image
    from PIL import Image
    check_extra_maps()
    checks = 0
    # Both padding strategies and final canvas modes must share pixel math.
    for crop in (False, True):
        for strategy in ("PO2", "AUTO", "QUAD", "CUST", "STRICTCUST"):
            checks += run_case(crop, strategy)
        # Small custom canvases exercise actual downscaling plus padding.
        checks += run_case(crop, "CUST", custom=(64, 64))
        checks += run_case(crop, "STRICTCUST", custom=(64, 64))
        checks += run_case(crop, "PO2", limited=True)
        checks += run_case(crop, "PO2", uniform=True, pixel_art=True)
        checks += run_case(crop, "PO2", uniform=True, pixel_art=True, tall=True)
        checks += run_case(crop, "PO2", uniform=True, pixel_art=True, tall=True, budget=True)
    bpy.ops.preferences.addon_disable(module=os.path.basename(ROOT))
    print("RESULT " + json.dumps({"uv_checks": checks, "passed": True}))


if __name__ == "__main__":
    main()
