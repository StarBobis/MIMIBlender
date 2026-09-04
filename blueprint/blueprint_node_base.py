'''
存放一些构建SSMT蓝图架构的基础节点
每种节点放在单独的py文件中
方便阅读理解
'''
import bpy
from bpy.types import NodeTree, Node, NodeSocket, PropertyGroup

from ..common.global_config import GlobalConfig



# Custom Socket Types
class SSMTSubmeshListItem(PropertyGroup):
    name: bpy.props.StringProperty(name="Submesh", default="") # type: ignore


class SSMTSocketObject(NodeSocket):
    '''Custom Socket for Object Data'''
    bl_idname = 'SSMTSocketObject'
    bl_label = '物体插槽'

    def draw_color(self, context, node):
        return (0.0, 0.8, 0.8, 1.0) # Cyan/Teal

    def draw(self, context, layout, node, text):
        layout.label(text=text)

# 1. 定义自定义节点树类型


class SSMTSocketTexture(NodeSocket):
    '''Custom Socket for Texture Slot'''
    bl_idname = 'SSMTSocketTexture'
    bl_label = '贴图插槽'

    def draw_color(self, context, node):
        return (0.8, 0.4, 0.9, 1.0)  # Purple/Magenta

    def draw(self, context, layout, node, text):
        layout.label(text=text)


class SSMTSocketCustomShader(NodeSocket):
    '''Custom Shader command list socket.'''
    bl_idname = 'SSMTSocketCustomShader'
    bl_label = 'CustomShader 插槽'

    def draw_color(self, context, node):
        return (0.95, 0.55, 0.15, 1.0)

    def draw(self, context, layout, node, text):
        layout.label(text=text)

class SSMTBlueprintTree(NodeTree):
    '''SSMT Mod Logic Blueprint'''
    bl_idname = 'SSMTBlueprintTreeType'
    bl_label = 'SSMT蓝图'
    bl_icon = 'NODETREE'


# 2. 定义基础节点
class SSMTNodeBase(Node):
    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == 'SSMTBlueprintTreeType'
    
    def calculate_text_width(self, text, padding=40):
        """计算文本所需的宽度（估算值）"""
        if not text:
            return 200
        
        # 中文字符宽度约为英文字符的2倍
        char_count = 0
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                char_count += 2
            else:
                char_count += 1
        
        # 每个字符约占用12像素宽度（Blender 节点 UI 字体较宽）
        width = char_count * 12 + padding
        
        # 确保最小宽度为200
        return max(200, width)
    
    def update_node_width(self, texts):
        """根据文本内容更新节点宽度"""
        if not texts:
            return
        
        max_width = 200
        for text in texts:
            width = self.calculate_text_width(text)
            if width > max_width:
                max_width = width
        
        # 给下拉列表预留额外宽度（右侧箭头和边距约50px）
        self.width = max_width + 50
    

class THEHERTA3_OT_OpenPersistentBlueprint(bpy.types.Operator):
    bl_idname = "theherta3.open_persistent_blueprint"
    bl_label = "打开蓝图界面"
    bl_description = "打开一个独立的蓝图窗口，用于配置Mod逻辑"
    bl_options = {'REGISTER', 'UNDO'}

    blueprint_name: bpy.props.StringProperty(
        name="Blueprint Name",
        default="",
        options={'SKIP_SAVE'},
    ) # type: ignore
    
    def execute(self, context):
        # 1. 获取或创建蓝图树
        GlobalConfig.read_from_main_json_ssmt4()
        requested_tree_name = str(self.blueprint_name or "").strip()
        tree_name = requested_tree_name or GlobalConfig.get_workspace_name()
        
        # 查找是否存在同名的 NodeGroup
        tree = bpy.data.node_groups.get(tree_name)
        if tree and getattr(tree, "bl_idname", "") != 'SSMTBlueprintTreeType':
            tree = None

        if not tree and requested_tree_name:
            from .blueprint_export_helper import BlueprintExportHelper
            tree = BlueprintExportHelper.get_selected_blueprint_tree(requested_tree_name, context=context)

        if not tree:
            # 创建新的 NodeTree，类型必须是我们定义的 bl_idname
            tree = bpy.data.node_groups.new(name=tree_name, type='SSMTBlueprintTreeType')
            tree.use_fake_user = True

        from .blueprint_export_helper import BlueprintExportHelper
        BlueprintExportHelper.set_runtime_blueprint_tree(tree)

        global_properties = getattr(getattr(context, "scene", None), "global_properties", None)
        if global_properties and getattr(global_properties, "selected_blueprint_name", "") != tree.name:
            global_properties.selected_blueprint_name = tree.name
        
        # 1.5 检查是否存在已开启的窗口；存在则复用，不再关闭重建。
        target_window = None
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'NODE_EDITOR' and space.node_tree == tree:
                            target_window = window
                            break
                if target_window: break
            if target_window: break

        if target_window:
            return {'FINISHED'}

        # 2. 打开独立主窗口，避免普通子窗口一直压在 Blender 主界面上方。
        old_windows = set(context.window_manager.windows)

        try:
            bpy.ops.wm.window_new_main()
        except (AttributeError, RuntimeError):
            bpy.ops.wm.window_new()
        
        new_windows = set(context.window_manager.windows)
        created_window = (new_windows - old_windows).pop() if (new_windows - old_windows) else None
        
        if created_window:
            screen = created_window.screen
            
            target_area = max(screen.areas, key=lambda a: a.width * a.height)
            
            if target_area:
                target_area.ui_type = 'SSMTBlueprintTreeType' # 似乎不起作用，NodeEditor需要指定tree type
                target_area.type = 'NODE_EDITOR'
                
                # 设置空间属性
                for space in target_area.spaces:
                    if space.type == 'NODE_EDITOR':
                        space.tree_type = 'SSMTBlueprintTreeType' # 关键：切换到自定义树类型
                        space.node_tree = tree # 设置要编辑的数据块
                        space.pin = True # 锁定
                        
                        # 尝试调整视图 (可选)
                        
        return {'FINISHED'}


class THEHERTA3_OT_DeletePersistentBlueprint(bpy.types.Operator):
    bl_idname = "theherta3.delete_persistent_blueprint"
    bl_label = "删除蓝图"
    bl_description = "删除当前选中的蓝图"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    blueprint_name: bpy.props.StringProperty(
        name="Blueprint Name",
        default="",
        options={'SKIP_SAVE'},
    ) # type: ignore

    def _get_target_tree(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        requested_tree_name = str(self.blueprint_name or "").strip()
        if requested_tree_name == "__NONE__":
            return None

        return BlueprintExportHelper.get_selected_blueprint_tree(requested_tree_name, context=context)

    def invoke(self, context, event):
        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, "当前没有蓝图可删除！")
            return {'CANCELLED'}

        self.blueprint_name = target_tree.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.label(text="确认删除当前选中的蓝图吗？", icon='TRASH')
        layout.label(text=self.blueprint_name)
        layout.label(text="删除后无法恢复，请确认不是误操作。", icon='ERROR')

    def execute(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, "当前没有蓝图可删除！")
            return {'CANCELLED'}

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'NODE_EDITOR':
                    continue
                for space in area.spaces:
                    if space.type != 'NODE_EDITOR':
                        continue
                    if getattr(space, "node_tree", None) == target_tree:
                        space.node_tree = None

        if BlueprintExportHelper.runtime_blueprint_tree_name == target_tree.name:
            BlueprintExportHelper.runtime_blueprint_tree_name = ""

        deleted_blueprint_name = target_tree.name
        bpy.data.node_groups.remove(target_tree)

        global_properties = getattr(getattr(context, "scene", None), "global_properties", None)
        preferred_blueprint_name = BlueprintExportHelper.get_preferred_blueprint_name(context=context)
        if global_properties:
            global_properties.selected_blueprint_name = preferred_blueprint_name or "__NONE__"

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, "已删除蓝图: " + deleted_blueprint_name)
        return {'FINISHED'}


class THEHERTA3_OT_RenamePersistentBlueprint(bpy.types.Operator):
    bl_idname = "theherta3.rename_persistent_blueprint"
    bl_label = "重命名蓝图"
    bl_description = "重命名当前选中的蓝图"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    blueprint_name: bpy.props.StringProperty(
        name="Blueprint Name",
        default="",
        options={'SKIP_SAVE'},
    ) # type: ignore

    new_blueprint_name: bpy.props.StringProperty(
        name="新蓝图名称",
        default="",
    ) # type: ignore

    def _get_target_tree(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        requested_tree_name = str(self.blueprint_name or "").strip()
        if requested_tree_name == "__NONE__":
            return None

        return BlueprintExportHelper.get_selected_blueprint_tree(requested_tree_name, context=context)

    def invoke(self, context, event):
        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, "当前没有蓝图可重命名！")
            return {'CANCELLED'}

        self.blueprint_name = target_tree.name
        self.new_blueprint_name = target_tree.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.label(text="请输入新的蓝图名称", icon='GREASEPENCIL')
        layout.prop(self, "new_blueprint_name", text="名称")

    def execute(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, "当前没有蓝图可重命名！")
            return {'CANCELLED'}

        new_name = str(self.new_blueprint_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, "蓝图名称不能为空！")
            return {'CANCELLED'}

        if new_name == "__NONE__":
            self.report({'ERROR'}, "蓝图名称不能使用保留值 __NONE__！")
            return {'CANCELLED'}

        if new_name == target_tree.name:
            self.report({'INFO'}, "蓝图名称未发生变化")
            return {'CANCELLED'}

        existing_tree = bpy.data.node_groups.get(new_name)
        if existing_tree and existing_tree != target_tree:
            self.report({'ERROR'}, "已存在同名蓝图，请使用其他名称！")
            return {'CANCELLED'}

        old_name = target_tree.name
        target_tree.name = new_name

        if BlueprintExportHelper.runtime_blueprint_tree_name == old_name:
            BlueprintExportHelper.runtime_blueprint_tree_name = target_tree.name

        global_properties = getattr(getattr(context, "scene", None), "global_properties", None)
        if global_properties:
            global_properties.selected_blueprint_name = target_tree.name

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, "已将蓝图重命名为: " + target_tree.name)
        return {'FINISHED'}
    
class SSMT_PT_FrameProperties(bpy.types.Panel):
    '''Frame 框属性面板：选中 Frame 节点后可在侧边栏调节颜色、透明度、标签等属性'''
    bl_idname = "SSMT_PT_FrameProperties"
    bl_label = "Frame 框属性"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "SSMT"

    @classmethod
    def poll(cls, context):
        # 仅在 SSMT 蓝图树中显示
        space = context.space_data
        if space.type != 'NODE_EDITOR':
            return False
        tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
        if not tree or getattr(tree, "bl_idname", "") != 'SSMTBlueprintTreeType':
            return False
        # 检查是否有 Frame 节点被选中
        if not context.selected_nodes:
            return False
        for node in context.selected_nodes:
            if node.bl_idname == 'NodeFrame':
                return True
        return False

    def draw(self, context):
        layout = self.layout
        # 收集所有选中的 Frame 节点
        frames = [n for n in context.selected_nodes if n.bl_idname == 'NodeFrame']
        if not frames:
            return

        # 全部用第一个 frame 的属性来设置，多选时统一应用
        frame = frames[0]

        # === 标签 ===
        box = layout.box()
        box.label(text="标签", icon='FONT_DATA')
        col = box.column(align=True)
        col.prop(frame, "label", text="名称")
        col.prop(frame, "label_size", text="字体大小")

        # === 外观 ===
        box = layout.box()
        box.label(text="外观", icon='MATERIAL')
        col = box.column(align=True)
        col.prop(frame, "use_custom_color", text="自定义颜色")
        if frame.use_custom_color:
            col.prop(frame, "color", text="")
        col.prop(frame, "shrink", text="自动收缩大小")

        # === 尺寸 ===
        box = layout.box()
        box.label(text="尺寸", icon='MESH_PLANE')
        col = box.column(align=True)
        col.prop(frame, "width", text="宽度")
        col.prop(frame, "height", text="高度")

        # === 扩展文本 ===
        box = layout.box()
        box.label(text="描述文本", icon='TEXT')
        col = box.column()
        col.prop(frame, "text", text="")

        # === 可见性 ===
        box = layout.box()
        box.label(text="可见性", icon='HIDE_OFF')
        col = box.column(align=True)
        col.prop(frame, "hide", text="隐藏")
        col.prop(frame, "mute", text="静音（禁用）")

        # === 多选统一应用按钮 ===
        if len(frames) > 1:
            layout.separator()
            layout.label(text=f"已选中 {len(frames)} 个 Frame", icon='INFO')
            layout.label(text="修改上方属性后，点击按钮应用到全部", icon='LOOP_BACK')
            op = layout.operator("ssmt.apply_frame_properties_to_all", text="应用到所有选中 Frame", icon='CHECKMARK')
            op.source_frame_name = frame.name
            op.tree_name = frame.id_data.name if frame.id_data else ""


class SSMT_OT_ApplyFramePropertiesToAll(bpy.types.Operator):
    '''将第一个选中 Frame 的所有属性复制到其余选中的 Frame'''
    bl_idname = "ssmt.apply_frame_properties_to_all"
    bl_label = "应用到所有选中 Frame"
    bl_options = {'REGISTER', 'UNDO'}

    source_frame_name: bpy.props.StringProperty()  # type: ignore
    tree_name: bpy.props.StringProperty()          # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        if not tree:
            return {'CANCELLED'}

        source = tree.nodes.get(self.source_frame_name)
        if not source or source.bl_idname != 'NodeFrame':
            return {'CANCELLED'}

        frames = [n for n in context.selected_nodes if n.bl_idname == 'NodeFrame' and n != source]
        props = [
            'label', 'label_size', 'use_custom_color', 'color',
            'shrink', 'width', 'height', 'text', 'hide', 'mute'
        ]
        for frame in frames:
            for prop in props:
                setattr(frame, prop, getattr(source, prop))

        self.report({'INFO'}, f"已将 {source.label or source.name} 的属性应用到 {len(frames)} 个 Frame")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(SSMTSubmeshListItem)
    bpy.utils.register_class(SSMTBlueprintTree)
    bpy.utils.register_class(SSMTSocketObject)
    bpy.utils.register_class(SSMTSocketTexture)
    bpy.utils.register_class(SSMTSocketCustomShader)
    bpy.utils.register_class(THEHERTA3_OT_OpenPersistentBlueprint)
    bpy.utils.register_class(THEHERTA3_OT_DeletePersistentBlueprint)
    bpy.utils.register_class(THEHERTA3_OT_RenamePersistentBlueprint)
    bpy.utils.register_class(SSMT_PT_FrameProperties)
    bpy.utils.register_class(SSMT_OT_ApplyFramePropertiesToAll)
    SSMTBlueprintTree.ssmt_submesh_items = bpy.props.CollectionProperty(type=SSMTSubmeshListItem) # type: ignore[attr-defined]
    from .blueprint_export_helper import BlueprintExportHelper
    BlueprintExportHelper.register_workspace_tree_sync_timer()


def unregister():
    from .blueprint_export_helper import BlueprintExportHelper
    BlueprintExportHelper.unregister_workspace_tree_sync_timer()
    del SSMTBlueprintTree.ssmt_submesh_items
    bpy.utils.unregister_class(SSMT_OT_ApplyFramePropertiesToAll)
    bpy.utils.unregister_class(SSMTSocketCustomShader)
    bpy.utils.unregister_class(SSMT_PT_FrameProperties)
    bpy.utils.unregister_class(THEHERTA3_OT_RenamePersistentBlueprint)
    bpy.utils.unregister_class(THEHERTA3_OT_DeletePersistentBlueprint)
    bpy.utils.unregister_class(SSMTSocketObject)
    bpy.utils.unregister_class(SSMTSocketTexture)
    bpy.utils.unregister_class(THEHERTA3_OT_OpenPersistentBlueprint)
    bpy.utils.unregister_class(SSMTBlueprintTree)
    bpy.utils.unregister_class(SSMTSubmeshListItem)
