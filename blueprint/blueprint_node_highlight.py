"""Synchronize MMT blueprint Object Info and Object List node colors with Blender selection state."""

import bpy


TREE_IDNAME = "MIMIBlueprintTreeType"
OBJECT_INFO_IDNAME = "MIMINode_Object_Info"
OBJECT_LIST_IDNAME = "MIMINode_Object_List"
OBJECT_PERSISTENT_ID_KEY = "_ssmt_object_uuid"

_COLORS = {
    "OBJECT": (0.0, 0.26, 0.27),
}

_STATE_KEY = "_ssmt_highlight_state"
_BASE_USE_COLOR_KEY = "_ssmt_highlight_base_use_custom_color"
_BASE_COLOR_KEY = "_ssmt_highlight_base_color"
_base_color_cache: dict[int, tuple[bool, tuple[float, float, float]]] = {}


def _node_get(node, key, default=None):
    try:
        return node.get(key, default)
    except (AttributeError, TypeError):
        return default


def _node_set(node, key, value) -> bool:
    try:
        node[key] = value
        return True
    except (AttributeError, TypeError):
        return False


def _node_del(node, key):
    try:
        if key in node:
            del node[key]
    except (AttributeError, TypeError):
        pass


def _remember_base_color(node):
    pointer = node.as_pointer()
    if pointer in _base_color_cache or _node_get(node, _STATE_KEY) is not None:
        return
    _base_color_cache[pointer] = (bool(node.use_custom_color), tuple(node.color[:]))
    _node_set(node, _STATE_KEY, "active")
    _node_set(node, _BASE_USE_COLOR_KEY, bool(node.use_custom_color))
    _node_set(node, _BASE_COLOR_KEY, list(node.color[:]))


def _set_highlight(node, color):
    _remember_base_color(node)
    if not node.use_custom_color:
        node.use_custom_color = True
    if tuple(node.color[:]) != color:
        node.color = color


def _restore_base_color(node):
    base_color_cache = _base_color_cache.pop(node.as_pointer(), None)
    has_persisted_base = _node_get(node, _STATE_KEY) is not None
    if base_color_cache is None and not has_persisted_base:
        return
    if base_color_cache is not None:
        base_use_color, base_color = base_color_cache
    else:
        base_use_color = _node_get(node, _BASE_USE_COLOR_KEY)
        base_color = _node_get(node, _BASE_COLOR_KEY)
    if base_use_color is not None:
        node.use_custom_color = bool(base_use_color)
    # Saved ID properties use IDPropertyArray after a blend-file reload.
    # Accept that sequence as well as the in-memory list/tuple cache.
    if base_color is not None and len(base_color) == 3:
        node.color = tuple(base_color)
    _node_del(node, _STATE_KEY)
    _node_del(node, _BASE_USE_COLOR_KEY)
    _node_del(node, _BASE_COLOR_KEY)


def _matches_selected_object(node, selected_objects) -> bool:
    # Use the same identity rules as export after renames or name reuse.
    # A stale display name alone must not highlight an unrelated object.
    from .blueprint_node_obj import ObjectPersistentIdManager
    target = ObjectPersistentIdManager.resolve_node_target(node)
    return target is not None and target in selected_objects


def _matches_object_list_item(node, selected_objects) -> bool:
    """An Object List node highlights when any of its items references a selected mesh."""
    items = getattr(node, "object_items", None)
    if not items:
        return False
    selected_names = {obj.name for obj in selected_objects}
    for item in items:
        # Every row references an object, so any match highlights the node.
        reference = getattr(item, "object_ref", None)
        object_name = reference.name if reference is not None else str(getattr(item, "object_name", "") or "").strip()
        if object_name and object_name in selected_names:
            return True
    return False


def _sync_highlights():
    """Apply only changed colors, keeping this safe to run as a short timer."""
    selected_meshes = set()
    for window in getattr(getattr(bpy.context, "window_manager", None), "windows", ()):
        if not any(area.type == "VIEW_3D" for area in window.screen.areas):
            continue
        # A standalone blueprint window may have a different active scene.
        # Read each visible 3D window's own layer rather than global context.
        layer = window.view_layer
        selected_meshes.update(obj for obj in layer.objects if obj.type == "MESH" and obj.select_get(view_layer=layer))

    for tree in bpy.data.node_groups:
        if getattr(tree, "bl_idname", "") != TREE_IDNAME:
            continue
        for node in tree.nodes:
            color = None
            node_idname = getattr(node, "bl_idname", "")
            if node_idname == OBJECT_INFO_IDNAME and _matches_selected_object(node, selected_meshes):
                color = _COLORS["OBJECT"]
            elif node_idname == OBJECT_LIST_IDNAME and _matches_object_list_item(node, selected_meshes):
                color = _COLORS["OBJECT"]

            if color is None:
                _restore_base_color(node)
            else:
                _set_highlight(node, color)

    for window in getattr(getattr(bpy.context, "window_manager", None), "windows", ()):
        for area in window.screen.areas:
            if area.type in {"NODE_EDITOR", "VIEW_3D"}:
                area.tag_redraw()


def _highlight_timer():
    try:
        _sync_highlights()
    except Exception as error:
        # The timer must never disrupt Blender interaction. Registration can
        # briefly expose restricted bpy data, which is retried on the next tick.
        print(f"[MMT Node Highlight] {error}")
    return 0.2


def _restore_all_highlights():
    for tree in getattr(bpy.data, "node_groups", ()):
        if getattr(tree, "bl_idname", "") != TREE_IDNAME:
            continue
        for node in tree.nodes:
            _restore_base_color(node)


@bpy.app.handlers.persistent
def _clear_highlight_cache_after_load(_scene=None):
    # Pointer addresses can be reused by a different node after loading a file.
    # Persisted base colors remain on each node and are the correct fallback.
    _base_color_cache.clear()


def register():
    if _clear_highlight_cache_after_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_clear_highlight_cache_after_load)
    if not bpy.app.timers.is_registered(_highlight_timer):
        bpy.app.timers.register(_highlight_timer, first_interval=0.2, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_highlight_timer):
        bpy.app.timers.unregister(_highlight_timer)
    _restore_all_highlights()
    _base_color_cache.clear()
    if _clear_highlight_cache_after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_clear_highlight_cache_after_load)
