"""Synchronize SSMT blueprint Object Info node colors with Blender selection state."""

import bpy


TREE_IDNAME = "SSMTBlueprintTreeType"
OBJECT_INFO_IDNAME = "SSMTNode_Object_Info"
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
    if isinstance(base_color, (list, tuple)) and len(base_color) == 3:
        node.color = tuple(base_color)
    _node_del(node, _STATE_KEY)
    _node_del(node, _BASE_USE_COLOR_KEY)
    _node_del(node, _BASE_COLOR_KEY)


def _matches_selected_object(node, selected_objects) -> bool:
    object_name = str(getattr(node, "object_name", "") or "")
    object_id = str(getattr(node, "object_id", "") or "")
    for obj in selected_objects:
        if object_name and obj.name == object_name:
            return True
        if object_id and object_id == str(obj.get(OBJECT_PERSISTENT_ID_KEY, "") or ""):
            return True
    return False


def _sync_highlights():
    """Apply only changed colors, keeping this safe to run as a short timer."""
    selected_meshes = ()
    for window in getattr(getattr(bpy.context, "window_manager", None), "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                selected_meshes = tuple(
                    obj
                    for obj in getattr(bpy.context, "selected_objects", ())
                    if obj.type == "MESH"
                )
                break
        if selected_meshes:
            break

    for tree in bpy.data.node_groups:
        if getattr(tree, "bl_idname", "") != TREE_IDNAME:
            continue
        for node in tree.nodes:
            color = None
            if getattr(node, "bl_idname", "") == OBJECT_INFO_IDNAME and _matches_selected_object(node, selected_meshes):
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
        print(f"[SSMT Node Highlight] {error}")
    return 0.2


def _restore_all_highlights():
    for tree in getattr(bpy.data, "node_groups", ()):
        if getattr(tree, "bl_idname", "") != TREE_IDNAME:
            continue
        for node in tree.nodes:
            _restore_base_color(node)


def register():
    if not bpy.app.timers.is_registered(_highlight_timer):
        bpy.app.timers.register(_highlight_timer, first_interval=0.2, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_highlight_timer):
        bpy.app.timers.unregister(_highlight_timer)
    _restore_all_highlights()
