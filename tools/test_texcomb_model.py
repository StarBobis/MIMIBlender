"""Validate atlas UVs on a copy of the original mesh in a supplied scene.

Run headlessly with --factory-startup; the source blend is never overwritten.
Outputs are kept in a temporary directory for manual inspection.
"""

import json
import os
import sys
import tempfile

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


def uv_values(layer):
    # Copy bulk UV values so later edits cannot alter the reference arrays.
    values = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", values)
    return values.reshape(-1, 2)


def main():
    bpy.ops.preferences.addon_enable(module=os.path.basename(ROOT))
    source = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.wm.open_mainfile(filepath=source)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    scene = bpy.context.scene
    # The supplied scene contains an already merged copy and a hidden source.
    originals = [obj for obj in scene.objects if obj.type == "MESH" and len(obj.data.materials) > 1]
    assert originals, "No unmerged source mesh available"
    original = max(originals, key=lambda obj: len(obj.data.materials))
    obj = original.copy()
    obj.data = original.data.copy()
    scene.collection.objects.link(obj)
    # Only process the fresh copy; hidden originals stay untouched in memory.
    for other in scene.objects:
        if other != obj:
            other.hide_set(True)
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.hide_render = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    layers = obj.data.uv_layers
    render_layer = next(layer for layer in layers if layer.active_render)
    render_name = render_layer.name
    before = uv_values(render_layer)
    auxiliaries = {layer.name: uv_values(layer) for layer in layers if layer.name != render_name}
    print("MODEL_INPUT", obj.name, "render", render_name, "edit", layers.active.name,
          "loops", len(before), "materials", len(obj.data.materials))
    # Optional canvas floor validates new settings on an old saved scene.
    if "--original-size" in sys.argv:
        start = sys.argv.index("--original-size")
        scene.mimi_smc_original_size = True
        scene.mimi_smc_original_width = int(sys.argv[start + 1])
        scene.mimi_smc_original_height = int(sys.argv[start + 2])
    # Optional total budget tests automatic resolution degradation.
    if "--total-size" in sys.argv:
        start = sys.argv.index("--total-size")
        scene.mimi_smc_total_size = True
        scene.mimi_smc_total_width = int(sys.argv[start + 1])
        scene.mimi_smc_total_height = int(sys.argv[start + 2])
    # Keep the user's other settings; output goes only to a temp folder.
    directory = tempfile.mkdtemp(prefix="texcomb_model_")
    scene.mimi_smc_save_path = directory
    assert bpy.ops.mimi.combiner(directory=directory) == {"FINISHED"}
    assert layers.active.name == render_name
    after = uv_values(layers[render_name])
    # Compare geometry in UV space, not just corner colors. Nondegenerate
    # source triangles must remain nondegenerate after the affine remapping.
    faces = []
    for poly in obj.data.polygons:
        if len(poly.loop_indices) == 3:
            faces.append(tuple(poly.loop_indices))
    indices = np.asarray(faces)
    old = before[indices]
    new = after[indices]
    def areas(values):
        a = values[:, 1] - values[:, 0]
        b = values[:, 2] - values[:, 0]
        return np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    old_area = areas(old)
    new_area = areas(new)
    # Ignore sub-texel source slivers: float32 atlas coordinates naturally
    # lose precision on triangles too small to cover a visible texel.
    valid = old_area > 1e-7
    collapsed = valid & (new_area == 0)
    assert not collapsed.any(), int(collapsed.sum())
    assert np.isfinite(after).all()
    assert after.min() >= -1e-5 and after.max() <= 1.00001
    assert len(np.unique(after, axis=0)) > 10000
    for name, values in auxiliaries.items():
        np.testing.assert_array_equal(uv_values(layers[name]), values)
    # Produce an atlas UV overlay for visual review without opening a GUI.
    from PIL import Image, ImageDraw
    atlas_path = next(os.path.join(directory, name) for name in os.listdir(directory)
                      if name.startswith("Atlas_") and name.endswith(".png"))
    preview = Image.open(atlas_path).convert("RGB")
    if scene.mimi_smc_total_size:
        assert preview.width <= scene.mimi_smc_total_width
        assert preview.height <= scene.mimi_smc_total_height
    print("MODEL_ATLAS_SIZE", preview.size)
    preview.thumbnail((1024, 1024))
    draw = ImageDraw.Draw(preview)
    width, height = preview.size
    # Subsample for legibility while keeping all areas represented.
    for triangle in new[::8]:
        points = [(float(uv[0]) * width, (1 - float(uv[1])) * height) for uv in triangle]
        draw.line(points + [points[0]], fill=(255, 140, 0), width=1)
    preview.save(os.path.join(directory, "uv_review.png"))
    # Save a review copy only, never the user-supplied input path.
    output = os.path.join(directory, "verified_model.blend")
    bpy.ops.wm.save_as_mainfile(filepath=output, copy=True)
    report = {"review": os.path.join(directory, "uv_review.png"), "loops": len(after), "unique_uvs": len(np.unique(after, axis=0)),
              "source_triangles": int(valid.sum()), "collapsed_triangles": int(collapsed.sum()),
              "auxiliary_layers_unchanged": len(auxiliaries), "output": output}
    print("RESULT " + json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
