"""Headless checks for the rest orientation of a rebuilt armature.

Run Blender with ``--factory-startup --python-exit-code 1 -P this file``.

Why this fixture exists
-----------------------
The skeleton pack stores a full rest matrix per bone (row-major, translation in
the fourth column), and ``skeleton.json`` copies it verbatim. The rebuilt
armature must reproduce that frame: head position, bone direction and roll.

Blender 5.2 creates an edit bone with **zero length**. Assigning
``EditBone.matrix`` to such a bone only stores the translation: head and tail
stay on one point, so the rotation never reaches the bone, and the later
``length`` assignment grows it along Blender's fallback +Z axis. Every imported
bone then pointed straight up while the heads stayed correct - the rig looked
like a field of vertical spikes. The old tests only compared head positions and
used identity rotations, so nothing caught it.

The fixture below uses genuinely rotated rest matrices (including roll) and
checks head, direction and the roll axis for the three frames the helper
supports: as stored, mirrored (``S M S``) and a scaled/rotated importer space.
"""
import importlib
import sys
import types
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

# Load just the helper so tests do not depend on optional add-on services.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("MIMIBlender")
package.__path__ = [str(ROOT)]
sys.modules["MIMIBlender"] = package
helper = importlib.import_module("MIMIBlender.utils.skeleton_helper").SkeletonHelper


def rest(translation, rotation_euler=(0.0, 0.0, 0.0)):
    """Row-major rest matrix of a bone: translation plus an XYZ rotation."""
    matrix = Matrix.Translation(Vector(translation)) @ Euler(rotation_euler, "XYZ").to_matrix().to_4x4()
    return matrix, [value for row in matrix for value in row]


FIXTURE = {
    "Id": "orientationcase",
    "Name": "OrientationCase",
    "Bones": [
        # Bone pointing up with an explicit roll around its own axis.
        {"Name": "root", "Parent": -1, "Length": 0.2,
         "Rest": rest((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))[1]},
        # Bone pointing along -Y (a ZZZ pelvis): the case that used to become +Z.
        {"Name": "pelvis", "Parent": 0, "Length": 0.25,
         "Rest": rest((0.0, 0.0, 0.9), (-1.5707963, 0.0, 0.0))[1]},
        # Bone pointing along +X with a 35 degree roll: direction plus roll.
        {"Name": "arm", "Parent": 1, "Length": 0.3,
         "Rest": rest((0.3, 0.0, 1.2), (0.6108652, 0.0, 1.5707963))[1]},
        # Diagonal bone, rolled the other way, with a non-zero head offset.
        {"Name": "leg", "Parent": 1, "Length": 0.4,
         "Rest": rest((-0.1, 0.05, 0.8), (2.0943951, 0.5235988, -0.7853982))[1]},
    ],
}


def expected_matrix(source, mirror_x, space_scale, space_rotation_z):
    """The frame the helper documents, rebuilt independently of its code."""
    matrix = Matrix([source["Rest"][0:4], source["Rest"][4:8],
                     source["Rest"][8:12], source["Rest"][12:16]])
    if mirror_x:
        reflection = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
        matrix = reflection @ matrix @ reflection
    if abs(space_rotation_z) > 1e-9:
        matrix = Matrix.Rotation(space_rotation_z * 3.141592653589793 / 180.0, 4, "Z") @ matrix
    if abs(space_scale - 1.0) > 1e-9:
        matrix = Matrix.Scale(space_scale, 4) @ matrix
    return matrix


def check_case(label, source, mirror_x, space_scale, space_rotation_z):
    fixture = {"Id": "orientationcase_" + label.replace(" ", "_"), "Bones": source}
    armature, created, _ = helper.build_armature(
        fixture,
        space_scale=space_scale,
        space_rotation_z=space_rotation_z,
        mirror_x=mirror_x,
        collection=bpy.context.scene.collection,
    )
    assert len(created) == len(source), "%s: %d bones built, expected %d" % (
        label, len(created), len(source))
    data = armature.data
    # The helper converts the source unit through the importer space (WWMI 0.01).
    scale_factor = space_scale
    # Display length is decided from geometry (an explicit ``Length`` is only
    # trusted near the child distance), independently of the rest rotation.
    display_lengths = helper._bone_lengths(source)

    for index, bone_data in enumerate(source):
        bone = data.bones[created[index]]
        wanted = expected_matrix(bone_data, mirror_x, space_scale, space_rotation_z)
        head = Vector(bone.head_local)
        assert (head - wanted.translation).length < 1e-5, (
            "%s/%s: head %s, expected %s" % (label, bone.name, tuple(head), tuple(wanted.translation)))

        actual = Matrix(bone.matrix_local).to_3x3()
        target = wanted.to_3x3()
        for axis in range(3):
            difference = (actual.col[axis].normalized() - target.col[axis].normalized()).length
            assert difference < 1e-4, (
                "%s/%s: rest axis %d is %s, expected %s (direction/roll lost)"
                % (label, bone.name, axis, tuple(actual.col[axis].normalized()),
                   tuple(target.col[axis].normalized())))

        direction = (Vector(bone.tail_local) - head).normalized()
        assert (direction - target.col[1].normalized()).length < 1e-4, (
            "%s/%s: bone points %s, expected %s" % (
                label, bone.name, tuple(direction), tuple(target.col[1].normalized())))
        assert abs(bone.length - display_lengths[index] * scale_factor) < 1e-4, (
            "%s/%s: length %.5f, expected %.5f" % (
                label, bone.name, bone.length, display_lengths[index] * scale_factor))

    # The regression itself: only a bone whose stored axis really is vertical
    # may end up vertical. Before the fix all four did.
    vertical = [
        bone.name for bone in data.bones
        if abs((Vector(bone.tail_local) - Vector(bone.head_local)).normalized().z) > 0.999
    ]
    stored_vertical = [
        bone_data["Name"] for bone_data in source
        if abs(expected_matrix(bone_data, mirror_x, space_scale, space_rotation_z)
               .to_3x3().col[1].normalized().z) > 0.999
    ]
    assert sorted(vertical) == sorted(stored_vertical), (
        "%s: vertical bones %s, the stored rig only has %s"
        % (label, vertical, stored_vertical))
    print("PASS: %s (%d bones)" % (label, len(data.bones)))
    bpy.data.objects.remove(armature, do_unlink=True)


check_case("stored frame", FIXTURE["Bones"], False, 1.0, 0.0)
check_case("mirrored frame", FIXTURE["Bones"], True, 1.0, 0.0)
check_case("importer space", FIXTURE["Bones"], False, 0.01, 180.0)
check_case("mirrored importer space", FIXTURE["Bones"], True, 0.01, 180.0)

# A bone created from an identity matrix must point along +Y (Blender's rest
# axis), not +Z: this is the fallback direction that used to win.
identity = {"Id": "identitycase", "Bones": [
    {"Name": "only", "Parent": -1, "Length": 0.5, "Rest": [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]},
]}
armature, created, _ = helper.build_armature(identity, collection=bpy.context.scene.collection)
bone = armature.data.bones[created[0]]
direction = (Vector(bone.tail_local) - Vector(bone.head_local)).normalized()
assert (direction - Vector((0.0, 1.0, 0.0))).length < 1e-4, tuple(direction)
assert abs(bone.length - 0.5) < 1e-5, bone.length
print("PASS: identity rest matrix keeps Blender's +Y bone axis")
bpy.data.objects.remove(armature, do_unlink=True)

print("PASS: skeleton rest orientation, roll and display length")
