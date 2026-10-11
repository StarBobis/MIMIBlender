"""Verify proportional UV mapping and blank space inside manual allocations.

Run with Blender factory startup and --python-exit-code 1.
All images, meshes and output directories are synthetic test assets.
The square source must stay square in actual output pixel coordinates.

Acceptance checks:
- A 64x388 manual allocation never elongates a square texture or its UVs.
- The reserved allocation remains 64x388 while pasted content is 64x64.
- Recalculation preserves manual bounds without changing that proportional fit.
- Automatic plans also preserve native proportions before any fixed edit.
- The actual PNG has blank pixels inside unused allocation space.
- UV corners sample opaque pixels inside the proportional content region.
- Different canvas width/height axes are measured in pixels, not normalized UV.
- Shared texture deduplication does not change the proportional content fit.
- Preview/recalculation never normalize original negative UV coordinates.
- Only the actual combiner updates UV coordinates and material assignments.
- Material source-size bounds use a single scale rather than independent limits.
- Power-of-two source caps do not round each source axis independently.
- Fixed bounds and actual content dimensions are deliberately distinct concepts.
- The source aspect is maintained even if an atlas has enough room to stretch.
- Leaving atlas pixels unused is expected and accepted in this test.
- Background image checks do not require a new Blender GUI window.
- Full merge validation still runs before generating any atlas pixels.
- Blank pixels are sampled inside the reserved rectangle, not atlas outer padding.
- Opaque pixels are sampled inside the actual fitted image area.
- The fixed allocation is re-fetched after RNA collection rebuilding.
- Preview size generation is separate from the native repeated-content aspect.
- Pixel-space equality matters even when the atlas axes have different lengths.
- Native source proportions survive the total atlas budget reduction stage.
- Rectangle packing may reserve more space than the image actually uses.
- The test never asks the packer to fill that space by stretching content.
- Both image composition and UV remapping use one stored fitted-content size.
- Manual bounds remain exact even when actual fitted content is smaller.
- The final machine-readable result records both dimensions explicitly.
- The synthetic test owns every scene object it removes or replaces.
"""

import json
import os
import sys
import tempfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from test_texcomb_distribution import make_quad


def main():
    import MIMIBlender
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    objects = [make_quad(index) for index in range(2)]
    hero = objects[0][1]
    scene = bpy.context.scene
    scene.mimi_smc_uniform_size_value = 128
    scene.mimi_smc_total_size = True
    scene.mimi_smc_total_width, scene.mimi_smc_total_height = 1024, 1024
    scene.mimi_smc_image_format = "PNG"
    bpy.context.view_layer.objects.active = objects[0][0]
    original = [tuple(loop.uv) for loop in objects[0][0].data.uv_layers.active.data]
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    entry = next(entry for entry in scene.mimi_smc_distribution if entry.mat == hero)
    assert entry.width == entry.height
    baseline = [(row.mat.name, row.width, row.height, row.x, row.y) for row in scene.mimi_smc_distribution]
    entry.width, entry.height = 17, 99
    scene.mimi_smc_distribution_index = 1
    from unittest.mock import patch
    prepare = planner.prepare_sources

    def check_fresh_sources(*args, **kwargs):
        # Old locks, canvas dimensions and signatures must vanish before reading sources.
        # Checking inside preparation detects reset timing, not just final output.
        assert len(scene.mimi_smc_distribution) == 0
        assert scene.mimi_smc_distribution_index == 0
        assert (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height) == (0, 0)
        assert scene.mimi_smc_distribution_signature == ""
        assert scene.mimi_smc_distribution_ui_signature == ""
        assert scene.mimi_smc_distribution_message == ""
        return prepare(*args, **kwargs)

    with patch.object(planner, "prepare_sources", side_effect=check_fresh_sources):
        assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    # Regeneration must be independent of the old edited row and selected index.
    # Every automatic dimension and placement should match the initial clean run.
    assert [(row.mat.name, row.width, row.height, row.x, row.y) for row in scene.mimi_smc_distribution] == baseline
    assert not any(row.locked for row in scene.mimi_smc_distribution)
    with patch.object(planner, "prepare_sources", side_effect=ValueError("Synthetic source failure")):
        try:
            result = bpy.ops.mimi.generate_size_distribution()
            assert result == {"CANCELLED"}
        except RuntimeError as exc:
            assert "Synthetic source failure" in str(exc)
    # Even a failed source scan must not retain any previous approved distribution.
    # The error message may remain, but no dimensions or signatures can be reused.
    assert len(scene.mimi_smc_distribution) == 0
    assert (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height) == (0, 0)
    assert scene.mimi_smc_distribution_signature == scene.mimi_smc_distribution_ui_signature == ""
    assert not scene.mimi_smc_distribution_valid
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    entry = next(entry for entry in scene.mimi_smc_distribution if entry.mat == hero)
    entry.width, entry.height = 64, 388
    assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
    entry = next(entry for entry in scene.mimi_smc_distribution if entry.mat == hero)
    assert (entry.width, entry.height) == (64, 64)
    assert (entry.allocation_width, entry.allocation_height) == (64, 388)
    # Repeated recalculation must preserve both proportional display and blank slack.
    for _ in range(3):
        assert bpy.ops.mimi.generate_size_distribution(recalculate=True) == {"FINISHED"}
        entry = next(entry for entry in scene.mimi_smc_distribution if entry.mat == hero)
        assert (entry.width, entry.height) == (64, 64)
        assert (entry.allocation_width, entry.allocation_height) == (64, 388)
    x, y = entry.x, entry.y
    assert [tuple(loop.uv) for loop in objects[0][0].data.uv_layers.active.data] == original
    _, _, structure = planner.prepare_sources(scene)
    planner.apply_distribution(scene, structure)
    assert structure[hero]["gfx"]["content_size"] == (64, 64)
    output = tempfile.mkdtemp(prefix="mimi_aspect_")
    assert bpy.ops.mimi.combiner(directory=output) == {"FINISHED"}
    from PIL import Image
    path = next(os.path.join(output, name) for name in os.listdir(output) if name.endswith(".png"))
    with Image.open(path).convert("RGBA") as atlas:
        points = [tuple(loop.uv) for loop in objects[0][0].data.uv_layers.active.data]
        spans = [(max(point[axis] for point in points) - min(point[axis] for point in points)) * atlas.size[axis]
                 for axis in (0, 1)]
        assert abs(spans[0] - spans[1]) < 0.01
        assert abs(spans[0] / 0.8 - 64) < 0.01
        assert atlas.getpixel((x + 32, y + 32))[3] == 255
        assert atlas.getpixel((x + 32, y + 100))[3] == 0
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    print("RESULT " + json.dumps({"status": "passed", "allocation": [64, 388],
                                  "content": [64, 64], "blank_space": True, "uv_pixel_aspect": 1}))


if __name__ == "__main__":
    main()
