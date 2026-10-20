"""Headless checks for per-DrawIB bone palettes and the naming-mode choice.

Run Blender with --factory-startup --python-exit-code 1 -P this file.

Why this fixture exists
-----------------------
A hand-rebuilt mod can index a *different* bone palette in every DrawIB: one
mesh was rebuilt by its author, another came from a different character, so the
same number ("0", "1", ...) can mean a different bone in each of them.

The desktop app therefore writes one ``BoneMap`` per DrawIB inside
``skeleton.json``. The Blender side must use the map that belongs to the DrawIB
it is binding, and it must decide the naming mode **once per character**:

* ``BONE_TO_GROUP`` renames *bones* to the numbers the vertex groups have. That
  is correct for a mod that shares one numbering (the normal case) and is what
  keeps a later mod export working.
* ``GROUP_TO_BONE`` renames *vertex groups* to the bone names. That is the only
  option when the DrawIBs disagree, because one armature cannot be renamed to
  two different numberings at the same time.

The bug this test locks down: the mode used to be chosen per DrawIB, so the
first DrawIB renamed the bones to numbers while the next renamed its groups to
the *old* bone names. Those names no longer existed, every weight of that
DrawIB was dead, and no error was reported.

Fixtures never touch a user scene: the armature and the meshes are created in
the current (factory start-up) file and the sidecar is written to ``tmp/``.
"""
import importlib
import json
import sys
import types
from pathlib import Path

import bpy
from mathutils import Matrix

# Load just the helper module, so the test does not depend on optional
# add-on services (updater, UI, textures). This mirrors the other headless
# skeleton tests and keeps the run time at a fraction of a second.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("MIMIBlender")
package.__path__ = [str(ROOT)]
sys.modules["MIMIBlender"] = package
helper_module = importlib.import_module("MIMIBlender.utils.skeleton_helper")
SkeletonHelper = helper_module.SkeletonHelper


def character():
    """Two-bone character whose palette is deliberately wrong for DrawIB B.

    ``BoneMap`` here is only the character-level default. The per-DrawIB maps
    below override it, which is exactly what the desktop app writes for a mod
    that mixes palettes.
    """
    rows = []
    for index, name in enumerate(["Pelvis", "Arm"]):
        # Rest matrices are identity except for the height, so both bones are
        # easy to reason about while the test only cares about names.
        rest = Matrix.Identity(4)
        rest.translation.z = 0.1 * index
        rows.append(
            {
                "Name": name,
                "Parent": index - 1,
                "Rest": [value for row in rest for value in row],
                "Length": 0.2,
            }
        )
    return {
        "Id": "palettecase",
        "Name": "PaletteCase",
        "Bones": rows,
        "BoneMap": {"0": "Pelvis", "1": "Arm"},
    }


def mesh_object(name, group_names):
    """Create a tiny triangle whose vertex groups are the numeric palette slots."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for index, group in enumerate(group_names):
        # One vertex per group is enough: the binding only reads group names.
        obj.vertex_groups.new(name=group).add([index % 3], 1.0, "REPLACE")
    return obj


# Two DrawIBs that name *different* bones under the same numeric index. Both
# objects are named "<drawib>-Component 0.<part>" because the importer numbers
# its objects that way; no component table is used here (that is the WWMI case).
first = mesh_object("paletteA-Component 0.body", ["0", "1"])
second = mesh_object("paletteB-Component 0.cloth", ["0", "1"])

folder = ROOT / "tmp"
folder.mkdir(exist_ok=True)
sidecar = folder / "skeleton_palette_test.json"
sidecar.write_text(
    json.dumps(
        {
            # The app asks for numeric bones, which is impossible here: the two
            # palettes cannot both be expressed as one set of bone names.
            "NamingMode": "boneToGroup",
            "Space": {"Scale": 1.0, "RotationZ": 0.0},
            "Characters": [character()],
            "DrawIBs": [
                {
                    "DrawIB": "paletteA",
                    "CharacterId": "palettecase",
                    "BoneMap": {"0": "Pelvis", "1": "Arm"},
                },
                {
                    "DrawIB": "paletteB",
                    "CharacterId": "palettecase",
                    # Same numbers, other bones: the case that used to bind one
                    # of the two meshes to the wrong side of the rig, or leave
                    # it with no working weights at all.
                    "BoneMap": {"0": "Arm", "1": "Pelvis"},
                },
            ],
        }
    ),
    encoding="utf-8",
)

summary = SkeletonHelper.apply_groups(
    "SIDECAR", {"paletteA": [first], "paletteB": [second]}, str(sidecar)
)
print("SUMMARY:", summary)

# One armature per character: the two DrawIBs must share it, otherwise the
# model ends up with two skeletons again.
armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
assert len(armatures) == 1, "one armature per character, got %d" % len(armatures)

# Both meshes must be bound although the sidecar asks for numeric bone names:
# the conflict forces group-to-bone naming for the whole character.
for obj in (first, second):
    assert any(mod.type == "ARMATURE" for mod in obj.modifiers), obj.name + " not bound"
    assert {group.name for group in obj.vertex_groups} == {"Pelvis", "Arm"}, (
        obj.name + " groups were not renamed: " + str([g.name for g in obj.vertex_groups])
    )

# Group "0" of each mesh must name the bone its own DrawIB declared. If the two
# meshes ended up with the same names, the second map was ignored.
first_zero = next(g for g in first.vertex_groups if g.name == "Pelvis")
second_zero = next(g for g in second.vertex_groups if g.name == "Arm")
assert first_zero.name == "Pelvis"
assert second_zero.name == "Arm"

# Nothing may keep a numeric group: those would match no bone and silently stay
# in rest position.
for obj in (first, second):
    assert not [g for g in obj.vertex_groups if g.name.isdigit()], (
        obj.name + " kept numeric groups: " + str([g.name for g in obj.vertex_groups])
    )

print("PASS: per-DrawIB palettes bind through group names")
