import os

import bpy
from ..common.global_config import GlobalConfig
from ..common.m_key import M_Key
from ..workspace.ssmt_workspace import SSMTWorkSpace

class BlueprintExportHelper:

    # 运行时记录当前操作对应的蓝图树，避免按钮触发后丢失上下文
    runtime_blueprint_tree_name = ""
    runtime_output_node = None
    _workspace_tree_sync_timer_registered = False
    _node_editor_tree_type_by_space = {}

    @staticmethod
    def _is_valid_blueprint_tree(tree):
        return (
            tree is not None
            and getattr(tree, "bl_idname", "") == 'SSMTBlueprintTreeType'
            and getattr(tree, "users", 0) > 0
        )

    @staticmethod
    def get_all_blueprint_trees():
        blueprint_trees = [
            node_group for node_group in bpy.data.node_groups
            if BlueprintExportHelper._is_valid_blueprint_tree(node_group)
        ]
        blueprint_trees.sort(key=lambda tree: tree.name.casefold())
        return blueprint_trees

    @staticmethod
    def get_blueprint_tree_by_name(tree_name):
        if not tree_name:
            return None

        tree = bpy.data.node_groups.get(tree_name)
        if BlueprintExportHelper._is_valid_blueprint_tree(tree):
            return tree

        return None

    @staticmethod
    def get_preferred_blueprint_name(selected_name="", context=None):
        selected_tree = BlueprintExportHelper.get_blueprint_tree_by_name(selected_name)
        if selected_tree:
            return selected_tree.name

        current_tree = BlueprintExportHelper._get_blueprint_tree_from_context(context)
        if BlueprintExportHelper._is_valid_blueprint_tree(current_tree):
            return current_tree.name

        runtime_tree = BlueprintExportHelper.get_blueprint_tree_by_name(
            BlueprintExportHelper.runtime_blueprint_tree_name,
        )
        if runtime_tree:
            return runtime_tree.name

        workspace_tree = BlueprintExportHelper.get_blueprint_tree_by_name(GlobalConfig.get_workspace_name())
        if workspace_tree:
            return workspace_tree.name

        all_blueprints = BlueprintExportHelper.get_all_blueprint_trees()
        if all_blueprints:
            return all_blueprints[0].name

        return ""

    @staticmethod
    def get_blueprint_enum_items(context=None):
        items = []
        preferred_name = BlueprintExportHelper.get_preferred_blueprint_name(context=context)

        for tree in BlueprintExportHelper.get_all_blueprint_trees():
            description = "当前默认蓝图" if tree.name == preferred_name else "选择该蓝图进行打开或生成 Mod"
            items.append((tree.name, tree.name, description))

        if not items:
            items.append(("__NONE__", "当前没有蓝图", "当前没有可选蓝图，请先打开蓝图界面或执行一键导入"))

        return items

    @staticmethod
    def set_runtime_blueprint_tree(tree):
        if BlueprintExportHelper._is_valid_blueprint_tree(tree):
            BlueprintExportHelper.runtime_blueprint_tree_name = tree.name

    @staticmethod
    def reveal_tree_in_node_editors(context, tree):
        '''让所有已打开的 SSMT 蓝图节点编辑器切换到指定的蓝图树。'''
        if not BlueprintExportHelper._is_valid_blueprint_tree(tree):
            return

        window_manager = getattr(context, "window_manager", None) if context else None
        if not window_manager:
            window_manager = getattr(bpy.context, "window_manager", None)
        if not window_manager:
            return

        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'NODE_EDITOR':
                    continue
                switched = False
                for space in area.spaces:
                    if space.type != 'NODE_EDITOR':
                        continue
                    if getattr(space, "tree_type", '') != 'SSMTBlueprintTreeType':
                        continue
                    if getattr(space, "node_tree", None) != tree:
                        space.node_tree = tree
                    switched = True
                if switched:
                    area.tag_redraw()

    @staticmethod
    def _get_blueprint_tree_from_context(context):
        if not context:
            return None

        space_data = getattr(context, "space_data", None)
        if space_data and getattr(space_data, "type", None) == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
            if BlueprintExportHelper._is_valid_blueprint_tree(node_tree):
                return node_tree

        window_manager = getattr(context, "window_manager", None)
        if not window_manager:
            return None

        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'NODE_EDITOR':
                    continue
                for space in area.spaces:
                    if space.type != 'NODE_EDITOR':
                        continue
                    node_tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
                    if BlueprintExportHelper._is_valid_blueprint_tree(node_tree):
                        return node_tree

        return None

    @staticmethod
    def _bind_workspace_tree_to_space(space):
        """当区域刚切换到 SSMT 树类型时绑定工作空间同名蓝图。"""
        if getattr(space, "tree_type", "") != 'SSMTBlueprintTreeType':
            return None
        workspace_name = str(GlobalConfig.get_workspace_name() or "").strip()
        if not workspace_name:
            return None
        tree = bpy.data.node_groups.get(workspace_name)
        if not BlueprintExportHelper._is_valid_blueprint_tree(tree):
            return None
        if getattr(space, "node_tree", None) != tree:
            space.node_tree = tree
        BlueprintExportHelper.set_runtime_blueprint_tree(tree)
        return tree

    @staticmethod
    def _sync_workspace_tree_timer():
        """仅在区域切换到 SSMT 蓝图类型时绑定工作空间蓝图一次。"""
        current_tree_type_by_space = {}
        for window in getattr(bpy.context.window_manager, "windows", []):
            for area in getattr(window.screen, "areas", []):
                if area.type != 'NODE_EDITOR':
                    continue
                for space in getattr(area, "spaces", []):
                    if space.type != 'NODE_EDITOR':
                        continue
                    space_id = space.as_pointer()
                    current_tree_type = getattr(space, "tree_type", "")
                    previous_tree_type = BlueprintExportHelper._node_editor_tree_type_by_space.get(space_id)
                    current_tree_type_by_space[space_id] = current_tree_type
                    if (
                        current_tree_type == 'SSMTBlueprintTreeType'
                        and previous_tree_type != 'SSMTBlueprintTreeType'
                        and getattr(space, "node_tree", None) is None
                    ):
                        BlueprintExportHelper._bind_workspace_tree_to_space(space)
        BlueprintExportHelper._node_editor_tree_type_by_space = current_tree_type_by_space
        return 0.5

    @staticmethod
    def register_workspace_tree_sync_timer():
        if BlueprintExportHelper._workspace_tree_sync_timer_registered:
            return
        bpy.app.timers.register(
            BlueprintExportHelper._sync_workspace_tree_timer,
            first_interval=0.1,
            persistent=True,
        )
        BlueprintExportHelper._workspace_tree_sync_timer_registered = True

    @staticmethod
    def unregister_workspace_tree_sync_timer():
        if not BlueprintExportHelper._workspace_tree_sync_timer_registered:
            return
        try:
            bpy.app.timers.unregister(BlueprintExportHelper._sync_workspace_tree_timer)
        except (ReferenceError, ValueError):
            pass
        BlueprintExportHelper._workspace_tree_sync_timer_registered = False
        BlueprintExportHelper._node_editor_tree_type_by_space.clear()
    
    @staticmethod
    def get_current_blueprint_tree(context=None):
        """获取当前工作空间对应的蓝图树"""
        tree = BlueprintExportHelper._get_blueprint_tree_from_context(context)
        if BlueprintExportHelper._is_valid_blueprint_tree(tree):
            BlueprintExportHelper.set_runtime_blueprint_tree(tree)
            return tree

        runtime_tree_name = BlueprintExportHelper.runtime_blueprint_tree_name
        if runtime_tree_name:
            tree = bpy.data.node_groups.get(runtime_tree_name)
            if BlueprintExportHelper._is_valid_blueprint_tree(tree):
                return tree

        tree_name = GlobalConfig.get_workspace_name()
        if not tree_name:
            return None
        
        tree = bpy.data.node_groups.get(tree_name)
        if BlueprintExportHelper._is_valid_blueprint_tree(tree):
            BlueprintExportHelper.set_runtime_blueprint_tree(tree)
            return tree

        return None

    @staticmethod
    def get_selected_blueprint_tree(selected_name="", context=None):
        preferred_name = BlueprintExportHelper.get_preferred_blueprint_name(
            selected_name=selected_name,
            context=context,
        )
        return BlueprintExportHelper.get_blueprint_tree_by_name(preferred_name)

    @staticmethod
    def get_tree_submesh_names(tree=None, context=None):
        current_tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not BlueprintExportHelper._is_valid_blueprint_tree(current_tree):
            return []

        return [str(item.name) for item in getattr(current_tree, "ssmt_submesh_items", []) if getattr(item, "name", "")]

    @staticmethod
    def set_tree_submesh_names(submesh_names, tree=None, context=None):
        current_tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not BlueprintExportHelper._is_valid_blueprint_tree(current_tree):
            return []

        normalized_names = []
        seen_names = set()
        for submesh_name in submesh_names:
            normalized_name = str(submesh_name or "").strip()
            if not normalized_name or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            normalized_names.append(normalized_name)

        current_tree.ssmt_submesh_items.clear()
        for submesh_name in normalized_names:
            item = current_tree.ssmt_submesh_items.add()
            item.name = submesh_name

        BlueprintExportHelper.set_runtime_blueprint_tree(current_tree)
        return normalized_names

    @staticmethod
    def refresh_tree_submesh_list(tree=None, context=None):
        current_tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not BlueprintExportHelper._is_valid_blueprint_tree(current_tree):
            return []

        from ..workspace.ssmt_workspace import WorkSpaceModel
        ws_model = WorkSpaceModel()
        all_display_names = ws_model.get_all_display_names()

        return BlueprintExportHelper.set_tree_submesh_names(all_display_names, tree=current_tree)

    @staticmethod
    def find_node_in_all_blueprints(node_name):
        """在所有蓝图中查找指定名称的节点"""
        for node_group in bpy.data.node_groups:
            if node_group.bl_idname == 'SSMTBlueprintTreeType':
                node = node_group.nodes.get(node_name)
                if node:
                    return node
        return None

    @staticmethod
    @staticmethod
    def get_node_from_bl_idname(tree, node_type:str):
        """在树中查找输出节点 (假设只有一个)"""
        if not tree:
            return None
        for node in tree.nodes:
            if node.bl_idname == node_type:
                return node
        return None
    
    @staticmethod
    def get_nodes_from_bl_idname(tree, node_type:str):
        """在树中查找所有匹配的节点"""
        if not tree:
            return []
        nodes = []
        for node in tree.nodes:
            if node.bl_idname == node_type:
                nodes.append(node)
        return nodes

    @staticmethod
    def get_active_mod_panel_nodes(context=None, tree=None):
        current_tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not current_tree:
            return []

        panel_nodes = BlueprintExportHelper.get_nodes_from_bl_idname(current_tree, 'SSMTNode_ModPanel')
        return [node for node in panel_nodes if not getattr(node, "mute", False)]

    @staticmethod
    def has_mod_panel_node(context=None, tree=None):
        return len(BlueprintExportHelper.get_active_mod_panel_nodes(context=context, tree=tree)) > 0

    @staticmethod
    def is_mod_panel_flow_effect_enabled(context=None, tree=None):
        panel_nodes = BlueprintExportHelper.get_active_mod_panel_nodes(context=context, tree=tree)
        if not panel_nodes:
            return False
        return any(getattr(node, "enable_flow_effect", True) for node in panel_nodes)
    
    @staticmethod
    def get_connected_nodes(current_node):
        """
        按照插槽顺序返回所有连接的节点
        """
        connected_groups = []
        if not current_node:
            return connected_groups
            
        # 遍历 Output 节点的所有输入插槽
        for socket in current_node.inputs:
            if socket.is_linked:
                # 遍历连线 (通常一个插槽只有一个连线，但数据结构是列表)
                for link in socket.links:
                    source_node = link.from_node
                    connected_groups.append(source_node)
        
        return connected_groups

    @staticmethod
    def get_output_chains(tree):
        """Return Result Output chains in upstream-to-downstream order.

        A Result Output node may feed another Result Output node through its
        output socket.  Every terminal output starts one chain; independent
        output nodes therefore become independent chains.
        """
        output_nodes = [
            node for node in getattr(tree, "nodes", [])
            if getattr(node, "bl_idname", "") == 'SSMTNode_Result_Output'
        ]
        if not output_nodes:
            return []

        downstream = {node: [] for node in output_nodes}
        upstream = {node: [] for node in output_nodes}
        output_socket_name = "输出"
        for node in output_nodes:
            outputs = getattr(node, "outputs", None)
            output_socket = outputs.get(output_socket_name) if hasattr(outputs, "get") else None
            if output_socket is None and outputs:
                output_socket = outputs[0]
            if output_socket is None:
                continue
            for link in output_socket.links:
                target = link.to_node
                if getattr(target, "bl_idname", "") != 'SSMTNode_Result_Output':
                    continue
                downstream[node].append(target)
                upstream[target].append(node)

        if any(len(targets) > 1 for targets in downstream.values()):
            raise ValueError("一个生成 Mod 输出不能同时连接多个输出节点")

        terminals = [node for node in output_nodes if not downstream[node]]
        if not terminals:
            raise ValueError("生成 Mod 输出节点之间存在循环连接")

        chains = []
        visited = set()

        def visit(node, chain, active):
            if node in active:
                raise ValueError("生成 Mod 输出节点之间存在循环连接")
            active = active | {node}
            parents = upstream[node]
            if len(parents) > 1:
                raise ValueError("一个生成 Mod 输出不能接收多个输出节点")
            if parents:
                visit(parents[0], chain, active)
            if node not in visited:
                chain.append(node)
                visited.add(node)

        for terminal in terminals:
            chain = []
            visit(terminal, chain, set())
            if chain:
                chains.append(chain)

        # An output node with an invalid/non-output outgoing link is still a
        # terminal from the INI chain's perspective and is covered above.
        if len(visited) != len(output_nodes):
            missing = [node.name for node in output_nodes if node not in visited]
            raise ValueError("无法解析生成 Mod 输出链: " + ", ".join(missing))
        return chains


    @staticmethod
    def get_current_shapekeyname_mkey_dict(context=None):
        """从「生成形态键」节点读取勾选的形态键列表和按键映射"""
        tree = BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not tree:
            return {}

        output_node = BlueprintExportHelper.runtime_output_node
        if output_node is not None and getattr(output_node, "id_data", None) is not tree:
            output_node = None
        for node in tree.nodes:
            if output_node is None and node.bl_idname == 'SSMTNode_Result_Output':
                output_node = node
                break
        if not output_node or not getattr(output_node, "enable_shapekey", False):
            return {}

        shapekey_name_mkey_dict = {}
        key_index = 0
        for item in output_node.shapekey_items:
            if not item.enabled or not item.shapekey_name.strip():
                continue
            m_key = M_Key()
            m_key.key_name = "$shapekey" + str(key_index)
            m_key.initialize_value = 0
            m_key.initialize_vk_str = item.key.strip()
            shapekey_name_mkey_dict[item.shapekey_name.strip()] = m_key
            key_index += 1

        return shapekey_name_mkey_dict





            
        
