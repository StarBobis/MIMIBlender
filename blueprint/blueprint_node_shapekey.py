
import bpy

from ..utils.translate_utils import iface_
# ── 形态键列表项 ──
class SSMTShapeKeyListItem(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(name="", default=False) # type: ignore
    shapekey_name: bpy.props.StringProperty(name="形态键名称", default="") # type: ignore
    key: bpy.props.StringProperty(name="按键", default="") # type: ignore


# ── 刷新形态键列表 ──
class SSMT_OT_RefreshShapeKeyList(bpy.types.Operator):
    bl_idname = "ssmt.refresh_shapekey_list"
    bl_label = "刷新形态键列表"
    bl_description = "扫描蓝图中的所有物体节点，提取形态键列表"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def _get_shapekeys_from_object(obj):
        """返回物体所有形态键名称（跳过第一个，即 Basis / 基型）。"""
        if not obj or obj.type != 'MESH':
            return []
        shape_keys = getattr(obj.data, 'shape_keys', None)
        if not shape_keys:
            return []
        return [kb.name for kb in list(shape_keys.key_blocks)[1:]]

    def execute(self, context):
        tree = context.space_data.edit_tree
        if not tree or getattr(tree, 'bl_idname', '') != 'SSMTBlueprintTreeType':
            self.report({'WARNING'}, "请在 SSMT 蓝图编辑器中执行")
            return {'CANCELLED'}

        output_node = None
        for node in tree.nodes:
            if node.bl_idname == 'SSMTNode_Result_Output':
                output_node = node
                break
        if not output_node:
            self.report({'WARNING'}, "当前蓝图缺少「生成 Mod」输出节点")
            return {'CANCELLED'}

        previous_items = {
            item.shapekey_name: (item.enabled, item.key)
            for item in output_node.shapekey_items
            if item.shapekey_name
        }
        seen = set()
        output_node.shapekey_items.clear()
        for node in tree.nodes:
            if node.bl_idname != 'SSMTNode_Object_Info':
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

        self.report({'INFO'}, f"已刷新 {len(output_node.shapekey_items)} 个形态键")
        return {'FINISHED'}


def draw_shapekey_settings(node, layout):
    """绘制 Generate Mod 输出节点中的形态键设置。"""
    layout.prop(node, "enable_shapekey", text=iface_("生成形态键 Mod"), icon='SHAPEKEY_DATA')
    if not node.enable_shapekey:
        return

    box = layout.box()
    row = box.row(align=True)
    row.operator("ssmt.refresh_shapekey_list", text=iface_("刷新列表"), icon='FILE_REFRESH')
    row.label(text=f"共 {len(node.shapekey_items)} 个" if node.shapekey_items else iface_("（空）"), icon='SHAPEKEY_DATA')

    for item in node.shapekey_items:
        row = box.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.shapekey_name, icon='SHAPEKEY_DATA')
        row.prop(item, "key", text="", placeholder="VK键值（可选）")
        op = row.operator("wm.url_open", text="", icon='HELP')
        op.url = "https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes"


classes = (
    SSMTShapeKeyListItem,
    SSMT_OT_RefreshShapeKeyList,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
