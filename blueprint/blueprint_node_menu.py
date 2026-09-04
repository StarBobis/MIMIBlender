
import bpy

from ..common.global_config import GlobalConfig
from ..utils.translate_utils import iface_, rpt_

from .blueprint_export_helper import BlueprintExportHelper


class SSMT_OT_CreateGroupFromSelection(bpy.types.Operator):
    '''Create nodes from selected objects and group them under a new Group node'''
    bl_idname = "ssmt.create_group_from_selection"
    bl_label = "将所选物体新建到组节点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'WARNING'}, rpt_("没有选择任何物体"))
            return {'CANCELLED'}

        # 获取当前活动的蓝图树
        node_tree = None
        
        # 1. 尝试从当前上下文获取蓝图树
        space_data = getattr(context, "space_data", None)
        if space_data and space_data.type == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        
        # 2. 如果当前不是节点编辑器，尝试查找当前打开的节点编辑器窗口
        if not node_tree:
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'NODE_EDITOR':
                        for space in area.spaces:
                            if space.type == 'NODE_EDITOR':
                                tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
                                if tree and tree.bl_idname == 'SSMTBlueprintTreeType':
                                    node_tree = tree
                                    break
                        if node_tree:
                            break
                if node_tree:
                    break
        
        # 3. 如果仍然找不到，使用默认的workspace蓝图
        if not node_tree:
            GlobalConfig.read_from_main_json_ssmt4()
            workspace_name = f"{GlobalConfig.get_workspace_name()}" if GlobalConfig.get_workspace_name() else "SSMT_Mod_Logic"
            node_tree = bpy.data.node_groups.get(workspace_name)
        
        if not node_tree or node_tree.bl_idname != 'SSMTBlueprintTreeType':
            self.report({'WARNING'}, rpt_("未找到有效的蓝图树，请先打开蓝图编辑器"))
            return {'CANCELLED'}

        # 计算节点位置偏移，防止重叠
        base_x = 0
        base_y = 0
        if node_tree.nodes:
             pass

        # 取消所有节点的选中状态
        for node in node_tree.nodes:
            node.select = False

        # 创建 Group 节点
        group_node = node_tree.nodes.new(type='SSMTNode_Object_Group')
        group_node.location = (base_x + 400, base_y)
        group_node.select = True
        
        # 创建 Object Nodes 并连接
        for i, obj in enumerate(selected_objects):
            obj_node = node_tree.nodes.new(type='SSMTNode_Object_Info')
            obj_node.location = (base_x, base_y - i * 150)
            obj_node.select = True
            
            obj_node.object_name = obj.name
            
            target_socket = None
            if len(group_node.inputs) > 0:
                 target_socket = group_node.inputs[-1]
            
            if target_socket:
                node_tree.links.new(obj_node.outputs[0], target_socket)
                group_node.update()

        return {'FINISHED'}


class SSMT_OT_CreateInternalSwitch(bpy.types.Operator):
    '''Create Object Info nodes from selected objects and connect them to a Switch Key node'''
    bl_idname = "ssmt.create_internal_switch"
    bl_label = "创建内部切换"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'WARNING'}, rpt_("没有选择任何物体"))
            return {'CANCELLED'}
        
        import re
        
        objects_with_sequence = []
        objects_without_sequence = []
        
        for obj in selected_objects:
            pattern = r'_(\d+)$'
            match = re.search(pattern, obj.name)
            
            if match:
                sequence_num = int(match.group(1))
                objects_with_sequence.append((sequence_num, obj))
            else:
                objects_without_sequence.append(obj)
        
        if objects_without_sequence:
            self.report({'WARNING'}, rpt_("以下物体没有序列号: {names}").format(names=', '.join([obj.name for obj in objects_without_sequence])))
            return {'CANCELLED'}
        
        if not objects_with_sequence:
            self.report({'WARNING'}, rpt_("没有找到带序列号的物体"))
            return {'CANCELLED'}
        
        objects_with_sequence.sort(key=lambda x: x[0])
        
        # 获取当前活动的蓝图树
        node_tree = None
        
        # 1. 尝试从当前上下文获取蓝图树
        space_data = getattr(context, "space_data", None)
        if space_data and space_data.type == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        
        # 2. 如果当前不是节点编辑器，尝试查找当前打开的节点编辑器窗口
        if not node_tree:
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'NODE_EDITOR':
                        for space in area.spaces:
                            if space.type == 'NODE_EDITOR':
                                tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
                                if tree and tree.bl_idname == 'SSMTBlueprintTreeType':
                                    node_tree = tree
                                    break
                        if node_tree:
                            break
                if node_tree:
                    break
        
        # 3. 如果仍然找不到，使用默认的workspace蓝图
        if not node_tree:
            GlobalConfig.read_from_main_json_ssmt4()
            workspace_name = f"{GlobalConfig.get_workspace_name()}" if GlobalConfig.get_workspace_name() else "SSMT_Mod_Logic"
            node_tree = bpy.data.node_groups.get(workspace_name)
        
        if not node_tree or node_tree.bl_idname != 'SSMTBlueprintTreeType':
            self.report({'WARNING'}, rpt_("未找到有效的蓝图树，请先打开蓝图编辑器"))
            return {'CANCELLED'}
        
        nodes = node_tree.nodes
        links = node_tree.links
        
        base_x = 0
        base_y = 0
        if nodes:
            max_x = max([node.location.x + node.width for node in nodes])
            base_x = max_x + 200
        
        for node in nodes:
            node.select = False
        
        switch_node = nodes.new(type='SSMTNode_SwitchKey')
        switch_node.location = (base_x + 600, base_y)
        
        while len(switch_node.inputs) > 1:
            switch_node.inputs.remove(switch_node.inputs[-1])
        
        while len(switch_node.inputs) < len(objects_with_sequence):
            switch_node.inputs.new('SSMTSocketObject', f"Status {len(switch_node.inputs)}")
        
        obj_nodes = []
        for i, (seq_num, obj) in enumerate(objects_with_sequence):
            obj_node = nodes.new(type='SSMTNode_Object_Info')
            obj_node.location = (base_x, base_y - i * 15)
            obj_node.object_name = obj.name
            obj_node.select = True
            obj_nodes.append(obj_node)
            
            if i < len(switch_node.inputs):
                links.new(obj_node.outputs[0], switch_node.inputs[i])
        
        switch_node.select = True
        
        self.report({'INFO'}, rpt_("已创建 {count} 个物体节点并连接到切换节点").format(count=len(obj_nodes)))
        return {'FINISHED'}


class SSMT_OT_RefreshBlueprintSubmeshList(bpy.types.Operator):
    bl_idname = "ssmt.refresh_blueprint_submesh_list"
    bl_label = "刷新 Submesh 列表"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        node_tree = BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not node_tree:
            self.report({'WARNING'}, rpt_("未找到有效的蓝图树，请先打开蓝图编辑器"))
            return {'CANCELLED'}

        submesh_names = BlueprintExportHelper.refresh_tree_submesh_list(tree=node_tree)
        self.report({'INFO'}, rpt_("已刷新当前蓝图的 Submesh 列表，共 {count} 项").format(count=len(submesh_names)))
        return {'FINISHED'}


class SSMT_OT_BatchSetSelectedObjectNodeSubmesh(bpy.types.Operator):
    bl_idname = "ssmt.batch_set_selected_object_node_submesh"
    bl_label = "批量设为指定Submesh"
    bl_options = {'REGISTER', 'UNDO'}

    def _get_node_tree(self, context):
        space_data = getattr(context, "space_data", None)
        if space_data and getattr(space_data, "type", None) == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
            if node_tree and getattr(node_tree, "bl_idname", "") == 'SSMTBlueprintTreeType':
                return node_tree
        return BlueprintExportHelper.get_current_blueprint_tree(context=context)

    def invoke(self, context, event):
        node_tree = self._get_node_tree(context)
        if not node_tree:
            self.report({'WARNING'}, rpt_("未找到有效的蓝图树，请先打开蓝图编辑器"))
            return {'CANCELLED'}

        BlueprintExportHelper.set_runtime_blueprint_tree(node_tree)
        submesh_names = BlueprintExportHelper.get_tree_submesh_names(tree=node_tree)
        if not submesh_names:
            self.report({'WARNING'}, rpt_("当前蓝图没有可用的 Submesh 列表，请先刷新 Submesh 列表"))
            return {'CANCELLED'}

        def draw_submesh_popup(menu, popup_context):
            layout = menu.layout
            for submesh_name in submesh_names:
                op = layout.operator(
                    "ssmt.apply_selected_object_node_submesh",
                    text=submesh_name,
                    icon='OUTLINER_COLLECTION',
                )
                op.target_submesh = submesh_name

        context.window_manager.popup_menu(
            draw_submesh_popup,
            title=iface_("目标 Submesh"),
            icon='OUTLINER_COLLECTION',
        )
        return {'FINISHED'}

    def execute(self, context):
        return self.invoke(context, None)


class SSMT_OT_ApplySelectedObjectNodeSubmesh(bpy.types.Operator):
    bl_idname = "ssmt.apply_selected_object_node_submesh"
    bl_label = "设为指定Submesh"
    bl_options = {'REGISTER', 'UNDO'}

    target_submesh: bpy.props.StringProperty(name="Submesh", default="") # type: ignore

    def _get_node_tree(self, context):
        space_data = getattr(context, "space_data", None)
        if space_data and getattr(space_data, "type", None) == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
            if node_tree and getattr(node_tree, "bl_idname", "") == 'SSMTBlueprintTreeType':
                return node_tree
        return BlueprintExportHelper.get_current_blueprint_tree(context=context)

    def execute(self, context):
        node_tree = self._get_node_tree(context)
        if not node_tree:
            self.report({'WARNING'}, rpt_("未找到有效的蓝图树，请先打开蓝图编辑器"))
            return {'CANCELLED'}

        target_submesh = str(self.target_submesh or "").strip()

        if not target_submesh:
            self.report({'WARNING'}, rpt_("请选择一个有效的 Submesh"))
            return {'CANCELLED'}

        updated_count = 0
        for node in node_tree.nodes:
            if not node.select or getattr(node, "bl_idname", "") != 'SSMTNode_Object_Info':
                continue
            node.submesh_name = target_submesh
            updated_count += 1

        if updated_count == 0:
            self.report({'WARNING'}, rpt_("当前未选中任何物体节点"))
            return {'CANCELLED'}

        self.report({'INFO'}, rpt_("已将 {count} 个物体节点设为 Submesh: {submesh}").format(count=updated_count, submesh=target_submesh))
        return {'FINISHED'}


def draw_objects_context_menu_add(self, context):
    layout = self.layout
    layout.separator()
    layout.menu("SSMT_MT_ObjectContextMenuSub", text=iface_("SSMT蓝图架构"), icon='NODETREE')

class SSMT_MT_ObjectContextMenuSub(bpy.types.Menu):
    bl_label = "SSMT蓝图架构"
    
    def draw(self, context):
        layout = self.layout
        layout.operator("ssmt.create_group_from_selection", text=iface_("将所选物体新建到组节点"), icon='GROUP')
        layout.operator("ssmt.create_internal_switch", text=iface_("创建内部切换"), icon='ARROW_LEFTRIGHT')

class SSMT_MT_NodeMenu_ModPanel(bpy.types.Menu):
    bl_label = "Mod面板"

    def draw(self, context):
        layout = self.layout
        layout.operator("node.add_node", text=iface_("生成Mod面板"), icon='MENU_PANEL').type = "SSMTNode_ModPanel"


class SSMT_OT_AlignNodes(bpy.types.Operator):
    '''将选中的节点按照矩阵对齐'''
    bl_idname = "ssmt.align_nodes"
    bl_label = "矩阵对齐节点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 获取当前节点树
        space_data = getattr(context, "space_data", None)
        if not space_data or space_data.type != 'NODE_EDITOR':
            self.report({'ERROR'}, rpt_("请在节点编辑器中使用此功能"))
            return {'CANCELLED'}

        node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        if not node_tree:
            self.report({'ERROR'}, rpt_("未找到节点树"))
            return {'CANCELLED'}

        # 获取选中的节点
        selected_nodes = [node for node in node_tree.nodes if node.select]
        if len(selected_nodes) < 2:
            self.report({'WARNING'}, rpt_("请至少选择2个节点"))
            return {'CANCELLED'}

        # 第一步：将节点按列分组（基于X坐标）
        columns = self.group_nodes_by_columns(selected_nodes)
        
        # 第二步：对每列内的节点进行垂直对齐
        for column in columns:
            self.align_column_vertically(column)
        
        # 第三步：对列之间进行横向对齐
        self.align_columns_horizontally(columns)
        
        # 第四步：调整节点顺序以匹配连接关系
        self.adjust_node_order_by_connections(selected_nodes, node_tree)

        self.report({'INFO'}, rpt_("已将 {node_count} 个节点结构化对齐，分为 {column_count} 列").format(node_count=len(selected_nodes), column_count=len(columns)))
        return {'FINISHED'}
    
    def group_nodes_by_columns(self, nodes):
        """将节点按X坐标分组成列"""
        if not nodes:
            return []
        
        # 计算节点平均宽度作为列间距阈值
        avg_width = sum(node.width for node in nodes) / len(nodes)
        column_threshold = avg_width * 1.1  # 检测范围为节点大小的1.1倍
        
        # 按X坐标排序节点
        sorted_nodes = sorted(nodes, key=lambda n: n.location.x)
        
        columns = []
        current_column = [sorted_nodes[0]]
        current_x = sorted_nodes[0].location.x
        
        for node in sorted_nodes[1:]:
            # 如果节点的X坐标与当前列的X坐标相差超过阈值，则开始新列
            if abs(node.location.x - current_x) > column_threshold:
                columns.append(current_column)
                current_column = [node]
                current_x = node.location.x
            else:
                current_column.append(node)
        
        # 添加最后一列
        if current_column:
            columns.append(current_column)
        
        return columns
    
    def align_column_vertically(self, column):
        """对单列内的节点进行垂直对齐"""
        if len(column) <= 1:
            return
        
        # 按Y坐标从上到下排序
        column.sort(key=lambda n: -n.location.y)
        
        # 计算起始位置（使用最上方的节点位置）
        start_x = column[0].location.x
        start_y = column[0].location.y
        
        # 固定的垂直间距
        vertical_spacing = 80.0
        
        # 对齐节点
        current_y = start_y
        for node in column:
            # 确保节点位置不重叠
            node.location = (start_x, current_y)
            # 使用固定的垂直间距
            current_y -= (node.height + vertical_spacing)
    
    def align_columns_horizontally(self, columns):
        """对列之间进行横向对齐"""
        if len(columns) <= 1:
            return
        
        # 计算所有节点的平均宽度，用于确定列间距
        all_nodes = [node for column in columns for node in column]
        avg_width = sum(node.width for node in all_nodes) / len(all_nodes)
        # 列间距保持为平均宽度的0.3倍，这是用户想要的间距
        column_spacing = avg_width * 0.3
        
        # 计算每列的边界
        column_bounds = []
        for i, column in enumerate(columns):
            if not column:
                continue
            
            # 计算列的边界，使用节点的实际位置
            x_min = min(node.location.x for node in column)
            x_max = max(node.location.x + node.width for node in column)
            
            # 计算列的中心X坐标
            center_x = (x_min + x_max) / 2
            
            # 计算列的宽度（包括边距）
            width = x_max - x_min + 10  # 添加10像素边距
            
            column_bounds.append({
                'index': i,
                'column': column,
                'center_x': center_x,
                'width': width,
                'x_min': x_min,
                'x_max': x_max
            })
        
        # 按中心X坐标排序列
        column_bounds.sort(key=lambda b: b['center_x'])
        
        # 对齐列，保持原有列间距
        current_x = column_bounds[0]['x_min']
        for bound in column_bounds:
            # 将列移动到当前X位置
            offset_x = current_x - bound['x_min']
            for node in bound['column']:
                node.location.x += offset_x
            
            # 更新当前X位置，为下一列预留空间
            # 使用基于节点大小的间距，确保大于检测范围（avg_width * 1.1）
            current_x += bound['width'] + column_spacing
    
    def adjust_node_order_by_connections(self, nodes, node_tree):
        """根据连接关系调整节点顺序，避免连接线交错"""
        if len(nodes) < 2:
            return
        
        # 构建节点连接图
        connection_graph = {}
        for node in nodes:
            connection_graph[node] = {'inputs': [], 'outputs': []}
        
        # 遍历所有连接
        for link in node_tree.links:
            from_node = link.from_node
            to_node = link.to_node
            
            if from_node in connection_graph and to_node in connection_graph:
                connection_graph[from_node]['outputs'].append(to_node)
                connection_graph[to_node]['inputs'].append(from_node)
        
        # 对每列中的节点进行排序
        for column in self.group_nodes_by_columns(nodes):
            if len(column) <= 1:
                continue
            
            # 按连接关系排序节点
            # 优先将没有输入的节点放在前面（源节点）
            column.sort(key=lambda n: (
                len(connection_graph[n]['inputs']),  # 输入数量少的在前
                -n.location.y  # 保持原有的垂直顺序
            ))


class SSMT_OT_BatchConnectNodes(bpy.types.Operator):
    '''批量连接选中的节点：支持一对一或多对一连接'''
    bl_idname = "ssmt.batch_connect_nodes"
    bl_label = "批量连接节点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 获取当前节点树
        space_data = getattr(context, "space_data", None)
        if not space_data or space_data.type != 'NODE_EDITOR':
            self.report({'ERROR'}, rpt_("请在节点编辑器中使用此功能"))
            return {'CANCELLED'}

        node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        if not node_tree:
            self.report({'ERROR'}, rpt_("未找到节点树"))
            return {'CANCELLED'}

        # 获取选中的节点
        selected_nodes = [node for node in node_tree.nodes if node.select]
        if len(selected_nodes) < 2:
            self.report({'WARNING'}, rpt_("请至少选择2个节点"))
            return {'CANCELLED'}

        # 统计节点类型分布
        type_count_dict = {}
        for node in selected_nodes:
            node_type = node.bl_idname
            type_count_dict[node_type] = type_count_dict.get(node_type, 0) + 1

        # 检查节点类型数量
        if len(type_count_dict) > 2:
            self.report({'ERROR'}, rpt_("所选节点类型过多（{count}种），请选择1-2种类型的节点").format(count=len(type_count_dict)))
            return {'CANCELLED'}

        # 判断连接模式
        if len(type_count_dict) == 1:
            # 只有一种类型：无法连接
            self.report({'ERROR'}, rpt_("所选节点类型相同，无法连接"))
            return {'CANCELLED'}
        else:
            # 两种类型：判断是一对一还是多对一
            type_items = list(type_count_dict.items())
            type_items.sort(key=lambda x: x[1], reverse=True)  # 按数量降序排序
            
            majority_type, majority_count = type_items[0]
            minority_type, minority_count = type_items[1]

            if majority_count == minority_count:
                # 数量相等：一对一连接
                return self.connect_one_to_one(selected_nodes, type_count_dict, node_tree)
            else:
                # 数量不等：多对一连接
                return self.connect_many_to_one(selected_nodes, type_count_dict, node_tree)

    def connect_one_to_one(self, selected_nodes, type_count_dict, node_tree):
        """一对一连接模式"""
        # 获取两种类型
        type_items = list(type_count_dict.items())
        type_a, count_a = type_items[0]
        type_b, count_b = type_items[1]

        # 按类型分组
        nodes_a = [node for node in selected_nodes if node.bl_idname == type_a]
        nodes_b = [node for node in selected_nodes if node.bl_idname == type_b]

        # 判断哪个是源节点（有输出端口），哪个是目标节点（有输入端口）
        # 优先根据端口特性判断，只有输出的作为源，有输入的作为目标
        a_has_output = len(nodes_a[0].outputs) > 0
        a_has_input = len(nodes_a[0].inputs) > 0
        b_has_output = len(nodes_b[0].outputs) > 0
        b_has_input = len(nodes_b[0].inputs) > 0

        if a_has_output and not a_has_input and b_has_input:
            # A只有输出，B有输入，A->B
            source_nodes, target_nodes = nodes_a, nodes_b
        elif b_has_output and not b_has_input and a_has_input:
            # B只有输出，A有输入，B->A
            source_nodes, target_nodes = nodes_b, nodes_a
        elif a_has_output and a_has_input and b_has_output and b_has_input:
            # 两种都有输入输出，根据位置判断（左边的连接到右边）
            avg_x_a = sum(node.location.x for node in nodes_a) / len(nodes_a)
            avg_x_b = sum(node.location.x for node in nodes_b) / len(nodes_b)
            if avg_x_a < avg_x_b:
                # A在左边，A->B
                source_nodes, target_nodes = nodes_a, nodes_b
            else:
                # B在左边，B->A
                source_nodes, target_nodes = nodes_b, nodes_a
        elif a_has_output and not a_has_input and not b_has_output:
            # A只有输出，B没有输出，A->B
            source_nodes, target_nodes = nodes_a, nodes_b
        elif b_has_output and not b_has_input and not a_has_output:
            # B只有输出，A没有输出，B->A
            source_nodes, target_nodes = nodes_b, nodes_a
        elif a_has_output and not b_has_input:
            # A有输出，B没有输入，A->B
            source_nodes, target_nodes = nodes_a, nodes_b
        elif b_has_output and not a_has_input:
            # B有输出，A没有输入，B->A
            source_nodes, target_nodes = nodes_b, nodes_a
        else:
            self.report({'ERROR'}, rpt_("无法确定连接方向，请检查节点端口配置"))
            return {'CANCELLED'}

        # 检查目标节点是否有输入端口
        for node in target_nodes:
            if len(node.inputs) == 0:
                self.report({'ERROR'}, rpt_("节点 '{node_name}' 没有输入端口").format(node_name=node.name))
                return {'CANCELLED'}

        # 清除现有连接
        for source_node in source_nodes:
            for output in source_node.outputs:
                for link in output.links:
                    if link.to_node in target_nodes:
                        node_tree.links.remove(link)

        # 按位置排序（从左到右，从上到下）
        source_nodes.sort(key=lambda n: (n.location.x, -n.location.y))
        target_nodes.sort(key=lambda n: (n.location.x, -n.location.y))

        # 一对一连接
        connection_info = []
        for i in range(min(len(source_nodes), len(target_nodes))):
            source_node = source_nodes[i]
            target_node = target_nodes[i]

            # 查找可用的输入端口
            available_input = None
            for input_socket in target_node.inputs:
                if not input_socket.is_linked:
                    available_input = input_socket
                    break

            # 如果没有可用的输入端口，尝试创建新端口
            if not available_input:
                try:
                    if hasattr(target_node, 'update'):
                        target_node.inputs.new('SSMTSocketObject', iface_("输入 {count}").format(count=len(target_node.inputs) + 1))
                        available_input = target_node.inputs[-1]
                except Exception:
                    self.report({'WARNING'}, rpt_("节点 '{node_name}' 没有可用的输入端口").format(node_name=target_node.name))
                    continue

            # 创建连接
            if available_input and len(source_node.outputs) > 0:
                node_tree.links.new(source_node.outputs[0], available_input)
                connection_info.append(f"{source_node.name} -> {target_node.name}")

        # 触发节点更新
        for node in target_nodes:
            if hasattr(node, 'update'):
                node.update()

        # 提供反馈
        total_connections = len(connection_info)
        self.report({'INFO'}, rpt_("一对一连接：成功连接 {count} 个节点对").format(count=total_connections))
        print(f"一对一连接完成，共创建 {total_connections} 个连接:")
        for info in connection_info:
            print(f"  {info}")

        return {'FINISHED'}

    def connect_many_to_one(self, selected_nodes, type_count_dict, node_tree):
        """多对一连接模式"""
        # 识别多数节点和少数节点
        type_items = list(type_count_dict.items())
        type_items.sort(key=lambda x: x[1], reverse=True)
        
        majority_type, majority_count = type_items[0]
        minority_type, minority_count = type_items[1]

        # 按类型分组节点
        majority_nodes = [node for node in selected_nodes if node.bl_idname == majority_type]
        minority_nodes = [node for node in selected_nodes if node.bl_idname == minority_type]

        # 检查节点是否有合适的输入/输出端口
        for node in majority_nodes:
            if len(node.outputs) == 0:
                self.report({'ERROR'}, rpt_("多数节点 '{node_name}' 没有输出端口").format(node_name=node.name))
                return {'CANCELLED'}

        for node in minority_nodes:
            if len(node.inputs) == 0:
                self.report({'ERROR'}, rpt_("少数节点 '{node_name}' 没有输入端口").format(node_name=node.name))
                return {'CANCELLED'}

        # 清除现有连接（只清除选中节点之间的连接）
        for node in majority_nodes:
            for output in node.outputs:
                for link in output.links:
                    if link.to_node in minority_nodes:
                        node_tree.links.remove(link)

        # 按从上到下的顺序排序节点（y坐标降序）
        majority_nodes.sort(key=lambda n: -n.location.y)
        minority_nodes.sort(key=lambda n: -n.location.y)

        # 分配连接：将多数节点平均分配到各个少数节点
        nodes_per_target = majority_count // minority_count
        remainder = majority_count % minority_count

        connection_info = []
        majority_index = 0

        for minority_index, minority_node in enumerate(minority_nodes):
            # 计算当前少数节点应该连接的多数节点数量
            current_batch_size = nodes_per_target + (1 if minority_index < remainder else 0)

            for i in range(current_batch_size):
                if majority_index >= len(majority_nodes):
                    break

                majority_node = majority_nodes[majority_index]

                # 查找可用的输入端口
                available_input = None
                for input_socket in minority_node.inputs:
                    if not input_socket.is_linked:
                        available_input = input_socket
                        break

                # 如果没有可用的输入端口，尝试创建新端口（针对支持动态端口的节点）
                if not available_input:
                    try:
                        # 某些节点（如Group、Output）支持动态添加端口
                        if hasattr(minority_node, 'update'):
                            minority_node.inputs.new('SSMTSocketObject', iface_("输入 {count}").format(count=len(minority_node.inputs) + 1))
                            available_input = minority_node.inputs[-1]
                    except Exception:
                        self.report({'WARNING'}, rpt_("节点 '{node_name}' 没有可用的输入端口").format(node_name=minority_node.name))
                        majority_index += 1
                        continue

                # 创建连接
                if available_input and len(majority_node.outputs) > 0:
                    node_tree.links.new(majority_node.outputs[0], available_input)
                    connection_info.append(f"{majority_node.name} -> {minority_node.name}")

                majority_index += 1

        # 触发节点更新
        for node in minority_nodes:
            if hasattr(node, 'update'):
                node.update()

        # 提供成功反馈
        total_connections = len(connection_info)
        self.report({'INFO'}, rpt_("多对一连接：成功连接 {count} 个节点对").format(count=total_connections))
        print(f"多对一连接完成，共创建 {total_connections} 个连接:")
        for info in connection_info:
            print(f"  {info}")

        return {'FINISHED'}
def draw_node_add_menu(self, context):
    if not isinstance(context.space_data, bpy.types.SpaceNodeEditor):
        return
    if context.space_data.tree_type != 'SSMTBlueprintTreeType':
        return
    
    layout = self.layout
    layout.operator("node.add_node", text=iface_("物体信息"), icon='OBJECT_DATAMODE').type = "SSMTNode_Object_Info"
    layout.operator("node.add_node", text=iface_("贴图"), icon='IMAGE_DATA').type = "SSMTNode_Texture"
    layout.operator("node.add_node", text="CustomShader", icon='NODE_COMPOSITING').type = "SSMTNode_CustomShader"
    layout.operator("node.add_node", text=iface_("分组"), icon='GROUP').type = "SSMTNode_Object_Group"
    layout.operator("node.add_node", text=iface_("生成Mod"), icon='EXPORT').type = "SSMTNode_Result_Output"
    layout.operator("node.add_node", text="导出面部 Mod", icon='MOD_MASK').type = "SSMTNode_Face_Mod_Export"
    layout.operator("node.add_node", text=iface_("按键切换"), icon='GROUP').type = "SSMTNode_SwitchKey"
    layout.menu("SSMT_MT_NodeMenu_ModPanel", text=iface_("Mod面板"), icon='MENU_PANEL')
    layout.separator()

    # Frame节点没有任何功能，它是Blender自带的一种辅助节点，用于在节点编辑器中组织和分组节点
    # 反正就当一个区域划分来用就行了
    layout.operator("node.add_node", text=iface_("框架"), icon='FILE_PARENT').type = "NodeFrame"
    layout.separator()



def draw_node_context_menu(self, context):
    """在节点编辑器右键菜单中添加批量连接选项"""
    if not isinstance(context.space_data, bpy.types.SpaceNodeEditor):
        return
    if context.space_data.tree_type != 'SSMTBlueprintTreeType':
        return
    
    layout = self.layout
    layout.separator()
    layout.operator("ssmt.make_group", text="Make Group", icon='NODETREE')
    layout.operator("ssmt.align_nodes", text=iface_("矩阵对齐节点"), icon='GRID')
    layout.operator("ssmt.batch_connect_nodes", text=iface_("批量连接节点"), icon='LINKED')
    layout.operator("ssmt.refresh_blueprint_submesh_list", text=iface_("刷新 Submesh 列表"), icon='FILE_REFRESH')
    layout.operator("ssmt.batch_set_selected_object_node_submesh", text=iface_("批量设为指定Submesh"), icon='OUTLINER_COLLECTION')
    layout.separator()
    layout.operator("ssmt.refresh_node_object_ids", text=iface_("刷新物体节点信息"), icon='FILE_REFRESH')


def register():
    bpy.utils.register_class(SSMT_OT_CreateGroupFromSelection)
    bpy.utils.register_class(SSMT_OT_CreateInternalSwitch)
    bpy.utils.register_class(SSMT_OT_RefreshBlueprintSubmeshList)
    bpy.utils.register_class(SSMT_OT_BatchSetSelectedObjectNodeSubmesh)
    bpy.utils.register_class(SSMT_OT_ApplySelectedObjectNodeSubmesh)
    bpy.utils.register_class(SSMT_OT_AlignNodes)
    bpy.utils.register_class(SSMT_OT_BatchConnectNodes)
    bpy.utils.register_class(SSMT_MT_ObjectContextMenuSub)
    bpy.utils.register_class(SSMT_MT_NodeMenu_ModPanel)
    bpy.types.NODE_MT_add.prepend(draw_node_add_menu)
    # 添加到 3D 视图物体右键菜单
    bpy.types.VIEW3D_MT_object_context_menu.append(draw_objects_context_menu_add)
    # 添加到节点编辑器右键菜单
    bpy.types.NODE_MT_context_menu.append(draw_node_context_menu)
    wm = bpy.context.window_manager
    keyconfig = wm.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')
        if not any(
            item.idname == 'ssmt.make_group' and item.type == 'G' and item.ctrl
            for item in keymap.keymap_items
        ):
            keymap.keymap_items.new('ssmt.make_group', 'G', 'PRESS', ctrl=True)
        if not any(item.idname == 'ssmt.group_tab' and item.type == 'TAB' for item in keymap.keymap_items):
            keymap.keymap_items.new('ssmt.group_tab', 'TAB', 'PRESS')

def unregister():
    wm = bpy.context.window_manager
    keyconfig = wm.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.get('Node Editor')
        if keymap:
            for item in list(keymap.keymap_items):
                if (
                    (item.idname == 'ssmt.make_group' and item.type == 'G' and item.ctrl)
                    or (item.idname == 'ssmt.group_tab' and item.type == 'TAB')
                ):
                    keymap.keymap_items.remove(item)
    bpy.types.NODE_MT_context_menu.remove(draw_node_context_menu)
    bpy.types.NODE_MT_add.remove(draw_node_add_menu)
    bpy.types.VIEW3D_MT_object_context_menu.remove(draw_objects_context_menu_add)

    bpy.utils.unregister_class(SSMT_MT_NodeMenu_ModPanel)
    bpy.utils.unregister_class(SSMT_MT_ObjectContextMenuSub)
    bpy.utils.unregister_class(SSMT_OT_BatchConnectNodes)
    bpy.utils.unregister_class(SSMT_OT_AlignNodes)
    bpy.utils.unregister_class(SSMT_OT_ApplySelectedObjectNodeSubmesh)
    bpy.utils.unregister_class(SSMT_OT_BatchSetSelectedObjectNodeSubmesh)
    bpy.utils.unregister_class(SSMT_OT_RefreshBlueprintSubmeshList)
    bpy.utils.unregister_class(SSMT_OT_CreateInternalSwitch)
    bpy.utils.unregister_class(SSMT_OT_CreateGroupFromSelection)
