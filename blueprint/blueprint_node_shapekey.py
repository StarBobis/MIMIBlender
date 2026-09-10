
import bpy

from ..i18n.i18n import I18nOperator, tr

# Shape key list item
class MIMIShapeKeyListItem(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(name="", default=False) # type: ignore
    shapekey_name: bpy.props.StringProperty(name=tr("Shape Key Name"), default="") # type: ignore
    key: bpy.props.StringProperty(name=tr("Key"), default="") # type: ignore


# Refresh shape key list
class SSMT_OT_RefreshShapeKeyList(I18nOperator):
    bl_idname = "mimi.refresh_shapekey_list"
    bl_label = "Refresh Shape Key List"
    bl_description = "Scans all object nodes in the blueprint and collects their shape keys"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def _get_shapekeys_from_object(obj):
        """Return the names of all shape keys of the object (skipping the first one, the Basis)."""
        if not obj or obj.type != 'MESH':
            return []
        shape_keys = getattr(obj.data, 'shape_keys', None)
        if not shape_keys:
            return []
        return [kb.name for kb in list(shape_keys.key_blocks)[1:]]

    def execute(self, context):
        tree = context.space_data.edit_tree
        if not tree or getattr(tree, 'bl_idname', '') != 'MIMIBlueprintTreeType':
            self.report({'WARNING'}, tr("Please run this inside the SSMT blueprint editor"))
            return {'CANCELLED'}

        output_node = None
        for node in tree.nodes:
            if node.bl_idname == 'MIMINode_Result_Output':
                output_node = node
                break
        if not output_node:
            self.report({'WARNING'}, tr("The current blueprint is missing a \"Generate Mod\" output node"))
            return {'CANCELLED'}

        previous_items = {
            item.shapekey_name: (item.enabled, item.key)
            for item in output_node.shapekey_items
            if item.shapekey_name
        }
        seen = set()
        output_node.shapekey_items.clear()
        for node in tree.nodes:
            if node.bl_idname != 'MIMINode_Object_Info':
                continue
            obj = bpy.data.objects.get(node.object_name)
            for sk_name in self._get_shapekeys_from_object(obj):
                if sk_name in seen:
                    continue
                seen.add(sk_name)
                item = output_node.shapekey_items.add()
                item.shapekey_name = sk_name
                if sk_name in previous_items:
                    item.enabled, item.key = previous_items[sk_name]

        self.report({'INFO'}, tr("Refreshed {count} shape keys").format(count=len(output_node.shapekey_items)))
        return {'FINISHED'}


def draw_shapekey_settings(node, layout):
    """Draw the shape key settings of the Generate Mod output node."""
    layout.prop(node, "enable_shapekey", text=tr("Generate Shape Key Mod"), icon='SHAPEKEY_DATA')
    if not node.enable_shapekey:
        return

    box = layout.box()
    row = box.row(align=True)
    row.operator("mimi.refresh_shapekey_list", text=tr("Refresh List"), icon='FILE_REFRESH')
    row.label(text=tr("Total: {count}").format(count=len(node.shapekey_items)) if node.shapekey_items else tr("(Empty)"), icon='SHAPEKEY_DATA')

    for item in node.shapekey_items:
        row = box.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.shapekey_name, icon='SHAPEKEY_DATA')
        row.prop(item, "key", text="", placeholder=tr("VK key value (optional)"))
        op = row.operator("wm.url_open", text="", icon='HELP')
        op.url = "https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes"


classes = (
    MIMIShapeKeyListItem,
    SSMT_OT_RefreshShapeKeyList,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
