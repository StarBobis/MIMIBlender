"""Shared helpers for timeline baking: sensible frame-range defaults and
static-tail detection.

A dynamic mod timeline replays its baked frames forever. If the baked range
extends past the last keyed pose, the trailing frames all hold the same pose
and the animation appears to freeze for a while at the end of every loop.
These helpers let the bake operators prefill the keyed range and warn about
such trailing holds without ever silently changing the user's data.
"""
import array
import hashlib
import math


def detect_animated_frame_range(source_obj):
    """Return the union (start, end) of keyed frame ranges, or None.

    The bake operators evaluate the object through the depsgraph, so any
    driver (object transform, shape key values, armature pose) shows up in
    the sampled meshes. Prefill the bake dialog with the union of the
    relevant action ranges instead of the scene range, because the scene
    range often contains padding past the last keyframe; baking that padding
    freezes the animation at the end of every loop.

    Only plain actions are considered. NLA-only setups fall back to the
    scene range like before.
    """
    if source_obj is None:
        return None
    ranges = []

    # Object level animation: location/rotation/scale and constraint keys.
    obj_action = getattr(getattr(source_obj, "animation_data", None), "action", None)
    if obj_action is not None:
        ranges.append(obj_action.frame_range)

    # Shape key value animation lives on the Key datablock, not the object.
    shape_keys = getattr(getattr(source_obj, "data", None), "shape_keys", None)
    key_action = getattr(getattr(shape_keys, "animation_data", None), "action", None)
    if key_action is not None:
        ranges.append(key_action.frame_range)

    # Armature driven pose deformation (find_armature exists on objects).
    find_armature = getattr(source_obj, "find_armature", None)
    armature = find_armature() if callable(find_armature) else None
    arm_action = getattr(getattr(armature, "animation_data", None), "action", None)
    if arm_action is not None:
        ranges.append(arm_action.frame_range)

    if not ranges:
        return None
    # Keyframes may sit on fractional frames; widen out to whole frames so
    # the first and last keyed poses are always included in the bake.
    start = math.floor(min(frame_range[0] for frame_range in ranges))
    end = math.ceil(max(frame_range[1] for frame_range in ranges))
    return int(start), int(end)


def count_trailing_repeats(values):
    """Count how many trailing items repeat the value before them.

    [a, b, c, c, c] returns 2: the last two items hold the same value as
    their predecessor, so a timeline built from these tokens freezes for
    two extra steps at the end of every loop. Works for any comparable
    values (floats, strings, bytes).
    """
    repeats = 0
    for index in range(len(values) - 1, 0, -1):
        if values[index] != values[index - 1]:
            break
        repeats += 1
    return repeats


def trailing_static_frame_info(frame_tokens, frame_numbers, fps):
    """Describe a trailing static hold, or return None when there is none.

    frame_tokens[i] is a hashable summary of the baked content of frame i
    (mesh content hash or sampled shape weight). frame_numbers[i] is the
    Blender frame number shown to the user. Returns a dict with the number
    of held frames, the freeze duration in seconds and the last frame
    number that still contains unique content.
    """
    held_frames = count_trailing_repeats(frame_tokens)
    if held_frames <= 0:
        return None
    last_unique_index = len(frame_tokens) - held_frames - 1
    return {
        "held_frames": held_frames,
        "held_seconds": held_frames / fps,
        "last_unique_frame": frame_numbers[last_unique_index],
    }


def mesh_content_hash(mesh):
    """Hash the vertex positions of a baked mesh.

    The bake already applied world transforms to the mesh data, so equal
    hashes mean the rendered pose is identical. Vertex positions are enough:
    a held pose repeats exactly the same coordinates. Hashing is far cheaper
    than comparing whole buffers and keeps memory flat for the 1000 frame
    bake cap.
    """
    vertex_count = len(mesh.vertices)
    coords = array.array("f", [0.0]) * (vertex_count * 3)
    if vertex_count:
        mesh.vertices.foreach_get("co", coords)
    digest = hashlib.md5()
    digest.update(str(vertex_count).encode("ascii"))
    digest.update(coords.tobytes())
    return digest.hexdigest()
