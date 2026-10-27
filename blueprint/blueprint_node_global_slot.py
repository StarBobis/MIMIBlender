"""Socketless Submesh defaults; never unconditional game-wide slot overrides.

Refresh preserves configured identities, including stale rows. Export rejects
active stale rows rather than silently redirecting them to another Submesh.
"""
import bpy
from .blueprint_node_base import MIMINodeBase
from .blueprint_node_texture import _load_submesh_mark_dicts
from .blueprint_node_hash_texture import _find_global_mark_source_path
from ..common.global_config import GlobalConfig
from ..common.texture_output_naming import (
    INDEX_PLACEHOLDER,
    global_slot_output_filename,
    normalize_alias_stem,
)
from ..i18n.i18n import I18nOperator, tr, translatable
from .texture_output_widgets import (
    draw_ib_from_name,
    draw_generated_name,
    draw_rename_box,
)
from .texture_format_widgets import (
    draw_convert_all as _draw_convert_all,
    draw_node_progress as _draw_node_progress,
    draw_row_controls as _draw_row_controls,
)


def refresh_global_slot_row_label(row):
    """Rebuild the one-line list label of one global slot row.

    The alias is part of the label because the list is the only place where a
    user can see which of the rows owns which generated texture file.
    """
    # A stale row keeps the identity it was configured with; the label is then
    # rebuilt from the saved detection fields, which are never cleared.
    label = str(row.submesh or "?") + " / " + str(row.slot or "?") + " / " + str(row.mark_name or "?")
    alias_stem = normalize_alias_stem(getattr(row, "output_name", ""))
    row.name = label + (" -> " + alias_stem if alias_stem else "")
    return row.name


def scan_slot_marks():
    """Use active workspace TYPE selections, retaining per-Submesh ownership."""
    import os
    from ..workspace.mmt_workspace import MMTWorkSpace
    # Discovery is restricted to the active workspace's TYPE selection.
    # A same-hash mark in a second Submesh is a second target, not an alias.
    # A replacement is never attached to a different mark by list position.
    # Missing originals remain visible so export can report them explicitly.
    result = {}
    folder = GlobalConfig.path_workspace_folder()
    if not os.path.isdir(folder):
        return result
    from .blueprint_node_hash_texture import _workspace_submesh_names_for_global_marks
    for name in _workspace_submesh_names_for_global_marks():
        try:
            json_path = MMTWorkSpace.check_and_get_submesh_json_path(name)
            marks = _load_submesh_mark_dicts(name, dedupe_names=False)
        except Exception:
            # Non-Submesh workspace folders are not texture targets.
            continue
        for mark in marks:
            if mark['type'] not in ('Slot', 'SharedSlot'):
                continue
            # Slot and semantic name together distinguish multiple marked roles.
            # Hash is excluded because re-extraction can change the content hash.
            # The JSON path also prevents accidentally reusing another workspace.
            # Case normalization follows the host filesystem's path convention.
            key = '|'.join((os.path.normcase(json_path), name, mark['slot'], mark['name']))
            # The TYPE path belongs to the identity. Re-extraction into a
            # different TYPE must require a deliberate refreshed configuration.
            result[key] = (name, mark, _find_global_mark_source_path(name, mark['filename']))
    return result


class GlobalSlotItem(bpy.types.PropertyGroup):
    # Persistent identities keep replacement edits stable across refreshes.
    # Missing state is visible but never destroys a configured file path.
    # These RNA fields serialize with the node tree in saved Blender files.
    # Detection fields describe ownership; editable fields describe user intent.
    # Original path is refreshed from the selected extract, never from the output.
    # Empty replacement means this manager does not claim the target.
    # Disabled rows retain their choice for later re-enabling.
    name: bpy.props.StringProperty()
    identity: bpy.props.StringProperty()
    submesh: bpy.props.StringProperty()
    slot: bpy.props.StringProperty()
    mark_name: bpy.props.StringProperty()
    original_path: bpy.props.StringProperty(subtype='FILE_PATH')
    file_path: bpy.props.StringProperty(name='Replacement', subtype='FILE_PATH')
    enabled: bpy.props.BoolProperty(name='Enabled', default=True)
    missing: bpy.props.BoolProperty(default=False)
    force_original_size: bpy.props.BoolProperty(name='Force Original Size', default=False)
    # Optional user alias: the generated texture file is renamed. Empty keeps
    # the generated name shown by the node.
    output_name: bpy.props.StringProperty(
        name=tr("Rename To"),
        description=tr("Leave empty to keep the generated file name shown above; fill in to rename the generated texture file"),
        default="",
        update=lambda self, context: refresh_global_slot_row_label(self),
    )


def refresh_global_slot_rows(node):
    """Reconcile the rows of one global slot node with the workspace marks.

    Returns the number of rows the node owns afterwards. The function is
    shared by the node's own refresh button and by the blueprint wide
    "Refresh Blueprint" entry, so both paths always behave identically.
    """
    # Complete the scan before mutating the saved collection.
    # Existing rows are retained when a mark disappears.
    # Their enabled replacement must be reviewed rather than silently deleted.
    # New marks start unconfigured and therefore do not affect export.
    marks = scan_slot_marks()
    rows = {row.identity: row for row in node.items}
    for row in node.items:
        row.missing = row.identity not in marks
    # Reuse rows by stable identity rather than their current display name.
    # Refresh never overwrites replacement paths, enabled flags or size policy.
    # The displayed label is informational and is not a binding key.
    for identity, (submesh, mark, path) in marks.items():
        row = rows.get(identity)
        if row is None:
            row = node.items.add()
            row.identity = identity
        # Only detection fields change; replacement/enable/size stay intact.
        # SharedSlot ownership is intentionally not collapsed by hash.
        row.submesh = submesh
        row.slot = mark['slot']
        row.mark_name = mark['name']
        row.original_path = path
        row.missing = False
        # Rebuild the label from the detection fields so a configured alias
        # survives the refresh instead of being wiped by a plain name write.
        refresh_global_slot_row_label(row)
    return len(node.items)


class RefreshGlobalSlots(I18nOperator):
    """Scan Slot and SharedSlot without deduplicating their hashes."""
    bl_idname = 'mimi.global_slot_refresh'
    bl_label = 'Refresh Slot Marks'
    bl_options = {'REGISTER', 'UNDO'}
    tree_name: bpy.props.StringProperty()
    node_name: bpy.props.StringProperty()

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        node = tree.nodes.get(self.node_name) if tree else None
        if not node or node.bl_idname != 'MIMINode_Texture_Global':
            return {'CANCELLED'}
        # The shared helper keeps this button and Refresh Blueprint in sync.
        refresh_global_slot_rows(node)
        return {'FINISHED'}


@translatable
class MIMINode_Texture_Global(MIMINodeBase):
    """Global manager for selected Submesh defaults, with no object sockets."""
    bl_idname = 'MIMINode_Texture_Global'
    bl_label = 'Global Slot Texture Bind'
    bl_icon = 'TEXTURE'
    items: bpy.props.CollectionProperty(type=GlobalSlotItem)
    index: bpy.props.IntProperty(default=0)

    def init(self, context):
        # Green marks a global manager; connected overrides use other colors.
        # No sockets means this node does not participate in object traversal.
        self.label = tr(self.bl_label)
        self.width = 360
        self.use_custom_color = True
        self.color = (0.20, 0.48, 0.28)

    # The manager is intentionally socketless, so it can work without object links.
    # Its rows are defaults for selected draws, not game-wide physical overrides.
    # UI selection changes only which row is shown, never export priority.
    # Original DDS availability is shown next to the replacement controls.
    # A stale active row requires explicit user withdrawal or reconfiguration.
    def draw_buttons(self, context, layout):
        # Running exact-format batches are global, so their progress shows here.
        _draw_node_progress(layout)
        layout.label(text='Submesh defaults / local draw overrides win', icon='INFO')
        op = layout.operator('mimi.global_slot_refresh', icon='FILE_REFRESH')
        op.tree_name, op.node_name = self.id_data.name, self.name
        layout.template_list('UI_UL_list', self.name, self, 'items', self, 'index', rows=4)
        if not 0 <= self.index < len(self.items):
            return
        row = self.items[self.index]
        layout.prop(row, 'enabled')
        layout.prop(row, 'file_path')
        layout.prop(row, 'force_original_size')
        # Original format, readiness and the per-row Convert button.
        tree = self.id_data
        _draw_row_controls(layout, self, row, int(self.index), tree)
        # Clearing or disabling withdraws only this layer of default binding.
        # The original and lower-priority configuration remain untouched.
        layout.label(text=row.original_path or 'Original DDS unavailable')
        # The DrawIB comes from the row's Submesh; the row index inside the
        # export pass is only known there, so it stays a placeholder.
        generated_name = global_slot_output_filename(
            draw_ib_from_name(row.submesh) or "<DrawIB>", INDEX_PLACEHOLDER,
        )
        draw_generated_name(layout, generated_name)
        # The copy stage always converts to DDS, so the alias is always .dds.
        draw_rename_box(layout, row, ".dds", generated_name)
        if row.missing:
            layout.label(text='Stale mark: clear or disable replacement', icon='ERROR')
        # One click prepares every replacement of this node in the background.
        _draw_convert_all(layout, self, tree)


classes = (GlobalSlotItem, RefreshGlobalSlots, MIMINode_Texture_Global)


# Register RNA item types before nodes that reference their collections.
# Unregister in reverse order to avoid dangling collection type references.
def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
