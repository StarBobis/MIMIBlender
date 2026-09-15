"""Headless smoke test for the texcomb texture combiner module.

Run with Blender 5.2:
    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        -b --factory-startup --python tools/texcomb_smoke_test.py

The test:
1. Enables the MIMIBlender addon (same path as the preferences dialog).
2. Verifies the combiner operator and its UI panel got registered.
3. Imports the pure-python texcomb.core package INSIDE Blender and runs one
   numeric check (proves the core works on Blender's bundled numpy).
4. Disables the addon again.

Exits with code 0 on success and 1 on the first failed assertion.
"""

import os
import sys

# Make the addon package importable: the repo root is the package itself, so
# its parent directory must be on sys.path (same as Blender's addon folder).
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT_DIR = os.path.dirname(_REPO_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

import bpy  # noqa: E402

_FAILURES = []


def check(label, condition):
    """Record one assertion result and print it immediately."""
    status = "PASS" if condition else "FAIL"
    print("[SMOKE {}] {}".format(status, label))
    if not condition:
        _FAILURES.append(label)


def main():
    import MIMIBlender

    # 1. Enable the addon through Blender's addon system.
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    check("addon_enable completed", True)

    # 2. The combiner operator and the refresh operator must be registered.
    check("combiner operator registered", hasattr(bpy.ops.mimi, "combiner"))
    check(
        "refresh operator registered",
        hasattr(bpy.ops.mimi, "refresh_ob_data"),
    )
    # Scene properties of the combiner must exist on the scene.
    check(
        "scene properties registered",
        hasattr(bpy.context.scene, "mimi_smc_ob_data"),
    )

    # 3. The pure-python core must import and compute inside Blender too.
    #    (Blender bundles numpy, so this also validates that dependency.)
    import numpy as np
    from MIMIBlender.texcomb.core import channels, pixels
    from MIMIBlender.texcomb.core.models import ChannelPlan

    plane = pixels.new_plane(2, 2, (0.25, 0.5, 0.75, 0.5))
    resized = pixels.resize_plane(plane, 4, 4, "lanczos3")
    check("core resize keeps flat plane flat", np.allclose(resized, plane[0, 0], atol=1e-5))

    out = channels.build_material_plane(ChannelPlan(base_key="", solid_color=(0.1, 0.2, 0.3, 0.5)), {}, size=(2, 2))
    check("core channel build works", np.allclose(out, (0.1, 0.2, 0.3, 0.5)))

    # 4. Clean unload through the addon system.
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    check("addon_disable completed", True)

    if _FAILURES:
        print("[SMOKE] {} check(s) FAILED".format(len(_FAILURES)))
        sys.exit(1)
    print("[SMOKE] all checks passed")
    sys.exit(0)


main()
