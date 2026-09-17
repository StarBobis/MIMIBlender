'''
Hash Texture Bind blueprint node (conditional hash-style texture override).

A transparent pass-through node: Object in, Object out. Every object that
passes through contributes (texture hash, replacement resource) rows that
are later merged into blueprint-global [TextureOverride_Texture_<hash>]
sections: each row becomes one conditional "this = ResourceXXX" block, so
pressing the switch key bound upstream flips the texture.

3Dmigoto facts backing this design:
- A [TextureOverride] section with "hash = xxx" runs every time the game
  binds that texture, and "this = ..." inside replaces the binding for
  that moment. When the section runs again with a false condition, no
  this= line executes and the original texture comes back, so unlike the
  slot style no explicit restore pass is needed.
- if/endif blocks are valid inside TextureOverride sections, which is how
  the per-branch conditions from Switch Key / Time Switch nodes reach the
  this= assignment.
- Hash overrides are global by nature: every draw that binds the hash is
  affected while the condition holds. The node therefore manages hashes,
  not slots, and its sections are emitted once per hash for the whole
  blueprint, not per DrawIB or per draw call.

Texture sources:
- MARK: reuse the source file of a Hash-style SSMT5 mark (resolved through
  the workspace extract folders), copied and declared like a FILE row so
  the binding stays self-contained even when the automatic hash pipeline
  is skipped for the managed hash.
- FILE: an external image file copied into the generated mod.
- RESOURCE: an already existing resource name.
'''
import re

import bpy
from bpy.types import PropertyGroup

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase
from .blueprint_node_texture import (
    _MARK_NAME_NONE,
    _find_submesh_mark_by_name,
    _load_submesh_mark_dicts,
    _resolve_upstream_submesh_name,
    normalize_mark_name_enum_value,
)

# A 3Dmigoto texture hash is 16 hexadecimal characters.
_TEXTURE_HASH_PATTERN = re.compile(r"^[0-9a-f]{16}$")


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


class MIMITextureHashItem(PropertyGroup):
    '''One hash texture binding row of a Hash Texture Bind node.'''
    name: bpy.props.StringProperty(name=tr("Binding"), default="") # type: ignore

    enabled: bpy.props.BoolProperty(
        name=tr("Enabled"),
        description=tr("Disabled rows are skipped at export time"),
        default=True,
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore

    texture_hash: bpy.props.StringProperty(
        name=tr("Texture Hash"),
        description=tr("Hash of the original texture to replace (16 hexadecimal characters); the override applies wherever the game binds this hash"),
        default="",
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore

    source_type: bpy.props.EnumProperty(
        name=tr("Source"),
        description=tr("Where the replacement texture comes from"),
        items=[
            ('MARK', tr("Marked Texture"), tr("Reuse the source file of a Hash-style mark from the SSMT5 texture mark page of this Submesh")),
            ('FILE', tr("External File"), tr("Copy an external image file into the generated mod")),
            ('RESOURCE', tr("Existing Resource"), tr("Reference an existing [ResourceXXX] section by name")),
        ],
        default='FILE',
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore

    mark_name: bpy.props.EnumProperty(
        name=tr("Mark Name"),
        description=tr("Hash-style mark from the SSMT5 texture mark page; its texture file is copied into the generated mod. Picking one fills the texture hash automatically"),
        items=lambda self, context: _texture_hash_bind_mark_name_items(self),
        update=lambda self, context: _texture_hash_item_mark_changed(self),
    ) # type: ignore

    file_path: bpy.props.StringProperty(
        name=tr("Texture File"),
        description=tr("Image file (dds, png, jpg, bmp or tga) copied into the generated mod at export time"),
        subtype='FILE_PATH',
        default="",
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore

    resource_name: bpy.props.StringProperty(
        name=tr("Resource Name"),
        description=tr("Name of an existing [ResourceXXX] section, e.g. ResourceMySharedTexture"),
        default="",
        update=lambda self, context: _texture_hash_item_refresh_display(self),
    ) # type: ignore


def _find_owner_hash_bind_node(item):
    '''Find the Hash Texture Bind node that owns the given collection item.'''
    tree = getattr(item, "id_data", None)
    if tree is None:
        return None
    for node in getattr(tree, "nodes", []):
        if getattr(node, "bl_idname", "") != 'MIMINode_Hash_Texture_Bind':
            continue
        for candidate in getattr(node, "texture_hash_items", []):
            if candidate.as_pointer() == item.as_pointer():
                return node
    return None


def _texture_hash_item_mark_changed(item):
    '''Picking a mark fills the texture hash from the mark's MarkHash value.'''
    mark_dict = _find_submesh_mark_by_name(item, _find_owner_hash_bind_node)
    if mark_dict and mark_dict["hash"]:
        item.texture_hash = mark_dict["hash"]
    _texture_hash_item_refresh_display(item)


def _texture_hash_bind_mark_name_items(item):
    '''Enum items for the mark name dropdown: Hash-style marks of the upstream Submesh.'''
    empty_items = [(_MARK_NAME_NONE, "(" + tr("none") + ")", "")]
    try:
        node = _find_owner_hash_bind_node(item)
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


class MMT_OT_TexHashBindAddItem(I18nOperator):
    '''Add one hash texture binding row to a Hash Texture Bind node'''
    bl_idname = "mimi.texhashbind_add_item"
    bl_label = "Add Hash Texture Binding"
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
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Hash_Texture_Bind':
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
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        if tree is None:
            tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if tree is None:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Hash_Texture_Bind':
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
        if tree is None:
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
        self.width = 360
        self.use_custom_color = True
        self.color = (0.16, 0.42, 0.55)

    def draw_buttons(self, context, layout):
        tree = self.id_data if getattr(self, "id_data", None) and getattr(self.id_data, "bl_idname", "") == 'MIMIBlueprintTreeType' else None

        row = layout.row()
        row.template_list(
            "UI_UL_list", "mimi_texture_hash_bind",
            self, "texture_hash_items",
            self, "texture_hash_index",
            rows=3,
        )
        column = row.column(align=True)
        add_operator = column.operator("mimi.texhashbind_add_item", text="", icon='ADD')
        add_operator.node_name = self.name
        add_operator.tree_name = tree.name if tree else ""
        remove_operator = column.operator("mimi.texhashbind_remove_item", text="", icon='REMOVE')
        remove_operator.node_name = self.name
        remove_operator.tree_name = tree.name if tree else ""
        # One click turns every Hash-style mark of the upstream Submesh
        # into a ready-made MARK binding row.
        autofill_operator = column.operator("mimi.texhashbind_autofill", text="", icon='FILE_REFRESH')
        autofill_operator.node_name = self.name
        autofill_operator.tree_name = tree.name if tree else ""

        if not self.texture_hash_items:
            layout.label(text=tr("No bindings; objects pass through unchanged"), icon='INFO')
            return

        index = int(self.texture_hash_index)
        if not (0 <= index < len(self.texture_hash_items)):
            return
        item = self.texture_hash_items[index]

        box = layout.box()
        box.prop(item, "enabled")
        box.prop(item, "texture_hash")
        box.prop(item, "source_type")

        source_type = str(item.source_type or "")
        if source_type == 'MARK':
            box.prop(item, "mark_name")
            upstream_submesh = _resolve_upstream_submesh_name(self)
            if not upstream_submesh:
                box.label(text=tr("Upstream Submesh not resolved; mark names unavailable"), icon='ERROR')
        elif source_type == 'FILE':
            box.prop(item, "file_path")
            # With a FILE source the mark dropdown only borrows the hash:
            # pick the original texture here, then point file_path at the
            # replacement image.
            box.prop(item, "mark_name")
        else:
            box.prop(item, "resource_name")

        # Early hash format feedback; the export pass validates again and
        # raises a hard error so a typo can never reach the generated INI.
        hash_text = str(item.texture_hash or "").strip().lower()
        if hash_text and _TEXTURE_HASH_PATTERN.match(hash_text) is None:
            layout.label(text=tr("Texture hash looks wrong; expected 16 hexadecimal characters"), icon='ERROR')

        active_count = len([row_item for row_item in self.texture_hash_items if row_item.enabled])
        layout.label(text=tr("{count} hash binding(s)").format(count=active_count), icon='TEXTURE_DATA')


classes = (
    MMT_OT_TexHashBindAddItem,
    MMT_OT_TexHashBindRemoveItem,
    MMT_OT_TexHashBindAutoFill,
    MIMINode_Hash_Texture_Bind,
)


def register():
    # The PropertyGroup must exist before the node class that references it.
    bpy.utils.register_class(MIMITextureHashItem)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(MIMITextureHashItem)
