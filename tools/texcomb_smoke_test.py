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
    check(
        "remove-unused operator registered",
        hasattr(bpy.ops.mimi, "remove_unused_materials"),
    )
    # Scene properties of the combiner must exist on the scene.
    check(
        "scene properties registered",
        hasattr(bpy.context.scene, "mimi_smc_ob_data"),
    )
    # Fresh scenes must expose the selected defaults after RNA registration.
    # These checks verify Blender resolves the dynamic enum identifiers.
    # Factory startup prevents saved choices from masking an incorrect default.
    check(
        "DDS output is selected by default",
        bpy.context.scene.mimi_smc_image_format == "DDS",
    )
    check(
        "BC7_UNORM_SRGB is selected by default",
        bpy.context.scene.mimi_smc_dds_format == "BC7_UNORM_SRGB",
    )

    # 2b. A stale slot left behind by partial model deletion must appear in
    #     the scan as a separated unused entry, then vanish after one click.
    mesh = bpy.data.meshes.new("smoke_mesh")
    obj = bpy.data.objects.new("smoke_obj", mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh.uv_layers.new(name="UVMap")
    used_mat = bpy.data.materials.new("smoke_used")
    stale_mat = bpy.data.materials.new("smoke_stale")
    mesh.materials.append(used_mat)
    mesh.materials.append(stale_mat)
    mesh.polygons[0].material_index = 0
    bpy.ops.mimi.refresh_ob_data()
    # Entry types: 0 = object, 1 = material, 2 = separator.
    entries = list(bpy.context.scene.mimi_smc_ob_data)
    mats = {e.mat.name: e for e in entries if e.type == 1 and e.mat}
    check("used slot listed as valid", mats["smoke_used"].unused is False)
    check("stale slot listed as unused", mats["smoke_stale"].unused is True)
    check("stale slot excluded from combine", mats["smoke_stale"].used is False)
    order = {e.type: i for i, e in enumerate(entries) if e.mat or e.type == 2}
    # The UIList sorts at draw time, so ask the real sorter for the order
    # instead of inspecting the raw collection, which keeps insert order.
    from MIMIBlender.texcomb.extend_lists import MIMISMC_UL_Combine_List

    sorted_indices = MIMISMC_UL_Combine_List._sort_group_items(
        list(enumerate(entries)), reverse_sort=False
    )
    positions = {
        entries[i].mat.name: pos
        for pos, i in enumerate(sorted_indices)
        if entries[i].mat
    }
    separator_pos = next(
        pos for pos, i in enumerate(sorted_indices) if entries[i].type == 2
    )
    check(
        "unused entries sorted below the separator",
        positions["smoke_used"] < separator_pos < positions["smoke_stale"],
    )
    bpy.ops.mimi.remove_unused_materials()
    check(
        "stale slot removed from mesh",
        len(mesh.materials) == 1 and mesh.materials[0] == used_mat,
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
