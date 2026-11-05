"""Live graph revision tokens for collaborative AI/user editing.

Tokens cover graph data rather than editor selection or viewport navigation.
A user may move the view while AI works, but a changed graph must invalidate a
previous read token before an AI copy-on-write patch can be constructed.
"""
# Revision semantics:
# - Tokens are session observations, not saved-file authenticity signatures.
# - Node identity, presentation properties and custom fields are covered.
# - Native row collections are covered beyond the inspection page size.
# - Socket names, identifiers and graph edges are part of the token.
# - Frame parent changes are graph edits and must invalidate the token.
# - Node selection is excluded so ordinary navigation does not cause conflicts.
# - Referenced custom-group contents are covered recursively.
# - Group recursion is represented explicitly rather than hanging the reader.
# - ID pointers use stable type/name identities, never memory addresses in JSON.
# - Collection and depth bounds reject oversized observations explicitly.
# - No geometry buffer is read by a blueprint revision token.
# - Geometry edits need their own object/mesh revision contract.
# - Hashing never creates UUID metadata or refreshes a node's object binding.
# - Existing callbacks may read host data, but no setter is invoked here.
# - Every scalar is finite JSON or an explicit unavailable marker.
# - A token must be reread after a successful graph mutation.
# - A token mismatch is a conflict, not permission to overwrite newer work.
# - The graph builder checks tokens before allocating a staging tree.
import hashlib
import json
import math

import bpy

from .contract import AutomationError


def value_state(value, depth=0):
    """Convert complete bounded custom RNA values into deterministic hash data."""
    if depth > 12:
        raise AutomationError("REVISION_TOO_LARGE", "Property revision nesting exceeds its bound")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"unavailable": "nonfinite"}
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, bpy.types.ID):
        return {"type": value.bl_rna.identifier, "name": value.name}
    if isinstance(value, bpy.types.PropertyGroup):
        return {prop.identifier: value_state(getattr(value, prop.identifier), depth + 1)
                for prop in value.bl_rna.properties if prop.identifier != "rna_type"}
    if isinstance(value, dict) or hasattr(value, "to_dict"):
        items = value.items() if isinstance(value, dict) else value.to_dict().items()
        return {str(key): value_state(item, depth + 1) for key, item in items}
    if hasattr(value, "__len__") and hasattr(value, "__iter__"):
        if len(value) > 10000:
            raise AutomationError("REVISION_TOO_LARGE", "Property collection exceeds the revision bound")
        return [value_state(item, depth + 1) for item in value]
    return {"unavailable": type(value).__name__}


def absolute_node_location(node):
    """Hash effective layout, not relative offsets changed by frame auto-fitting.

    Blender moves/resizes shrink-to-fit frames during the first desktop draw.
    Their child absolute positions remain the same and are the user-visible edit.
    """
    x, y = node.location
    parent = node.parent
    seen = {node.as_pointer()}
    while parent is not None:
        if parent.as_pointer() in seen or len(seen) > 32:
            raise AutomationError("FRAME_RECURSION", "Frame layout has invalid parent recursion")
        seen.add(parent.as_pointer())
        x += parent.location.x
        y += parent.location.y
        parent = parent.parent
    return [x, y]


def tree_state(tree, ancestors=()):
    """Read full graph data, including custom-group dependencies, without edits."""
    if tree.as_pointer() in ancestors:
        return {"recursive_group": tree.name}
    if len(ancestors) > 32 or len(tree.nodes) > 10000:
        raise AutomationError("REVISION_TOO_LARGE", "Blueprint exceeds revision bounds")
    # The base Node RNA contains UI and ownership fields that are not settings.
    # Custom fields and a small explicit presentation set define graph edits.
    base_fields = set(bpy.types.Node.bl_rna.properties.keys())
    nodes = []
    for node in sorted(tree.nodes, key=lambda item: item.name):
        properties = {}
        for prop in node.bl_rna.properties:
            if prop.identifier in base_fields:
                continue
            try:
                properties[prop.identifier] = value_state(getattr(node, prop.identifier))
            except AutomationError:
                raise
            except Exception:
                properties[prop.identifier] = {"unavailable": "context_required"}
        child = getattr(node, "node_tree", None)
        sockets = lambda values: [(socket.identifier, socket.name, socket.bl_idname) for socket in values]
        auto_frame = node.bl_idname == "NodeFrame" and getattr(node, "shrink", False)
        # Automatic frame bounds are drawing state, not independent user edits.
        # Moving a frame still changes its children's effective positions below.
        nodes.append({"name": node.name, "type": node.bl_idname, "label": node.label,
                      "location": None if auto_frame else absolute_node_location(node), "parent": node.parent.name if node.parent else None,
                      "mute": node.mute, "hide": node.hide, "width": None if auto_frame else node.width,
                      "properties": properties, "inputs": sockets(node.inputs), "outputs": sockets(node.outputs),
                      "group": tree_state(child, ancestors + (tree.as_pointer(),)) if child else None})
    # Link ordering is not semantic for ordinary single-input sockets.
    # Multi-input sort IDs are included when the native tree exposes them.
    links = sorted((link.from_node.name, link.from_socket.identifier, link.to_node.name,
                    link.to_socket.identifier, getattr(link, "multi_input_sort_id", 0)) for link in tree.links)
    interface = [(item.name, item.in_out, item.socket_type) for item in tree.interface.items_tree if item.item_type == "SOCKET"]
    return {"nodes": nodes, "links": links, "interface": interface,
            "workflow": tree.get("mimi_ai_workflow")}


def blueprint_revision(tree):
    """Return a stable token that changes when graph data or dependencies change."""
    state = json.dumps(tree_state(tree), sort_keys=True, ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(state.encode("utf-8")).hexdigest()
