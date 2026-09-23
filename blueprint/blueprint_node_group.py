"""Custom node-tree grouping for ``MIMIBlueprintTreeType``.

The built-in node grouping operators intentionally reject custom trees.  This
module keeps the transformation data-oriented so it is usable from tests and
does not depend on clipboard or editor selection operators.
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass

import bpy

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase

TREE_IDNAME = "MIMIBlueprintTreeType"
GROUP_NODE_IDNAME = "SSMTBlueprintGroupNode"
GROUP_INPUT_IDNAME = "NodeGroupInput"
GROUP_OUTPUT_IDNAME = "NodeGroupOutput"

# Navigation belongs to an editor instance, not to the shared group datablock:
# one group tree can be opened through more than one Group node.
_navigation_state = {}


class GroupingError(RuntimeError):
    pass


@dataclass(frozen=True)
class BoundaryInput:
    external_from_socket: object
    internal_to_socket: object
    multi_input_sort_id: int


@dataclass(frozen=True)
class BoundaryOutput:
    internal_from_socket: object
    external_to_socket: object


def _tree_from_context(context):
    space = getattr(context, "space_data", None)
    if not isinstance(space, bpy.types.SpaceNodeEditor):
        return None
    tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
    if getattr(tree, "bl_idname", "") != TREE_IDNAME:
        return None
    return tree


def _navigation_key(space):
    return space.as_pointer() if hasattr(space, "as_pointer") else id(space)


def _remember_navigation(space, action, group_node):
    state = _navigation_state.setdefault(_navigation_key(space), {"stack": []})
    state["action"] = action
    state["group_node"] = group_node


def _enter_group(space, group_node):
    child = getattr(group_node, "node_tree", None)
    if child is None:
        raise GroupingError(tr("No group to enter"))
    try:
        space.path.append(child, node=group_node)
    except Exception as exc:
        raise GroupingError(tr("Cannot enter node group: {error}").format(error=exc)) from exc
    state = _navigation_state.setdefault(_navigation_key(space), {"stack": []})
    state["stack"].append(group_node)
    _remember_navigation(space, "ENTER", group_node)


def _exit_group(space):
    if len(space.path) <= 1:
        raise GroupingError(tr("Currently at the outermost blueprint"))
    state = _navigation_state.get(_navigation_key(space), {})
    stack = state.get("stack", [])
    group_node = stack[-1] if stack else None
    # Blender saves its editor path, but our Python navigation stack is not
    # saved. Exiting must still work after loading a file or using breadcrumbs.
    # Only remember a reverse action when the actual instance is unambiguous.
    try:
        if group_node is None or group_node.node_tree != _tree_from_space(space):
            parent_tree = space.path[-2].node_tree
            matches = [node for node in parent_tree.nodes if node.bl_idname == GROUP_NODE_IDNAME and node.node_tree == _tree_from_space(space)]
            group_node = matches[0] if len(matches) == 1 else None
    except ReferenceError:
        group_node = None
    space.path.pop()
    if stack:
        stack.pop()
    _remember_navigation(space, "EXIT", group_node)


def _tree_from_space(space):
    return getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)


def partition_links(tree, selected):
    """Return internal and boundary links from a stable link snapshot."""
    selected = set(selected)
    internal, incoming, outgoing = [], [], []
    for link in list(tree.links):
        source_inside = link.from_node in selected
        target_inside = link.to_node in selected
        if source_inside and target_inside:
            internal.append(link)
        elif not source_inside and target_inside:
            incoming.append(BoundaryInput(
                link.from_socket,
                link.to_socket,
                getattr(link, "multi_input_sort_id", 0),
            ))
        elif source_inside and not target_inside:
            outgoing.append(BoundaryOutput(link.from_socket, link.to_socket))
    return internal, incoming, outgoing


def _expand_frame_selection(nodes):
    """Selecting a Frame always includes all of its descendants."""
    selected = set(nodes)
    changed = True
    while changed:
        changed = False
        for node in list(selected):
            for candidate in node.id_data.nodes:
                if candidate.parent == node and candidate not in selected:
                    selected.add(candidate)
                    changed = True
    return selected


def _absolute_location(node):
    x, y = node.location
    parent = node.parent
    while parent is not None:
        x += parent.location.x
        y += parent.location.y
        parent = parent.parent
    return x, y


def _restore_node_parents(node_map):
    """Restore frame relationships inside the copied set, preserving layout."""
    for source, target in node_map.items():
        target.parent = node_map.get(source.parent)
    for source, target in node_map.items():
        target.location = source.location if source.parent in node_map else _absolute_location(source)


def _ordered_links(links):
    """Recreate each multi-input target from low to high sort ID."""
    grouped = {}
    for index, link in enumerate(links):
        grouped.setdefault(link.to_socket, []).append((index, link))
    ordered = []
    for entries in grouped.values():
        if getattr(entries[0][1].to_socket, "is_multi_input", False):
            entries.sort(key=lambda entry: getattr(entry[1], "multi_input_sort_id", 0))
        ordered.extend(link for _, link in entries)
    return ordered


def _ordered_boundary_inputs(boundaries):
    grouped = {}
    for boundary in boundaries:
        grouped.setdefault(boundary.internal_to_socket, []).append(boundary)
    ordered = []
    for entries in grouped.values():
        if getattr(entries[0].internal_to_socket, "is_multi_input", False):
            entries.sort(key=lambda boundary: boundary.multi_input_sort_id)
        ordered.extend(entries)
    return ordered


def _copy_value(value):
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _copy_id_properties(source, target):
    for key in source.keys():
        if key == "_RNA_UI":
            continue
        try:
            target[key] = _copy_value(source[key])
        except (TypeError, ValueError, AttributeError):
            continue


_RNA_EXCLUDE = {
    "rna_type", "type", "bl_idname", "name", "label", "inputs", "outputs",
    "internal_links", "select", "parent", "location", "width", "height",
    "dimensions", "id_data", "node_tree", "interface", "mute", "hide",
}


def _copy_collection_items(source, target):
    """Copy RNA collections recursively, including every row's settings."""
    # ID-property deepcopy does not copy Blender PropertyGroup collections.
    # Rebuild each collection explicitly so grouping cannot discard user data.
    # Native read-only collections (such as node warnings) are not settings.
    # Only PropertyGroup collections expose add/clear for reconstruction.
    if not hasattr(target, "add") or not hasattr(target, "clear"):
        return
    target.clear()
    for source_item in source:
        target_item = target.add()
        for prop in source_item.bl_rna.properties:
            name = prop.identifier
            if name == "rna_type":
                continue
            if prop.type == "COLLECTION":
                _copy_collection_items(getattr(source_item, name), getattr(target_item, name))
            elif not prop.is_readonly:
                if prop.type == "ENUM" and name in source_item.keys():
                    # Dynamic texture-mark enums need upstream links, which
                    # are restored only after cloning. Preserve the stored
                    # RNA value without triggering an unavailable dropdown.
                    target_item[name] = _copy_value(source_item[name])
                else:
                    setattr(target_item, name, _copy_value(getattr(source_item, name)))


def _copy_node_properties(source, target):
    for prop in source.bl_rna.properties:
        identifier = prop.identifier
        if identifier in _RNA_EXCLUDE or prop.is_readonly or prop.type == "COLLECTION":
            continue
        try:
            setattr(target, identifier, _copy_value(getattr(source, identifier)))
        except (AttributeError, TypeError, ValueError, RuntimeError):
            continue
    for attr in ("label", "width", "height", "hide", "mute", "use_custom_color", "color"):
        if hasattr(source, attr) and hasattr(target, attr):
            try:
                setattr(target, attr, _copy_value(getattr(source, attr)))
            except Exception:
                pass
    _copy_id_properties(source, target)
    # Copy addon collections after generic properties; row update callbacks
    # may depend on the scalar configuration already being available.
    for prop in source.bl_rna.properties:
        if prop.identifier not in _RNA_EXCLUDE and prop.type == "COLLECTION":
            _copy_collection_items(getattr(source, prop.identifier), getattr(target, prop.identifier))


def _socket_key(socket):
    return (getattr(socket, "identifier", ""), getattr(socket, "name", ""))


def _copy_socket_defaults(source, target):
    source_sockets = list(source.inputs)
    for target_socket in target.inputs:
        match = None
        for candidate in source_sockets:
            if _socket_key(candidate) == _socket_key(target_socket):
                match = candidate
                break
        if match is None:
            index = list(target.inputs).index(target_socket)
            if index < len(source_sockets):
                match = source_sockets[index]
        if match is None or not hasattr(match, "default_value") or not hasattr(target_socket, "default_value"):
            continue
        try:
            target_socket.default_value = _copy_value(match.default_value)
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass


def would_create_group_cycle(parent_tree, candidate_child_tree):
    if parent_tree == candidate_child_tree:
        return True
    visited = set()
    stack = [candidate_child_tree]
    while stack:
        tree = stack.pop()
        if tree is None or tree in visited:
            continue
        visited.add(tree)
        if tree == parent_tree:
            return True
        for node in tree.nodes:
            if getattr(node, "bl_idname", "") == GROUP_NODE_IDNAME:
                stack.append(getattr(node, "node_tree", None))
    return False


def _clone_node(source, target_tree):
    try:
        target = target_tree.nodes.new(source.bl_idname)
    except Exception as exc:
        raise GroupingError(tr("Cannot copy node {name} ({idname}): {error}").format(name=source.name, idname=source.bl_idname, error=exc)) from exc
    target.location = source.location
    target["ssmt_uuid"] = uuid.uuid4().hex

    _copy_node_properties(source, target)
    # Both directions can be dynamic (Object List has per-object outputs).
    # Clone identifiers, not just names: removed/re-added sockets may have
    # identifiers that differ from their labels or their current positions.
    if isinstance(source, MIMINodeBase):
        for direction in ("inputs", "outputs"):
            source_sockets = getattr(source, direction)
            target_sockets = getattr(target, direction)
            target_sockets.clear()
            for socket in source_sockets:
                target_sockets.new(socket.bl_idname, socket.name, identifier=socket.identifier)
    # Native Frame/Reroute sockets are owned by Blender and cannot be removed.
    # Their constructor already creates the correct ports; links set the type.
    if getattr(source, "bl_idname", "") == GROUP_NODE_IDNAME and getattr(source, "node_tree", None):
        if would_create_group_cycle(target_tree, source.node_tree):
            raise GroupingError(tr("Copying node {name} would create a recursive node group").format(name=source.name))
        target.node_tree = source.node_tree
    _copy_socket_defaults(source, target)
    return target


def _new_interface_socket(tree, source_socket, direction, name):
    try:
        item = tree.interface.new_socket(name=name, in_out=direction, socket_type=source_socket.bl_idname)
    except Exception as exc:
        raise GroupingError(tr("Cannot create group interface {name} ({idname}): {error}").format(name=name, idname=source_socket.bl_idname, error=exc)) from exc
    for attr in ("description", "hide_value"):
        if hasattr(source_socket, attr) and hasattr(item, attr):
            try:
                setattr(item, attr, getattr(source_socket, attr))
            except Exception:
                pass
    return item


def _interface_identifier(item):
    return getattr(item, "identifier", "") or getattr(item, "name", "")


def get_group_output_node(tree):
    """Choose one output even in custom trees without a native active flag."""
    # Blender does not automatically activate Group Output in custom trees.
    # Prefer an explicit active output, then the first output for legacy files.
    outputs = [node for node in tree.nodes if node.bl_idname == GROUP_OUTPUT_IDNAME]
    return next((node for node in outputs if node.is_active_output), outputs[0] if outputs else None)


def _make_group_input_output(tree):
    try:
        group_input = tree.nodes.new(GROUP_INPUT_IDNAME)
        group_output = tree.nodes.new(GROUP_OUTPUT_IDNAME)
    except Exception as exc:
        raise GroupingError(tr("This Blender build does not support Group Input/Output nodes in custom trees")) from exc
    group_input.location = (-300, 0)
    group_output.location = (300, 0)
    return group_input, group_output


def _all_interface_items(tree):
    return [item for item in tree.interface.items_tree if getattr(item, "item_type", "") == "SOCKET"]


def _interface_socket_type(item):
    return getattr(item, "bl_socket_idname", "") or getattr(item, "socket_type", "")


def _group_socket_for_interface(group_node, group_tree, item, direction):
    items = [candidate for candidate in _all_interface_items(group_tree) if candidate.in_out == direction]
    try:
        index = items.index(item)
    except ValueError:
        return None
    sockets = group_node.inputs if direction == "INPUT" else group_node.outputs
    return sockets[index] if index < len(sockets) else None


def sync_group_node_sockets(group_node):
    """Synchronize interfaces in place so existing wires keep their identity."""
    tree = getattr(group_node, "node_tree", None)
    items = _all_interface_items(tree) if tree is not None else []
    for direction, sockets in (("INPUT", group_node.inputs), ("OUTPUT", group_node.outputs)):
        wanted = [item for item in items if item.in_out == direction]
        retained = set()
        # Socket ID properties are unsupported on some Blender socket types.
        # Store legacy-to-interface mappings on the owning node instead.
        map_key = "ssmt_interface_" + direction.lower()
        previous_ids = json.loads(group_node.get(map_key, "{}"))
        current_ids = {}
        for index, item in enumerate(wanted):
            identifier = _interface_identifier(item)
            socket_type = _interface_socket_type(item)
            if not socket_type:
                raise GroupingError(tr("Interface {name} has no usable socket type").format(name=item.name))
            # The identifier survives interface renames and reordering.
            # Legacy sockets have no stored ID; adopt their positional match.
            socket_id = previous_ids.get(identifier, identifier)
            socket = next((sock for sock in sockets if sock.identifier == socket_id), None)
            if socket is None and not group_node.get("ssmt_interface_synced") and index < len(sockets):
                candidate = sockets[index]
                if candidate not in retained:
                    socket = candidate
            if socket is not None and socket.bl_idname != socket_type:
                sockets.remove(socket)
                socket = None
            if socket is None:
                socket = sockets.new(socket_type, item.name, identifier=identifier)
            current_ids[identifier] = socket.identifier
            socket.name = item.name
            retained.add(socket)
            sockets.move(list(sockets).index(socket), index)
        # Only removed interface items lose their wires; unchanged items stay.
        for socket in list(sockets):
            if socket not in retained:
                sockets.remove(socket)
        group_node[map_key] = json.dumps(current_ids)
    group_node["ssmt_interface_synced"] = True
    group_node["ssmt_interface_signature"] = _interface_signature(tree)


def _interface_signature(tree):
    # Plain strings persist through undo/load without stale RNA pointers.
    items = _all_interface_items(tree) if tree is not None else []
    return json.dumps([(item.identifier, item.name, item.in_out, _interface_socket_type(item)) for item in items])


def _sync_group_interfaces():
    """Fallback for custom-tree interface edits without native notifications."""
    # Blender's interface_update callback is not emitted for every custom-tree
    # edit. Only synchronize changed schemas; idle ticks must not dirty files.
    for tree in bpy.data.node_groups:
        if getattr(tree, "bl_idname", "") != TREE_IDNAME:
            continue
        for node in tree.nodes:
            if node.bl_idname == GROUP_NODE_IDNAME:
                signature = _interface_signature(node.node_tree)
                if node.get("ssmt_interface_signature") != signature:
                    sync_group_node_sockets(node)


def _group_interface_timer():
    try:
        _sync_group_interfaces()
    except (ReferenceError, RuntimeError) as error:
        # Retry after a transient undo/load/read-only transition.
        print(f"[MMT Group Interface] {error}")
    return 0.5


@bpy.app.handlers.persistent
def _clear_navigation_after_load(_scene=None):
    # Pointer-keyed editor state belongs only to the current blend session.
    _navigation_state.clear()


def _snapshot_links(tree):
    # Dynamic nodes may delete empty sockets when a link is removed. Capture
    # socket metadata too, never dereference a removed socket during rollback.
    return [((link.from_node, link.from_socket.identifier, link.from_socket.name, link.from_socket.bl_idname),
             (link.to_node, link.to_socket.identifier, link.to_socket.name, link.to_socket.bl_idname))
            for link in tree.links]


def _restore_links(tree, snapshot):
    # Recreate sockets removed by dynamic update callbacks before reconnecting.
    # Node instances are retained until the final successful transaction step.
    for link in list(tree.links):
        tree.links.remove(link)
    for source, target in snapshot:
        endpoints = []
        for saved, direction in ((source, "outputs"), (target, "inputs")):
            node, identifier, name, socket_type = saved
            sockets = getattr(node, direction)
            socket = next((item for item in sockets if item.identifier == identifier), None)
            if socket is None:
                socket = sockets.new(socket_type, name, identifier=identifier)
            endpoints.append(socket)
        tree.links.new(*endpoints)


def make_group_from_selection(context, group_name="Group"):
    parent_tree = _tree_from_context(context)
    if parent_tree is None or parent_tree.bl_idname != TREE_IDNAME:
        raise GroupingError(tr("The current tree is not an editable MMT blueprint tree"))
    selected = _expand_frame_selection(node for node in parent_tree.nodes if node.select)
    if not selected:
        raise GroupingError(tr("No nodes are selected"))
    if any(node.bl_idname in {GROUP_INPUT_IDNAME, GROUP_OUTPUT_IDNAME} for node in selected):
        raise GroupingError(tr("Group Input/Output nodes cannot be grouped again"))

    internal, incoming, outgoing = partition_links(parent_tree, selected)
    group_tree = None
    group_node = None
    # RNA NodeLink wrappers become invalid as soon as a link is removed.
    # Store socket endpoints now; dereferencing deleted links can crash Blender.
    old_links = _snapshot_links(parent_tree)
    old_selection = [(node, node.select) for node in parent_tree.nodes]
    try:
        clean_name = str(group_name or "Group").strip() or "Group"
        group_tree = bpy.data.node_groups.new(clean_name, TREE_IDNAME)
        group_tree["ssmt_is_group"] = True
        # Version 2 stores root positions relative to the group instance.
        group_tree["ssmt_group_schema_version"] = 2
        group_tree["ssmt_interface_map"] = "{}"
        group_input, group_output = _make_group_input_output(group_tree)
        for node in selected:
            if not node.get("ssmt_uuid"):
                node["ssmt_uuid"] = uuid.uuid4().hex
        node_map = {node: _clone_node(node, group_tree) for node in selected}
        _restore_node_parents(node_map)
        # Store child roots relative to the new group's world-space center.
        # Frame children already use relative coordinates and must not shift.
        center = tuple(sum(_absolute_location(node)[axis] for node in selected) / len(selected) for axis in (0, 1))
        for cloned in node_map.values():
            if cloned.parent is None:
                cloned.location.x -= center[0]
                cloned.location.y -= center[1]
        # Keep submesh search choices available when editing inside the group.
        for source_item in parent_tree.ssmt_submesh_items:
            group_tree.ssmt_submesh_items.add().name = source_item.name

        for link in _ordered_links(internal):
            group_tree.links.new(node_map[link.from_node].outputs[link.from_socket.identifier],
                                 node_map[link.to_node].inputs[link.to_socket.identifier])

        interface_map = {}
        input_map, output_map = {}, {}
        for index, boundary in enumerate(incoming):
            source, target = boundary.external_from_socket, boundary.internal_to_socket
            item = _new_interface_socket(group_tree, target, "INPUT", f"{boundary.internal_to_socket.node.name}.{target.name}")
            identifier = _interface_identifier(item)
            interface_map[identifier] = {"direction": "INPUT", "node": target.node.get("ssmt_uuid", ""), "socket": target.identifier}
            input_map[boundary] = item
        output_items = {}
        for index, boundary in enumerate(outgoing):
            source, target = boundary.internal_from_socket, boundary.external_to_socket
            source_key = (source.node.name, source.identifier)
            item = output_items.get(source_key)
            if item is None:
                item = _new_interface_socket(group_tree, source, "OUTPUT", f"{source.node.name}.{source.name}")
                output_items[source_key] = item
                identifier = _interface_identifier(item)
                interface_map[identifier] = {"direction": "OUTPUT", "node": source.node.get("ssmt_uuid", ""), "socket": source.identifier}
            output_map[boundary] = item
        group_tree["ssmt_interface_map"] = json.dumps(interface_map)

        # Interface sockets are mirrored by generic Group Input/Output nodes.
        for boundary in _ordered_boundary_inputs(input_map):
            item = input_map[boundary]
            group_socket = group_input.outputs.get(_interface_identifier(item))
            cloned_socket = node_map[boundary.internal_to_socket.node].inputs.get(boundary.internal_to_socket.identifier)
            if group_socket and cloned_socket:
                group_tree.links.new(group_socket, cloned_socket)
        connected_output_items = set()
        for boundary, item in output_map.items():
            item_key = _interface_identifier(item)
            if item_key in connected_output_items:
                continue
            connected_output_items.add(item_key)
            group_socket = group_output.inputs.get(_interface_identifier(item))
            cloned_socket = node_map[boundary.internal_from_socket.node].outputs.get(boundary.internal_from_socket.identifier)
            if group_socket and cloned_socket:
                group_tree.links.new(cloned_socket, group_socket)
        group_tree.update_tag()

        group_node = parent_tree.nodes.new(GROUP_NODE_IDNAME)
        group_node.node_tree = group_tree
        group_node.location = center

        # Wire replacements before removing sources. Dynamic targets keep
        # their sockets alive while at least one link still occupies the port.
        # Removing the selected nodes below clears their old links atomically.
        for boundary, item in input_map.items():
            group_socket = _group_socket_for_interface(group_node, group_tree, item, "INPUT")
            if group_socket:
                parent_tree.links.new(boundary.external_from_socket, group_socket)
        for boundary, item in output_map.items():
            group_socket = _group_socket_for_interface(group_node, group_tree, item, "OUTPUT")
            if group_socket:
                parent_tree.links.new(group_socket, boundary.external_to_socket)
        for node in list(selected):
            parent_tree.nodes.remove(node)
        for node in parent_tree.nodes:
            node.select = False
        group_node.select = True
        parent_tree.nodes.active = group_node
        parent_tree.update_tag()
        return group_node
    except Exception:
        # Restore links before removing the temporary node/tree.
        if group_node is not None and parent_tree.nodes.get(group_node.name) == group_node:
            parent_tree.nodes.remove(group_node)
        _restore_links(parent_tree, old_links)
        for node, selected_state in old_selection:
            if parent_tree.nodes.get(node.name) == node:
                node.select = selected_state
        if group_tree is not None and group_tree.users == 0:
            bpy.data.node_groups.remove(group_tree, do_unlink=True)
        raise


def ungroup_node(parent_tree, group_node):
    """Expand atomically; a failed clone must leave the original group intact."""
    # Keep endpoints, not RNA links, because removing nodes invalidates links.
    # All risky copies happen before the original group is removed.
    existing_nodes = set(parent_tree.nodes)
    old_links = _snapshot_links(parent_tree)
    old_selection = [(node, node.select) for node in parent_tree.nodes]
    try:
        return _ungroup_node_impl(parent_tree, group_node)
    except Exception:
        for node in list(parent_tree.nodes):
            if node not in existing_nodes:
                parent_tree.nodes.remove(node)
        _restore_links(parent_tree, old_links)
        for node, selected in old_selection:
            node.select = selected
        raise


def _ungroup_node_impl(parent_tree, group_node):
    """Expand one independent group instance back into its parent tree."""
    group_tree = getattr(group_node, "node_tree", None)
    if group_tree is None:
        raise GroupingError(tr("The group node has no child tree"))
    child_nodes = [
        node for node in group_tree.nodes
        if node.bl_idname not in {GROUP_INPUT_IDNAME, GROUP_OUTPUT_IDNAME}
    ]

    input_node = next((node for node in group_tree.nodes if node.bl_idname == GROUP_INPUT_IDNAME), None)
    output_node = get_group_output_node(group_tree)
    node_map = {node: _clone_node(node, parent_tree) for node in child_nodes}
    _restore_node_parents(node_map)
    # Ungroup where the instance is now, not where it was originally created.
    # Preserve frame-relative positions and account for a parent frame too.
    center = _absolute_location(group_node)
    # Schema-1 files stored absolute child positions. Keep their old layout
    # instead of applying the new relative-coordinate offset a second time.
    if group_tree.get("ssmt_group_schema_version", 2) >= 2:
        for cloned in node_map.values():
            if cloned.parent is None:
                cloned.location.x += center[0]
                cloned.location.y += center[1]
    for link in _ordered_links(list(group_tree.links)):
        if link.from_node in node_map and link.to_node in node_map:
            parent_tree.links.new(
                node_map[link.from_node].outputs[link.from_socket.identifier],
                node_map[link.to_node].inputs[link.to_socket.identifier],
            )

    inbound = {index: [] for index in range(len(group_node.inputs))}
    outbound = {index: [] for index in range(len(group_node.outputs))}
    for link in list(parent_tree.links):
        if link.to_node == group_node:
            inbound[list(group_node.inputs).index(link.to_socket)].append(link.from_socket)
        elif link.from_node == group_node:
            outbound[list(group_node.outputs).index(link.from_socket)].append(link.to_socket)
    input_targets = {index: [] for index in inbound}
    output_sources = {index: [] for index in outbound}
    if input_node:
        for index, socket in enumerate(input_node.outputs):
            for link in socket.links:
                if link.to_node in node_map:
                    input_targets[index].append(node_map[link.to_node].inputs[link.to_socket.identifier])
    if output_node:
        for index, socket in enumerate(output_node.inputs):
            for link in socket.links:
                if link.from_node in node_map:
                    output_sources[index].append(node_map[link.from_node].outputs[link.from_socket.identifier])
                elif link.from_node == input_node:
                    # A direct Group Input -> Group Output is a valid wire.
                    # Preserve it even when the child contains no ordinary nodes.
                    input_index = list(input_node.outputs).index(link.from_socket)
                    output_sources[index].extend(inbound.get(input_index, []))

    # Keep the old instance linked until replacements occupy its targets.
    # Otherwise dynamic target nodes may delete the saved input sockets.
    for index, source_sockets in inbound.items():
        for source_socket in source_sockets:
            for target_socket in input_targets.get(index, []):
                parent_tree.links.new(source_socket, target_socket)
    for index, source_sockets in output_sources.items():
        for source_socket in source_sockets:
            for target_socket in outbound.get(index, []):
                parent_tree.links.new(source_socket, target_socket)
    parent_tree.nodes.remove(group_node)
    for node in parent_tree.nodes:
        node.select = False
    for node in node_map.values():
        node.select = True
    parent_tree.nodes.active = next(iter(node_map.values()), None)
    parent_tree.update_tag()
    if group_tree.users == 0:
        bpy.data.node_groups.remove(group_tree, do_unlink=True)


@translatable
class MMTBlueprintGroupNode(MIMINodeBase):
    bl_idname = GROUP_NODE_IDNAME
    bl_label = "Group"
    bl_icon = "NODETREE"

    def update_group_tree(self, context):
        try:
            if self.node_tree and would_create_group_cycle(self.id_data, self.node_tree):
                self.node_tree = None
                return
            sync_group_node_sockets(self)
        except GroupingError:
            pass

    node_tree: bpy.props.PointerProperty(
        name=tr("Group Tree"),
        type=bpy.types.NodeTree,
        update=update_group_tree,
    )  # type: ignore

    @classmethod
    def poll(cls, node_tree):
        return bool(node_tree and getattr(node_tree, "bl_idname", "") == TREE_IDNAME)

    def copy(self, source):
        self.node_tree = source.node_tree

    def free(self):
        pass

    def draw_buttons(self, context, layout):
        row = layout.row(align=True)
        op = row.operator("mimi.group_enter", text="", icon="NODETREE")
        op.node_name = self.name
        op = row.operator("mimi.ungroup", text="", icon="UNLINKED")
        op.node_name = self.name


class MMT_OT_MakeGroup(I18nOperator):
    bl_idname = "mimi.make_group"
    bl_label = "Make Group"
    bl_options = {"REGISTER", "UNDO"}
    # The default value stays English because it becomes the node group's name (data).
    group_name: bpy.props.StringProperty(name=tr("Group Name"), default="Group")

    @classmethod
    def poll(cls, context):
        tree = _tree_from_context(context)
        return bool(tree and tree.bl_idname == TREE_IDNAME and any(n.select for n in tree.nodes))

    def execute(self, context):
        try:
            make_group_from_selection(context, self.group_name)
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, tr("Grouping failed: {error}").format(error=exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class MMT_OT_Ungroup(I18nOperator):
    bl_idname = "mimi.ungroup"
    bl_label = "Ungroup"
    bl_options = {"REGISTER", "UNDO"}
    node_name: bpy.props.StringProperty(default="")

    def execute(self, context):
        tree = _tree_from_context(context)
        node = tree.nodes.get(self.node_name) if tree and self.node_name else getattr(tree.nodes, "active", None) if tree else None
        if not tree or not node or node.bl_idname != GROUP_NODE_IDNAME or not getattr(node, "node_tree", None):
            self.report({"ERROR"}, tr("Select a valid custom group node"))
            return {"CANCELLED"}
        try:
            ungroup_node(tree, node)
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, tr("Ungrouping failed: {error}").format(error=exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class MMT_OT_GroupEnter(I18nOperator):
    bl_idname = "mimi.group_enter"
    bl_label = "Enter Group"
    bl_options = {"REGISTER", "UNDO"}
    node_name: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        # A node's own Enter button supplies node_name after polling.
        # Requiring the active node to be a group disables other groups' buttons.
        return _tree_from_context(context) is not None

    def execute(self, context):
        tree = _tree_from_context(context)
        node = tree.nodes.get(self.node_name) if tree and self.node_name else getattr(tree.nodes, "active", None) if tree else None
        space = getattr(context, "space_data", None)
        if not node or not getattr(node, "node_tree", None) or not space:
            self.report({"ERROR"}, tr("No group to enter"))
            return {"CANCELLED"}
        try:
            _enter_group(space, node)
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class MMT_OT_GroupExit(I18nOperator):
    bl_idname = "mimi.group_exit"
    bl_label = "Exit Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        space = getattr(context, "space_data", None)
        if not space:
            return {"CANCELLED"}
        try:
            _exit_group(space)
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class MMT_OT_GroupTab(I18nOperator):
    """Navigate MMT groups with context-sensitive Tab behavior."""
    bl_idname = "mimi.group_tab"
    bl_label = "Toggle Group Navigation"

    @classmethod
    def poll(cls, context):
        return bool(_tree_from_context(context))

    def execute(self, context):
        tree = _tree_from_context(context)
        space = getattr(context, "space_data", None)
        selected = [node for node in tree.nodes if node.select]
        group_node = next(
            (node for node in selected if node.bl_idname == GROUP_NODE_IDNAME and node.node_tree),
            None,
        )
        proxy_selected = any(
            node.bl_idname in {GROUP_INPUT_IDNAME, GROUP_OUTPUT_IDNAME}
            for node in selected
        )
        try:
            if group_node is not None:
                _enter_group(space, group_node)
            elif proxy_selected:
                _exit_group(space)
            else:
                state = _navigation_state.get(_navigation_key(space), {})
                if state.get("action") == "ENTER":
                    _exit_group(space)
                elif state.get("action") == "EXIT":
                    previous_group = state.get("group_node")
                    if previous_group is None or previous_group.id_data != tree:
                        raise GroupingError(tr("The group exited last time is no longer available"))
                    _enter_group(space, previous_group)
                else:
                    raise GroupingError(tr("No group navigation action to reverse"))
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (
    MMTBlueprintGroupNode,
    MMT_OT_MakeGroup,
    MMT_OT_Ungroup,
    MMT_OT_GroupEnter,
    MMT_OT_GroupExit,
    MMT_OT_GroupTab,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.timers.is_registered(_group_interface_timer):
        bpy.app.timers.register(_group_interface_timer, first_interval=0.5, persistent=True)
    if _clear_navigation_after_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_clear_navigation_after_load)


def unregister():
    # Stop callbacks before their RNA classes disappear during addon reload.
    if bpy.app.timers.is_registered(_group_interface_timer):
        bpy.app.timers.unregister(_group_interface_timer)
    if _clear_navigation_after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_clear_navigation_after_load)
    _navigation_state.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
