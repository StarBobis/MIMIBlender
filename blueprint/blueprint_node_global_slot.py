"""Socketless Submesh defaults; never unconditional game-wide slot overrides.

Refresh preserves configured identities, including stale rows. Export rejects
active stale rows rather than silently redirecting them to another Submesh.
"""
import bpy
from .blueprint_node_base import MIMINodeBase
from .blueprint_node_texture import _load_submesh_mark_dicts
from .blueprint_node_hash_texture import _find_global_mark_source_path
from ..common.global_config import GlobalConfig
from ..i18n.i18n import I18nOperator, tr, translatable


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
            row.name = submesh + ' / ' + mark['slot'] + ' / ' + mark['name']
            row.submesh = submesh
            row.slot = mark['slot']
            row.mark_name = mark['name']
            row.original_path = path
            row.missing = False
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
        # Clearing or disabling withdraws only this layer of default binding.
        # The original and lower-priority configuration remain untouched.
        layout.label(text=row.original_path or 'Original DDS unavailable')
        if row.missing:
            layout.label(text='Stale mark: clear or disable replacement', icon='ERROR')


classes = (GlobalSlotItem, RefreshGlobalSlots, MIMINode_Texture_Global)


# Register RNA item types before nodes that reference their collections.
# Unregister in reverse order to avoid dangling collection type references.
def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
