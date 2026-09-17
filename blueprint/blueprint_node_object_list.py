'''
Object List blueprint node: many objects in one collapsible node.

Motivation: baked animation mods can produce dozens of frame objects
(48 frames -> 48 meshes).  Laying down one Object Info node per frame
floods the blueprint, so this node keeps the whole list inside a single
collapsible body:

- Every list item gets its own MIMISocketObject output socket, so any
  object can be wired individually (e.g. one branch per frame of a
  Switch Key / Time Switch).
- A leading "All" output socket emits every enabled item in list order,
  so the whole set can feed one downstream chain (texture bind, plain
  output, ...) with a single wire.
- The node body collapses to a one-line "{n} objects" summary, keeping
  the graph readable when the details do not matter.

Parse-side contract (see BluePrintModel):
- The parser threads the link's from_socket down the traversal, so the
  Object List branch knows which output socket a chain left from.
- Leaving from a per-item socket emits exactly that object; leaving from
  "All" (or visiting without socket info) emits every enabled item in
  list order.  Duplicate objects inside one expansion are an error,
  because they would silently duplicate drawindexed calls.
'''
import bpy
from bpy.types import PropertyGroup

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase

# Fixed name of the aggregate output socket; it always sits at outputs[0].
ALL_SOCKET_NAME = "All"


def _object_list_item_refresh_display(item):
    '''Rebuild the one-line display name shown inside the list widget.'''
    object_name = str(getattr(item, "object_name", "") or "").strip()
    item.name = object_name if object_name else "?"


def _sync_item_socket_label(node, item):
    '''Rename the output socket that mirrors the given list item.

    Socket order mirrors item order with the leading "All" socket:
    outputs[0] is "All", outputs[i + 1] belongs to items[i].
    '''
    try:
        index = -1
        for candidate_index, candidate in enumerate(node.object_items):
            if candidate.as_pointer() == item.as_pointer():
                index = candidate_index
                break
        if index < 0 or index + 1 >= len(node.outputs):
            return
        socket = node.outputs[index + 1]
        socket.name = item.name or "?"
    except Exception:
        # Label sync must never break the node editor drawing.
        pass


def _object_list_item_changed(item):
    '''Update callback: keep the list row, its socket label and the node width in sync.'''
    _object_list_item_refresh_display(item)
    node = _find_owner_object_list_node(item)
    if node is not None:
        _sync_item_socket_label(node, item)
        # Width writes are forbidden while Blender draws the node (some draw
        # contexts are read-only), so the width is maintained from property
        # updates and operators instead of draw_buttons.
        node._refresh_width()


def _find_owner_object_list_node(item):
    '''Find the Object List node that owns the given collection item.'''
    tree = getattr(item, "id_data", None)
    if tree is None:
        return None
    for node in getattr(tree, "nodes", []):
        if getattr(node, "bl_idname", "") != 'MIMINode_Object_List':
            continue
        for candidate in getattr(node, "object_items", []):
            if candidate.as_pointer() == item.as_pointer():
                return node
    return None


def _append_object_list_item(node, object_name):
    '''Add one item plus its mirrored output socket; returns the new item.'''
    item = node.object_items.add()
    item.object_name = object_name
    item.enabled = True
    _object_list_item_refresh_display(item)
    node.outputs.new('MIMISocketObject', item.name)
    node.object_index = len(node.object_items) - 1
    node._refresh_width()
    return item


def _remove_object_list_item(node, index):
    '''Remove the item at index plus its mirrored output socket.'''
    if not (0 <= index < len(node.object_items)):
        return
    node.object_items.remove(index)
    # outputs[0] is the "All" socket, so item i mirrors outputs[i + 1].
    if index + 1 < len(node.outputs):
        node.outputs.remove(node.outputs[index + 1])
    node.object_index = max(0, min(index, len(node.object_items) - 1))
    node._refresh_width()


def _lookup_object_list_node(context, tree_name, node_name):
    '''Shared operator helper: resolve the target node from its names.'''
    tree = bpy.data.node_groups.get(tree_name) if tree_name else None
    if tree is None:
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
    if tree is None:
        return None
    node = tree.nodes.get(node_name)
    if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Object_List':
        return None
    return node


class MIMIObjectListItem(PropertyGroup):
    '''One object entry of an Object List node.'''
    name: bpy.props.StringProperty(name=tr("Object"), default="") # type: ignore

    enabled: bpy.props.BoolProperty(
        name=tr("Enabled"),
        description=tr("Disabled entries are skipped at export time"),
        default=True,
    ) # type: ignore

    object_name: bpy.props.StringProperty(
        name=tr("Object Name"),
        description=tr("Blender object of this entry; parse falls back to object name resolution when the Submesh is empty"),
        default="",
        update=lambda self, context: _object_list_item_changed(self),
    ) # type: ignore

    submesh_name: bpy.props.StringProperty(
        name=tr("Submesh"),
        description=tr("Optional Submesh override, same semantics as the Object Info node"),
        default="",
        update=lambda self, context: _object_list_item_changed(self),
    ) # type: ignore


class MMT_OT_ObjectListAddItem(I18nOperator):
    '''Add one object entry (and its output socket) to an Object List node'''
    bl_idname = "mimi.objlist_add_item"
    bl_label = "Add Object"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _lookup_object_list_node(context, self.tree_name, self.node_name)
        if node is None:
            return {'CANCELLED'}
        _append_object_list_item(node, "")
        return {'FINISHED'}


class MMT_OT_ObjectListRemoveItem(I18nOperator):
    '''Remove the selected object entry (and its output socket) from an Object List node'''
    bl_idname = "mimi.objlist_remove_item"
    bl_label = "Remove Object"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _lookup_object_list_node(context, self.tree_name, self.node_name)
        if node is None:
            return {'CANCELLED'}
        _remove_object_list_item(node, int(getattr(node, "object_index", 0)))
        return {'FINISHED'}


class MMT_OT_ObjectListAddSelected(I18nOperator):
    '''Add every selected mesh object that is not in the list yet'''
    bl_idname = "mimi.objlist_add_selected"
    bl_label = "Add Selected Objects"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _lookup_object_list_node(context, self.tree_name, self.node_name)
        if node is None:
            return {'CANCELLED'}
        existing_names = set()
        for row_item in node.object_items:
            existing_names.add(str(row_item.object_name or "").strip())
        added_count = 0
        for obj in getattr(context, "selected_objects", []):
            if getattr(obj, "type", "") != 'MESH':
                continue
            if obj.name in existing_names:
                continue
            _append_object_list_item(node, obj.name)
            existing_names.add(obj.name)
            added_count += 1
        self.report({'INFO'}, tr("Added {count} object(s)").format(count=added_count))
        return {'FINISHED'}


@translatable
class MIMINode_Object_List(MIMINodeBase):
    '''Object List emits many objects from one collapsible node: per-item sockets for individual wiring, an All socket for the whole set'''
    bl_idname = 'MIMINode_Object_List'
    bl_label = 'Object List'
    bl_icon = 'OUTLINER_OB_GROUP_INSTANCE'
    bl_width_min = 200

    object_items: bpy.props.CollectionProperty(type=MIMIObjectListItem) # type: ignore
    object_index: bpy.props.IntProperty(default=0) # type: ignore
    # Collapsed by default: long animation lists must not flood the graph.
    show_details: bpy.props.BoolProperty(
        name=tr("Show Details"),
        description=tr("Expand the object list; collapse to keep the blueprint compact"),
        default=False,
    ) # type: ignore

    def width_texts(self):
        """Return every text that decides how wide this node has to be."""
        return [self.label]

    def _refresh_width(self):
        """Fit the node width to everything the node displays.

        The socket labels mirror the item names, so the widest object name
        decides the width; the count line and the aggregate All socket are
        included as well. Called from property update callbacks and the
        add/remove operators, never from draw_buttons (ID writes are
        forbidden in draw contexts).
        """
        texts = [
            str(self.label or ""),
            tr("{count} object(s)").format(count=len(self.object_items)),
            ALL_SOCKET_NAME,
        ]
        for item in self.object_items:
            texts.append(str(item.name or "?"))
            submesh_name = str(getattr(item, "submesh_name", "") or "").strip()
            if submesh_name:
                texts.append(submesh_name)
        self.update_node_width(texts)

    def init(self, context):
        # The default title is instance data, so bake in the active language.
        self.label = tr("Object List")
        # The aggregate socket is created first, so it renders on top.
        self.outputs.new('MIMISocketObject', ALL_SOCKET_NAME)
        self.width = 220
        self.use_custom_color = True
        self.color = (0.35, 0.30, 0.50)

    def draw_buttons(self, context, layout):
        tree = self.id_data if getattr(self, "id_data", None) and getattr(self.id_data, "bl_idname", "") == 'MIMIBlueprintTreeType' else None

        # NOTE: never write node data (e.g. the width) here; Blender forbids
        # ID writes in several draw contexts. The width is maintained from
        # property update callbacks and the add/remove operators instead.

        # Collapsed header: one toggle plus the object count. This is all a
        # reader sees for a 48-frame animation list until they expand it.
        header_row = layout.row(align=True)
        header_row.prop(
            self, "show_details",
            text="",
            icon='TRIA_DOWN' if self.show_details else 'TRIA_RIGHT',
            toggle=True,
        )
        enabled_count = len([row_item for row_item in self.object_items if row_item.enabled])
        header_row.label(text=tr("{count} object(s)").format(count=enabled_count), icon='OBJECT_DATAMODE')

        if not self.show_details:
            return

        row = layout.row()
        row.template_list(
            "UI_UL_list", "mimi_object_list",
            self, "object_items",
            self, "object_index",
            rows=4,
        )
        column = row.column(align=True)
        add_operator = column.operator("mimi.objlist_add_item", text="", icon='ADD')
        add_operator.node_name = self.name
        add_operator.tree_name = tree.name if tree else ""
        remove_operator = column.operator("mimi.objlist_remove_item", text="", icon='REMOVE')
        remove_operator.node_name = self.name
        remove_operator.tree_name = tree.name if tree else ""
        # One click pulls every selected mesh into the list (skips existing).
        add_selected_operator = column.operator("mimi.objlist_add_selected", text="", icon='SELECT_EXTEND')
        add_selected_operator.node_name = self.name
        add_selected_operator.tree_name = tree.name if tree else ""

        index = int(self.object_index)
        if not (0 <= index < len(self.object_items)):
            return
        item = self.object_items[index]

        box = layout.box()
        box.prop(item, "enabled")
        box.prop_search(item, "object_name", bpy.data, "objects", text="", icon='OBJECT_DATA')
        if tree is not None:
            box.prop_search(item, "submesh_name", tree, "ssmt_submesh_items", text=tr("Submesh"), icon='OUTLINER_COLLECTION')


classes = (
    MMT_OT_ObjectListAddItem,
    MMT_OT_ObjectListRemoveItem,
    MMT_OT_ObjectListAddSelected,
    MIMINode_Object_List,
)


def _sync_item_socket_integrity(node):
    '''Recreate missing per-item output sockets and relabel mismatches.

    A blueprint saved by an older version, or an edit that was interrupted,
    can leave the node without the mirrored output socket of an item. The
    item still shows up inside the list, yet there is nothing to wire from.
    This check restores the invariant outputs[i + 1] <-> items[i] that the
    parser and the wiring both rely on. It only ever ADDS sockets or fixes
    labels; foreign or extra sockets are never deleted here.
    '''
    changed = False
    # outputs[0] is the aggregate "All" socket; recreate it only when the
    # node has no outputs at all.
    if len(node.outputs) == 0:
        node.outputs.new('MIMISocketObject', ALL_SOCKET_NAME)
        changed = True
    for index, item in enumerate(node.object_items):
        socket_index = index + 1
        if socket_index >= len(node.outputs):
            node.outputs.new('MIMISocketObject', item.name or "?")
            changed = True
            continue
        socket = node.outputs[socket_index]
        if getattr(socket, "bl_idname", "") != 'MIMISocketObject':
            # A socket we do not own occupies the mirrored slot; skip it
            # instead of deleting data we do not understand.
            continue
        if socket.name != (item.name or "?"):
            socket.name = item.name or "?"
            changed = True
    if changed:
        node._refresh_width()


def _object_list_socket_sync_timer():
    '''Timer entry: keep every Object List node's sockets in sync with its items.'''
    try:
        for tree in bpy.data.node_groups:
            if getattr(tree, "bl_idname", "") != 'MIMIBlueprintTreeType':
                continue
            for node in tree.nodes:
                if getattr(node, "bl_idname", "") == 'MIMINode_Object_List':
                    _sync_item_socket_integrity(node)
    except Exception as error:
        # The timer must never disrupt Blender interaction; a later tick
        # retries once the data is editable again.
        print(f"[MMT Object List] socket sync failed: {error}")
    return 0.5


def register():
    # The PropertyGroup must exist before the node class that references it.
    bpy.utils.register_class(MIMIObjectListItem)
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.timers.is_registered(_object_list_socket_sync_timer):
        bpy.app.timers.register(_object_list_socket_sync_timer, first_interval=0.5, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_object_list_socket_sync_timer):
        bpy.app.timers.unregister(_object_list_socket_sync_timer)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(MIMIObjectListItem)
