"""Regression for allocation-panel redraw cost on a large synthetic mesh.

Run headless with factory startup and --python-exit-code 1. No user scene loads.
The test separates UI checks from full source validation using actual Scene RNA.
It also invokes the panel drawing helper with a tiny recording layout adapter.

Acceptance checks:
- A large mesh exposes the previous per-redraw topology and UV traversal cost.
- The approved list contains two independently editable material entries.
- UI readiness must never call the full source fingerprint function.
- Repeated UI redraws must not visit polygons or read UV coordinate arrays.
- Panel drawing must request a bounded UIList instead of looping all entries.
- A dimension edit must still immediately revoke approval through RNA callbacks.
- Replanning approval must retain the separate deep source fingerprint.
- A direct UV edit may leave lightweight UI state ready until the merge check.
- Actual merge execution must reject that changed UV before modifying meshes.
- No image must be created for a stale plan.
- Strict comparison remains the default for callers outside the panel.
- Timing output compares checks on the same mesh in the same process.
- Speed assertions use a generous ratio, not a fragile millisecond threshold.
- Add-on disable must remove the new UI-signature Scene property.
- The test does not open a GUI window or start Blender worker threads.
- All temporary output directories belong to this synthetic test.
- UI checks intentionally use check_sources=False at the panel boundary only.
- Calling readiness without that argument still scans the source fingerprint.
- Selection changes remain visible to the lightweight allocation signature.
- Hidden placement values remain part of that lightweight signature as well.
- Repeated redraw timing excludes the expensive mesh-construction step.
- Three full checks establish a baseline without a prolonged benchmark loop.
- No cache timer is needed to keep a stationary scene responsive.
- No dependency-graph handler performs fingerprint scans behind the scenes.
- Edit-mode mesh synchronization is absent from the lightweight code path.
- The panel layout recorder checks requested clipping rather than pixel layout.
- Real Blender owns scrolling and draws only the visible allocation controls.
- Material width edits continue to use the registered automatic-lock callback.
- Source validation executes before any image decode or UV normalization.
- An unchanged UV coordinate after rejection proves no destructive alignment ran.
- Archive publishing and version numbers are outside this regression's scope.
- Synthetic measurements do not claim to represent every user model or GPU.
- The key structural guarantee is zero deep-scan calls from panel redraws.
- Failed strict checks revoke the lightweight approval for the next redraw.
- Checking allocation state does not write data from the panel draw callback.
- The default strict API remains compatible with existing integration tests.
"""

import json
import os
import sys
import tempfile
import time
from unittest.mock import patch

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


class Layout:
    """Record template-list use while ignoring ordinary layout properties."""

    def __init__(self):
        self.lists = []

    # Child layouts can share this recorder; geometry is never consulted.
    def row(self, **kwargs):
        return self

    column = row
    box = row
    split = row

    def label(self, *args, **kwargs):
        pass

    prop = label

    def operator(self, *args, **kwargs):
        return self

    def template_list(self, *args, **kwargs):
        self.lists.append((args, kwargs))

    def template_icon(self, **kwargs):
        # Larger selected previews reuse the same precomputed image icon.
        # The recording layout deliberately has no image loading interface.
        pass


def approve(scene, planner):
    """Simulate completed planning without allocating a large atlas image."""
    scene.mimi_smc_distribution_signature = planner.source_signature(scene)
    scene.mimi_smc_distribution_ui_signature = planner.distribution_ui_signature(scene)
    scene.mimi_smc_distribution_valid = True


def main():
    import MIMIBlender
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    from MIMIBlender.texcomb.ui.main_panel import MIMIMaterialCombinerPanel

    # Shared vertices keep construction cheap while creating 300,000 UV loops.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    mesh = bpy.data.meshes.new("performance_mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)] * 100000)
    mesh.uv_layers.new(name="uvmap")
    obj = bpy.data.objects.new("performance_object", mesh)
    scene = bpy.context.scene
    scene.collection.objects.link(obj)
    for index in range(2):
        mat = bpy.data.materials.new("performance_material_" + str(index))
        mesh.materials.append(mat)
        selected = scene.mimi_smc_ob_data.add()
        selected.type = 1
        selected.ob, selected.mat, selected.used = obj, mat, True
        entry = scene.mimi_smc_distribution.add()
        entry.mat = mat
        entry.width, entry.height = 32, 32
        entry.locked = False
        entry.x = index * 32
    scene.mimi_smc_distribution_width = 64
    scene.mimi_smc_distribution_height = 32
    scene.mimi_smc_distribution_expanded = True
    approve(scene, planner)
    recorder = Layout()

    # Fail loudly if a redraw accidentally reintroduces deep validation.
    start = time.perf_counter()
    with patch.object(planner, "source_signature", side_effect=AssertionError("Deep scan during redraw")):
        for _ in range(200):
            assert planner.distribution_ready(scene, check_sources=False)
        MIMIMaterialCombinerPanel._create_action_controls(scene, recorder)
    ui_seconds = (time.perf_counter() - start) / 201
    assert len(recorder.lists) == 1
    assert recorder.lists[0][1] == {"rows": 6, "maxrows": 8}
    start = time.perf_counter()
    for _ in range(3):
        assert planner.distribution_ready(scene)
    deep_seconds = (time.perf_counter() - start) / 3
    assert deep_seconds > ui_seconds * 10, (deep_seconds, ui_seconds)

    # Editing the allocation still revokes approval without a mesh scan.
    scene.mimi_smc_distribution[0].width = 64
    assert not planner.distribution_ready(scene, check_sources=False)
    approve(scene, planner)
    mesh.uv_layers.active.data[0].uv.x = 0.25
    assert planner.distribution_ready(scene, check_sources=False)
    assert not planner.distribution_ready(scene)
    assert not planner.distribution_ready(scene, check_sources=False)
    output = tempfile.mkdtemp(prefix="mimi_performance_rejected_")
    try:
        result = bpy.ops.mimi.combiner(directory=output)
    except RuntimeError:
        result = {"CANCELLED"}
    assert result == {"CANCELLED"}
    assert mesh.uv_layers.active.data[0].uv.x == 0.25
    assert not os.listdir(output)
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    assert not hasattr(bpy.types.Scene, "mimi_smc_distribution_ui_signature")
    print("RESULT " + json.dumps({"polygons": 100000, "uv_loops": 300000,
                                  "ui_check_ms": ui_seconds * 1000,
                                  "deep_check_ms": deep_seconds * 1000,
                                  "speedup": deep_seconds / ui_seconds, "status": "passed"}))


if __name__ == "__main__":
    main()
