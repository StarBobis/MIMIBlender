"""Visible incremental mesh edits with independent recoverable checkpoints.

The original scene object keeps its identity, so existing blueprint/skeleton
references remain valid when the user hands an in-progress model to AI.
Edits stage on a private mesh/object copy and commit only after full validation.
"""
# Mesh edit ownership:
# - The target object and its current revision are explicit.
# - Existing shared mesh data is never modified in place by the AI edit.
# - Checkpoint meshes are independent copies, retained with fake users.
# - The scene object identity, parent and modifiers remain unchanged.
# - Vertex/UV/key edits validate all indices before committing a staged mesh.
# - Bone weights use named object vertex groups and finite bounded weights.
# - Shape keys stage on copied data, not on the user's original key blocks.
# - A failed edit discards only its uncommitted staging object/mesh.
# - Restoration creates a new checkpoint of current work before restoring older data.
# - Checkpoints are not overwritten when another user/AI edit occurs.
# - Object/Edit/Pose mode ownership is never forcibly changed.
# - Existing blueprints keep referencing the same visible edited object.
# - This API edits data, not caller-provided Python expressions.
# - Scene presentation is real and may be deferred explicitly for a batch.
# - No files, game processes or original extraction buffers are modified.
# - Checkpoint limits are explicit rather than silently deleting history.
import json
from pathlib import Path
import uuid

import bpy

from .contract import AutomationError, validate
from .inspection import object_state
from .preservation import object_signature
from .presentation import desktop_window, present_objects, redraw


HISTORY_KEY = "mimi_ai_mesh_history"


def require_mesh(name, editing=False):
    """Resolve a real current-scene target without implicit selection fallback."""
    desktop_window()
    obj = bpy.context.scene.objects.get(name)
    if obj is None or obj.type != "MESH":
        raise AutomationError("NOT_FOUND", "Current-scene mesh object was not found", {"object": name})
    if editing and (bpy.context.mode != "OBJECT" or obj.name not in bpy.context.view_layer.objects):
        raise AutomationError("USER_EDIT_IN_PROGRESS", "Finish current edit/pose work before an AI mesh transaction")
    if editing and not getattr(obj, "is_editable", obj.library is None):
        raise AutomationError("READ_ONLY_OBJECT", "Make the linked object editable before an AI mesh transaction")
    bpy.context.view_layer.update()
    return obj


def history(obj):
    """Read checkpoint metadata without changing source mesh/user selection."""
    try:
        entries = json.loads(obj.get(HISTORY_KEY, "[]"))
    except (TypeError, ValueError) as error:
        raise AutomationError("INVALID_HISTORY", "Mesh checkpoint metadata is invalid") from error
    if not isinstance(entries, list) or not all(isinstance(item, dict) and {"id", "mesh", "groups", "matrix", "rotation_mode"}.issubset(item) for item in entries):
        raise AutomationError("INVALID_HISTORY", "Checkpoint history must be a list of complete records")
    validate(entries, {}, "history")
    return entries


def check_revision(obj, expected):
    """Reject a stale AI observation before allocating any stage/checkpoint."""
    actual = object_signature(obj)
    if expected != actual:
        raise AutomationError("STALE_REVISION", "User mesh changed after the caller's observation", {"current_revision": actual})


def groups_state(obj):
    """Group names are object-owned while sparse weight indices live in the mesh."""
    return [{"name": group.name, "locked": group.lock_weight} for group in obj.vertex_groups]


def checkpoint(obj):
    """Retain an independent recoverable pre-edit mesh and group/transform state."""
    entries = history(obj)
    if len(entries) >= 32:
        raise AutomationError("CHECKPOINT_LIMIT", "Preserve/save older mesh history before creating more than 32 checkpoints")
    identifier = uuid.uuid4().hex
    backup = obj.data.copy()
    backup.name = "ai-checkpoint-" + identifier
    backup["mimi_ai_checkpoint"] = identifier
    backup.use_fake_user = True
    record = {"id": identifier, "mesh": backup.name, "groups": groups_state(obj),
              "matrix": [list(row) for row in obj.matrix_world], "rotation_mode": obj.rotation_mode}
    entries.append(record)
    obj[HISTORY_KEY] = json.dumps(entries, sort_keys=True)
    return record


def restore_groups(obj, definitions, weights):
    """Restore names and exact weights on new mesh data, never the checkpoint."""
    obj.vertex_groups.clear()
    for item in definitions:
        group = obj.vertex_groups.new(name=item["name"])
        group.lock_weight = item["locked"]
    modes = [item.identifier for item in bpy.types.VertexGroup.bl_rna.functions["add"].parameters["type"].enum_items]
    replace = next(item for item in modes if item == "REPLACE")
    for group_index, values in weights.items():
        for weight, indices in values.items():
            obj.vertex_groups[group_index].add(indices, weight, replace)


def weights_state(mesh):
    """Batch equal group/weight assignments while retaining every sparse member."""
    groups = {}
    for vertex in mesh.vertices:
        for member in vertex.groups:
            groups.setdefault(member.group, {}).setdefault(member.weight, []).append(vertex.index)
    return groups


def set_coordinates(collection, entries, field):
    """Check target indices and numeric dimensions before staging coordinate edits."""
    seen = set()
    for item in entries:
        index = item["index"]
        if index >= len(collection) or index in seen:
            raise AutomationError("INVALID_INDEX", "Coordinate edit index is missing or repeated", {"index": index})
        seen.add(index)
        setattr(collection[index], field, item["value"])


def apply_patch(stage, params):
    """Apply only explicitly supported data edits to the disposable stage."""
    mesh = stage.data
    if params.get("vertices"):
        if mesh.shape_keys:
            raise AutomationError("SHAPE_KEY_TARGET_REQUIRED", "Edit the Basis/named shape key explicitly when keys exist")
        set_coordinates(mesh.vertices, params["vertices"], "co")
    modes = [item.identifier for item in bpy.types.VertexGroup.bl_rna.functions["add"].parameters["type"].enum_items]
    replace = next(item for item in modes if item == "REPLACE")
    for item in params.get("weights", []):
        group = stage.vertex_groups.get(item["group"]) or stage.vertex_groups.new(name=item["group"])
        if group.lock_weight:
            raise AutomationError("LOCKED_GROUP", "Unlock the targeted vertex group explicitly before editing weights", {"group": group.name})
        for value in item["values"]:
            if value["index"] >= len(mesh.vertices):
                raise AutomationError("INVALID_INDEX", "Weight edit vertex index is out of range")
            if value["weight"] == 0:
                group.remove([value["index"]])
            else:
                group.add([value["index"]], value["weight"], replace)
    for item in params.get("uvs", []):
        layer = mesh.uv_layers.get(item["layer"])
        if layer is None:
            if not item.get("create", False):
                raise AutomationError("NOT_FOUND", "UV layer was not found", {"layer": item["layer"]})
            layer = mesh.uv_layers.new(name=item["layer"])
        set_coordinates(layer.data, item["values"], "uv")
    for item in params.get("shape_keys", []):
        if mesh.shape_keys is None:
            stage.shape_key_add(name="Basis")
        key = mesh.shape_keys.key_blocks.get(item["name"])
        if key is None:
            if not item.get("create", False):
                raise AutomationError("NOT_FOUND", "Shape key was not found", {"key": item["name"]})
            key = stage.shape_key_add(name=item["name"])
        set_coordinates(key.data, item.get("vertices", []), "co")
        if "value" in item:
            if not key.slider_min <= item["value"] <= key.slider_max:
                raise AutomationError("INVALID_ARGUMENT", "Shape value is outside the key's native slider range")
            key.value = item["value"]
        if "mute" in item:
            key.mute = item["mute"]
    transform = params.get("transform", {})
    if "rotation_euler" in transform and stage.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
        raise AutomationError("ROTATION_MODE_REQUIRED", "Euler edits require an Euler-mode object; do not reinterpret quaternion/axis-angle work")
    for field in ("location", "rotation_euler", "scale"):
        if field in transform:
            setattr(stage, field, transform[field])
    mesh.update()


def reset_group_definitions(obj, definitions):
    """Reset object-owned group names on disposable data before restoring old mesh."""
    obj.vertex_groups.clear()
    for item in definitions:
        group = obj.vertex_groups.new(name=item["name"])
        group.lock_weight = item["locked"]


def rollback_commit(obj, original_data, saved):
    """Restore old object metadata while avoiding writes to shared original data."""
    from mathutils import Matrix
    # Clear/remap groups only on the rejected newly assigned mesh.
    # Assign the original shared mesh after group definitions match again.
    reset_group_definitions(obj, saved["groups"])
    obj.data = original_data
    obj.rotation_mode = saved["rotation_mode"]
    obj.matrix_world = Matrix(saved["matrix"])


def stage_geometry(obj, stage, params):
    """Rebuild explicit topology only when destructive channel changes are acknowledged."""
    geometry = params.get("geometry")
    if not geometry:
        return obj.data.copy()
    if obj.data.shape_keys and not params.get("drop_shape_keys", False):
        raise AutomationError("SHAPE_KEYS_REQUIRE_ACK", "Topology replacement requires explicit shape-key replacement acknowledgement")
    raw = [attribute.name for attribute in obj.data.attributes if attribute.name.startswith(("3DMigoto:", "SSMT:", "_ssmt"))]
    if raw and not params.get("drop_raw_attributes", False):
        raise AutomationError("RAW_CHANNELS_REQUIRE_ACK", "New topology cannot silently discard game-owned raw channels", {"attributes": raw})
    if obj.vertex_groups and not params.get("weights"):
        raise AutomationError("WEIGHTS_REQUIRED", "Replacement geometry requires explicit weights for this skinned object")
    if obj.data.uv_layers and not params.get("uvs"):
        raise AutomationError("UVS_REQUIRED", "Replacement geometry requires explicit UV data")
    positions, faces = geometry["positions"], geometry["faces"]
    if any(index >= len(positions) for face in faces for index in face):
        raise AutomationError("INVALID_INDEX", "Replacement face references an out-of-range vertex")
    mesh = bpy.data.meshes.new("ai-replacement-" + uuid.uuid4().hex)
    try:
        mesh.from_pydata(positions, [], faces)
        mesh.update()
        for material in obj.data.materials:
            mesh.materials.append(material)
        return mesh
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise


def mesh_patch(params):
    """Commit a typed data edit to the same visible object after staging succeeds."""
    obj = require_mesh(params["object"], editing=True)  # Current visible target, never an inferred selection.
    check_revision(obj, params["revision"])  # User changes invalidate old AI observations.
    if not any(params.get(key) for key in ("geometry", "vertices", "weights", "uvs", "shape_keys", "transform")):  # Do not create history for an empty request.
        raise AutomationError("EMPTY_EDIT", "Mesh transaction contains no edits")
    original_data = obj.data  # Shared original data stays untouched until a successful swap.
    stage = obj.copy()  # Stage object-owned vertex groups independently as well.
    staged_mesh = None  # Geometry preflight may fail before allocating mesh data.
    saved = None  # A checkpoint is created only after staged edits validate.
    assigned = False  # Track whether rollback must restore the original object data link.
    committed = False  # Success includes state serialization and real presentation.
    try:
        stage.data = stage_geometry(obj, stage, params)  # New topology needs explicit source-channel acknowledgements.
        staged_mesh = stage.data  # Retain private data identity for failure cleanup.
        apply_patch(stage, params)  # Original mesh coordinates, keys and weights remain unchanged here.
        definitions = groups_state(stage)  # Group names/locks belong to the staged object.
        weights = weights_state(staged_mesh)  # Capture sparse indices before rebuilding original group definitions.
        saved = checkpoint(obj)  # Independent fake-user backup survives manual user/AI continuation.
        obj.data = staged_mesh  # The same scene object keeps its blueprint/skeleton identity.
        assigned = True  # Any later failure must restore the previous shared data link.
        restore_groups(obj, definitions, weights)  # Rebuild only the newly assigned private data's weights.
        obj.location = stage.location  # Local transforms preserve unchanged parent relationships.
        obj.rotation_euler = stage.rotation_euler  # Quaternion reinterpretation was rejected during staging.
        obj.scale = stage.scale  # Scale changes are explicit, not import-axis compensation.
        # Remove the staging object before UI redraw/UUID integrity callbacks.
        bpy.data.objects.remove(stage)  # Only this disposable unlinked object is removed.
        stage = None  # Prevent duplicate cleanup of an already removed staging identity.
        bpy.context.view_layer.update()  # The real viewport sees updated data/transforms.
        shown = present_objects([obj.name]) if params.get("present", True) else {"visible": False, "deferred": True}  # UI failure still belongs to the transaction.
        redraw(bpy.context.window)  # Request redraw of actual desktop areas.
        result = {"object": obj.name, "revision": object_signature(obj), "checkpoint": saved["id"],  # Publish a fresh actual data token.
                  "state": object_state(obj), "presentation": shown}
        committed = True  # All requested data and presentation steps succeeded.
        return result  # The user can resume editing the same object immediately.
    except Exception:  # Never leave partially assigned data on an explicit failed request.
        if assigned and saved is not None:  # Earlier staging-only failures do not touch the original.
            rollback_commit(obj, original_data, saved)  # Preserve original shared users and object group metadata.
        raise  # Dispatcher returns the structured original error.
    finally:
        if stage is not None:  # Release only an uncommitted temporary object.
            bpy.data.objects.remove(stage)
        if not committed and staged_mesh is not None and staged_mesh.users == 0:  # Never remove user/backup data.
            bpy.data.meshes.remove(staged_mesh)


def mesh_restore(params):
    """Restore old data while checkpointing the user's current version first."""
    obj = require_mesh(params["object"], editing=True)
    check_revision(obj, params["revision"])
    saved = next((item for item in history(obj) if item["id"] == params["checkpoint"]), None)
    backup = bpy.data.meshes.get(saved["mesh"]) if saved else None
    if saved is None or backup is None or backup.get("mimi_ai_checkpoint") != saved["id"]:
        raise AutomationError("CHECKPOINT_NOT_FOUND", "Requested independent mesh checkpoint was not found")
    from mathutils import Matrix
    original_data = obj.data  # Current manual/AI work remains available during recovery.
    current = checkpoint(obj)  # Restore itself is versioned, not destructive history replacement.
    mesh = bpy.data.meshes[saved["mesh"]].copy()  # Never mutate the independently retained checkpoint.
    weights = weights_state(mesh)  # Group membership must match the saved object definitions.
    assigned = False  # Cleanup cannot unlink original data before an actual swap.
    committed = False  # Presentation and token generation are part of recovery success.
    try:
        obj.data = mesh  # Object identity and existing scene/blueprint references remain stable.
        assigned = True  # Later errors can safely restore current work.
        restore_groups(obj, saved["groups"], weights)  # Remap groups on copied checkpoint data only.
        obj.rotation_mode = saved["rotation_mode"]  # Use the original observed native rotation representation.
        obj.matrix_world = Matrix(saved["matrix"])  # Preserve parent-relative world placement accurately.
        bpy.context.view_layer.update()  # Update the actual desktop dependency graph.
        shown = present_objects([obj.name]) if params.get("present", True) else {"visible": False, "deferred": True}  # No hidden processing scene.
        result = {"object": obj.name, "revision": object_signature(obj), "checkpoint": current["id"], "presentation": shown}  # Return the new current observation.
        committed = True  # Recovery is accepted only after every step completed.
        return result  # Both old and restored-away versions remain checkpointed.
    except Exception:  # A failed visible restore cannot replace the user's latest work.
        if assigned:
            rollback_commit(obj, original_data, current)  # Rollback does not write into shared old data.
        raise  # Preserve stable dispatcher failure handling.
    finally:
        if not committed and mesh.users == 0:  # Discard only the newly allocated rejected copy.
            bpy.data.meshes.remove(mesh)


def mesh_inspect(params):
    """Return current data/revision and a paginated editable local-space vertex view."""
    obj = require_mesh(params["object"])
    offset, limit = params.get("offset", 0), params.get("limit", 50)
    end = min(offset + limit, len(obj.data.vertices))
    return {"object": obj.name, "revision": object_signature(obj), "state": object_state(obj),
            "vertices": [{"index": vertex.index, "value": list(vertex.co),
                          "weights": [{"group": obj.vertex_groups[item.group].name, "weight": item.weight} for item in vertex.groups]}
                         for vertex in obj.data.vertices[offset:end]],
            "total_vertices": len(obj.data.vertices), "next_offset": end if end < len(obj.data.vertices) else None,
            "checkpoints": history(obj), "coordinate_space": "mesh_local"}


HANDLERS = {"mesh.inspect": mesh_inspect, "mesh.patch": mesh_patch, "mesh.restore": mesh_restore}
