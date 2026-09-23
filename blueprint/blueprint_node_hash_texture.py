'''
Hash texture blueprint nodes.

The conditional node is a transparent Object in/Object out node. Every object
that passes through contributes a texture-hash replacement row. The exporter
merges those rows into one global TextureOverride section per hash and wraps
the replacement in the object's switch condition.

The global node has no object sockets on purpose. Its rows are collected from
the blueprint even when the node is not connected, because a hash replacement
is global by nature and does not need a particular draw call to identify it.

3Dmigoto facts backing this design:
- A TextureOverride section with "hash = xxx" runs whenever the game binds
  that texture, so the replacement applies beyond the connected objects.
- A conditional hash row can use an if/endif block, while a global row uses
  an unconditional this= assignment as the default replacement.
- External files are copied to the generated Mod's Textures folder and are
  declared by a generated resource name, keeping the exported INI portable.

Both nodes scan Hash marks with a Refresh button. The conditional node
only scans upstream connected sources; the global node scans the workspace.
Each unique hash has an original image and an optional external replacement.
Legacy MARK/FILE/RESOURCE fields remain readable for saved blueprints, not as
UI choices. Refreshed rows use the same simple file replacement controls.
'''
import os
import re

import bpy
from bpy.types import PropertyGroup
from bpy_extras.io_utils import ImportHelper

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase
from .hash_texture_preview import texture_icon, clear_previews
from .blueprint_node_texture import (
    _MARK_NAME_NONE,
    _find_submesh_mark_by_name,
    _load_submesh_mark_dicts,
    _resolve_upstream_submesh_name,
    normalize_mark_name_enum_value,
)

# A 3Dmigoto texture hash is 8 hexadecimal characters (a 32-bit hash).
_TEXTURE_HASH_PATTERN = re.compile(r"^[0-9a-f]{8}$")

# Both hash nodes share the same row type and the same add/remove operators.
_HASH_NODE_IDNAMES = {
    'MIMINode_Hash_Texture_Bind',
    'MIMINode_Hash_Texture_Global',
}

# The browser only exposes formats that 3Dmigoto can load directly.
_TEXTURE_FILE_FILTER = "*.dds;*.png;*.jpg;*.jpeg;*.bmp;*.tga"


def _is_hash_texture_node(node):
    '''Return whether a node owns hash texture rows.'''
    return getattr(node, "bl_idname", "") in _HASH_NODE_IDNAMES


def _get_hash_node_items(node):
    '''Return the row collection shared by both hash node variants.'''
    return getattr(node, "texture_hash_items", None)


def _texture_hash_item_refresh_display(item):
    '''Rebuild the one-line display name shown inside the list widget.'''
    source_type = str(getattr(item, "source_type", "") or "")
    if source_type == 'MARK':
        source = str(getattr(item, "mark_name", "") or "").strip() or "?"
    elif source_type == 'FILE':
        source = bpy.path.basename(str(getattr(item, "file_path", "") or "").strip()) or "?"
    else:
        source = str(getattr(item, "resource_name", "") or "").strip() or "?"
    texture_hash = str(getattr(item, "texture_hash", "") or "").strip().lower()
    hash_text = texture_hash[:12] + "..." if len(texture_hash) > 12 else (texture_hash or "?")
    item.name = "{hash} <- {source}".format(hash=hash_text, source=source)


def _texture_hash_item_file_path_changed(item, context):
    '''Treat a manually typed path as an explicit FILE source.'''
    if str(getattr(item, "file_path", "") or "").strip():
        if str(getattr(item, "source_type", "") or "") != 'FILE':
            item.source_type = 'FILE'
        # Global rows need the original mark alongside the replacement image.
        # Changing the replacement must not erase the left-hand preview.
        if getattr(item, "global_detected", False):
            item.global_replacement_used = True
        else:
            item.mark_source_submesh = ""
            item.mark_source_name = ""
            item.mark_source_file_path = ""
    _texture_hash_item_refresh_display(item)


def _find_hash_item_owner(item):
    '''Find the hash node that owns one collection row.'''
    tree = getattr(item, "id_data", None)
    if tree is None:
        return None
    for node in getattr(tree, "nodes", []):
        if not _is_hash_texture_node(node):
            continue
        for candidate in _get_hash_node_items(node) or []:
            if candidate.as_pointer() == item.as_pointer():
                return node
    return None


def _workspace_submesh_names_for_global_marks():
    '''Return every workspace Submesh name that can own a Hash-style mark.'''
    try:
        from ..workspace.mmt_workspace import WorkSpaceModel

        # Use the same LOD/component mapping as the import and export paths.
        # This includes short names and avoids ambiguous aliases in identities.
        return WorkSpaceModel().get_all_new_format_names()
    except Exception:
        # A missing workspace should leave the dropdown usable and empty.
        return []


def _find_global_mark_source_path(submesh_name, mark_filename):
    '''Find a marked texture file below one workspace Submesh folder.'''
    if not submesh_name or not mark_filename:
        return ""
    try:
        from ..workspace.mmt_workspace import MMTWorkSpace

        # The active SubmeshJson selects the correct TYPE folder. Do not pick
        # an arbitrary same-named image from another extracted game type.
        json_path = MMTWorkSpace.check_and_get_submesh_json_path(submesh_name)
        candidate = os.path.join(os.path.dirname(json_path), mark_filename)
        if os.path.isfile(candidate):
            return candidate
    except Exception:
        pass
    return ""


def _connected_submesh_names(node):
    '''Collect only enabled sources reachable through this node's input wires.'''
    from .blueprint_graph import iter_object_sources

    # The shared traversal respects list output ports and custom group outputs.
    # Do not scan other branches simply because they share a workspace/tree.
    names = set()
    for source in iter_object_sources(node):
        name = str(getattr(source, "submesh_name", "") or getattr(source, "object_name", "") or "").strip()
        if name:
            names.add(name)
    return sorted(names)


def _load_global_hash_mark_entries(submesh_names=None):
    '''Build mark records for the workspace or an explicit connected scope.'''
    entries = []
    seen_keys = set()
    if submesh_names is None:
        submesh_names = _workspace_submesh_names_for_global_marks()
    for submesh_name in submesh_names:
        try:
            mark_dict_list = _load_submesh_mark_dicts(submesh_name, dedupe_names=False)
        except Exception:
            # One incomplete Submesh must not hide valid marks elsewhere.
            continue
        for mark_dict in mark_dict_list:
            if mark_dict["type"] != "Hash" or not mark_dict["hash"]:
                continue
            mark_name = str(mark_dict["name"] or "").strip()
            source_path = _find_global_mark_source_path(
                submesh_name=submesh_name,
                mark_filename=mark_dict["filename"],
            )
            source_key = (submesh_name, mark_name.lower(), mark_dict["hash"].lower())
            if not mark_name or source_key in seen_keys:
                continue
            seen_keys.add(source_key)
            safe_submesh = re.sub(r"[^A-Za-z0-9_]", "_", submesh_name)
            safe_mark = re.sub(r"[^A-Za-z0-9_]", "_", mark_name)
            identifier = "global_hash_" + mark_dict["hash"].lower() + "_" + safe_submesh + "_" + safe_mark
            entries.append({
                "identifier": identifier[:63],
                "label": mark_name + " [" + submesh_name + "]",
                "name": mark_name,
                "submesh_name": submesh_name,
                "hash": mark_dict["hash"].lower(),
                "filename": mark_dict["filename"],
                "slot": str(mark_dict.get("slot", "") or "").strip().lower(),
                "source_path": source_path,
            })
    return entries


def _refresh_global_hash_rows(node):
    '''Reconcile scanned marks by hash while preserving replacement choices.'''
    if node.bl_idname == 'MIMINode_Hash_Texture_Global':
        entries = _load_global_hash_mark_entries()
    else:
        entries = _load_global_hash_mark_entries(_connected_submesh_names(node))
    marks = {}
    for entry in entries:
        texture_hash = entry["hash"].strip().lower()
        if _TEXTURE_HASH_PATTERN.fullmatch(texture_hash) is None:
            continue
        # Hashes are globally shared. Prefer an available original image when
        # multiple Submeshes refer to the same texture, but emit only one row.
        if texture_hash not in marks or not marks[texture_hash]["source_path"]:
            marks[texture_hash] = entry

    saved = {}
    selected_hash = ""
    for index, item in enumerate(node.texture_hash_items):
        texture_hash = item.texture_hash.strip().lower()
        if index == node.texture_hash_index:
            selected_hash = texture_hash
        state = {
            "file_path": item.file_path,
            "enabled": item.enabled,
            "replacement_used": item.global_replacement_used,
            "name": item.mark_source_name,
            "submesh_name": item.mark_source_submesh,
            "source_path": item.mark_source_file_path,
            "slot": item.mark_source_slot,
        }
        if texture_hash not in saved or state["file_path"]:
            saved[texture_hash] = state

    # Discovery finishes before mutating RNA. Existing choices are keyed by
    # hash rather than list index, so inserting/reordering marks is harmless.
    node.texture_hash_items.clear()
    for texture_hash in sorted(set(marks) | set(saved)):
        entry = marks.get(texture_hash)
        previous = saved.get(texture_hash, {})
        if entry is None and not previous.get("file_path"):
            continue
        item = node.texture_hash_items.add()
        item.global_detected = True
        item.texture_hash = texture_hash
        item.source_type = 'FILE'
        item.enabled = previous.get("enabled", True)
        item.global_replacement_used = previous.get("replacement_used", False)
        item.file_path = previous.get("file_path", "")
        # Retain a configured missing mark for review instead of silently
        # deleting its replacement. Export will reject active stale entries.
        original = entry or previous
        item.mark_missing = entry is None
        item.mark_source_name = original.get("name", "")
        item.mark_source_submesh = original.get("submesh_name", "")
        item.mark_source_file_path = original.get("source_path", "")
        item.mark_source_slot = str(original.get("slot", "") or "").strip().lower()
        item.name = texture_hash + " - " + item.mark_source_name
        if texture_hash == selected_hash:
            node.texture_hash_index = len(node.texture_hash_items) - 1
    node.texture_hash_index = min(max(0, node.texture_hash_index), max(0, len(node.texture_hash_items) - 1))
    clear_previews()
    return len(marks)


class MMT_OT_GlobalHashRefresh(I18nOperator):
    '''Refresh marks using the scope of the target Hash node.'''
    # Keep the operator ID for compatibility with saved operator history.
    bl_idname = "mimi.global_hash_refresh"
    bl_label = "Refresh Hash Texture Marks"
    bl_description = "Refresh marked Hash textures and preserve replacement choices"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _find_hash_node_for_operator(self, context)
        if not _is_hash_texture_node(node):
            return {'CANCELLED'}
        try:
            count = _refresh_global_hash_rows(node)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, tr("Detected {count} Hash texture marks").format(count=count))
        return {'FINISHED'}


class MIMI_UL_GlobalHashTextures(bpy.types.UIList):
    '''Compact original/replacement thumbnails with a selectable detail view.'''
    bl_idname = "MIMI_UL_global_hash_textures"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.mark_source_name or item.texture_hash,
                  icon_value=texture_icon(item.mark_source_file_path))
        row.label(text="", icon='FORWARD')
        row.label(text=bpy.path.basename(item.file_path) if item.file_path else tr("Unchanged"),
                  icon_value=texture_icon(item.file_path))
        if item.mark_missing:
            row.label(text="", icon='ERROR')


def _draw_global_texture_preview(layout, title, file_path):
    '''Draw thumbnails side by side without altering Blender Image datablocks.'''
    box = layout.box()
    box.label(text=tr(title))
    icon_id = texture_icon(file_path)
    if icon_id:
        box.template_icon(icon_value=icon_id, scale=6.0)
    else:
        message = "Preview unavailable" if file_path or title == "Original marked texture" else "Unchanged"
        box.label(text=tr(message), icon='IMAGE_DATA')
    if file_path:
        box.label(text=bpy.path.basename(file_path))


def _find_global_hash_mark_by_identifier(identifier):
    '''Find the workspace mark represented by a global enum identifier.'''
    for entry in _load_global_hash_mark_entries():
        if entry["identifier"] == str(identifier or ""):
            return entry
    return None


def _texture_hash_source_type_items(item, context):
    '''Return source choices for either conditional or global hash nodes.'''
    return [
        ('FILE', tr("External File"), tr("Copy an external image file into the generated mod")),
        ('MARK', tr("Marked Texture"), tr("Reuse the source file of a Hash-style mark from the SSMT5 texture mark page of this Submesh")),
        ('RESOURCE', tr("Existing Resource"), tr("Reference an existing [ResourceXXX] section by name")),
    ]


class MIMITextureHashItem(PropertyGroup):
    '''One hash texture replacement row shared by both hash nodes.'''
    name: bpy.props.StringProperty(name=tr("Binding"), default="") # type: ignore

    enabled: bpy.props.BoolProperty(
        name=tr("Enabled"),
        description=tr("Disabled rows are skipped at export time"),
        default=True,
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore

    texture_hash: bpy.props.StringProperty(
        name=tr("Texture Hash"),
        description=tr("Hash of the original texture to replace (8 hexadecimal characters, a 32-bit texture hash); the override applies wherever the game binds this hash"),
        default="",
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore

    source_type: bpy.props.EnumProperty(
        name=tr("Source"),
        description=tr("Where the replacement texture comes from"),
        items=_texture_hash_source_type_items,
        # Dynamic enum item callbacks use an integer index for the default;
        # FILE is intentionally the first option for both hash node variants.
        default=0,
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore

    mark_name: bpy.props.EnumProperty(
        name=tr("Mark Name"),
        description=tr("Hash-style mark from the SSMT5 texture mark page; its texture file is copied into the generated mod. Picking one fills the texture hash automatically"),
        items=lambda self, context: _texture_hash_bind_mark_name_items(self),
        update=lambda self, context: _texture_hash_item_mark_changed(self),
    ) # type: ignore

    # Global mark selections keep their source identity separately because the
    # same mark label can occur in many Submeshes in one workspace.
    mark_source_submesh: bpy.props.StringProperty(default="", options={'HIDDEN'}) # type: ignore
    mark_source_name: bpy.props.StringProperty(default="", options={'HIDDEN'}) # type: ignore
    mark_source_file_path: bpy.props.StringProperty(default="", options={'HIDDEN'}) # type: ignore
    # Texture slot of the marked texture (such as ps-t0). A row that knows its
    # slot can bind the replacement inside the owning object's draw section,
    # which scopes the replacement to that object instead of the whole hash.
    mark_source_slot: bpy.props.StringProperty(default="", options={'HIDDEN'}) # type: ignore
    # Scanned rows are optional replacements, not automatic MARK overrides.
    # Keep stale configured rows visible so a refresh never loses user work.
    global_detected: bpy.props.BoolProperty(default=False, options={'HIDDEN'}) # type: ignore
    # Remember edited rows so clearing/disabling can restore the original
    # bytes under a previously overwritten marked output filename.
    global_replacement_used: bpy.props.BoolProperty(default=False, options={'HIDDEN'}) # type: ignore
    mark_missing: bpy.props.BoolProperty(default=False, options={'HIDDEN'}) # type: ignore

    file_path: bpy.props.StringProperty(
        name=tr("Texture File"),
        description=tr("Image file (dds, png, jpg, bmp or tga) copied into the generated mod at export time"),
        subtype='FILE_PATH',
        default="",
        update=_texture_hash_item_file_path_changed,
    ) # type: ignore

    resource_name: bpy.props.StringProperty(
        name=tr("Resource Name"),
        description=tr("Name of an existing [ResourceXXX] section, e.g. ResourceMySharedTexture"),
        default="",
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore


def _find_owner_hash_bind_node(item):
    '''Find the Hash Texture Bind node that owns the given collection item.'''
    return _find_hash_item_owner(item)


def _texture_hash_item_mark_changed(item):
    '''Picking a mark fills the hash and source metadata automatically.'''
    owner = _find_owner_hash_bind_node(item)
    if getattr(owner, "bl_idname", "") == 'MIMINode_Hash_Texture_Global':
        global_mark = _find_global_hash_mark_by_identifier(item.mark_name)
        if global_mark:
            item.texture_hash = global_mark["hash"]
            item.mark_source_submesh = global_mark["submesh_name"]
            item.mark_source_name = global_mark["name"]
            item.mark_source_file_path = global_mark["source_path"]
            item.mark_source_slot = str(global_mark.get("slot", "") or "").strip().lower()
        else:
            item.mark_source_submesh = ""
            item.mark_source_name = ""
            item.mark_source_file_path = ""
            item.mark_source_slot = ""
        _texture_hash_item_refresh_display(item)
        return

    mark_dict = _find_submesh_mark_by_name(item, _find_owner_hash_bind_node)
    if mark_dict and mark_dict["hash"]:
        item.texture_hash = mark_dict["hash"]
        # The slot lets this row bind per object instead of per hash.
        item.mark_source_slot = str(mark_dict.get("slot", "") or "").strip().lower()
    _texture_hash_item_refresh_display(item)


def _texture_hash_bind_mark_name_items(item):
    '''Enum items for conditional or workspace-wide Hash mark dropdowns.'''
    empty_items = [(_MARK_NAME_NONE, "(" + tr("none") + ")", "")]
    try:
        node = _find_owner_hash_bind_node(item)
        if getattr(node, "bl_idname", "") == 'MIMINode_Hash_Texture_Global':
            global_items = list(empty_items)
            for entry in _load_global_hash_mark_entries():
                global_items.append((entry["identifier"], entry["label"], entry["source_path"] or entry["filename"]))
            return global_items

        submesh_name = _resolve_upstream_submesh_name(node)
        if not submesh_name:
            return empty_items
        items = list(empty_items)
        for mark_dict in _load_submesh_mark_dicts(submesh_name):
            # Only Hash-style marks make sense for this node.
            if mark_dict["type"] != "Hash":
                continue
            items.append((mark_dict["name"], mark_dict["name"], ""))
        return items if len(items) > 1 else empty_items
    except Exception:
        # Never let a dropdown lookup break the node editor drawing.
        return empty_items


def _find_hash_node_for_operator(operator, context):
    '''Resolve an operator's explicit node target without cross-tree fallback.'''
    tree = bpy.data.node_groups.get(operator.tree_name) if operator.tree_name else None
    if tree is None and not operator.tree_name:
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
    if tree is None:
        return None
    node = tree.nodes.get(operator.node_name)
    if node is None or not _is_hash_texture_node(node):
        return None
    return node


class MMT_OT_TexHashBindSelectFile(I18nOperator, ImportHelper):
    '''Choose an external image with Blender's file browser.'''
    bl_idname = "mimi.texhashbind_select_file"
    bl_label = "Choose Hash Texture File"
    bl_description = "Choose an external texture with Blender's file browser"
    bl_options = {'REGISTER', 'UNDO'}

    # ImportHelper supplies filepath; these properties identify the row after
    # the modal file browser returns control to the operator.
    filter_glob: bpy.props.StringProperty(
        default=_TEXTURE_FILE_FILTER,
        options={'HIDDEN'},
    ) # type: ignore
    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore
    item_index: bpy.props.IntProperty(default=-1, options={'HIDDEN'}) # type: ignore
    target_hash: bpy.props.StringProperty(default="", options={'HIDDEN'}) # type: ignore

    def invoke(self, context, event):
        node = _find_hash_node_for_operator(self, context)
        items = _get_hash_node_items(node) if node is not None else None
        if items is None or not 0 <= self.item_index < len(items):
            self.report({'ERROR'}, tr("Hash texture row no longer exists"))
            return {'CANCELLED'}

        # Reopen beside the current file when the row already has a path.
        current_path = str(getattr(items[self.item_index], "file_path", "") or "").strip()
        if current_path:
            self.filepath = bpy.path.abspath(current_path)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        node = _find_hash_node_for_operator(self, context)
        items = _get_hash_node_items(node) if node is not None else None
        if items is not None and self.target_hash:
            # Refresh in another editor may reorder rows while the file
            # browser is open. Assign by hash instead of a stale list index.
            self.item_index = next((i for i, item in enumerate(items) if item.texture_hash == self.target_hash), -1)
        if items is None or not 0 <= self.item_index < len(items):
            self.report({'ERROR'}, tr("Hash texture row no longer exists"))
            return {'CANCELLED'}

        selected_path = str(self.filepath or "").strip()
        selected_path = bpy.path.abspath(selected_path) if selected_path else ""
        selected_path = os.path.normpath(selected_path) if selected_path else ""
        if not selected_path or not os.path.isfile(selected_path):
            self.report({'ERROR'}, tr("Please select a valid texture file"))
            return {'CANCELLED'}

        item = items[self.item_index]
        item.file_path = selected_path
        # Selecting a file is also an explicit source choice, even when the
        # row previously referenced a mark or an existing resource.
        item.source_type = 'FILE'
        _texture_hash_item_refresh_display(item)
        self.report({'INFO'}, tr("Hash texture file selected: {path}").format(path=selected_path))
        return {'FINISHED'}


class MMT_OT_TexHashBindClearFile(I18nOperator):
    '''Clear the external file path of one hash texture row.'''
    bl_idname = "mimi.texhashbind_clear_file"
    bl_label = "Clear Hash Texture File"
    bl_description = "Clear Hash Texture File"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore
    item_index: bpy.props.IntProperty(default=-1, options={'HIDDEN'}) # type: ignore

    def execute(self, context):
        node = _find_hash_node_for_operator(self, context)
        items = _get_hash_node_items(node) if node is not None else None
        if items is None or not 0 <= self.item_index < len(items):
            return {'CANCELLED'}
        items[self.item_index].file_path = ""
        _texture_hash_item_refresh_display(items[self.item_index])
        return {'FINISHED'}


class MMT_OT_TexHashBindAddItem(I18nOperator):
    '''Add one hash texture binding row to a Hash Texture Bind node'''
    bl_idname = "mimi.texhashbind_add_item"
    bl_label = "Add Hash Texture Binding"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _find_hash_node_for_operator(self, context)
        if node is None:
            return {'CANCELLED'}
        item = node.texture_hash_items.add()
        _texture_hash_item_refresh_display(item)
        node.texture_hash_index = len(node.texture_hash_items) - 1
        return {'FINISHED'}


class MMT_OT_TexHashBindRemoveItem(I18nOperator):
    '''Remove the selected hash texture binding row from a Hash Texture Bind node'''
    bl_idname = "mimi.texhashbind_remove_item"
    bl_label = "Remove Hash Texture Binding"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _find_hash_node_for_operator(self, context)
        if node is None:
            return {'CANCELLED'}
        index = int(getattr(node, "texture_hash_index", 0))
        if 0 <= index < len(node.texture_hash_items):
            node.texture_hash_items.remove(index)
            node.texture_hash_index = max(0, min(index, len(node.texture_hash_items) - 1))
        return {'FINISHED'}


class MMT_OT_TexHashBindAutoFill(I18nOperator):
    '''Add one binding row for every Hash-style mark of the upstream Submesh'''
    bl_idname = "mimi.texhashbind_autofill"
    bl_label = "Auto Fill From Marks"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        # Explicit targets must not fall back to another open blueprint.
        if tree is None and not self.tree_name:
            tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if tree is None:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Hash_Texture_Bind':
            return {'CANCELLED'}

        submesh_name = _resolve_upstream_submesh_name(node)
        if not submesh_name:
            self.report({'ERROR'}, tr("Upstream Submesh not resolved; set the Submesh on the upstream Object Info node first"))
            return {'CANCELLED'}

        # Rows already referencing a mark are kept untouched; the operator
        # only appends what is missing, so it is safe to press repeatedly.
        existing_names = set()
        for row_item in node.texture_hash_items:
            if str(row_item.source_type or "") == 'MARK':
                existing_names.add(normalize_mark_name_enum_value(row_item.mark_name).lower())

        added_count = 0
        skipped_count = 0
        try:
            mark_dict_list = _load_submesh_mark_dicts(submesh_name)
        except Exception as error:
            self.report({'ERROR'}, tr("Failed to read the texture marks of Submesh") + " '" + submesh_name + "': " + str(error))
            return {'CANCELLED'}

        for mark_dict in mark_dict_list:
            if mark_dict["type"] != "Hash":
                continue
            if not mark_dict["name"] or mark_dict["name"].lower() in existing_names:
                skipped_count += 1
                continue
            if not mark_dict["hash"]:
                print("Hash Texture Bind auto fill: mark '" + mark_dict["name"] + "' has no MarkHash, skipped")
                skipped_count += 1
                continue
            row_item = node.texture_hash_items.add()
            row_item.enabled = True
            row_item.texture_hash = mark_dict["hash"]
            row_item.source_type = 'MARK'
            row_item.mark_name = mark_dict["name"]
            _texture_hash_item_refresh_display(row_item)
            added_count += 1
            existing_names.add(mark_dict["name"].lower())

        node.texture_hash_index = len(node.texture_hash_items) - 1
        self.report({'INFO'}, tr("Auto fill done: {added} row(s) added, {skipped} skipped").format(added=added_count, skipped=skipped_count))
        return {'FINISHED'}


def _draw_hash_file_picker(layout, item, node, tree, item_index):
    '''Use one chooser, without Blender's extra FILE_PATH browse control.'''
    row = layout.row(align=True)

    select_operator = row.operator(
        "mimi.texhashbind_select_file",
        text=tr("Choose Replacement Texture"),
        icon='FILE_FOLDER',
    )
    select_operator.node_name = node.name
    select_operator.tree_name = tree.name if tree else ""
    select_operator.item_index = item_index
    select_operator.target_hash = item.texture_hash if item.global_detected else ""

    # Clearing is a separate action, not another file chooser. Hide it until
    # a replacement exists, and keep filenames visible in the preview cards.
    if not item.file_path:
        return
    clear_operator = row.operator(
        "mimi.texhashbind_clear_file",
        text="",
        icon='X',
    )
    clear_operator.node_name = node.name
    clear_operator.tree_name = tree.name if tree else ""
    clear_operator.item_index = item_index


def _draw_hash_replacements(node, context, layout):
    '''Both nodes use the same controls; only the discovery scope differs.'''
    tree = node.id_data
    refresh = layout.operator("mimi.global_hash_refresh", text=tr("Refresh Hash Texture Marks"), icon='FILE_REFRESH')
    refresh.node_name = node.name
    refresh.tree_name = tree.name
    if node.bl_idname == 'MIMINode_Hash_Texture_Global':
        layout.label(text=tr("Scope: all workspace Hash marks"), icon='WORLD')
    else:
        layout.label(text=tr("Scope: connected upstream Hash marks only"), icon='LINKED')
    if not node.texture_hash_items:
        layout.label(text=tr("Refresh to detect marked Hash textures"), icon='INFO')
        return

    # No editable hash/source fields, and no FILE_PATH widget with its own
    # implicit browse button. All visible captions translate at draw time.
    layout.template_list(
        "MIMI_UL_global_hash_textures", "mimi_hash_replacements_" + node.name,
        node, "texture_hash_items", node, "texture_hash_index", rows=4,
    )
    index = min(max(0, int(node.texture_hash_index)), len(node.texture_hash_items) - 1)
    item = node.texture_hash_items[index]
    box = layout.box()
    box.label(text=item.texture_hash + " - " + item.mark_source_name)
    box.label(text=item.mark_source_submesh)
    if item.mark_missing:
        box.label(text=tr("Mark is outside the current scope; clear its replacement or disable this row"), icon='ERROR')
    elif not item.global_detected:
        box.label(text=tr("Refresh to detect marked Hash textures"), icon='INFO')
    previews = box.row(align=True)
    _draw_global_texture_preview(previews.column(), "Original marked texture", item.mark_source_file_path)
    _draw_global_texture_preview(previews.column(), "Replacement texture", item.file_path)
    _draw_hash_file_picker(box, item, node, tree, index)
    if item.file_path and not os.path.isfile(bpy.path.abspath(item.file_path)):
        box.label(text=tr("Replacement file was not found"), icon='ERROR')
    layout.label(text=tr("No replacement selected: keep the original texture"), icon='INFO')


@translatable
class MIMINode_Hash_Texture_Bind(MIMINodeBase):
    '''Hash Texture Bind replaces a texture hash with conditional this= blocks while the upstream switch conditions hold'''
    bl_idname = 'MIMINode_Hash_Texture_Bind'
    bl_label = 'Hash Texture Bind'
    bl_icon = 'TEXTURE_DATA'
    bl_width_min = 340

    texture_hash_items: bpy.props.CollectionProperty(type=MIMITextureHashItem) # type: ignore
    texture_hash_index: bpy.props.IntProperty(default=0) # type: ignore

    def width_texts(self):
        """Return every text that decides how wide this node has to be."""
        return [self.label]

    def init(self, context):
        # The default title is instance data, so bake in the active language.
        self.label = tr("Hash Texture Bind")
        self.inputs.new('MIMISocketObject', "Object")
        self.outputs.new('MIMISocketObject', "Output")
        self.width = 480
        self.use_custom_color = True
        self.color = (0.16, 0.42, 0.55)

    def draw_buttons(self, context, layout):
        _draw_hash_replacements(self, context, layout)

        # This node is a conditional pass-through. A dangling output means
        # the exporter cannot reach it from Generate Mod, so make the silent
        # no-op visible and point users to the socket-less global node.
        if not self.outputs or not self.outputs[0].is_linked:
            layout.label(
                text=tr("Hash Texture Bind output is not connected; use Global Hash Texture Bind for an unconditional replacement"),
                icon='ERROR',
            )



@translatable
class MIMINode_Hash_Texture_Global(MIMINodeBase):
    '''Specify unconditional global hash replacements without object links.'''
    bl_idname = 'MIMINode_Hash_Texture_Global'
    bl_label = 'Global Hash Texture Bind'
    bl_icon = 'TEXTURE_DATA'
    bl_width_min = 340

    texture_hash_items: bpy.props.CollectionProperty(type=MIMITextureHashItem) # type: ignore
    texture_hash_index: bpy.props.IntProperty(default=0) # type: ignore

    def width_texts(self):
        """Return every text that decides how wide this node has to be."""
        return [self.label]

    def init(self, context):
        # This node deliberately has no sockets: hash replacements are global
        # and must not be tied to an individual object's draw path.
        self.label = tr("Global Hash Texture Bind")
        self.width = 480
        self.use_custom_color = True
        self.color = (0.25, 0.48, 0.30)

    def draw_buttons(self, context, layout):
        _draw_hash_replacements(self, context, layout)


classes = (
    MMT_OT_GlobalHashRefresh,
    MIMI_UL_GlobalHashTextures,
    MMT_OT_TexHashBindSelectFile,
    MMT_OT_TexHashBindClearFile,
    MMT_OT_TexHashBindAddItem,
    MMT_OT_TexHashBindRemoveItem,
    MMT_OT_TexHashBindAutoFill,
    MIMINode_Hash_Texture_Bind,
    MIMINode_Hash_Texture_Global,
)


def register():
    # The PropertyGroup must exist before the node class that references it.
    bpy.utils.register_class(MIMITextureHashItem)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    clear_previews()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(MIMITextureHashItem)
