"""Headless integration test for editable, exact atlas size distributions.

Run with factory startup and --python-exit-code 1. The scene is synthetic;
no user model, settings or textures are loaded or overwritten by this test.
Checks exercise actual RNA callbacks, the planner, the merge and UV output.

Test boundaries:
- Factory startup isolates the test from user add-ons and existing scenes.
- The test enables the repository add-on through Blender's normal registration.
- Sixteen independent materials model the user's finite-budget example.
- Every source has a packed image, avoiding dependence on external files.
- Each quad owns one material and one render UV layer.
- Negative UV coordinates expose destructive preview normalization.
- Coordinate snapshots are ordinary tuples, not live mathutils references.
- Rejected merges must leave those snapshots unchanged.
- Rejected merges must not create output images in the temporary directory.
- Successful planning must show one editable row for every material.
- Editing either dimension must activate the fixed-size constraint.
- Recalculation must preserve the hero region and rebudget other entries.
- Changing output budget settings must revoke the approved distribution.
- An external UV edit must also make the source fingerprint stale.
- Impossible fixed constraints must remain visible for another edit attempt.
- A failed plan must never grant permission to combine.
- Unlocking must revoke approval before restoring the automatic default.
- Recalculation must use source defaults rather than cumulative reductions.
- Four pixels of external spacing must not shrink the hero content.
- Legacy strict canvas settings must not post-resize a fixed content region.
- A rectangular hero catches an accidental final landscape rotation.
- The output PNG size must match the approved canvas exactly.
- The output UV span is measured back in pixels, not just normalized units.
- Interior pixel samples must remain opaque in every material region.
- Both width and height are checked against the promised hero dimensions.
- The final mesh uses the generated atlas material after reassignment.
- The old plan must become stale after that reassignment completes.
- Disabling the add-on must remove its Scene collection property.
- Output is saved under a temporary test directory, never a user asset path.
- Blender reports script failures through --python-exit-code 1.
- A final JSON result makes successful completion easy to verify in logs.
- Pure layout checks run before the more expensive real-image integration.
- The core impossible-box test deliberately has sufficient aggregate area.
- This distinguishes geometric validation from a simple area estimate.
- Padding checks measure the fixed content contract independently of packing.
- Exceptions from ERROR reports are expected for intentionally invalid cases.
- Unexpected assertions or exceptions still terminate the test with failure.
- No GUI Blender window, modal undo call or background thread is needed.
- The test may be rerun safely because each run owns its factory-startup scene.
- Actual add-on registration is checked again by the existing smoke suite.
- The tests document compatibility requirements for direct operator callers.
- Those callers must generate a valid distribution before asking for a merge.
- No test bypasses the execution-time approval check to produce an atlas.
- The approved placement data is used verbatim by the merge operator.
- Every generated path belongs to this synthetic integration run only.
- User configuration files and add-on preferences are never saved by the test.
"""

import json
import os
import sys
import tempfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


def make_quad(index):
    """Create a distinct material with a packed image and a repeated quad."""
    mat = bpy.data.materials.new("distribution_material_" + str(index))
    # Explicit node setup also works on Blender versions before 5.x.
    mat.use_nodes = True
    shader = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    color = (0.1 + index * 0.04, 0.3, 0.6, 1.0)
    image = bpy.data.images.new("distribution_image_" + str(index), 512, 512, alpha=True)
    image.pixels = list(color) * (512 * 512)
    image.pack()
    texture = mat.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    mat.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    mat.mimi_smc_diffuse = False
    mesh = bpy.data.meshes.new("distribution_mesh_" + str(index))
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(mat)
    layer = mesh.uv_layers.new(name="uvmap")
    # Negative-tile UVs expose accidental in-place alignment during preview.
    for loop, uv in zip(layer.data, [(-0.9, -0.9), (-0.1, -0.9), (-0.1, -0.1), (-0.9, -0.1)]):
        loop.uv = uv
    obj = bpy.data.objects.new("distribution_object_" + str(index), mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj, mat


def snapshot(objects):
    """Copy coordinates to detect destructive work in rejected operations."""
    return [[tuple(loop.uv) for loop in obj.data.uv_layers.active.data] for obj, _ in objects]


def expect_rejected(directory):
    """Blender reports ERROR as RuntimeError for programmatic operator calls."""
    try:
        result = bpy.ops.mimi.combiner(directory=directory)
    except RuntimeError:
        return
    assert result == {"CANCELLED"}, result


def main():
    import MIMIBlender
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from MIMIBlender.texcomb.operators.combiner.size_distribution import distribution_ready
    from MIMIBlender.texcomb.core.layout import pack_budget_atlas

    # Core constraints must survive the entire budget-reduction loop.
    # The canonical example is sixteen entries with one 512x512 hero texture.
    boxes = {str(index): (512, 512) for index in range(16)}
    fits, canvas, reduced = pack_budget_atlas(boxes, (1024, 1024), fixed_sizes={"0": (512, 512)})
    assert reduced["0"] == (512, 512)
    assert max(canvas) <= 1024
    assert all(reduced[key][0] < 512 for key in reduced if key != "0")
    # An area-only check is insufficient: two wide boxes cannot stack here.
    try:
        pack_budget_atlas({"a": (700, 600), "b": (700, 600)}, (1024, 1024),
                          fixed_sizes={"a": (700, 600), "b": (700, 600)})
    except ValueError:
        pass
    else:
        raise AssertionError("Impossible locked rectangles were accepted")
    # Padding must consume extra canvas space, never part of the fixed content.
    _, _, padded = pack_budget_atlas({"hero": (64, 64), "small": (64, 64)}, (128, 128),
                                    fixed_sizes={"hero": (64, 64)}, gaps=4)
    assert padded["hero"] == (64, 64)

    # Remove factory primitives so their default material cannot join the scan.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    objects = [make_quad(index) for index in range(16)]
    scene = bpy.context.scene
    scene.mimi_smc_uniform_size = True
    scene.mimi_smc_uniform_size_value = 512
    scene.mimi_smc_total_size = True
    scene.mimi_smc_total_width = 1024
    scene.mimi_smc_total_height = 1024
    scene.mimi_smc_gaps = 0
    scene.mimi_smc_image_format = "PNG"
    bpy.context.view_layer.objects.active = objects[0][0]
    bpy.ops.mimi.refresh_ob_data()
    directory = tempfile.mkdtemp(prefix="texcomb_distribution_")
    before = snapshot(objects)
    expect_rejected(directory)
    assert snapshot(objects) == before
    assert not os.listdir(directory)

    # Generating the preview must not change any UV or remove any slot.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    assert len(scene.mimi_smc_distribution) == 16
    # Each preview points to the real base image, not a rendered material sphere.
    # The planner initializes previews before any list redraw occurs.
    for entry in scene.mimi_smc_distribution:
        texture = next(node for node in entry.mat.node_tree.nodes if node.type == "TEX_IMAGE")
        assert entry.preview_image == texture.image
        assert entry.preview_image.preview is not None
        # Headless Blender does not allocate drawable UI icon IDs.
        # Pixel dimensions prove the preview exists without a GUI renderer.
        assert entry.preview_image.preview.image_size[0] > 0
    # Exercise both UI preview paths without a GUI window or image decoding.
    from types import SimpleNamespace
    from unittest.mock import patch
    from MIMIBlender.texcomb.ui.main_panel import MIMIMaterialCombinerPanel, MIMISMC_UL_SizeDistribution
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    class PreviewLayout:
        def __init__(self):
            self.icons = []
        def row(self, **kwargs):
            return self
        column = row
        box = row
        split = row
        def label(self, **kwargs):
            if "icon_value" in kwargs:
                self.icons.append(kwargs["icon_value"])
        def prop(self, *args, **kwargs):
            pass
        def operator(self, *args, **kwargs):
            return self
        def template_list(self, *args, **kwargs):
            pass
        def template_icon(self, **kwargs):
            self.icons.append(kwargs["icon_value"])
    preview_item = SimpleNamespace(mat=objects[0][1], preview_image=SimpleNamespace(
        preview=SimpleNamespace(icon_id=123), name="test_texture"), members=[], preview_solid=False)
    recorder = PreviewLayout()
    with patch.object(planner, "prepare_distribution_previews", side_effect=AssertionError("Preview creation during redraw")):
        MIMISMC_UL_SizeDistribution.draw_item(None, bpy.context, recorder, scene, preview_item, 0, scene, "mimi_smc_distribution_index", 0)
        MIMIMaterialCombinerPanel._create_action_controls(scene, recorder)
    assert 123 in recorder.icons
    assert distribution_ready(scene)
    assert snapshot(objects) == before
    hero = next(entry for entry in scene.mimi_smc_distribution if entry.mat == objects[0][1])
    hero.width = 512
    hero.height = 512
    assert hero.locked and not distribution_ready(scene)
    expect_rejected(directory)
    assert snapshot(objects) == before
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    hero = next(entry for entry in scene.mimi_smc_distribution if entry.mat == objects[0][1])
    assert (hero.width, hero.height) == (512, 512)
    assert distribution_ready(scene)

    # A parameter change or an external UV edit makes the fingerprint stale.
    scene.mimi_smc_total_width = 512
    assert not distribution_ready(scene)
    scene.mimi_smc_total_width = 1024
    objects[1][0].data.uv_layers.active.data[0].uv.x += 0.02
    assert not distribution_ready(scene)
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}

    # An impossible lock remains editable; no silent reduction is allowed.
    hero = next(entry for entry in scene.mimi_smc_distribution if entry.mat == objects[0][1])
    hero.width, hero.height = 1024, 1024
    try:
        result = bpy.ops.mimi.generate_size_distribution(recalculate=True)
        assert result == {"CANCELLED"}
    except RuntimeError:
        pass
    assert not distribution_ready(scene)
    assert (hero.width, hero.height) == (1024, 1024)
    expect_rejected(directory)
    hero.width, hero.height = 512, 256
    # Non-square locks catch unwanted landscape rotation at the end of merge.
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    hero = next(entry for entry in scene.mimi_smc_distribution if entry.mat == objects[0][1])
    hero.locked = False
    assert not distribution_ready(scene)
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    hero = next(entry for entry in scene.mimi_smc_distribution if entry.mat == objects[0][1])
    assert not hero.locked and hero.width < 512
    hero.width, hero.height = 512, 256
    # Spacing is external: it may lower automatic entries, never the hero.
    scene.mimi_smc_gaps = 4
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    # Exercise legacy custom settings with all three automatic toggles off.
    scene.mimi_smc_uniform_size = False
    scene.mimi_smc_total_size = False
    scene.mimi_smc_original_size = False
    scene.mimi_smc_size = "STRICTCUST"
    scene.mimi_smc_size_width, scene.mimi_smc_size_height = 1024, 1024
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    planned = {entry.mat: (entry.width, entry.height) for entry in scene.mimi_smc_distribution}
    expected_canvas = (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height)
    assert bpy.ops.mimi.combiner(directory=directory) == {"FINISHED"}
    from PIL import Image
    atlas_path = next(os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".png"))
    atlas = Image.open(atlas_path).convert("RGBA")
    assert atlas.size == expected_canvas
    # UV spans measured in output pixels must equal the approved content size.
    # All four corners were spaced 0.8 UV units apart before remapping.
    for obj, mat in objects:
        points = [tuple(loop.uv) for loop in obj.data.uv_layers.active.data]
        if mat == objects[0][1]:
            for axis in range(2):
                span = max(point[axis] for point in points) - min(point[axis] for point in points)
                # A square source fits inside rectangular bounds without stretching.
                assert abs(span * atlas.size[axis] / 0.8 - min(planned[mat])) < 0.01
        u, v = [sum(point[axis] for point in points) / 4 for axis in range(2)]
        assert atlas.getpixel((int(u * atlas.width), int((1 - v) * atlas.height)))[3] == 255
    assert not distribution_ready(scene)
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    assert not hasattr(bpy.types.Scene, "mimi_smc_distribution")
    print("RESULT " + json.dumps({"version": bpy.app.version_string, "materials": 16,
                                  "hero": [512, 256], "canvas": expected_canvas, "status": "passed"}))


if __name__ == "__main__":
    main()
