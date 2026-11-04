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
from ..i18n.i18n import tr, translatable
# The row gallery is shared with Global Hash Texture Bind; the node declares
# what its rows mean and the gallery owns how they are edited.
from .texture_output_widgets import draw_ib_from_name
from .texture_row_ui import (
    TextureRowProfile,
    draw_texture_row_panel,
    register_profile,
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
    # Blender requires a property update callback to return None; returning the
    # new name made every alias edit print "the return value must be None".
    # The list reads row.name, so no caller needs the value.


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
    # User-visible RNA names follow the selected UI language just like the
    # captions below. They are read once at registration time, so a language
    # change takes effect after the add-on is reloaded.
    file_path: bpy.props.StringProperty(name=tr("Replacement"), subtype='FILE_PATH')
    enabled: bpy.props.BoolProperty(name=tr("Enabled"), default=True)
    missing: bpy.props.BoolProperty(default=False)
    force_original_size: bpy.props.BoolProperty(name=tr("Force Original Resolution"), default=False)
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
        # Same gallery as Global Hash Texture Bind: one list, one preview pair,
        # one chooser. Only the row profile and the export path differ.
        draw_texture_row_panel(self, layout)


def _slot_row_warnings(item):
    """Status lines that only a Submesh slot default can produce."""
    if bool(getattr(item, "missing", False)):
        return [('ERROR', tr("Stale mark: clear or disable replacement"))]
    return []


def _slot_row_set_file(item, path):
    """Store the replacement image of one slot default."""
    # The label describes the mark and the alias, not the picked file, so no
    # extra bookkeeping runs here; the export resolves the path itself.
    item.file_path = path


def _slot_row_output_name(node, item):
    """Return (generated_name, suffix, suffix_is_certain) of one slot default.

    The export pass decides the row index, so the name shows a placeholder; the
    copy stage always converts to DDS, which makes the suffix certain.
    """
    draw_ib = draw_ib_from_name(getattr(item, "submesh", "")) or "<DrawIB>"
    return global_slot_output_filename(draw_ib, INDEX_PLACEHOLDER), ".dds", True


def _slot_row_title(item):
    """Return the familiar 'Submesh / slot / mark' caption of one row."""
    return ' / '.join(
        str(part or "?") for part in (
            getattr(item, "submesh", "") or "?",
            getattr(item, "slot", "") or "?",
            getattr(item, "mark_name", "") or "?",
        )
    )


def _slot_row_list_title(item):
    """List caption of one row, including the alias of its generated file.

    The list is the only place where a user can see which row owns which
    renamed texture, so the alias stays part of it exactly like the previous
    plain ``row.name`` list showed it.
    """
    title = _slot_row_title(item)
    alias_stem = normalize_alias_stem(getattr(item, "output_name", ""))
    return title + (" -> " + alias_stem if alias_stem else "")


_SLOT_ROW_PROFILE = TextureRowProfile(
    rows_prop="items",
    index_prop="index",
    # Identity carries the Submesh, the slot and the mark name; the texture
    # hash is intentionally absent because re-extraction changes it.
    key=lambda item: str(getattr(item, "identity", "") or ""),
    list_title=_slot_row_list_title,
    title=_slot_row_title,
    subtitle=lambda item: "",
    original_path=lambda item: str(getattr(item, "original_path", "") or ""),
    replacement_path=lambda item: str(getattr(item, "file_path", "") or ""),
    set_file=_slot_row_set_file,
    warnings=_slot_row_warnings,
    generated_name=_slot_row_output_name,
    scope_text=lambda: tr("Submesh defaults / local draw overrides win"),
    empty_hint=lambda: tr("Refresh to detect marked Slot textures"),
    # A slot default owns no file: disabling it only stops emitting the
    # per-draw binding, so the game's own texture stays bound.
    disabled_hint=lambda: tr("Disabled: this Submesh draws with the game's own texture"),
    scope_icon='INFO',
)

register_profile('MIMINode_Texture_Global', profile=_SLOT_ROW_PROFILE)


classes = (GlobalSlotItem, MIMINode_Texture_Global)


# Register RNA item types before nodes that reference their collections.
# Unregister in reverse order to avoid dangling collection type references.
def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
