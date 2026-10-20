"""Shared exact-format UI for the four texture replacement nodes.

This module owns everything the node panels need besides their own rows:

- the RNA enum callbacks (manual format list and format source),
- the per-row status line ("Converted: BC7_UNORM_SRGB", "Needs conversion"),
- the Convert / Convert All / Cancel buttons,
- the shared progress line while a background batch is running.

The conversion itself never runs here. The work is delegated to
``common.texture_format_service`` so the node draw code stays short and every
node reports the same state.
"""
import bpy

from ..common import texture_format_service as service
from ..i18n.i18n import I18nOperator, tr
from ..texcomb.core import dds_match

# A saved node must always have a valid enum value, even if texcomb cannot be
# imported (for example while a partial install is loaded). These formats are
# the common colour targets used by the supported games.
FALLBACK_FORMATS = (
    "BC7_UNORM_SRGB",
    "BC7_UNORM",
    "BC3_UNORM_SRGB",
    "BC5_UNORM",
    "R8G8B8A8_UNORM_SRGB",
)
DEFAULT_MANUAL_FORMAT = "BC7_UNORM_SRGB"


def manual_format_items(self, context):
    """Dynamic enum items listing every format texconv can write."""
    try:
        names = dds_match.format_names()
    except Exception:
        # Import failures must not make the node editor unable to draw.
        names = FALLBACK_FORMATS
    return [(name, name, tr("Convert the replacement to this DXGI format")) for name in names]


def format_mode_items(self, context):
    """Auto follows the capture; Manual is the explicit fallback."""
    return [
        ('AUTO', tr("Auto (match original)"),
         tr("Convert the replacement to the format detected on the original game texture")),
        ('MANUAL', tr("Manual format"),
         tr("Convert the replacement to the format selected below, even when no original can be resolved")),
    ]


def row_target_format(node, item):
    """Return (target_format, state, detail) for one replacement row.

    ``state`` reuses the service states: resolved, missing or conflict. When
    a manual format is selected and no capture exists it becomes the target.
    """
    source = service._row_file_path(item)
    if not source:
        return "", service.STATE_MISSING, ""
    if getattr(node, "bl_idname", "") in ('MIMINode_Texture_Bind', 'MIMINode_Hash_Texture_Bind'):
        if str(getattr(item, "source_type", "") or "") != 'FILE':
            return "", service.STATE_MISSING, ""
    selectors = service.row_selectors(node, item)
    submesh = service.row_submesh(node, item)
    metadata, state, detail, _agreed = service.resolve_original(submesh_name=submesh, **selectors)
    mode = str(getattr(item, "format_mode", "AUTO") or "AUTO").strip().upper()
    manual = str(getattr(item, "manual_format", "") or "").strip()
    if state == service.STATE_CONFLICT:
        return "", state, detail
    if metadata is not None:
        # An available capture always wins, which matches the export rule.
        return metadata.format, state, ""
    if mode == "MANUAL" and manual:
        return manual, service.STATE_RESOLVED, ""
    return "", service.STATE_MISSING, ""


def predicted_suffix(node, item, source_path):
    """Return (suffix, is_certain) of the file the export will really write.

    Before exact-format conversion the generated name simply followed the
    source image suffix. That stopped being true for a resolved capture: the
    replacement is then always written as a DDS. Using the same lookup as the
    status line keeps the node preview and the exporter in agreement.
    """
    from .texture_output_widgets import exact_format_enabled, texture_source_suffix

    source_suffix = texture_source_suffix(source_path)
    if not exact_format_enabled():
        # The global switch restores the historical copy-as-is behaviour.
        return source_suffix, True
    target_format, _state, _detail = row_target_format(node, item)
    if target_format:
        # A resolved capture or an explicit manual format always becomes DDS.
        return ".dds", True
    # No capture today means the raw copy keeps its suffix, but extracting or
    # refreshing the workspace can turn the row into a converted DDS, so the
    # preview stays labelled as "may still change".
    return source_suffix, False


def row_status(node, item):
    """Return (icon, text) describing the conversion state of one row."""
    source = service._row_file_path(item)
    if not source:
        return 'NONE', ""
    if getattr(node, "bl_idname", "") in ('MIMINode_Texture_Bind', 'MIMINode_Hash_Texture_Bind'):
        if str(getattr(item, "source_type", "") or "") != 'FILE':
            # Mark rows reuse the captured file bytes and need no conversion.
            return 'NONE', ""
    target, state, detail = row_target_format(node, item)
    if state == service.STATE_CONFLICT:
        return 'ERROR', tr("Original formats disagree: {formats}").format(formats=detail)
    if not target:
        return 'INFO', tr("Original format unknown; the replacement is copied unchanged")
    cached = service.get_cache().lookup(source)
    if cached and str(cached.get("format", "")) == target:
        return 'CHECKMARK', tr("Converted: {format}").format(format=target)
    if service.is_running():
        return 'TIME', tr("Waiting for conversion: {format}").format(format=target)
    return 'INFO', tr("Needs conversion to {format}").format(format=target)


def draw_row_status(layout, node, item):
    """Draw the one-line status of a row without adding any control."""
    icon, text = row_status(node, item)
    if text:
        layout.label(text=text, icon=icon if icon != 'NONE' else 'INFO')


def draw_row_controls(layout, node, item, row_index, tree):
    """Draw the per-row status plus the Convert / Cancel buttons."""
    draw_row_status(layout, node, item)
    row = layout.row(align=True)
    convert = row.operator("mimi.texture_format_convert", text=tr("Convert Now"), icon='FILE_REFRESH')
    convert.node_name = node.name
    convert.tree_name = tree.name if tree else ""
    convert.row_index = int(row_index)
    if service.is_running():
        row.operator("mimi.texture_format_cancel", text="", icon='CANCEL')


def draw_node_progress(layout):
    """Draw the shared batch progress line; returns True while running."""
    snapshot = service.progress_snapshot()
    if snapshot["running"]:
        layout.label(
            text=tr("Converting {done}/{total}: {current}").format(
                done=snapshot["done"], total=snapshot["total"], current=snapshot["current"] or "",
            ),
            icon='TIME',
        )
        return True
    message = service.last_message()
    if message:
        layout.label(text=message, icon='INFO')
    return False


def draw_convert_all(layout, node, tree, label=None):
    """Draw the node level Convert All button."""
    operator = layout.operator(
        "mimi.texture_format_convert",
        text=tr(label) if label else tr("Convert All Replacements"),
        icon='FILE_REFRESH',
    )
    operator.node_name = node.name
    operator.tree_name = tree.name if tree else ""
    operator.row_index = -1


def _resolve_node(operator, context):
    """Resolve the node an operator was invoked from, never another tree."""
    tree = bpy.data.node_groups.get(operator.tree_name) if operator.tree_name else None
    if tree is None and not operator.tree_name:
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
    if tree is None:
        return None, None
    return tree, tree.nodes.get(operator.node_name)


class MIMI_OT_TextureFormatConvert(I18nOperator):
    """Convert one row, or every row of the node when row_index is -1."""
    bl_idname = "mimi.texture_format_convert"
    bl_label = "Convert Replacement Textures"
    bl_description = "Convert replacement textures to the exact format of the original game texture in the background"
    bl_options = {'REGISTER'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore
    row_index: bpy.props.IntProperty(default=-1) # type: ignore

    def execute(self, context):
        tree, node = _resolve_node(self, context)
        if tree is None:
            self.report({'ERROR'}, tr("Texture node was not found"))
            return {'CANCELLED'}
        # An empty node name means "every replacement in this blueprint".
        if node is None and self.node_name:
            self.report({'ERROR'}, tr("Texture node was not found"))
            return {'CANCELLED'}
        if node is None:
            jobs = service.collect_tree_jobs(tree)
        else:
            rows = service.node_rows(node)
            if 0 <= self.row_index < len(rows):
                selected_rows = [rows[self.row_index]]
            else:
                selected_rows = service.enabled_rows(node)
            submesh = service.upstream_submesh(node)
            jobs = []
            for item in selected_rows:
                job = service.job_for_row(node, item, submesh)
                if job:
                    jobs.append(job)
        if not jobs:
            self.report({'INFO'}, tr("No replacement needs exact format conversion"))
            return {'FINISHED'}
        started = service.start_conversion(jobs)
        if not started:
            if service.is_running():
                self.report({'WARNING'}, tr("A conversion is already running"))
            else:
                self.report({'ERROR'}, tr("Texture format conversion could not start; see the console for details"))
            return {'CANCELLED'}
        self.report({'INFO'}, tr("Converting {count} replacement texture(s)").format(count=started))
        return {'FINISHED'}


class MIMI_OT_TextureFormatCancel(I18nOperator):
    """Stop the background batch after the current texture."""
    bl_idname = "mimi.texture_format_cancel"
    bl_label = "Cancel Texture Conversion"
    bl_description = "Stop converting after the current replacement texture"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not service.is_running():
            return {'CANCELLED'}
        service.cancel_conversion()
        self.report({'INFO'}, tr("Cancelling texture format conversion"))
        return {'FINISHED'}


class MIMI_OT_TextureFormatClearCache(I18nOperator):
    """Delete every converted texture of the current workspace cache."""
    bl_idname = "mimi.texture_format_clear_cache"
    bl_label = "Clear Texture Conversion Cache"
    bl_description = "Delete the converted replacement textures of this workspace; they are recreated on demand"
    bl_options = {'REGISTER'}

    def execute(self, context):
        cache = service.get_cache()
        freed = cache.total_size()
        try:
            cache.clear()
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        service.clear_lookup_cache()
        self.report({'INFO'}, tr("Removed {size} of cached texture conversions").format(size=format_size(freed)))
        return {'FINISHED'}


def format_size(size):
    """Format a byte count for a compact UI report."""
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return "{:.1f} {}".format(value, unit)
        value /= 1024.0
    return "{:.1f} GB".format(value)


classes = (
    MIMI_OT_TextureFormatConvert,
    MIMI_OT_TextureFormatCancel,
    MIMI_OT_TextureFormatClearCache,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
