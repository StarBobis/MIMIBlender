import os

import bpy
from ..common.global_config import GlobalConfig
from ..common.m_key import M_Key
from ..workspace.ssmt_workspace import SSMTWorkSpace

class BlueprintExportHelper:

    # Record the blueprint tree of the current operation at runtime, so the context is not lost after a button press
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
            description = "Current Default Blueprint" if tree.name == preferred_name else "Choose this blueprint to open or generate a Mod"
            items.append((tree.name, tree.name, description))

        if not items:
            items.append(("__NONE__", "No Blueprint Available", "No blueprint available. Please open the blueprint editor or run one-click import first."))

        return items

    @staticmethod
    def set_runtime_blueprint_tree(tree):
        if BlueprintExportHelper._is_valid_blueprint_tree(tree):
            BlueprintExportHelper.runtime_blueprint_tree_name = tree.name

    @staticmethod
    def reveal_tree_in_node_editors(context, tree):
        '''Switch every open SSMT Blueprint node editor to the specified blueprint tree.'''
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
        """Bind the workspace blueprint of the same name when an area has just switched to the SSMT tree type."""
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
        """Bind the workspace blueprint only once, when an area switches to the SSMT Blueprint type."""
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
        """Get the blueprint tree that matches the current workspace"""
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
        """Find the node with the given name in all blueprints"""
        for node_group in bpy.data.node_groups:
            if node_group.bl_idname == 'SSMTBlueprintTreeType':
                node = node_group.nodes.get(node_name)
                if node:
                    return node
        return None

    @staticmethod
    @staticmethod
    def get_node_from_bl_idname(tree, node_type:str):
        """Find the output node in the tree (assumes there is only one)"""
        if not tree:
            return None
        for node in tree.nodes:
            if node.bl_idname == node_type:
                return node
        return None

    @staticmethod
    def get_connected_nodes(current_node):
        """
        Return all connected nodes in socket order
        """
        connected_groups = []
        if not current_node:
            return connected_groups
            
        # Iterate over all input sockets of the Output node
        for socket in current_node.inputs:
            if socket.is_linked:
                # Iterate over the links (a socket usually has one link, but the data structure is a list)
                for link in socket.links:
                    source_node = link.from_node
                    connected_groups.append(source_node)
        
        return connected_groups

    @staticmethod
    def get_current_shapekeyname_mkey_dict(context=None):
        """Read the checked shapekey list and key mapping from the shapekey-generation node"""
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





            
        
