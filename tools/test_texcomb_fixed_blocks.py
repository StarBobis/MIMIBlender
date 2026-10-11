"""Exercise fixed atlas blocks through the real Blender combiner operator.

Use --background --factory-startup --python-exit-code 1 -P to run safely.
Synthetic quads check image dimensions, solid colors, and corner/interior UVs.
"""

import json
import os
import sys
import tempfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


def make_quad(index, size, color):
    # Constant colors make resampling comparisons exact at any resolution.
    mat = bpy.data.materials.new("block_material_" + str(index))
    shader = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = color
    mat.mimi_smc_diffuse = False
    if size:
        image = bpy.data.images.new("block_image_" + str(index), size[0], size[1], alpha=True)
        image.pixels = list(color) * (size[0] * size[1])
        image.pack()
        texture = mat.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        mat.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    mesh = bpy.data.meshes.new("block_mesh_" + str(index))
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(mat)
    layer = mesh.uv_layers.new(name="uvmap")
    # Interior corners avoid padding and exact 0/1 sampling ambiguities.
    for loop, uv in zip(layer.data, [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]):
        loop.uv = uv
    obj = bpy.data.objects.new("block_object_" + str(index), mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj, mat


def run_case(sizes, expected_regions, expected_canvas, gaps, original=None, limit_sources=True, total=None):
    # This process owns only the synthetic factory-startup scene.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    objects = []
    for index, size in enumerate(sizes):
        color = ((index % 3) * 0.3 + 0.1, 0.3, 0.6, 1)
        objects.append(make_quad(index, size, color))
    scene = bpy.context.scene
    scene.mimi_smc_uniform_size = limit_sources
    scene.mimi_smc_uniform_size_value = 1024
    # Budget mode can reduce source regions independently of the source limit.
    scene.mimi_smc_total_size = total is not None
    if total is not None:
        scene.mimi_smc_total_width, scene.mimi_smc_total_height = total
    # A canvas floor pads output independently of the source-size ceiling.
    scene.mimi_smc_original_size = original is not None
    if original is not None:
        scene.mimi_smc_original_width, scene.mimi_smc_original_height = original
    scene.mimi_smc_gaps = gaps
    scene.mimi_smc_diffuse_size = 256
    # Legacy strict output must not override tight packing or the game floor.
    scene.mimi_smc_size = "STRICTCUST"
    scene.mimi_smc_size_width = 64
    scene.mimi_smc_size_height = 64
    scene.mimi_smc_image_format = "PNG"
    scene.mimi_smc_include_extra_textures = False
    bpy.context.view_layer.objects.active = objects[0][0]
    # Use the approved distribution as the single source of planned dimensions.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    planned = {}
    for entry in scene.mimi_smc_distribution:
        members = [member.mat for member in entry.members] or [entry.mat]
        for mat in members:
            planned[mat] = (entry.width, entry.height)
    for (obj, mat), expected in zip(objects, expected_regions):
        assert planned[mat] == expected, (sizes, mat.name, planned[mat], expected)
    planned_canvas = (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height)
    assert planned_canvas == expected_canvas, (sizes, planned_canvas, expected_canvas)
    directory = tempfile.mkdtemp(prefix="texcomb_blocks_")
    assert bpy.ops.mimi.combiner(directory=directory) == {"FINISHED"}
    from PIL import Image
    path = next(os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".png"))
    atlas = Image.open(path).convert("RGBA")
    assert atlas.size == expected_canvas, (atlas.size, expected_canvas)
    width, height = atlas.size
    # Each face must stay inside its own region and sample an opaque color.
    for obj, mat in objects:
        points = [tuple(loop.uv) for loop in obj.data.uv_layers.active.data]
        center = tuple(sum(point[axis] for point in points) / 4 for axis in range(2))
        colors = []
        for u, v in points + [center]:
            assert 0 <= u <= 1 and 0 <= v <= 1
            colors.append(atlas.getpixel((int(u * width), int((1 - v) * height))))
        assert all(color[3] == 255 for color in colors)
        assert all(max(abs(a - b) for a, b in zip(color, colors[-1])) < 3 for color in colors)
        # Padding is external to content, so UV extents retain the full size.
        expected = expected_regions[[item[0] for item in objects].index(obj)]
        for axis, canvas_axis in enumerate((width, height)):
            span = max(point[axis] for point in points) - min(point[axis] for point in points)
            actual_pixels = span * canvas_axis
            expected_pixels = 0.8 * expected[axis]
            assert abs(actual_pixels - expected_pixels) < 0.01, (
                sizes, expected, axis, actual_pixels, expected_pixels, points
            )
        assert len(obj.data.materials) == 1
    print("BLOCK_CASE", sizes, expected_regions, atlas.size, "gaps", gaps)


def main():
    bpy.ops.preferences.addon_enable(module=os.path.basename(ROOT))
    # Four pixels of external gaps require one axis to grow beyond 512.
    small = [(500, 500), (500, 500), None]
    regions = [(256, 256), (256, 256), (32, 32)]
    run_case(small, regions, (1024, 512), 4)
    # Exactly the same content keeps the same pixel footprint on a larger canvas.
    run_case(small, regions, (1024, 1024), 4, original=(1024, 1024))
    run_case(small, regions, (2048, 1024), 4, original=(2048, 1024))
    # The canvas floor works without the individual source-size ceiling.
    run_case([(500, 500), (500, 500)], [(256, 256), (256, 256)],
             (1024, 1024), 0, original=(1024, 1024), limit_sources=False)
    # Power-of-two aspect ratios preserve exact dimensions while mixing sizes.
    run_case([(500, 500), (555, 555), (512, 256), None],
             [(256, 256), (512, 512), (512, 256), (32, 32)], (1024, 1024), 4)
    # External padding can push the 1024px block onto the next power-of-two canvas.
    run_case([(2048, 2048), None], [(1024, 1024), (32, 32)], (2048, 2048), 4)
    # Four padded blocks form a 2x2 grid on the next power-of-two canvas.
    run_case([(1024, 1024)] * 4, [(1024, 1024)] * 4, (4096, 4096), 4)
    # Five padded blocks use a compact arrangement on the next power-of-two canvas.
    run_case([(1024, 1024)] * 5, [(1024, 1024)] * 5, (4096, 4096), 4)
    # Sixteen real 512px sources must become 256px regions in one 1024 atlas.
    run_case([(512, 512)] * 16, [(256, 256)] * 16, (1024, 1024),
             0, total=(1024, 1024))
    # Total budget works without enabling the individual source-size ceiling.
    run_case([(512, 512)] * 16, [(256, 256)] * 16, (1024, 1024),
             0, total=(1024, 1024), limit_sources=False)
    # Mixed source sizes protect tiny regions while degrading larger images.
    run_case([(1024, 1024), (64, 64), None], [(256, 256), (64, 64), (32, 32)],
             (512, 512), 4, original=(512, 512), total=(512, 512))
    bpy.ops.preferences.addon_disable(module=os.path.basename(ROOT))
    print("RESULT " + json.dumps({"size_constraint_cases": 11, "passed": True}))


if __name__ == "__main__":
    main()
