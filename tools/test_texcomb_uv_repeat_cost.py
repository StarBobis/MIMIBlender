"""Regress the atlas cost of UVs that overshoot one tile.

Run in Blender with --background --factory-startup --python-exit-code 1.
The scene is synthetic; no user model, settings or textures are read or
written. Every output goes to a fresh temporary directory.

Acceptance boundaries:
- UVs that stay inside 0-1 keep the historical one-tile region.
- A sub-texel overshoot reserves about one tile, not a duplicated 2x2 block.
- A seam-crossing island reserves only the fraction of a tile it reaches.
- The cropped sliver repeats the source's first texel, so wrapping stays exact.
- Disabling "Crop to UV Bounds" restores the explicit whole-tile grid.
- The merged atlas matches the approved canvas and contains the regions.
- No source image, material or UV is modified by planning or merging.
"""
import os
import sys
import tempfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

SIZE = 512

# name: four UV corners in loop order; the source is a horizontal gradient.
QUADS = {
    "exact": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
    "tiny": [(0.0, 0.0), (1.0002, 0.0), (1.0002, 1.0), (0.0, 1.0)],
    "seam": [(0.98, 0.98), (1.02, 0.98), (1.02, 1.02), (0.98, 1.02)],
}


def make_quad(name, uvs):
    """Create one material, one packed gradient image and one quad."""
    mat = bpy.data.materials.new("repeat_cost_" + name)
    mat.use_nodes = True
    shader = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    image = bpy.data.images.new("repeat_cost_image_" + name, SIZE, SIZE, alpha=True)
    # A horizontal gradient makes the first and last texel columns distinct.
    pixels = []
    for _y in range(SIZE):
        for x in range(SIZE):
            pixels.extend((x / (SIZE - 1), 0.25, 0.75, 1.0))
    image.pixels = pixels
    image.pack()
    texture = mat.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    mat.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    mat.mimi_smc_diffuse = False
    mesh = bpy.data.meshes.new("repeat_cost_mesh_" + name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(mat)
    layer = mesh.uv_layers.new(name="uvmap")
    for loop, uv in zip(layer.data, uvs):
        loop.uv = uv
    obj = bpy.data.objects.new("repeat_cost_object_" + name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj, mat


def rows_by_material(scene):
    """Return {(material name): (width, height, repeat_u, repeat_v)}."""
    result = {}
    for row in scene.mimi_smc_distribution:
        result[row.mat.name] = (row.width, row.height, row.uv_repeat_u, row.uv_repeat_v)
    return result


def main():
    """Check exact-crop sizing, the legacy switch and the merged pixels."""
    import MIMIBlender  # noqa: F401  (enables the add-on in this process only)

    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from PIL import Image
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner

    # Remove factory primitives so their default material cannot join the scan.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    pairs = [make_quad(name, uvs) for name, uvs in QUADS.items()]
    materials = {name: mat for (obj, mat), name in zip(pairs, QUADS)}

    scene = bpy.context.scene
    scene.mimi_smc_uniform_size = True
    scene.mimi_smc_uniform_size_value = SIZE
    scene.mimi_smc_total_size = False
    scene.mimi_smc_original_size = False
    scene.mimi_smc_gaps = 0
    scene.mimi_smc_crop = True
    scene.mimi_smc_image_format = "PNG"
    bpy.context.view_layer.objects.active = pairs[0][0]
    for obj, _mat in pairs:
        obj.select_set(True)

    bpy.ops.mimi.refresh_ob_data()
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    rows = rows_by_material(scene)
    exact = rows[materials["exact"].name]
    tiny = rows[materials["tiny"].name]
    seam = rows[materials["seam"].name]
    # One tile stays exactly as before.
    assert exact[:2] == (SIZE, SIZE), exact
    # A sub-texel overshoot adds one pixel, never a whole duplicated tile.
    assert tiny[0] == SIZE + 1 and tiny[1] == SIZE, tiny
    assert abs(tiny[2] - (SIZE + 1) / SIZE) < 1e-6, tiny
    # A seam-crossing island reserves only the fraction it really reaches.
    assert seam[0] == 523 and seam[1] == 523, seam
    assert 0.98 * SIZE <= seam[2] * SIZE <= 1.03 * SIZE, seam
    # Before this fix both overshooting rows were 1024x1024 (four copies each),
    # so the whole atlas needed at least a 2048x2048 canvas.
    canvas = (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height)
    assert canvas[0] * canvas[1] <= 2048 * 1024, canvas

    # The UI switch must still restore the explicit whole-tile grid.
    scene.mimi_smc_crop = False
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    legacy = rows_by_material(scene)
    assert legacy[materials["tiny"].name][:2] == (2 * SIZE, 2 * SIZE), legacy
    assert legacy[materials["seam"].name][0] == 2 * SIZE, legacy
    scene.mimi_smc_crop = True
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    assert rows_by_material(scene) == rows

    # The cropped sliver must repeat the source's first texel, not smear it.
    _, _, structure = planner.prepare_sources(scene)
    planner.apply_distribution(scene, structure)
    gfx = structure[materials["tiny"]]["gfx"]
    paste_x = gfx["fit"]["x"]
    paste_y = gfx["fit"]["y"]
    content_width, content_height = gfx["content_size"]
    assert (content_width, content_height) == (SIZE + 1, SIZE)

    directory = tempfile.mkdtemp(prefix="texcomb_repeat_cost_")
    assert bpy.ops.mimi.combiner(directory=directory) == {"FINISHED"}
    atlas_path = next(os.path.join(directory, name) for name in os.listdir(directory)
                      if name.endswith(".png"))
    with Image.open(atlas_path) as atlas:
        atlas = atlas.convert("RGBA")
        assert atlas.size == (scene.mimi_smc_distribution_width,
                              scene.mimi_smc_distribution_height)
        middle = paste_y + content_height // 2
        first = atlas.getpixel((paste_x, middle))
        last = atlas.getpixel((paste_x + content_width - 1, middle))
        previous = atlas.getpixel((paste_x + content_width - 2, middle))
        # Column 512 is column 0 of the next tile, so it equals the first texel.
        assert first == last, (first, last)
        # The column before it is the far end of the source tile.
        assert previous != last, (previous, last)
    print("RESULT {\"status\": \"passed\", \"rows\": %r}" % (rows,))


if __name__ == "__main__":
    main()
