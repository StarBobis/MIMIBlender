"""Custom node-tree grouping for ``SSMTBlueprintTreeType``.

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

from .blueprint_node_base import SSMTNodeBase

TREE_IDNAME = "SSMTBlueprintTreeType"
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
        raise GroupingError("没有可进入的组")
    try:
        space.path.append(child, node=group_node)
    except Exception as exc:
        raise GroupingError(f"无法进入节点组: {exc}") from exc
    state = _navigation_state.setdefault(_navigation_key(space), {"stack": []})
    state["stack"].append(group_node)
    _remember_navigation(space, "ENTER", group_node)


def _exit_group(space):
    if len(space.path) <= 1:
        raise GroupingError("当前已在最外层蓝图")
    state = _navigation_state.get(_navigation_key(space), {})
    stack = state.get("stack", [])
    group_node = stack[-1] if stack else None
    if group_node is None or getattr(group_node, "node_tree", None) != _tree_from_space(space):
        raise GroupingError("无法确定当前组的父实例")
    space.path.pop()
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
        raise GroupingError(f"无法复制节点 {source.name} ({source.bl_idname}): {exc}") from exc
    target.location = source.location
    target["ssmt_uuid"] = uuid.uuid4().hex

    # Dynamic SSMT nodes need their collections/socket count established first.
    if hasattr(source, "texture_slot_items") and hasattr(target, "texture_slot_items"):
        try:
            while len(target.texture_slot_items) < len(source.texture_slot_items):
                target._add_texture_slot()
            for index, item in enumerate(source.texture_slot_items):
                if index < len(target.texture_slot_items):
                    for attr in ("slot_index", "slot_type", "custom_slot_key"):
                        if hasattr(item, attr) and hasattr(target.texture_slot_items[index], attr):
                            setattr(target.texture_slot_items[index], attr, getattr(item, attr))
        except Exception:
            pass
    if len(getattr(source, "inputs", ())) > len(getattr(target, "inputs", ())):
        for sock in list(source.inputs)[len(target.inputs):]:
            try:
                target.inputs.new(sock.bl_idname, sock.name)
            except Exception as exc:
                raise GroupingError(f"无法复制节点 {source.name} 的动态插槽: {exc}") from exc
    _copy_node_properties(source, target)
    if getattr(source, "bl_idname", "") == GROUP_NODE_IDNAME and getattr(source, "node_tree", None):
        if would_create_group_cycle(target_tree, source.node_tree):
            raise GroupingError(f"复制节点 {source.name} 会产生递归节点组")
        target.node_tree = source.node_tree
    _copy_socket_defaults(source, target)
    return target


def _new_interface_socket(tree, source_socket, direction, name):
    try:
        item = tree.interface.new_socket(name=name, in_out=direction, socket_type=source_socket.bl_idname)
    except Exception as exc:
        raise GroupingError(f"无法创建组接口 {name} ({source_socket.bl_idname}): {exc}") from exc
    for attr in ("description", "hide_value"):
        if hasattr(source_socket, attr) and hasattr(item, attr):
            try:
                setattr(item, attr, getattr(source_socket, attr))
            except Exception:
                pass
    return item


def _interface_identifier(item):
    return getattr(item, "identifier", "") or getattr(item, "name", "")


def _make_group_input_output(tree):
    try:
        group_input = tree.nodes.new(GROUP_INPUT_IDNAME)
        group_output = tree.nodes.new(GROUP_OUTPUT_IDNAME)
    except Exception as exc:
        raise GroupingError("当前 Blender 构建不支持自定义树的 Group Input/Output 节点") from exc
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
    """Rebuild a custom group node from its child tree's single interface."""
    tree = getattr(group_node, "node_tree", None)
    if tree is None:
        return
    for sockets in (group_node.inputs, group_node.outputs):
        for socket in list(sockets):
            sockets.remove(socket)
    for item in _all_interface_items(tree):
        socket_type = _interface_socket_type(item)
        if not socket_type:
            raise GroupingError(f"接口 {item.name} 没有可用的插槽类型")
        sockets = group_node.inputs if item.in_out == "INPUT" else group_node.outputs
        sockets.new(socket_type, item.name)


def make_group_from_selection(context, group_name="Group"):
    parent_tree = _tree_from_context(context)
    if parent_tree is None or parent_tree.bl_idname != TREE_IDNAME:
        raise GroupingError("当前不是可编辑的 SSMT 蓝图树")
    selected = _expand_frame_selection(node for node in parent_tree.nodes if node.select)
    if not selected:
        raise GroupingError("没有选择任何节点")
    if any(node.bl_idname in {GROUP_INPUT_IDNAME, GROUP_OUTPUT_IDNAME} for node in selected):
        raise GroupingError("不能将 Group Input/Output 节点再次分组")

    internal, incoming, outgoing = partition_links(parent_tree, selected)
    group_tree = None
    group_node = None
    old_links = list(parent_tree.links)
    old_selection = [(node, node.select) for node in parent_tree.nodes]
    try:
        clean_name = str(group_name or "Group").strip() or "Group"
        group_tree = bpy.data.node_groups.new(clean_name, TREE_IDNAME)
        group_tree["ssmt_is_group"] = True
        group_tree["ssmt_group_schema_version"] = 1
        group_tree["ssmt_interface_map"] = "{}"
        group_input, group_output = _make_group_input_output(group_tree)
        for node in selected:
            if not node.get("ssmt_uuid"):
                node["ssmt_uuid"] = uuid.uuid4().hex
        node_map = {node: _clone_node(node, group_tree) for node in selected}
        _restore_node_parents(node_map)

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
        if selected:
            group_node.location = tuple(sum(node.location[i] for node in selected) / len(selected) for i in (0, 1))

        for link in list(parent_tree.links):
            if link.from_node in selected or link.to_node in selected:
                parent_tree.links.remove(link)
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
        if group_node is not None and group_node in parent_tree.nodes:
            parent_tree.nodes.remove(group_node)
        for link in list(parent_tree.links):
            parent_tree.links.remove(link)
        for link in old_links:
            try:
                parent_tree.links.new(link.from_socket, link.to_socket)
            except Exception:
                pass
        for node, selected_state in old_selection:
            if node in parent_tree.nodes:
                node.select = selected_state
        if group_tree is not None and group_tree.users == 0:
            bpy.data.node_groups.remove(group_tree, do_unlink=True)
        raise


def ungroup_node(parent_tree, group_node):
    """Expand one independent group instance back into its parent tree."""
    group_tree = getattr(group_node, "node_tree", None)
    if group_tree is None:
        raise GroupingError("组节点没有子树")
    child_nodes = [
        node for node in group_tree.nodes
        if node.bl_idname not in {GROUP_INPUT_IDNAME, GROUP_OUTPUT_IDNAME}
    ]

    input_node = next((node for node in group_tree.nodes if node.bl_idname == GROUP_INPUT_IDNAME), None)
    output_node = next((node for node in group_tree.nodes if node.bl_idname == GROUP_OUTPUT_IDNAME), None)
    node_map = {node: _clone_node(node, parent_tree) for node in child_nodes}
    _restore_node_parents(node_map)
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

    for link in list(parent_tree.links):
        if link.from_node == group_node or link.to_node == group_node:
            parent_tree.links.remove(link)
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


class SSMTBlueprintGroupNode(SSMTNodeBase):
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
        name="Group Tree",
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
        op = row.operator("ssmt.group_enter", text="", icon="NODETREE")
        op.node_name = self.name
        op = row.operator("ssmt.ungroup", text="", icon="UNLINKED")
        op.node_name = self.name


class SSMT_OT_MakeGroup(bpy.types.Operator):
    bl_idname = "ssmt.make_group"
    bl_label = "Make Group"
    bl_options = {"REGISTER", "UNDO"}
    group_name: bpy.props.StringProperty(name="Group Name", default="Group")

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
            self.report({"ERROR"}, f"分组失败: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class SSMT_OT_Ungroup(bpy.types.Operator):
    bl_idname = "ssmt.ungroup"
    bl_label = "Ungroup"
    bl_options = {"REGISTER", "UNDO"}
    node_name: bpy.props.StringProperty(default="")

    def execute(self, context):
        tree = _tree_from_context(context)
        node = tree.nodes.get(self.node_name) if tree and self.node_name else getattr(tree.nodes, "active", None) if tree else None
        if not tree or not node or node.bl_idname != GROUP_NODE_IDNAME or not getattr(node, "node_tree", None):
            self.report({"ERROR"}, "请选择有效的自定义组节点")
            return {"CANCELLED"}
        try:
            ungroup_node(tree, node)
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"展开分组失败: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class SSMT_OT_GroupEnter(bpy.types.Operator):
    bl_idname = "ssmt.group_enter"
    bl_label = "Enter Group"
    bl_options = {"REGISTER", "UNDO"}
    node_name: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        tree = _tree_from_context(context)
        node = tree.nodes.get(getattr(context, "active_node", None).name) if tree and getattr(context, "active_node", None) else None
        return bool(node and node.bl_idname == GROUP_NODE_IDNAME and node.node_tree)

    def execute(self, context):
        tree = _tree_from_context(context)
        node = tree.nodes.get(self.node_name) if tree and self.node_name else getattr(tree.nodes, "active", None) if tree else None
        space = getattr(context, "space_data", None)
        if not node or not getattr(node, "node_tree", None) or not space:
            self.report({"ERROR"}, "没有可进入的组")
            return {"CANCELLED"}
        try:
            _enter_group(space, node)
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class SSMT_OT_GroupExit(bpy.types.Operator):
    bl_idname = "ssmt.group_exit"
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


class SSMT_OT_GroupTab(bpy.types.Operator):
    """Navigate SSMT groups with context-sensitive Tab behavior."""
    bl_idname = "ssmt.group_tab"
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
                        raise GroupingError("上次退出的组已不可用")
                    _enter_group(space, previous_group)
                else:
                    raise GroupingError("没有可反向执行的组导航操作")
        except GroupingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (
    SSMTBlueprintGroupNode,
    SSMT_OT_MakeGroup,
    SSMT_OT_Ungroup,
    SSMT_OT_GroupEnter,
    SSMT_OT_GroupExit,
    SSMT_OT_GroupTab,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
