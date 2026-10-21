"""Headless checks for the mirror-matched skeleton binding.

Run Blender with ``--factory-startup --python-exit-code 1 -P this file``.

Why this fixture exists
-----------------------
The skeleton packs are stored in the non-mirrored orientation while the game's
vertex buffers keep the historical mirrored orientation. The desktop app
therefore reflects the model in X before matching and records that decision as
``Space.MatchMirrorX`` in ``skeleton.json``.

The Blender side must place the armature in the same frame as the mesh:

* default (mirrored) import keeps the mesh mirrored, so the armature must be
  reflected;
* the non-mirrored workflow bakes the reflection into the mesh, so the armature
  must stay as the sidecar stored it;
* a sidecar written before the flag existed was matched without the reflection,
  so it keeps the historical placement (the armature follows the mesh).

The bug this test locks down: the armature used to be reflected exactly when the
mesh marker was present, i.e. backwards for a mirror-matched sidecar.
"""
import importlib
import json
import sys
import types
from pathlib import Path

import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("MIMIBlender")
package.__path__ = [str(ROOT)]
sys.modules["MIMIBlender"] = package
helper_module = importlib.import_module("MIMIBlender.utils.skeleton_helper")
SkeletonHelper = helper_module.SkeletonHelper


def rest_matrix(x):
    """Identity rotation with the bone head at ``x`` on the X axis."""
    matrix = Matrix.Identity(4)
    matrix.translation.x = x
    return [value for row in matrix for value in row]


def character():
    """Two hand bones: the pack stores its left hand on negative X."""
    return {
        "Id": "mirrorcase",
        "Name": "MirrorCase",
        "Bones": [
            {
                "Name": "Bip001 L Hand",
                "Parent": -1,
                "Rest": rest_matrix(-0.5),
                "Length": 0.2,
            },
            {
                "Name": "Bip001 R Hand",
                "Parent": -1,
                "Rest": rest_matrix(0.5),
                "Length": 0.2,
            },
        ],
        "BoneMap": {"0": "Bip001 L Hand", "1": "Bip001 R Hand"},
    }


def make_mesh(name):
    """One triangle with the two numeric palette groups of the character."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.vertex_groups.new(name="0").add([0], 1.0, "REPLACE")
    obj.vertex_groups.new(name="1").add([1], 1.0, "REPLACE")
    return obj


def run_case(match_mirror_x, import_mirror):
    """Bind one DrawIB with the given sidecar flag / import mode.

    Returns the armature bone X positions, then removes everything the case
    created so the next case starts from a clean scene.
    """
    folder = ROOT / "tmp"
    folder.mkdir(exist_ok=True)
    sidecar = folder / "skeleton_mirror_test.json"
    space = {"Scale": 1.0, "RotationZ": 0.0}
    if match_mirror_x is not None:
        space["MatchMirrorX"] = bool(match_mirror_x)
    sidecar.write_text(
        json.dumps(
            {
                "NamingMode": "groupToBone",
                "Space": space,
                "Characters": [character()],
                "DrawIBs": [
                    {
                        "DrawIB": "mirrorcase",
                        "CharacterId": "mirrorcase",
                        "BoneMap": {"0": "Bip001 L Hand", "1": "Bip001 R Hand"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    obj = make_mesh("mirrorcase-Component 0.body")
    objects_before = set(bpy.data.objects)
    SkeletonHelper.apply_groups(
        "SIDECAR",
        {"mirrorcase": [obj]},
        str(sidecar),
        "NONE",
        import_mirror=import_mirror,
    )
    created = [item for item in bpy.data.objects if item not in objects_before]
    armatures = [item for item in created if item.type == "ARMATURE"]
    assert len(armatures) == 1, "one armature expected, got %d" % len(armatures)
    armature = armatures[0]
    positions = {bone.name: bone.head_local.x for bone in armature.data.bones}

    # The bind itself must have happened: groups renamed, modifier attached.
    assert any(mod.type == "ARMATURE" for mod in obj.modifiers), "mesh not bound"
    assert {group.name for group in obj.vertex_groups} == {
        "Bip001 L Hand",
        "Bip001 R Hand",
    }, [group.name for group in obj.vertex_groups]

    for item in created:
        bpy.data.objects.remove(item, do_unlink=True)
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    sidecar.unlink(missing_ok=True)
    return positions


def check(label, positions, left_x, right_x):
    assert abs(positions["Bip001 L Hand"] - left_x) < 1e-5, (
        "%s: left bone at %.3f, expected %.3f" % (label, positions["Bip001 L Hand"], left_x)
    )
    assert abs(positions["Bip001 R Hand"] - right_x) < 1e-5, (
        "%s: right bone at %.3f, expected %.3f" % (label, positions["Bip001 R Hand"], right_x)
    )
    print("PASS:", label, positions)


# Default mirrored import: the mesh is still mirrored, so the armature must be.
check(
    "mirror-matched sidecar, mirrored default import",
    run_case(True, False),
    0.5,
    -0.5,
)

# Non-mirrored workflow: the mesh already carries the reflection.
check(
    "mirror-matched sidecar, non-mirrored import",
    run_case(True, True),
    -0.5,
    0.5,
)

# Sidecar from before the flag: historical placement (armature follows the mesh).
check(
    "legacy sidecar, mirrored default import",
    run_case(None, None),
    -0.5,
    0.5,
)
check(
    "legacy sidecar, non-mirrored import",
    run_case(False, True),
    0.5,
    -0.5,
)

print("PASS: skeleton mirror follows the import workflow mode")
