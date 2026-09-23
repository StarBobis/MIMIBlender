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

Texture sources for the conditional node:
- MARK: reuse a Hash-style SSMT5 mark file.
- FILE: copy an external image file into the generated mod.
- RESOURCE: reference an existing resource name.

Texture sources for the global node are FILE and RESOURCE. A global node has
no upstream Submesh, so it cannot resolve a mark name safely.
'''
import os
import re

import bpy
from bpy.types import PropertyGroup
from bpy_extras.io_utils import ImportHelper

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase
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
    if str(getattr(item, "file_path", "") or "").strip() and str(getattr(item, "source_type", "") or "") != 'FILE':
        item.source_type = 'FILE'
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


def _texture_hash_source_type_items(item, context):
    '''Hide mark sources on a global node that has no Submesh.'''
    owner = _find_hash_item_owner(item)
    if getattr(owner, "bl_idname", "") == 'MIMINode_Hash_Texture_Global':
        return [
            ('FILE', tr("External File"), tr("Copy an external image file into the generated mod")),
            ('RESOURCE', tr("Existing Resource"), tr("Reference an existing [ResourceXXX] section by name")),
        ]
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
    '''Draw a visible browse button beside the path field.'''
    row = layout.row(align=True)
    row.prop(item, "file_path", text=tr("Texture File"))

    select_operator = row.operator(
        "mimi.texhashbind_select_file",
        text="",
        icon='FILE_FOLDER',
    )
    select_operator.node_name = node.name
    select_operator.tree_name = tree.name if tree else ""
    select_operator.item_index = item_index

    clear_operator = row.operator(
        "mimi.texhashbind_clear_file",
        text="",
        icon='X',
    )
    clear_operator.node_name = node.name
    clear_operator.tree_name = tree.name if tree else ""
    clear_operator.item_index = item_index


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
        # Unique list id per node; see the Texture Bind node for why a
        # constant id would share the scroll/height state between nodes.
        row.template_list(
            "UI_UL_list", "mimi_texture_hash_bind_" + self.name,
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
            _draw_hash_file_picker(
                layout=box,
                item=item,
                node=self,
                tree=tree,
                item_index=index,
            )
            # The optional mark dropdown borrows only the original hash. The
            # selected file remains the replacement image that is copied.
            box.prop(item, "mark_name", text=tr("Hash Source Mark"))
        else:
            box.prop(item, "resource_name")

        # Early hash format feedback; the export pass validates again and
        # raises a hard error so a typo can never reach the generated INI.
        hash_text = str(item.texture_hash or "").strip().lower()
        if hash_text and _TEXTURE_HASH_PATTERN.match(hash_text) is None:
            layout.label(text=tr("Texture hash looks wrong; expected 8 hexadecimal characters (a 32-bit texture hash)"), icon='ERROR')

        active_count = len([row_item for row_item in self.texture_hash_items if row_item.enabled])
        layout.label(text=tr("{count} hash binding(s)").format(count=active_count), icon='TEXTURE_DATA')


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
        self.width = 360
        self.use_custom_color = True
        self.color = (0.25, 0.48, 0.30)

    def draw_buttons(self, context, layout):
        tree = self.id_data if getattr(self, "id_data", None) and getattr(self.id_data, "bl_idname", "") == 'MIMIBlueprintTreeType' else None

        row = layout.row()
        row.template_list(
            "UI_UL_list", "mimi_texture_hash_global_" + self.name,
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

        if not self.texture_hash_items:
            layout.label(text=tr("No global hash overrides configured"), icon='INFO')
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
        if source_type == 'FILE':
            _draw_hash_file_picker(
                layout=box,
                item=item,
                node=self,
                tree=tree,
                item_index=index,
            )
        elif source_type == 'RESOURCE':
            box.prop(item, "resource_name")
        else:
            box.label(text=tr("Global node accepts External File or Existing Resource"), icon='ERROR')

        hash_text = str(item.texture_hash or "").strip().lower()
        if hash_text and _TEXTURE_HASH_PATTERN.match(hash_text) is None:
            layout.label(text=tr("Texture hash looks wrong; expected 8 hexadecimal characters (a 32-bit texture hash)"), icon='ERROR')

        active_count = len([row_item for row_item in self.texture_hash_items if row_item.enabled])
        layout.label(text=tr("{count} global hash replacement(s)").format(count=active_count), icon='TEXTURE_DATA')


classes = (
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
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(MIMITextureHashItem)
