'''
Slot Texture Bind blueprint node (per-object texture slot binding).

A transparent pass-through node: Object in, Object out. Every object that
passes through it gets its texture slots replaced right before its own
drawindexed line, so two objects of the same Submesh can use different
textures under different switch states.

3Dmigoto facts backing this design:
- A texture slot assignment (e.g. "ps-t0 = ResourceXXX") inside a
  TextureOverride section stays in effect until another assignment changes
  it, so writing the binding immediately before the drawindexed call is
  the correct "replace only for this draw" pattern.
- The "ref" keyword captures the currently bound resource
  ("bak = ref ps-t0"), the same trick the SnowBreak exporter already uses
  to back up the index buffer; it allows restoring the original texture
  after the draw when the user enables "Restore After Draw".
- Resource sections are plain "[ResourceXXX] filename = ..." blocks; the
  exporter deduplicates them by resource name.

Texture sources:
- MARK:     reuse a texture marked in SSMT5 (TextureMarkUpInfoList of the
            Submesh). No new file copy or resource section is needed; the
            existing Slot / SharedSlot pipeline already provides them.
- FILE:     an external image file (dds/png/...). The exporter copies it
            into the generated mod and emits a dedicated resource section.
- RESOURCE: an already existing resource name (advanced users who share
            one resource between several objects).
'''
import re

import bpy
from bpy.types import PropertyGroup

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase

# 3Dmigoto texture slot syntax: shader stage (ps/vs/gs/hs/ds/cs) + binding
# type (t/s/b/u) + register number, written lowercase by convention.
_SLOT_PATTERN = re.compile(r"^(ps|vs|gs|hs|ds|cs)-(t|s|b|u)\d+$")

# Placeholder identifier of the mark name dropdown. Blender enum identifiers
# must not be empty strings, otherwise RNA falls back to the numeric index
# and the stored value stops round-tripping ("current value '0' matches no
# enum" warning).
_MARK_NAME_NONE = "(none)"


def _texture_slot_item_refresh_display(item):
    '''Rebuild the one-line display name shown inside the list widget.'''
    source_type = str(getattr(item, "source_type", "") or "")
    if source_type == 'MARK':
        source = str(getattr(item, "mark_name", "") or "").strip() or "?"
    elif source_type == 'FILE':
        source = bpy.path.basename(str(getattr(item, "file_path", "") or "").strip()) or "?"
    else:
        source = str(getattr(item, "resource_name", "") or "").strip() or "?"
    restore_suffix = " (+restore)" if getattr(item, "restore_after_draw", False) else ""
    item.name = "{slot} <- {source}{suffix}".format(
        slot=str(getattr(item, "slot", "") or "").strip() or "?",
        source=source,
        suffix=restore_suffix,
    )


class MIMITextureSlotItem(PropertyGroup):
    '''One texture slot binding row of a Texture Bind node.'''
    name: bpy.props.StringProperty(name=tr("Binding"), default="") # type: ignore

    enabled: bpy.props.BoolProperty(
        name=tr("Enabled"),
        description=tr("Disabled rows are skipped at export time"),
        default=True,
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    slot: bpy.props.StringProperty(
        name=tr("Slot"),
        description=tr("Texture slot to replace right before this object's drawindexed, e.g. ps-t0"),
        default="ps-t0",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    source_type: bpy.props.EnumProperty(
        name=tr("Source"),
        description=tr("Where the replacement texture comes from"),
        items=[
            ('MARK', tr("Marked Texture"), tr("Reuse a texture marked in the SSMT5 texture mark page of this Submesh")),
            ('FILE', tr("External File"), tr("Copy an external image file into the generated mod")),
            ('RESOURCE', tr("Existing Resource"), tr("Reference an existing [ResourceXXX] section by name")),
        ],
        default='MARK',
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    mark_name: bpy.props.EnumProperty(
        name=tr("Mark Name"),
        description=tr("Semantic mark name from the SSMT5 texture mark page; resolved against the Submesh of the upstream object. Picking one fills the slot automatically"),
        items=lambda self, context: _texture_bind_mark_name_items(self),
        update=lambda self, context: _texture_slot_item_mark_changed(self),
    ) # type: ignore

    file_path: bpy.props.StringProperty(
        name=tr("Texture File"),
        description=tr("Image file (dds, png, jpg, bmp or tga) copied into the generated mod at export time"),
        subtype='FILE_PATH',
        default="",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    resource_name: bpy.props.StringProperty(
        name=tr("Resource Name"),
        description=tr("Name of an existing [ResourceXXX] section, e.g. ResourceMySharedTexture"),
        default="",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    restore_after_draw: bpy.props.BoolProperty(
        name=tr("Restore After Draw"),
        description=tr("Capture the original texture with ref before the draw and bind it back after drawindexed; needed when a later draw must see the original texture again"),
        default=False,
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore


def _find_owner_bind_node(item):
    '''Find the Texture Bind node that owns the given collection item.'''
    tree = getattr(item, "id_data", None)
    if tree is None:
        return None
    for node in getattr(tree, "nodes", []):
        if getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            continue
        for candidate in getattr(node, "texture_slot_items", []):
            if candidate.as_pointer() == item.as_pointer():
                return node
    return None


def _resolve_upstream_submesh_name(node, depth=0):
    '''Find the first enabled upstream source, respecting list/group ports.'''
    # The old Object-Info-only traversal left marked-texture dropdowns empty
    # when an Object List or custom group fed the binding node.
    from .blueprint_graph import iter_object_sources
    for source in iter_object_sources(node):
        submesh_name = str(getattr(source, "submesh_name", "") or "").strip()
        object_name = str(getattr(source, "object_name", "") or "").strip()
        if submesh_name or object_name:
            return submesh_name or object_name
    return ""


def _load_submesh_mark_dicts(submesh_name):
    '''Texture marks of one Submesh as normalized plain dicts.

    Shared by the mark dropdowns, the auto-fill operators and the
    pick-a-mark update callbacks, so all of them agree on the workspace
    format. Returns [] when the Submesh JSON is missing or has no marks.
    '''
    if not submesh_name:
        return []
    # Imported here so a missing workspace never breaks the node UI.
    from ..workspace.submesh_json import SubmeshJson
    from ..workspace.mmt_workspace import MMTWorkSpace
    submesh_json = SubmeshJson(MMTWorkSpace.check_and_get_submesh_json_path(submesh_name))
    mark_dict_list = []
    seen_names = set()
    for raw_mark in submesh_json.TextureMarkUpInfoList:
        if isinstance(raw_mark, dict):
            mark_name = str(raw_mark.get("MarkName", "") or "").strip()
            mark_dict = {
                "name": mark_name,
                "type": str(raw_mark.get("MarkType", "") or "").strip(),
                "slot": str(raw_mark.get("MarkSlot", "") or "").strip().lower(),
                "hash": str(raw_mark.get("MarkHash", "") or "").strip().lower(),
                "filename": str(raw_mark.get("MarkFileName", "") or "").strip(),
            }
        else:
            mark_name = str(getattr(raw_mark, "MarkName", "") or "").strip()
            mark_dict = {
                "name": mark_name,
                "type": str(getattr(raw_mark, "MarkType", "") or "").strip(),
                "slot": str(getattr(raw_mark, "MarkSlot", "") or "").strip().lower(),
                "hash": str(getattr(raw_mark, "MarkHash", "") or "").strip().lower(),
                "filename": str(getattr(raw_mark, "MarkFileName", "") or "").strip(),
            }
        normalized = mark_name.lower()
        if not mark_name or normalized in seen_names:
            continue
        seen_names.add(normalized)
        mark_dict_list.append(mark_dict)
    return mark_dict_list


def _find_submesh_mark_by_name(item, find_owner_node):
    '''Locate the mark dict matching the row's mark name ("" when missing).'''
    try:
        mark_name = normalize_mark_name_enum_value(getattr(item, "mark_name", ""))
        if not mark_name:
            return None
        node = find_owner_node(item)
        submesh_name = _resolve_upstream_submesh_name(node)
        if not submesh_name:
            return None
        for mark_dict in _load_submesh_mark_dicts(submesh_name):
            if mark_dict["name"].lower() == mark_name.lower():
                return mark_dict
    except Exception:
        # Dropdown and callback lookups must never break the node editor.
        pass
    return None


def _texture_slot_item_mark_changed(item):
    '''Picking a mark fills the slot from the mark's own MarkSlot value.'''
    mark_dict = _find_submesh_mark_by_name(item, _find_owner_bind_node)
    if mark_dict and mark_dict["slot"]:
        item.slot = mark_dict["slot"]
    _texture_slot_item_refresh_display(item)


def _texture_bind_mark_name_items(item):
    '''Enum items for the mark name dropdown: marks of the upstream Submesh.'''
    empty_items = [(_MARK_NAME_NONE, "(" + tr("none") + ")", "")]
    try:
        node = _find_owner_bind_node(item)
        submesh_name = _resolve_upstream_submesh_name(node)
        if not submesh_name:
            return empty_items
        items = list(empty_items)
        for mark_dict in _load_submesh_mark_dicts(submesh_name):
            items.append((mark_dict["name"], mark_dict["name"], ""))
        return items if len(items) > 1 else empty_items
    except Exception:
        # Never let a dropdown lookup break the node editor drawing.
        return empty_items


def normalize_mark_name_enum_value(value):
    '''Map the dropdown placeholder back to an empty mark name at export.'''
    text = str(value or "").strip()
    return "" if text == _MARK_NAME_NONE else text


class MMT_OT_TexBindAddItem(I18nOperator):
    '''Add one texture slot binding row to a Texture Bind node'''
    bl_idname = "mimi.texbind_add_item"
    bl_label = "Add Texture Binding"
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
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            return {'CANCELLED'}
        item = node.texture_slot_items.add()
        # Bake the display name immediately so the new row is not blank.
        _texture_slot_item_refresh_display(item)
        node.texture_slot_index = len(node.texture_slot_items) - 1
        return {'FINISHED'}


class MMT_OT_TexBindRemoveItem(I18nOperator):
    '''Remove the selected texture slot binding row from a Texture Bind node'''
    bl_idname = "mimi.texbind_remove_item"
    bl_label = "Remove Texture Binding"
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
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            return {'CANCELLED'}
        index = int(getattr(node, "texture_slot_index", 0))
        if 0 <= index < len(node.texture_slot_items):
            node.texture_slot_items.remove(index)
            node.texture_slot_index = max(0, min(index, len(node.texture_slot_items) - 1))
        return {'FINISHED'}


class MMT_OT_TexBindAutoFill(I18nOperator):
    '''Add one binding row for every Slot / SharedSlot mark of the upstream Submesh'''
    bl_idname = "mimi.texbind_autofill"
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
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            return {'CANCELLED'}

        submesh_name = _resolve_upstream_submesh_name(node)
        if not submesh_name:
            self.report({'ERROR'}, tr("Upstream Submesh not resolved; set the Submesh on the upstream Object Info node first"))
            return {'CANCELLED'}

        # Rows already referencing a mark are kept untouched; the operator
        # only appends what is missing, so it is safe to press repeatedly.
        existing_names = set()
        for row_item in node.texture_slot_items:
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
            if mark_dict["type"] not in ("Slot", "SharedSlot"):
                continue
            if not mark_dict["name"] or mark_dict["name"].lower() in existing_names:
                skipped_count += 1
                continue
            if not mark_dict["slot"]:
                print("Slot Texture Bind auto fill: mark '" + mark_dict["name"] + "' has no MarkSlot, skipped")
                skipped_count += 1
                continue
            row_item = node.texture_slot_items.add()
            row_item.enabled = True
            row_item.slot = mark_dict["slot"]
            row_item.source_type = 'MARK'
            row_item.mark_name = mark_dict["name"]
            _texture_slot_item_refresh_display(row_item)
            added_count += 1
            existing_names.add(mark_dict["name"].lower())

        node.texture_slot_index = len(node.texture_slot_items) - 1
        self.report({'INFO'}, tr("Auto fill done: {added} row(s) added, {skipped} skipped").format(added=added_count, skipped=skipped_count))
        return {'FINISHED'}


@translatable
class MIMINode_Texture_Bind(MIMINodeBase):
    '''Slot Texture Bind assigns replacement textures to slots right before each passing object's drawindexed'''
    bl_idname = 'MIMINode_Texture_Bind'
    bl_label = 'Slot Texture Bind'
    bl_icon = 'TEXTURE'
    bl_width_min = 320

    texture_slot_items: bpy.props.CollectionProperty(type=MIMITextureSlotItem) # type: ignore
    texture_slot_index: bpy.props.IntProperty(default=0) # type: ignore

    def width_texts(self):
        """Return every text that decides how wide this node has to be."""
        return [self.label]

    def init(self, context):
        # The default title is instance data, so bake in the active language.
        self.label = tr("Slot Texture Bind")
        self.inputs.new('MIMISocketObject', "Object")
        self.outputs.new('MIMISocketObject', "Output")
        self.width = 340
        self.use_custom_color = True
        self.color = (0.55, 0.42, 0.16)

    def draw_buttons(self, context, layout):
        tree = self.id_data if getattr(self, "id_data", None) and getattr(self.id_data, "bl_idname", "") == 'MIMIBlueprintTreeType' else None

        row = layout.row()
        # The list shows the compact one-line summary of every binding row.
        # The list id must be unique per node: the uiList runtime state
        # (scroll offset and resize-grip height) is keyed by this id, so a
        # constant id would sync the height of every Texture Bind node.
        row.template_list(
            "UI_UL_list", "mimi_texture_bind_" + self.name,
            self, "texture_slot_items",
            self, "texture_slot_index",
            rows=3,
        )
        column = row.column(align=True)
        add_operator = column.operator("mimi.texbind_add_item", text="", icon='ADD')
        add_operator.node_name = self.name
        add_operator.tree_name = tree.name if tree else ""
        remove_operator = column.operator("mimi.texbind_remove_item", text="", icon='REMOVE')
        remove_operator.node_name = self.name
        remove_operator.tree_name = tree.name if tree else ""
        # One click turns every Slot / SharedSlot mark of the upstream
        # Submesh into a ready-made MARK binding row.
        autofill_operator = column.operator("mimi.texbind_autofill", text="", icon='FILE_REFRESH')
        autofill_operator.node_name = self.name
        autofill_operator.tree_name = tree.name if tree else ""

        if not self.texture_slot_items:
            layout.label(text=tr("No bindings; objects pass through unchanged"), icon='INFO')
            return

        index = int(self.texture_slot_index)
        if not (0 <= index < len(self.texture_slot_items)):
            return
        item = self.texture_slot_items[index]

        box = layout.box()
        box.prop(item, "enabled")
        box.prop(item, "slot")
        box.prop(item, "source_type")

        source_type = str(item.source_type or "")
        if source_type == 'MARK':
            box.prop(item, "mark_name")
            # Tell the user when the dropdown could not resolve the upstream
            # Submesh, instead of leaving a mysteriously empty dropdown.
            upstream_submesh = _resolve_upstream_submesh_name(self)
            if not upstream_submesh:
                box.label(text=tr("Upstream Submesh not resolved; mark names unavailable"), icon='ERROR')
        elif source_type == 'FILE':
            box.prop(item, "file_path")
        else:
            box.prop(item, "resource_name")

        box.prop(item, "restore_after_draw")

        # Early slot format feedback; the export pass validates again and
        # raises a hard error so a typo can never reach the generated INI.
        slot_text = str(item.slot or "").strip().lower()
        if slot_text and _SLOT_PATTERN.match(slot_text) is None:
            layout.label(text=tr("Slot format looks wrong; expected something like ps-t0"), icon='ERROR')

        active_count = len([row_item for row_item in self.texture_slot_items if row_item.enabled])
        layout.label(text=tr("{count} slot binding(s)").format(count=active_count), icon='TEXTURE')


classes = (
    MMT_OT_TexBindAddItem,
    MMT_OT_TexBindRemoveItem,
    MMT_OT_TexBindAutoFill,
    MIMINode_Texture_Bind,
)


def register():
    # The PropertyGroup must exist before the node class that references it.
    bpy.utils.register_class(MIMITextureSlotItem)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(MIMITextureSlotItem)
