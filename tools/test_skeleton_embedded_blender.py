"""Headless checks for the skeleton block embedded in each SubmeshJson.

Run Blender with ``--factory-startup --python-exit-code 1 -P this file``.

Why this fixture exists
-----------------------
A workspace or reverse output can mix LODs, characters and bone palettes, so a
single workspace-level skeleton.json cannot describe all of them. The desktop
app now writes a ``Skeleton`` block into every SubmeshJson and the add-on builds
one armature per block ``Hash``:

* two DrawIBs with the same skeleton share one armature (no duplicate rigs);
* a DrawIB with a different skeleton gets its own armature;
* each DrawIB binds through its own ``BoneMap``;
* the block's ``Space.MatchMirrorX`` and the import mode still decide whether
  the armature is reflected.
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
    matrix = Matrix.Identity(4)
    matrix.translation.x = x
    return [value for row in matrix for value in row]


def block(hash_value, character_id, bones, bone_map, match_mirror_x=False, naming="groupToBone"):
    return {
        "Version": 1,
        "Hash": hash_value,
        "CharacterId": character_id,
        "CharacterName": character_id.title(),
        "NamingMode": naming,
        "Space": {"Scale": 1.0, "RotationZ": 0.0, "MatchMirrorX": match_mirror_x},
        "Bones": [
            {"Name": name, "Parent": -1, "Rest": rest_matrix(x), "Length": 0.2}
            for name, x in bones
        ],
        "BoneMap": bone_map,
    }


def make_mesh(name, group_names):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for index, group in enumerate(group_names):
        obj.vertex_groups.new(name=group).add([index % 3], 1.0, "REPLACE")
    return obj


first = make_mesh("hashA-Component 0.body", ["0", "1"])
second = make_mesh("hashB-Component 0.cloth", ["0", "1"])
third = make_mesh("hashC-Component 0.prop", ["0", "1"])

shared = block(
    "a" * 64,
    "sharedrig",
    [("Bip001 L Hand", -0.5), ("Bip001 R Hand", 0.5)],
    {"0": "Bip001 L Hand", "1": "Bip001 R Hand"},
)
other = block(
    "b" * 64,
    "otherrig",
    [("Prop Root", -0.3), ("Prop Tip", 0.3)],
    {"0": "Prop Root", "1": "Prop Tip"},
    # A block from the short-lived mirror-matched build: the armature must be
    # reflected even in the default (unreflected) import.
    match_mirror_x=True,
)

summary = SkeletonHelper.apply_groups(
    "SIDECAR",
    {"hashA": [first], "hashB": [second], "hashC": [third]},
    "",
    "NONE",
    import_mirror=False,
    skeletons={"hashA": shared, "hashB": shared, "hashC": other},
)
print("SUMMARY:", summary)

armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
assert len(armatures) == 2, "one armature per skeleton hash, got %d" % len(armatures)

# The two DrawIBs of the shared rig must use one armature, the other one its own.
shared_armatures = [
    armature for armature in armatures
    if {bone.name for bone in armature.data.bones} == {"Bip001 L Hand", "Bip001 R Hand"}
]
assert len(shared_armatures) == 1, "the shared hash must produce exactly one armature"
shared_armature = shared_armatures[0]
for mesh in (first, second):
    modifiers = [mod for mod in mesh.modifiers if mod.type == "ARMATURE"]
    assert len(modifiers) == 1 and modifiers[0].object == shared_armature, mesh.name + " not bound to the shared rig"
    assert {group.name for group in mesh.vertex_groups} == {"Bip001 L Hand", "Bip001 R Hand"}

# The same bones in the default import keep the block's placement.
positions = {bone.name: bone.head_local.x for bone in shared_armature.data.bones}
assert abs(positions["Bip001 L Hand"] + 0.5) < 1e-5, positions
assert abs(positions["Bip001 R Hand"] - 0.5) < 1e-5, positions

# The second rig is its own armature and its MatchMirrorX reflection is applied.
other_armatures = [armature for armature in armatures if armature is not shared_armature]
assert len(other_armatures) == 1
other_positions = {bone.name: bone.head_local.x for bone in other_armatures[0].data.bones}
assert abs(other_positions["Prop Root"] - 0.3) < 1e-5, other_positions
assert abs(other_positions["Prop Tip"] + 0.3) < 1e-5, other_positions
assert any(mod.type == "ARMATURE" and mod.object == other_armatures[0] for mod in third.modifiers)

# The block decides the naming mode: no sidecar file is needed at all.
assert not [group for group in first.vertex_groups if group.name.isdigit()]

print("PASS: per-SubmeshJson skeletons share or split armatures by hash")
