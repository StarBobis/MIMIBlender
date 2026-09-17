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
        description=tr("Semantic mark name from the SSMT5 texture mark page; resolved against the Submesh of the upstream object"),
        items=lambda self, context: _texture_bind_mark_name_items(self),
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
    '''Walk upstream through pass-through nodes to find an Object Info node.'''
    if node is None or depth > 16:
        return ""
    if getattr(node, "bl_idname", "") == 'MIMINode_Object_Info':
        submesh_name = str(getattr(node, "submesh_name", "") or "").strip()
        if submesh_name:
            return submesh_name
        return str(getattr(node, "object_name", "") or "").strip()
    for socket in getattr(node, "inputs", []):
        for link in getattr(socket, "links", []):
            found = _resolve_upstream_submesh_name(link.from_node, depth + 1)
            if found:
                return found
    return ""


def _texture_bind_mark_name_items(item):
    '''Enum items for the mark name dropdown: marks of the upstream Submesh.'''
    empty_items = [(_MARK_NAME_NONE, "(" + tr("none") + ")", "")]
    try:
        node = _find_owner_bind_node(item)
        submesh_name = _resolve_upstream_submesh_name(node)
        if not submesh_name:
            return empty_items
        # Imported here so a missing workspace never breaks the node UI.
        from ..workspace.submesh_json import SubmeshJson
        from ..workspace.mmt_workspace import MMTWorkSpace
        submesh_json = SubmeshJson(MMTWorkSpace.check_and_get_submesh_json_path(submesh_name))
        items = list(empty_items)
        seen_names = set()
        for raw_mark in submesh_json.TextureMarkUpInfoList:
            mark_name = ""
            if isinstance(raw_mark, dict):
                mark_name = str(raw_mark.get("MarkName", "") or "").strip()
            else:
                mark_name = str(getattr(raw_mark, "MarkName", "") or "").strip()
            normalized = mark_name.lower()
            if not mark_name or normalized in seen_names:
                continue
            seen_names.add(normalized)
            items.append((mark_name, mark_name, ""))
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
        if tree is None:
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
        if tree is None:
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
        row.template_list(
            "UI_UL_list", "mimi_texture_bind",
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
