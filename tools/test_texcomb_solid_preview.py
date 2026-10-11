"""Check pure-color allocation previews with real Blender RNA and UI adapters.

Run headless with factory startup and --python-exit-code 1.
This test creates only synthetic solid materials and never loads a user scene.
The shown color must match the diffuse fallback actually baked by the combiner.

Acceptance checks:
- No-image materials receive a cached solid-color preview flag.
- Preview RGB is linear so Blender's color widget displays it correctly.
- Two identical solid outputs share one allocation row and one color swatch.
- A different solid color remains a separate allocation group.
- No synthetic preview image datablock is needed for a flat color.
- Both the list row and selected preview use the cached color property.
- UI redraw never calls diffuse extraction or packed-image lookup.
- The color widget is read-only and does not modify source material colors.
- The actual atlas contains the matching solid colors after merge.
- Allocation dimensions and fixed locks are unaffected by preview fields.
- Blender registration and teardown include the new preview RNA fields.
- No render jobs are created merely to show flat color previews.
- RGB color comparisons allow the existing byte quantization of get_diffuse.
- Background tests do not create a Blender GUI window.
- Output images live only in a temporary test directory.
- Missing texture images use the same fallback color as no-image materials.
- Presentation fields do not participate in packed rectangle dimensions.
- Color lookup occurs once during explicit generation or recalculation only.
- No additional timer or dependency graph scan is introduced by color swatches.
- Every row reads cached floats rather than traversing a Principled shader node.
- Member grouping still preserves both source material pointers.
- The material icon fallback remains available for unusable image previews.
- Selected previews display a pure-color label without requiring an image name.
- Temporary color display never creates a generated texture datablock.
- Color widget gamma handling must match the existing sRGB export pipeline.
- Source material editing remains outside the read-only allocation preview.
- Recalculation refreshes color values after a source material color change.
"""

import json
import os
import sys
import tempfile
from unittest.mock import patch

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from test_texcomb_distribution import make_quad
from test_texcomb_distribution_performance import Layout


class ColorLayout(Layout):
    """Record color properties while ignoring ordinary panel layout widgets."""

    def __init__(self):
        super().__init__()
        self.swatches = 0
        self.splits = []

    def split(self, **kwargs):
        # Fixed split factors must not depend on material name or group count.
        self.splits.append(kwargs["factor"])
        return self

    def prop(self, data, name, **kwargs):
        # Color preview readout must not request any source color accessor.
        if name == "preview_color":
            self.swatches += 1


def main():
    import MIMIBlender
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    from MIMIBlender.texcomb.ui.main_panel import MIMISMC_UL_SizeDistribution, MIMIMaterialCombinerPanel
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    objects = [make_quad(index) for index in range(3)]
    for index, (obj, mat) in enumerate(objects):
        # Removing the image link forces the same pure-color fallback as baking.
        for node in list(mat.node_tree.nodes):
            if node.type == "TEX_IMAGE":
                mat.node_tree.nodes.remove(node)
        shader = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        shader.inputs["Base Color"].default_value = (0.2, 0.5, 0.8, 1) if index < 2 else (0.8, 0.1, 0.2, 1)
    scene = bpy.context.scene
    scene.mimi_smc_image_format = "PNG"
    bpy.context.view_layer.objects.active = objects[0][0]
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    assert len(scene.mimi_smc_distribution) == 2
    entries = planner.distribution_entries(scene)
    entry = entries[objects[0][1]]
    assert entry == entries[objects[1][1]]
    assert entry.preview_solid and entry.preview_image is None
    assert all(abs(a - b) < 0.01 for a, b in zip(entry.preview_color, (0.2, 0.5, 0.8, 1)))
    scene.mimi_smc_distribution_index = next(i for i, row in enumerate(scene.mimi_smc_distribution) if row == entry)
    recorder = ColorLayout()
    with patch.object(planner, "get_diffuse", side_effect=AssertionError("Diffuse scan during redraw")):
        MIMISMC_UL_SizeDistribution.draw_item(None, bpy.context, recorder, scene, entry, 0, scene, "mimi_smc_distribution_index", 0)
        MIMIMaterialCombinerPanel._create_action_controls(scene, recorder)
    assert recorder.swatches == 2
    assert recorder.splits == [0.40, 0.16 / 0.60, 0.5, 0.15, 0.78]
    # Single-material rows retain the same count column as shared-material rows.
    single = entries[objects[2][1]]
    single_layout = ColorLayout()
    MIMISMC_UL_SizeDistribution.draw_item(None, bpy.context, single_layout, scene, single, 0, scene, "mimi_smc_distribution_index", 1)
    assert single_layout.splits == recorder.splits
    output = tempfile.mkdtemp(prefix="mimi_solid_preview_")
    assert bpy.ops.mimi.combiner(directory=output) == {"FINISHED"}
    from PIL import Image
    path = next(os.path.join(output, name) for name in os.listdir(output) if name.endswith(".png"))
    with Image.open(path).convert("RGBA") as atlas:
        for obj, mat in objects:
            points = [tuple(loop.uv) for loop in obj.data.uv_layers.active.data]
            u, v = [sum(point[axis] for point in points) / 4 for axis in (0, 1)]
            assert atlas.getpixel((int(u * atlas.width), int((1 - v) * atlas.height)))[3] == 255
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    print("RESULT " + json.dumps({"status": "passed", "solid_groups": 2,
                                  "cached_color": True, "draw_swatches": recorder.swatches}))


if __name__ == "__main__":
    main()
