"""Versioned shader-input and existing-image edits on one visible object slot."""
# Material ownership:
# - Target the current-scene object and exact slot, never an implicit selection.
# - Shared materials and DATA-linked mesh slots are not mutated in place.
# - Copy the complete native shader graph; preserve all unrelated nodes/links.
# - Input sockets are addressed by native identifiers discovered by inspection.
# - Node names identify instances; node types identify shader behavior.
# - Existing image datablocks may be rebound but pixels/files are never rewritten.
# - Linked sockets require graph editing instead of silently ineffective defaults.
# - Keep an independent fake-user material checkpoint for every committed edit.
# - Restore also checkpoints current work before assigning an older private copy.
# - Recovery uses OBJECT overrides to keep other shared mesh users untouched.
# - Stale material/slot/object observations fail before creating a checkpoint.
# - User Edit/Pose/Paint modes are never forcibly exited.
# - Presentation failure restores the original slot link and material identity.
# - Retained checkpoint identity and content are checked before recovery.
# - This adapter preserves native shaders, not a claimed game shader reconstruction.
import hashlib
import json
import math
import uuid

import bpy

from .contract import AutomationError, validate
from .meshes import require_mesh
from .preservation import object_signature
from .presentation import present_objects, redraw


HISTORY = "mimi_ai_material_history"  # Object-owned recovery does not alter the shared mesh.


def scalar(value):
    """Serialize native socket values without exposing bpy pointers."""
    if isinstance(value, (str, bool, int, float)):
        return value  # The strict JSON validator rejects nonfinite scalar values later.
    try:
        return list(value)  # Native numeric arrays become finite JSON data only.
    except TypeError:
        return None  # Unsupported socket data is explicitly non-editable.


def material_state(material, visited=None):
    """Observe native shader nodes, values, links and image bindings by type."""
    nodes = []
    visited = set(visited or ())  # Recursive group references are bounded observations, never infinite traversal.
    tree = material.node_tree if material.use_nodes else None  # Do not enable nodes as an inspection side effect.
    if tree and tree.as_pointer() in visited:
        return {"recursive_group": tree.name}  # Retain identity without recursively evaluating a shader cycle.
    if tree:
        visited.add(tree.as_pointer())  # Sibling group instances may independently observe the same unchanged source.
        for node in tree.nodes:
            properties = {}  # Scalar native node parameters supplement socket values in revisions.
            for prop in node.bl_rna.properties:
                if not prop.is_readonly and prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
                    properties[prop.identifier] = scalar(getattr(node, prop.identifier))
            image = getattr(node, "image", None)  # Image identity/path is a binding observation, not pixel verification.
            group = getattr(node, "node_tree", None)  # Nested user shader edits must invalidate an older material token.
            from types import SimpleNamespace
            group_state = material_state(SimpleNamespace(name=group.name, use_nodes=True, node_tree=group), visited) if group else None
            nodes.append({"name": node.name, "type": node.type, "properties": properties,
                          "group": group_state,
                          "image": {"name": image.name, "path": image.filepath, "dirty": image.is_dirty,
                                    "colorspace": image.colorspace_settings.name, "alpha_mode": image.alpha_mode} if image else None,
                          "inputs": [{"identifier": item.identifier, "type": item.type, "linked": item.is_linked,
                                      "value": scalar(item.default_value) if hasattr(item, "default_value") else None}
                                     for item in node.inputs]})
    links = [[link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier]
             for link in tree.links] if tree else []  # Preserve exact native connections, including unedited channels.
    material_properties = {}  # Native render/material flags are user edits even when socket values are unchanged.
    if hasattr(material, "bl_rna"):
        for prop in material.bl_rna.properties:
            if not prop.is_readonly and prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
                material_properties[prop.identifier] = scalar(getattr(material, prop.identifier))
    state = {"name": material.name, "use_nodes": material.use_nodes, "properties": material_properties, "nodes": nodes, "links": links}
    validate(state, {}, "material")  # Never emit a nonfinite shader parameter as valid JSON.
    return state


def fingerprint(material):
    """Hash inspected native graph state, not a localized material display label."""
    return hashlib.sha256(json.dumps(material_state(material), sort_keys=True, allow_nan=False).encode()).hexdigest()


def target(params, editing=False):
    """Resolve one editable mesh slot without changing user selection or mode."""
    obj = require_mesh(params["object"], editing=editing)  # Existing visible mesh/mode guards remain authoritative.
    index = params["slot"]  # Slot indices are zero-based native object material-slot indices.
    if index >= len(obj.material_slots) or obj.material_slots[index].material is None:
        raise AutomationError("NOT_FOUND", "Material slot is missing or empty", {"slot": index})
    slot = obj.material_slots[index]  # DATA/OBJECT link mode is part of the revision-bearing target.
    revision = hashlib.sha256((object_signature(obj) + slot.link + fingerprint(slot.material)).encode()).hexdigest()
    if editing and params["revision"] != revision:
        raise AutomationError("STALE_REVISION", "User material or object changed after inspection", {"current_revision": revision})
    return obj, slot, revision  # No allocation occurs before stale-revision preflight passes.


def history(obj):
    """Read bounded material checkpoint records without changing them."""
    try:
        records = json.loads(obj.get(HISTORY, "[]"))
        validate(records, {}, "history")
        if not isinstance(records, list) or not all(isinstance(item, dict) and {"id", "slot", "material", "fingerprint"} <= set(item) for item in records):
            raise ValueError("Invalid material checkpoint structure")
        return records
    except (TypeError, ValueError) as error:
        raise AutomationError("INVALID_HISTORY", "Material checkpoint history is invalid") from error


def copy_material(material):
    """Retain independent nested shader groups, while preserving image bindings."""
    memo = {}  # One copied material retains aliasing between its own repeated group instances.
    def copy_group(group):
        if group.as_pointer() in memo:
            return memo[group.as_pointer()]  # Recursive group references cannot duplicate forever.
        copied = group.copy()
        copied.name = "ai-material-group-" + uuid.uuid4().hex
        memo[group.as_pointer()] = copied  # Register before walking nested references or cycles.
        for node in copied.nodes:
            nested = getattr(node, "node_tree", None)
            if nested:
                node.node_tree = copy_group(nested)  # User group edits cannot mutate retained checkpoint graphs.
        return copied
    copied = material.copy()  # Native material flags, links, animation and node values stay intact.
    if copied.node_tree:
        for node in copied.node_tree.nodes:
            group = getattr(node, "node_tree", None)
            if group:
                node.node_tree = copy_group(group)  # Restored current work cannot mutate old checkpoint groups either.
    return copied


def checkpoint(obj, index, material):
    """Retain a complete independent pre-edit native material graph."""
    records = history(obj)  # Corrupt metadata cannot select arbitrary user datablocks.
    if len(records) >= 32:
        raise AutomationError("CHECKPOINT_LIMIT", "Save older material recovery versions before adding more than 32 checkpoints")
    identifier = uuid.uuid4().hex  # Recovery identities are data, never Python attribute expressions.
    backup = copy_material(material)  # Shader graph and node values are independently copied.
    backup.name = "ai-material-checkpoint-" + identifier
    backup.use_fake_user = True  # Saving the user's blend retains the pre-edit shader version.
    backup["mimi_ai_material_checkpoint"] = identifier
    record = {"id": identifier, "slot": index, "material": backup.name, "fingerprint": fingerprint(backup)}
    records.append(record)
    obj[HISTORY] = json.dumps(records, sort_keys=True)  # Store only JSON identities and observations.
    return record


def apply(stage, params):
    """Edit existing unlinked socket defaults and native image-texture bindings."""
    if not stage.use_nodes or stage.node_tree is None:
        raise AutomationError("NODE_MATERIAL_REQUIRED", "Enable a native node material explicitly before shader-input edits")
    seen = set()  # Duplicate edits cannot depend on caller ordering to select the last value.
    for edit in params.get("inputs", []):
        node = stage.node_tree.nodes.get(edit["node"])  # Exact instance names are returned by material.inspect.
        socket = next((item for item in node.inputs if item.identifier == edit["socket"]), None) if node else None
        key = (edit["node"], edit["socket"])
        if socket is None or socket.is_linked or not hasattr(socket, "default_value") or key in seen:
            raise AutomationError("INVALID_SOCKET", "Socket is missing, linked, unsupported or repeated", {"node": edit["node"], "socket": edit["socket"]})
        seen.add(key)
        old, value = scalar(socket.default_value), edit["value"]  # Numeric shape is defined by actual native socket data.
        if isinstance(old, bool) or not isinstance(old, (int, float, list)):
            raise AutomationError("UNSUPPORTED_SOCKET", "Only numeric shader socket values are editable")
        if isinstance(old, list):
            valid = isinstance(value, list) and len(value) == len(old) and all(type(item) in {int, float} and math.isfinite(item) for item in value)
        else:
            valid = type(value) in {int, float} and math.isfinite(value)
        if not valid:
            raise AutomationError("INVALID_ARGUMENT", "Socket value must match its native finite numeric shape")
        socket.default_value = value  # Assignment occurs only on the private full material copy.
        actual = scalar(socket.default_value)  # Native RNA must not silently clamp the caller's requested value.
        expected_values = value if isinstance(value, list) else [value]
        actual_values = actual if isinstance(actual, list) else [actual]
        if not all(math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6) for a, b in zip(actual_values, expected_values)):
            raise AutomationError("INVALID_ARGUMENT", "Socket value was outside its native writable range")
    for edit in params.get("images", []):
        node = stage.node_tree.nodes.get(edit["node"])
        image = bpy.data.images.get(edit["image"])  # No file loading or pixel replacement is implicit in a binding edit.
        key = ("image", edit["node"])  # Repeated image targets cannot silently depend on caller ordering.
        if node is None or node.type != "TEX_IMAGE" or image is None or key in seen:
            raise AutomationError("INVALID_IMAGE_BINDING", "An existing native image-texture node and image are required without repeated targets")
        seen.add(key)
        node.image = image  # All other texture node parameters/links remain native and unchanged.


def commit(obj, slot, index, stage, present):
    """Swap one object-owned slot transactionally without editing shared DATA."""
    old_material, old_link = slot.material, slot.link  # Save original identity/link mode for exact failure rollback.
    saved = checkpoint(obj, index, old_material)  # The retained pre-edit version survives both later user and AI changes.
    try:
        links = [item.identifier for item in slot.bl_rna.properties["link"].enum_items]
        slot.link = next(item for item in links if item == "OBJECT")  # Never overwrite material slots on shared mesh data.
        slot.material = stage  # Blueprint/rig/object references remain intact.
        shown = present_objects([obj.name]) if present else {"visible": False, "deferred": True}
        _, _, revision = target({"object": obj.name, "slot": index})
        redraw(bpy.context.window)
        return {"object": obj.name, "slot": index, "revision": revision, "checkpoint": saved["id"], "presentation": shown}
    except Exception:
        slot.material = old_material  # Current OBJECT override is restored before reconnecting DATA mode.
        slot.link = old_link  # Failure restores exact original binding and leaves other shared users unchanged.
        raise


def material_inspect(params):
    """Report a revision-bearing native shader and available retained checkpoints."""
    obj, slot, revision = target(params)
    return {"object": obj.name, "slot": params["slot"], "link": slot.link, "revision": revision,
            "material": material_state(slot.material), "checkpoints": [item for item in history(obj) if item["slot"] == params["slot"]],
            "pixel_content_verified": False}  # Image binding observations do not certify pixel content or game rendering.


def material_patch(params):
    """Stage native shader edits, then visibly commit to the same scene object."""
    obj, slot, revision = target(params, editing=True)  # Reject user mode and stale state before staging.
    if not params.get("inputs") and not params.get("images"):
        raise AutomationError("EMPTY_EDIT", "Material transaction contains no edits")
    stage = copy_material(slot.material)  # Shared original material remains byte/state unchanged.
    stage.name = "ai-material-edit-" + uuid.uuid4().hex
    try:
        apply(stage, params)  # Invalid edits never reach the live slot.
        return commit(obj, slot, params["slot"], stage, params.get("present", True))
    except Exception:
        stage.use_fake_user = True  # Retain rejected AI-owned staging data instead of hard-deleting user data.
        raise


def material_restore(params):
    """Recover an independent checkpoint while retaining the current shader too."""
    obj, slot, revision = target(params, editing=True)
    record = next((item for item in history(obj) if item["id"] == params["checkpoint"] and item["slot"] == params["slot"]), None)
    backup = bpy.data.materials.get(record["material"]) if record else None
    if backup is None or backup.get("mimi_ai_material_checkpoint") != params["checkpoint"]:
        raise AutomationError("CHECKPOINT_NOT_FOUND", "Material checkpoint identity was not found")
    if fingerprint(backup) != record["fingerprint"]:
        raise AutomationError("CHECKPOINT_CHANGED", "Retained material checkpoint was manually changed; inspect it explicitly")
    stage = copy_material(backup)  # Restoring never assigns the mutable retained checkpoint itself.
    stage.name = "ai-material-restored-" + uuid.uuid4().hex
    return commit(obj, slot, params["slot"], stage, params.get("present", True))


HANDLERS = {"material.inspect": material_inspect, "material.patch": material_patch, "material.restore": material_restore}
