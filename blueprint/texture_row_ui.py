"""Shared row gallery for the socketless texture managers.

Global Hash Texture Bind and Global Slot Texture Bind organise their rows
differently on purpose.  A texture hash is globally unique and replaces one
texture wherever the game binds it, while a slot default belongs to exactly one
Submesh and only applies to that Submesh's draws.  Their editing surface does
not have to differ, and it did: one node showed original/replacement
thumbnails, rejected a missing file and offered an explicit clear button, while
the other showed a raw path string that only the export pass validated, minutes
later.

This module owns the parts both nodes share: the row list, the preview pair,
the image chooser, the refresh button and the order of the detail panel.  The
node specific half is declared once as a ``TextureRowProfile`` and registered
by the owning node module, so a field name or an export rule stays with the
node that owns it instead of leaking into a generic draw function.

Nothing here decides what an export writes.  A disabled Hash row restores the
original bytes while a disabled Slot row merely stops binding; that difference
stays in the export path and is only *named* here through ``disabled_hint``, so
two identical-looking panels cannot behave differently without saying so.
"""
import os

import bpy
from bpy_extras.io_utils import ImportHelper

from ..i18n.i18n import I18nOperator, tr
from .hash_texture_preview import texture_icon
from .texture_format_widgets import (
    draw_convert_all,
    draw_node_progress,
    draw_row_controls,
)
from .texture_output_widgets import (
    alias_suffix_note,
    draw_generated_name,
    draw_rename_box,
)

# The only image formats 3Dmigoto loads directly, so the browser offers no other.
TEXTURE_FILE_FILTER = "*.dds;*.png;*.jpg;*.jpeg;*.bmp;*.tga"

# One profile per node type, filled by the node modules at import time.
# Keeping the registry here lets a single UIList serve several node types
# without this module importing the nodes (which would close an import cycle).
_ROW_PROFILES = {}

_ERROR = 'ERROR'
_INFO = 'INFO'


class TextureRowProfile:
    """How one node maps its rows onto the shared gallery.

    Every callable takes the RNA row (and the node where the answer depends on
    it) and returns display data only; no export rule lives here.  Text fields
    are callables so they are translated when the node is drawn, not when the
    add-on is imported.

    ``rows_prop`` / ``index_prop`` name the node's row collection and selected
    index.  The two managers keep them under different RNA names, and the list
    widget can only address RNA by name.
    """

    def __init__(
        self,
        *,
        rows_prop,
        index_prop,
        key,
        list_title,
        title,
        subtitle,
        original_path,
        replacement_path,
        set_file,
        warnings,
        generated_name,
        scope_text,
        empty_hint,
        disabled_hint,
        scope_icon=_INFO,
    ):
        self.rows_prop = rows_prop
        self.index_prop = index_prop
        # Semantic identity of a row. The chooser finds rows by this value and
        # never by list position, because a refresh can insert rows while the
        # file browser is open.
        self.key = key
        # One-line list label; keeps each node's familiar caption.
        self.list_title = list_title
        self.title = title
        self.subtitle = subtitle
        # The captured original and the user's replacement. Both nodes store
        # them under different field names, which is the whole point of the
        # profile.
        self.original_path = original_path
        self.replacement_path = replacement_path
        # Assigning the path must keep the node's own bookkeeping alive, so the
        # node supplies the writer instead of this module poking ``file_path``.
        self.set_file = set_file
        # Node specific status lines, already translated, as (icon, text).
        self.warnings = warnings
        self.generated_name = generated_name
        self.scope_text = scope_text
        self.empty_hint = empty_hint
        self.disabled_hint = disabled_hint
        self.scope_icon = scope_icon


def register_profile(*node_idnames, profile):
    """Attach one profile to the node types that share the same row RNA."""
    for node_idname in node_idnames:
        _ROW_PROFILES[str(node_idname)] = profile


def profile_for(node):
    """Return the row profile of one node, or None when it has none."""
    return _ROW_PROFILES.get(str(getattr(node, "bl_idname", "") or ""))


def _row_text(value):
    """Evaluate one zero-argument profile text field and never fail drawing."""
    if callable(value):
        return str(value() or "")
    return str(value or "")


def _is_file(path):
    """Return whether a stored path still points at a file."""
    text = str(path or "").strip()
    if not text:
        return False
    try:
        # Relative Blender paths resolve exactly like the export pass does.
        return os.path.isfile(bpy.path.abspath(text))
    except Exception:
        return True


def _row_warnings(profile, item):
    """Status lines of one row: node specific ones plus the shared file checks.

    The file checks used to live in one node only.  Both now report a vanished
    replacement and a vanished capture, so a broken row is visible before the
    export pass reaches it.
    """
    warnings = list(profile.warnings(item) or [])
    replacement = str(profile.replacement_path(item) or "").strip()
    if replacement and not _is_file(replacement):
        warnings.append((_ERROR, tr("Replacement file was not found")))
    original = str(profile.original_path(item) or "").strip()
    if original and not _is_file(original):
        warnings.append((_ERROR, tr("Original capture file is missing")))
    return warnings


def draw_preview_card(layout, title, file_path, empty_text):
    """Draw one thumbnail card without touching the user's Image datablocks.

    ``title`` and ``empty_text`` are already translated by the caller, which is
    what keeps both captions visible to the i18n coverage check.
    """
    box = layout.box()
    box.label(text=title)
    icon_id = texture_icon(file_path)
    if icon_id:
        box.template_icon(icon_value=icon_id, scale=6.0)
    elif file_path:
        # A path that does not decode is not the same as "no replacement yet".
        box.label(text=tr("Preview unavailable"), icon='IMAGE_DATA')
    else:
        box.label(text=empty_text, icon='IMAGE_DATA')
    if file_path:
        box.label(text=bpy.path.basename(file_path))


def draw_preview_pair(layout, original_path, replacement_path):
    """Draw the captured original next to the chosen replacement."""
    row = layout.row(align=True)
    draw_preview_card(
        row.column(), tr("Original marked texture"), original_path, tr("Preview unavailable"),
    )
    draw_preview_card(
        row.column(), tr("Replacement texture"), replacement_path, tr("Unchanged"),
    )


def draw_file_picker(layout, node, item):
    """Draw the one chooser both nodes use, plus its explicit clear button."""
    profile = profile_for(node)
    if profile is None:
        return
    row_key = str(profile.key(item) or "")
    if not row_key:
        # A row with no identity cannot be addressed after a refresh and cannot
        # be exported either, so its chooser would be a dead button.
        layout.label(text=tr("This row has no identity yet; refresh the node first"), icon='INFO')
        return
    row = layout.row(align=True)
    select = row.operator(
        "mimi.texture_row_select_file",
        text=tr("Choose Replacement Texture"),
        icon='FILE_FOLDER',
    )
    select.node_name = node.name
    select.tree_name = node.id_data.name
    select.row_key = row_key
    # Clearing is a separate action, not another file browser: an empty path is
    # a meaningful state ("keep the original"), so it must be reachable.
    if not str(profile.replacement_path(item) or "").strip():
        return
    clear = row.operator("mimi.texture_row_clear_file", text="", icon='X')
    clear.node_name = node.name
    clear.tree_name = node.id_data.name
    clear.row_key = row_key


class MIMI_UL_TextureRows(bpy.types.UIList):
    """One-line row gallery: enabled, original, arrow, replacement, status."""

    bl_idname = "MIMI_UL_texture_rows"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        profile = profile_for(data)
        if profile is None:
            # A future node type must still render instead of raising.
            layout.label(text=str(getattr(item, "name", "")))
            return
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=profile.list_title(item), icon_value=texture_icon(profile.original_path(item)))
        row.label(text="", icon='FORWARD')
        replacement = str(profile.replacement_path(item) or "").strip()
        row.label(
            text=bpy.path.basename(replacement) if replacement else tr("Unchanged"),
            icon_value=texture_icon(replacement),
        )
        # The first warning decides the row icon, so a stale target or a
        # deleted file is visible without opening the detail box.
        warnings = _row_warnings(profile, item)
        if warnings:
            row.label(text="", icon=warnings[0][0])


def _draw_row_detail(node, item, index, layout):
    """Draw the detail box of the selected row in the shared order."""
    profile = profile_for(node)
    tree = node.id_data
    box = layout.box()
    box.label(text=profile.title(item))
    # A subtitle is optional: a Hash row names its originating Submesh, a slot
    # default already carries it in the title line.
    subtitle = str(profile.subtitle(item) or "")
    if subtitle:
        box.label(text=subtitle)
    for warning_icon, warning_text in _row_warnings(profile, item):
        box.label(text=warning_text, icon=warning_icon)
    draw_preview_pair(
        box,
        str(profile.original_path(item) or ""),
        str(profile.replacement_path(item) or ""),
    )
    draw_file_picker(box, node, item)
    # Enabled lives next to the hint that says what disabling really does,
    # because that is the one rule the two managers must not blur.
    box.prop(item, "enabled")
    box.prop(item, "force_original_size")
    # Detected original format, readiness and the per-row Convert button.
    draw_row_controls(box, node, item, index, tree)
    generated_name, suffix, suffix_is_certain = profile.generated_name(node, item)
    draw_generated_name(box, generated_name, certainty_note=alias_suffix_note(suffix_is_certain))
    draw_rename_box(box, item, suffix, generated_name)
    if not bool(getattr(item, "enabled", True)):
        box.label(text=_row_text(profile.disabled_hint), icon='INFO')
    layout.label(text=tr("No replacement selected: keep the original texture"), icon='INFO')
    # One click prepares every replacement of this node in the background.
    draw_convert_all(layout, node, tree)


def draw_texture_row_panel(node, layout):
    """Draw the whole panel both socketless managers share.

    The order is fixed here on purpose: refresh, scope, list, one detail box.
    Returns the number of rows the node owns.
    """
    profile = profile_for(node)
    if profile is None:
        # A node without a profile has no rows to manage; say so instead of
        # drawing an empty box that looks like a refresh problem.
        layout.label(text=tr("This texture node has no row profile"), icon='ERROR')
        return 0
    # A running exact-format batch is global, so its progress shows here.
    draw_node_progress(layout)
    refresh = layout.operator(
        "mimi.texture_row_refresh",
        text=tr("Refresh Marked Textures"),
        icon='FILE_REFRESH',
    )
    refresh.node_name = node.name
    refresh.tree_name = node.id_data.name
    layout.label(text=_row_text(profile.scope_text), icon=profile.scope_icon)
    rows = getattr(node, profile.rows_prop, None)
    if not rows:
        layout.label(text=_row_text(profile.empty_hint), icon='INFO')
        return 0
    layout.template_list(
        "MIMI_UL_texture_rows", "mimi_texture_rows_" + node.name,
        node, profile.rows_prop, node, profile.index_prop, rows=4,
    )
    index = min(max(0, int(getattr(node, profile.index_prop, 0))), len(rows) - 1)
    _draw_row_detail(node, rows[index], index, layout)
    return len(rows)


def _resolve_node(operator, context):
    """Resolve the node an operator was invoked from, never another tree."""
    tree = bpy.data.node_groups.get(operator.tree_name) if operator.tree_name else None
    if tree is None and not operator.tree_name:
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
    return tree.nodes.get(operator.node_name) if tree is not None else None


def _resolve_row(operator, node, profile):
    """Find the row an operator targets by its semantic key, never by position."""
    rows = getattr(node, profile.rows_prop, None) or []
    row_key = str(getattr(operator, "row_key", "") or "")
    if not row_key:
        return None
    return next((item for item in rows if str(profile.key(item)) == row_key), None)


class MIMI_OT_TextureRowSelectFile(I18nOperator, ImportHelper):
    """Choose an external image for one row of either global manager."""

    bl_idname = "mimi.texture_row_select_file"
    bl_label = "Choose Replacement Texture"
    bl_description = "Choose an external texture with Blender's file browser"
    bl_options = {'REGISTER', 'UNDO'}

    # ImportHelper supplies filepath; these properties re-find the row after
    # the modal file browser returns control to the operator.
    filter_glob: bpy.props.StringProperty(default=TEXTURE_FILE_FILTER, options={'HIDDEN'}) # type: ignore
    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore
    row_key: bpy.props.StringProperty(default="", options={'HIDDEN'}) # type: ignore

    def invoke(self, context, event):
        node = _resolve_node(self, context)
        profile = profile_for(node)
        row = _resolve_row(self, node, profile) if profile is not None else None
        if row is None:
            self.report({'ERROR'}, tr("Texture row no longer exists"))
            return {'CANCELLED'}
        current_path = str(profile.replacement_path(row) or "").strip()
        if current_path:
            # Reopen beside the current file instead of the last used folder.
            self.filepath = bpy.path.abspath(current_path)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        node = _resolve_node(self, context)
        profile = profile_for(node)
        row = _resolve_row(self, node, profile) if profile is not None else None
        if row is None:
            self.report({'ERROR'}, tr("Texture row no longer exists"))
            return {'CANCELLED'}
        selected_path = str(self.filepath or "").strip()
        selected_path = bpy.path.abspath(selected_path) if selected_path else ""
        selected_path = os.path.normpath(selected_path) if selected_path else ""
        if not selected_path or not os.path.isfile(selected_path):
            self.report({'ERROR'}, tr("Please select a valid texture file"))
            return {'CANCELLED'}
        # The node owns the assignment: a Hash row has to retype itself as a
        # FILE replacement, a Slot row only stores the path.
        profile.set_file(row, selected_path)
        self.report({'INFO'}, tr("Texture file selected: {path}").format(path=selected_path))
        return {'FINISHED'}


class MIMI_OT_TextureRowClearFile(I18nOperator):
    """Clear the stored replacement of one row, leaving the detected fields."""

    bl_idname = "mimi.texture_row_clear_file"
    bl_label = "Clear Replacement Texture"
    bl_description = "Clear Replacement Texture"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore
    row_key: bpy.props.StringProperty(default="", options={'HIDDEN'}) # type: ignore

    def execute(self, context):
        node = _resolve_node(self, context)
        profile = profile_for(node)
        row = _resolve_row(self, node, profile) if profile is not None else None
        if row is None:
            return {'CANCELLED'}
        profile.set_file(row, "")
        return {'FINISHED'}


class MIMI_OT_TextureRowRefresh(I18nOperator):
    """Refresh the rows of either global manager from the workspace marks."""

    bl_idname = "mimi.texture_row_refresh"
    bl_label = "Refresh Marked Textures"
    bl_description = "Re-read the marked textures of this node and keep every replacement choice"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _resolve_node(self, context)
        if node is None or profile_for(node) is None:
            return {'CANCELLED'}
        # One dispatcher keeps this button and the blueprint wide refresh in
        # agreement for both managers.
        from .texture_node_refresh import refresh_texture_node

        try:
            count = refresh_texture_node(node)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, tr("Detected {count} texture marks").format(count=count))
        return {'FINISHED'}


classes = (
    MIMI_UL_TextureRows,
    MIMI_OT_TextureRowSelectFile,
    MIMI_OT_TextureRowClearFile,
    MIMI_OT_TextureRowRefresh,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    # The profiles belong to the node modules, which stay imported; clearing
    # them here would leave a re-registered add-on without a gallery.
