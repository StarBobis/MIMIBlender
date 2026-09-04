"""Synchronize SSMT blueprint node colors with Blender selection state."""

import os

import bpy


TREE_IDNAME = "SSMTBlueprintTreeType"
OBJECT_INFO_IDNAME = "SSMTNode_Object_Info"
TEXTURE_IDNAME = "SSMTNode_Texture"
OBJECT_PERSISTENT_ID_KEY = "_ssmt_object_uuid"

# A Texture node can match both sources. A selected shader node is the more
# explicit interaction, so it takes precedence over the image editor state.
_COLORS = {
    "OBJECT": (0.0, 0.26, 0.27),
    "SHADER_IMAGE": (0.03, 0.28, 0.08),
    "IMAGE_EDITOR": (0.03, 0.12, 0.32),
}

_STATE_KEY = "_ssmt_highlight_state"
_BASE_USE_COLOR_KEY = "_ssmt_highlight_base_use_custom_color"
_BASE_COLOR_KEY = "_ssmt_highlight_base_color"
_base_color_cache: dict[int, tuple[bool, tuple[float, float, float]]] = {}
_last_mismatch_signatures: dict[str, tuple] = {}
_last_shader_editor_debug_signature = None


def _path_key(path: str) -> str:
    path = str(path or "").strip()
    if not path:
        return ""
    try:
        path = bpy.path.abspath(path)
    except Exception:
        pass
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _image_paths(image) -> set[str]:
    paths = set()
    if image is None:
        return paths
    for attribute in ("filepath", "filepath_raw"):
        path = _path_key(getattr(image, attribute, ""))
        if path:
            paths.add(path)
    return paths


def _file_identity(value: str) -> set[str]:
    """Return basename identities for images whose absolute paths differ."""
    filename = os.path.basename(str(value or "").strip()).casefold()
    if not filename:
        return set()
    return {filename, os.path.splitext(filename)[0]}


def _image_identities(image) -> tuple[set[str], set[str]]:
    paths = _image_paths(image)
    filenames = _file_identity(getattr(image, "name", ""))
    for path in paths:
        filenames.update(_file_identity(path))
    return paths, filenames


def _texture_paths(node) -> set[str]:
    """Return the source image plus its generated JPG preview, if present."""
    source_path = _path_key(getattr(node, "texture_filepath", ""))
    if not source_path:
        return set()
    paths = {source_path}
    preview_path = os.path.splitext(source_path)[0] + ".jpg"
    if os.path.isfile(preview_path):
        paths.add(_path_key(preview_path))
    return paths


def _texture_identities(node) -> tuple[set[str], set[str]]:
    paths = _texture_paths(node)
    filenames = _file_identity(getattr(node, "texture_filename", ""))
    for path in paths:
        filenames.update(_file_identity(path))
    return paths, filenames


def _iter_open_editor_spaces(area_type: str):
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == area_type:
                yield area.spaces.active


def _visible_image_editor_sources():
    for space in _iter_open_editor_spaces("IMAGE_EDITOR"):
        image = getattr(space, "image", None)
        if image is not None:
            yield "Image/UV Editor: " + str(getattr(image, "name", "<unnamed>")), *_image_identities(image)


def _open_shader_node_trees():
    """Yield only the trees currently displayed by visible Shader Editors."""
    visited_trees = set()
    for space in _iter_open_editor_spaces("NODE_EDITOR"):
        node_tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
        if getattr(node_tree, "bl_idname", "") != "ShaderNodeTree":
            continue
        pointer = node_tree.as_pointer()
        if pointer not in visited_trees:
            visited_trees.add(pointer)
            yield node_tree


def _shader_editor_debug_descriptions() -> tuple:
    descriptions = []
    for space in _iter_open_editor_spaces("NODE_EDITOR"):
        node_tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
        selected_nodes = tuple(
            node.name
            for node in getattr(node_tree, "nodes", ())
            if getattr(node, "select", False)
        )
        descriptions.append((
            str(getattr(space, "tree_type", "")),
            str(getattr(space, "ui_type", "")),
            str(getattr(node_tree, "name", "")),
            str(getattr(node_tree, "bl_idname", "")),
            selected_nodes,
        ))
    return tuple(descriptions)


def _log_shader_editor_debug_state():
    global _last_shader_editor_debug_signature
    signature = _shader_editor_debug_descriptions()
    previous_signature = _last_shader_editor_debug_signature
    if signature == previous_signature:
        return
    _last_shader_editor_debug_signature = signature
    if signature:
        print("[SSMT Node Highlight] Open Node Editor state: " + repr(signature))
    elif previous_signature:
        print("[SSMT Node Highlight] No open Node Editor is being monitored")


def _selected_shader_image_sources():
    for node_tree in _open_shader_node_trees():
        for node in node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.select:
                image = getattr(node, "image", None)
                yield (
                    "Shader Editor: " + node_tree.name + " / " + node.name,
                    *_image_identities(image),
                )


def _combine_image_identities(image_sources) -> tuple[set[str], set[str]]:
    paths = set()
    filenames = set()
    for _, image_paths, image_filenames in image_sources:
        paths.update(image_paths)
        filenames.update(image_filenames)
    return paths, filenames


def _has_open_editor(area_type: str) -> bool:
    return next(_iter_open_editor_spaces(area_type), None) is not None


def _textures_match(node, image_paths, image_filenames) -> bool:
    texture_paths, texture_filenames = _texture_identities(node)
    return bool(
        texture_paths & image_paths
        or texture_filenames & image_filenames
    )


def _texture_debug_descriptions(texture_nodes) -> tuple:
    descriptions = []
    for tree, node in texture_nodes:
        descriptions.append((
            tree.name,
            node.name,
            str(getattr(node, "texture_filepath", "") or ""),
            str(getattr(node, "texture_filename", "") or ""),
            str(getattr(node, "texture_hash", "") or ""),
        ))
    return tuple(descriptions)


def _log_unmatched_texture_sources(kind, image_sources, texture_nodes):
    """Log a changed mismatch once, so the timer does not flood the console."""
    unmatched_sources = tuple(
        (label, tuple(sorted(image_paths)), tuple(sorted(image_filenames)))
        for label, image_paths, image_filenames in image_sources
        if not any(_textures_match(node, image_paths, image_filenames) for _, node in texture_nodes)
    )
    if not unmatched_sources:
        _last_mismatch_signatures.pop(kind, None)
        return

    texture_descriptions = _texture_debug_descriptions(texture_nodes)
    signature = (unmatched_sources, texture_descriptions)
    if _last_mismatch_signatures.get(kind) == signature:
        return
    _last_mismatch_signatures[kind] = signature
    print(
        "[SSMT Node Highlight] Unmatched " + kind + " image source(s): "
        + repr(unmatched_sources)
        + "; texture_nodes=(tree, node, source_path, filename, hash) "
        + repr(texture_descriptions)
    )


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
    _log_shader_editor_debug_state()
    selected_meshes = ()
    if _has_open_editor("VIEW_3D"):
        selected_meshes = tuple(
            obj for obj in getattr(bpy.context, "selected_objects", ()) if obj.type == "MESH"
        )
    shader_image_sources = tuple(_selected_shader_image_sources())
    image_editor_sources = tuple(_visible_image_editor_sources())
    shader_image_paths, shader_image_filenames = _combine_image_identities(shader_image_sources)
    image_editor_paths, image_editor_filenames = _combine_image_identities(image_editor_sources)
    texture_nodes = [
        (tree, node)
        for tree in bpy.data.node_groups
        if getattr(tree, "bl_idname", "") == TREE_IDNAME
        for node in tree.nodes
        if getattr(node, "bl_idname", "") == TEXTURE_IDNAME
    ]

    _log_unmatched_texture_sources(
        "selected Shader Editor",
        shader_image_sources,
        texture_nodes,
    )
    _log_unmatched_texture_sources(
        "Image/UV Editor",
        image_editor_sources,
        texture_nodes,
    )

    for tree in bpy.data.node_groups:
        if getattr(tree, "bl_idname", "") != TREE_IDNAME:
            continue
        for node in tree.nodes:
            node_type = getattr(node, "bl_idname", "")
            color = None
            if node_type == OBJECT_INFO_IDNAME and _matches_selected_object(node, selected_meshes):
                color = _COLORS["OBJECT"]
            elif node_type == TEXTURE_IDNAME:
                if _textures_match(node, shader_image_paths, shader_image_filenames):
                    color = _COLORS["SHADER_IMAGE"]
                elif _textures_match(node, image_editor_paths, image_editor_filenames):
                    color = _COLORS["IMAGE_EDITOR"]

            if color is None:
                _restore_base_color(node)
            else:
                _set_highlight(node, color)

    for window in getattr(getattr(bpy.context, "window_manager", None), "windows", ()):
        for area in window.screen.areas:
            if area.type in {"NODE_EDITOR", "VIEW_3D", "IMAGE_EDITOR"}:
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
