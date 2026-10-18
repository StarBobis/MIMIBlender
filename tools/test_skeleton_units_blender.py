"""Headless checks for armature lengths in source units.

Run Blender with --factory-startup --python-exit-code 1 -P this file.
Fixtures never open or modify the user's scene. Bone display size must not
change the head positions, rest pose, weights, or armature object scale.
"""
import importlib
import sys
import types
from pathlib import Path

import bpy
from mathutils import Matrix

# Load just the helper so tests do not depend on optional add-on services.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("MIMIBlender")
package.__path__ = [str(ROOT)]
sys.modules["MIMIBlender"] = package
helper = importlib.import_module("MIMIBlender.utils.skeleton_helper").SkeletonHelper


def character(unit):
    # Identical physical geometry, represented in metres or centimetres.
    rows = []
    for index, (name, height, length) in enumerate([
        ("root", 0.0, 0.86), ("pelvis", 0.86, 0.064), ("spine", 0.924, 0.21),
    ]):
        rest = Matrix.Identity(4)
        rest.translation.z = height * unit
        rows.append({"Name": name, "Parent": index - 1,
                     "Rest": [value for row in rest for value in row],
                     "Length": length * unit})
    return {"Name": "UnitsFixture", "Bones": rows}


# Explicit lengths are authoritative, even when larger than one source unit.
for unit, scale in [(1.0, 1.0), (100.0, 0.01)]:
    fixture = character(unit)
    armature, _, _ = helper.build_armature(fixture, "BONE_TO_GROUP", space_scale=scale, space_rotation_z=180.0)
    for bone, source in zip(armature.data.bones, fixture["Bones"]):
        assert abs(bone.length - source["Length"] * scale) < 1e-5
        assert abs(bone.head_local.z - source["Rest"][11] * scale) < 1e-5
    # Bake units into rest geometry, never into object scale.
    assert tuple(armature.scale) == (1.0, 1.0, 1.0)

# Legacy sidecars without Length must infer lengths without a one-unit cap.
legacy = character(100.0)
for bone in legacy["Bones"]:
    bone.pop("Length")
lengths = helper._bone_lengths(legacy["Bones"])
assert abs(lengths[0] - 86.0) < 1e-4
assert abs(lengths[1] - 6.4) < 1e-4
assert abs(lengths[2] - 6.4 * 0.6) < 1e-4
# A recovery mesh has no component identity. Preserve it without an invalid
# armature modifier; the real component remains bound and its groups resolve.
import json

objects = []
for name in ["units-Component 0.Part", "units-WholeBuffer"]:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.vertex_groups.new(name="0").add([0, 1, 2], 1.0, 'REPLACE')
    objects.append(obj)
fixture = character(100.0)
fixture["Id"] = "units"
folder = ROOT / "tmp"
folder.mkdir(exist_ok=True)
sidecar = folder / "skeleton_units_test.json"
sidecar.write_text(json.dumps({
    "Space": {"Scale": 0.01}, "Characters": [fixture],
    "DrawIBs": [{"DrawIB": "units", "CharacterId": "units", "Components": [
        {"ComponentIndex": 0, "BoneMap": {"0": "root"}},
    ]}],
}), encoding="utf-8")
summary = helper.apply_groups("BONE_TO_GROUP", {"units": objects}, str(sidecar))
assert "1 meshes" in summary
assert objects[0].vertex_groups.get("root") is not None
assert any(mod.type == 'ARMATURE' for mod in objects[0].modifiers)
assert not any(mod.type == 'ARMATURE' for mod in objects[1].modifiers)
assert objects[1].parent is None
assert len(objects[1].data.polygons) == 1
print("PASS: source-unit lengths and component-only binding")
