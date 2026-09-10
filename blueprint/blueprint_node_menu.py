
import bpy

from ..common.global_config import GlobalConfig
from ..i18n.i18n import I18nOperator, tr, translatable

from .blueprint_export_helper import BlueprintExportHelper


class SSMT_OT_CreateGroupFromSelection(I18nOperator):
    '''Create nodes from selected objects and group them under a new Group node'''
    bl_idname = "mimi.create_group_from_selection"
    bl_label = "Create Group from Selected Objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'WARNING'}, tr("No objects selected"))
            return {'CANCELLED'}

        # Get the current active blueprint tree
        node_tree = None
        
        # 1. Try to get the blueprint tree from the current context
        space_data = getattr(context, "space_data", None)
        if space_data and space_data.type == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        
        # 2. If not in a node editor, search for an open node editor window
        if not node_tree:
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'NODE_EDITOR':
                        for space in area.spaces:
                            if space.type == 'NODE_EDITOR':
                                tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
                                if tree and tree.bl_idname == 'MIMIBlueprintTreeType':
                                    node_tree = tree
                                    break
                        if node_tree:
                            break
                if node_tree:
                    break
        
        # 3. If still not found, fall back to the default workspace blueprint
        if not node_tree:
            GlobalConfig.read_from_main_json_ssmt4()
            workspace_name = f"{GlobalConfig.get_workspace_name()}" if GlobalConfig.get_workspace_name() else "SSMT_Mod_Logic"
            node_tree = bpy.data.node_groups.get(workspace_name)
        
        if not node_tree or node_tree.bl_idname != 'MIMIBlueprintTreeType':
            self.report({'WARNING'}, tr("No valid blueprint tree found. Please open the blueprint editor first."))
            return {'CANCELLED'}

        # Compute the node position offset to prevent overlap
        base_x = 0
        base_y = 0
        if node_tree.nodes:
             pass

        # Deselect all nodes
        for node in node_tree.nodes:
            node.select = False

        # Create the Group node
        group_node = node_tree.nodes.new(type='MIMINode_Object_Group')
        group_node.location = (base_x + 400, base_y)
        group_node.select = True
        
        # Create Object Info nodes and connect them
        for i, obj in enumerate(selected_objects):
            obj_node = node_tree.nodes.new(type='MIMINode_Object_Info')
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


class SSMT_OT_CreateInternalSwitch(I18nOperator):
    '''Create Object Info nodes from selected objects and connect them to a Switch Key node'''
    bl_idname = "mimi.create_internal_switch"
    bl_label = "Create Internal Switch"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'WARNING'}, tr("No objects selected"))
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
            self.report({'WARNING'}, tr("These objects do not have sequence numbers: {names}").format(names=', '.join([obj.name for obj in objects_without_sequence])))
            return {'CANCELLED'}
        
        if not objects_with_sequence:
            self.report({'WARNING'}, tr("No objects with sequence numbers were found."))
            return {'CANCELLED'}
        
        objects_with_sequence.sort(key=lambda x: x[0])
        
        # Get the current active blueprint tree
        node_tree = None
        
        # 1. Try to get the blueprint tree from the current context
        space_data = getattr(context, "space_data", None)
        if space_data and space_data.type == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        
        # 2. If not in a node editor, search for an open node editor window
        if not node_tree:
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'NODE_EDITOR':
                        for space in area.spaces:
                            if space.type == 'NODE_EDITOR':
                                tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
                                if tree and tree.bl_idname == 'MIMIBlueprintTreeType':
                                    node_tree = tree
                                    break
                        if node_tree:
                            break
                if node_tree:
                    break
        
        # 3. If still not found, fall back to the default workspace blueprint
        if not node_tree:
            GlobalConfig.read_from_main_json_ssmt4()
            workspace_name = f"{GlobalConfig.get_workspace_name()}" if GlobalConfig.get_workspace_name() else "SSMT_Mod_Logic"
            node_tree = bpy.data.node_groups.get(workspace_name)
        
        if not node_tree or node_tree.bl_idname != 'MIMIBlueprintTreeType':
            self.report({'WARNING'}, tr("No valid blueprint tree found. Please open the blueprint editor first."))
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
        
        switch_node = nodes.new(type='MIMINode_SwitchKey')
        switch_node.location = (base_x + 600, base_y)
        
        while len(switch_node.inputs) > 1:
            switch_node.inputs.remove(switch_node.inputs[-1])
        
        while len(switch_node.inputs) < len(objects_with_sequence):
            switch_node.inputs.new('MIMISocketObject', f"Status {len(switch_node.inputs)}")
        
        obj_nodes = []
        for i, (seq_num, obj) in enumerate(objects_with_sequence):
            obj_node = nodes.new(type='MIMINode_Object_Info')
            obj_node.location = (base_x, base_y - i * 15)
            obj_node.object_name = obj.name
            obj_node.select = True
            obj_nodes.append(obj_node)
            
            if i < len(switch_node.inputs):
                links.new(obj_node.outputs[0], switch_node.inputs[i])
        
        switch_node.select = True
        
        self.report({'INFO'}, tr("Created {count} object nodes and connected them to the switch node").format(count=len(obj_nodes)))
        return {'FINISHED'}


class SSMT_OT_RefreshBlueprintSubmeshList(I18nOperator):
    bl_idname = "mimi.refresh_blueprint_submesh_list"
    bl_label = "Refresh Submesh List"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        node_tree = BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not node_tree:
            self.report({'WARNING'}, tr("No valid blueprint tree found. Please open the blueprint editor first."))
            return {'CANCELLED'}

        submesh_names = BlueprintExportHelper.refresh_tree_submesh_list(tree=node_tree)
        self.report({'INFO'}, tr("Refreshed the current blueprint submesh list with {count} entries").format(count=len(submesh_names)))
        return {'FINISHED'}


class SSMT_OT_BatchSetSelectedObjectNodeSubmesh(I18nOperator):
    bl_idname = "mimi.batch_set_selected_object_node_submesh"
    bl_label = "Batch Set Selected Nodes to Submesh"
    bl_options = {'REGISTER', 'UNDO'}

    def _get_node_tree(self, context):
        space_data = getattr(context, "space_data", None)
        if space_data and getattr(space_data, "type", None) == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
            if node_tree and getattr(node_tree, "bl_idname", "") == 'MIMIBlueprintTreeType':
                return node_tree
        return BlueprintExportHelper.get_current_blueprint_tree(context=context)

    def invoke(self, context, event):
        node_tree = self._get_node_tree(context)
        if not node_tree:
            self.report({'WARNING'}, tr("No valid blueprint tree found. Please open the blueprint editor first."))
            return {'CANCELLED'}

        BlueprintExportHelper.set_runtime_blueprint_tree(node_tree)
        submesh_names = BlueprintExportHelper.get_tree_submesh_names(tree=node_tree)
        if not submesh_names:
            self.report({'WARNING'}, tr("No Submesh list is available in the current blueprint. Please refresh the Submesh list first."))
            return {'CANCELLED'}

        def draw_submesh_popup(menu, popup_context):
            layout = menu.layout
            for submesh_name in submesh_names:
                op = layout.operator(
                    "mimi.apply_selected_object_node_submesh",
                    text=submesh_name,
                    icon='OUTLINER_COLLECTION',
                )
                op.target_submesh = submesh_name

        context.window_manager.popup_menu(
            draw_submesh_popup,
            title=tr("Target Submesh"),
            icon='OUTLINER_COLLECTION',
        )
        return {'FINISHED'}

    def execute(self, context):
        return self.invoke(context, None)


class SSMT_OT_ApplySelectedObjectNodeSubmesh(I18nOperator):
    bl_idname = "mimi.apply_selected_object_node_submesh"
    bl_label = "Set to Specified Submesh"
    bl_options = {'REGISTER', 'UNDO'}

    target_submesh: bpy.props.StringProperty(name=tr("Submesh"), default="") # type: ignore

    def _get_node_tree(self, context):
        space_data = getattr(context, "space_data", None)
        if space_data and getattr(space_data, "type", None) == 'NODE_EDITOR':
            node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
            if node_tree and getattr(node_tree, "bl_idname", "") == 'MIMIBlueprintTreeType':
                return node_tree
        return BlueprintExportHelper.get_current_blueprint_tree(context=context)

    def execute(self, context):
        node_tree = self._get_node_tree(context)
        if not node_tree:
            self.report({'WARNING'}, tr("No valid blueprint tree found. Please open the blueprint editor first."))
            return {'CANCELLED'}

        target_submesh = str(self.target_submesh or "").strip()

        if not target_submesh:
            self.report({'WARNING'}, tr("Please select a valid Submesh."))
            return {'CANCELLED'}

        updated_count = 0
        for node in node_tree.nodes:
            if not node.select or getattr(node, "bl_idname", "") != 'MIMINode_Object_Info':
                continue
            node.submesh_name = target_submesh
            updated_count += 1

        if updated_count == 0:
            self.report({'WARNING'}, tr("No object info nodes are currently selected"))
            return {'CANCELLED'}

        self.report({'INFO'}, tr("Set {count} object info nodes to submesh: {submesh}").format(count=updated_count, submesh=target_submesh))
        return {'FINISHED'}


def draw_objects_context_menu_add(self, context):
    layout = self.layout
    layout.separator()
    layout.menu("MIMIMT_ObjectContextMenuSub", text=tr("SSMT Blueprint Graph"), icon='NODETREE')

@translatable
class MIMIMT_ObjectContextMenuSub(bpy.types.Menu):
    bl_label = "SSMT Blueprint Graph"
    
    def draw(self, context):
        layout = self.layout
        layout.operator("mimi.create_group_from_selection", text=tr("Create Group from Selected Objects"), icon='GROUP')
        layout.operator("mimi.create_internal_switch", text=tr("Create Internal Switch"), icon='ARROW_LEFTRIGHT')


class SSMT_OT_AlignNodes(I18nOperator):
    '''Align the selected nodes in a grid layout'''
    bl_idname = "mimi.align_nodes"
    bl_label = "Align Nodes in Grid"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Get the current node tree
        space_data = getattr(context, "space_data", None)
        if not space_data or space_data.type != 'NODE_EDITOR':
            self.report({'ERROR'}, tr("Please use this feature in the node editor"))
            return {'CANCELLED'}

        node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        if not node_tree:
            self.report({'ERROR'}, tr("Node tree not found"))
            return {'CANCELLED'}

        # Get the selected nodes
        selected_nodes = [node for node in node_tree.nodes if node.select]
        if len(selected_nodes) < 2:
            self.report({'WARNING'}, tr("Please select at least 2 nodes"))
            return {'CANCELLED'}

        # Step 1: group the nodes into columns (based on X coordinate)
        columns = self.group_nodes_by_columns(selected_nodes)
        
        # Step 2: vertically align the nodes within each column
        for column in columns:
            self.align_column_vertically(column)
        
        # Step 3: horizontally align the columns
        self.align_columns_horizontally(columns)
        
        # Step 4: reorder the nodes to match their connections
        self.adjust_node_order_by_connections(selected_nodes, node_tree)

        self.report({'INFO'}, tr("Aligned {node_count} nodes into a structured layout with {column_count} columns").format(node_count=len(selected_nodes), column_count=len(columns)))
        return {'FINISHED'}
    
    def group_nodes_by_columns(self, nodes):
        """Group the nodes into columns by X coordinate"""
        if not nodes:
            return []
        
        # Compute the average node width as the column spacing threshold
        avg_width = sum(node.width for node in nodes) / len(nodes)
        column_threshold = avg_width * 1.1  # detection range is 1.1x the node size
        
        # Sort the nodes by X coordinate
        sorted_nodes = sorted(nodes, key=lambda n: n.location.x)
        
        columns = []
        current_column = [sorted_nodes[0]]
        current_x = sorted_nodes[0].location.x
        
        for node in sorted_nodes[1:]:
            # Start a new column when X differs from the current column by more than the threshold
            if abs(node.location.x - current_x) > column_threshold:
                columns.append(current_column)
                current_column = [node]
                current_x = node.location.x
            else:
                current_column.append(node)
        
        # Append the last column
        if current_column:
            columns.append(current_column)
        
        return columns
    
    def align_column_vertically(self, column):
        """Vertically align the nodes within a single column"""
        if len(column) <= 1:
            return
        
        # Sort by Y coordinate from top to bottom
        column.sort(key=lambda n: -n.location.y)
        
        # Compute the start position (use the topmost node)
        start_x = column[0].location.x
        start_y = column[0].location.y
        
        # Fixed vertical spacing
        vertical_spacing = 80.0
        
        # Align the nodes
        current_y = start_y
        for node in column:
            # Ensure node positions do not overlap
            node.location = (start_x, current_y)
            # Use the fixed vertical spacing
            current_y -= (node.height + vertical_spacing)
    
    def align_columns_horizontally(self, columns):
        """Align the columns horizontally"""
        if len(columns) <= 1:
            return
        
        # Average width of all nodes determines the column spacing
        all_nodes = [node for column in columns for node in column]
        avg_width = sum(node.width for node in all_nodes) / len(all_nodes)
        # Keep column spacing at 0.3x the average width, the spacing the user wanted
        column_spacing = avg_width * 0.3
        
        # Compute the bounds of each column
        column_bounds = []
        for i, column in enumerate(columns):
            if not column:
                continue
            
            # Compute the column bounds from the actual node positions
            x_min = min(node.location.x for node in column)
            x_max = max(node.location.x + node.width for node in column)
            
            # Compute the center X of the column
            center_x = (x_min + x_max) / 2
            
            # Compute the width of the column (including margin)
            width = x_max - x_min + 10  # add a 10 pixel margin
            
            column_bounds.append({
                'index': i,
                'column': column,
                'center_x': center_x,
                'width': width,
                'x_min': x_min,
                'x_max': x_max
            })
        
        # Sort the columns by center X
        column_bounds.sort(key=lambda b: b['center_x'])
        
        # Align the columns while keeping the existing column spacing
        current_x = column_bounds[0]['x_min']
        for bound in column_bounds:
            # Move the column to the current X position
            offset_x = current_x - bound['x_min']
            for node in bound['column']:
                node.location.x += offset_x
            
            # Advance the current X, reserving space for the next column
            # Use spacing based on node size, ensuring it exceeds the detection range (avg_width * 1.1)
            current_x += bound['width'] + column_spacing
    
    def adjust_node_order_by_connections(self, nodes, node_tree):
        """Reorder nodes by their connections to avoid crossed wires"""
        if len(nodes) < 2:
            return
        
        # Build the node connection graph
        connection_graph = {}
        for node in nodes:
            connection_graph[node] = {'inputs': [], 'outputs': []}
        
        # Iterate over all links
        for link in node_tree.links:
            from_node = link.from_node
            to_node = link.to_node
            
            if from_node in connection_graph and to_node in connection_graph:
                connection_graph[from_node]['outputs'].append(to_node)
                connection_graph[to_node]['inputs'].append(from_node)
        
        # Sort the nodes in each column
        for column in self.group_nodes_by_columns(nodes):
            if len(column) <= 1:
                continue
            
            # Sort the nodes by their connections
            # Put nodes without inputs first (source nodes)
            column.sort(key=lambda n: (
                len(connection_graph[n]['inputs']),  # fewer inputs first
                -n.location.y  # keep the existing vertical order
            ))


class SSMT_OT_BatchConnectNodes(I18nOperator):
    '''Batch connect the selected nodes: supports one-to-one or many-to-one connections'''
    bl_idname = "mimi.batch_connect_nodes"
    bl_label = "Batch Connect Nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Get the current node tree
        space_data = getattr(context, "space_data", None)
        if not space_data or space_data.type != 'NODE_EDITOR':
            self.report({'ERROR'}, tr("Please use this feature in the node editor"))
            return {'CANCELLED'}

        node_tree = getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)
        if not node_tree:
            self.report({'ERROR'}, tr("Node tree not found"))
            return {'CANCELLED'}

        # Get the selected nodes
        selected_nodes = [node for node in node_tree.nodes if node.select]
        if len(selected_nodes) < 2:
            self.report({'WARNING'}, tr("Please select at least 2 nodes"))
            return {'CANCELLED'}

        # Count the node type distribution
        type_count_dict = {}
        for node in selected_nodes:
            node_type = node.bl_idname
            type_count_dict[node_type] = type_count_dict.get(node_type, 0) + 1

        # Check the number of node types
        if len(type_count_dict) > 2:
            self.report({'ERROR'}, tr("Too many selected node types ({count}). Please select 1 or 2 types of nodes.").format(count=len(type_count_dict)))
            return {'CANCELLED'}

        # Determine the connection mode
        if len(type_count_dict) == 1:
            # Only one type: cannot connect
            self.report({'ERROR'}, tr("Selected nodes are all the same type and cannot be connected"))
            return {'CANCELLED'}
        else:
            # Two types: determine whether this is one-to-one or many-to-one
            type_items = list(type_count_dict.items())
            type_items.sort(key=lambda x: x[1], reverse=True)  # sort by count in descending order
            
            majority_type, majority_count = type_items[0]
            minority_type, minority_count = type_items[1]

            if majority_count == minority_count:
                # Equal counts: one-to-one connection
                return self.connect_one_to_one(selected_nodes, type_count_dict, node_tree)
            else:
                # Unequal counts: many-to-one connection
                return self.connect_many_to_one(selected_nodes, type_count_dict, node_tree)

    def connect_one_to_one(self, selected_nodes, type_count_dict, node_tree):
        """One-to-one connection mode"""
        # Get the two types
        type_items = list(type_count_dict.items())
        type_a, count_a = type_items[0]
        type_b, count_b = type_items[1]

        # Group by type
        nodes_a = [node for node in selected_nodes if node.bl_idname == type_a]
        nodes_b = [node for node in selected_nodes if node.bl_idname == type_b]

        # Determine which group is the source (has outputs) and which is the target (has inputs)
        # Prefer socket characteristics: outputs-only acts as source, inputs as target
        a_has_output = len(nodes_a[0].outputs) > 0
        a_has_input = len(nodes_a[0].inputs) > 0
        b_has_output = len(nodes_b[0].outputs) > 0
        b_has_input = len(nodes_b[0].inputs) > 0

        if a_has_output and not a_has_input and b_has_input:
            # A has only outputs, B has inputs: A -> B
            source_nodes, target_nodes = nodes_a, nodes_b
        elif b_has_output and not b_has_input and a_has_input:
            # B has only outputs, A has inputs: B -> A
            source_nodes, target_nodes = nodes_b, nodes_a
        elif a_has_output and a_has_input and b_has_output and b_has_input:
            # Both have inputs and outputs: decide by position (left connects to right)
            avg_x_a = sum(node.location.x for node in nodes_a) / len(nodes_a)
            avg_x_b = sum(node.location.x for node in nodes_b) / len(nodes_b)
            if avg_x_a < avg_x_b:
                # A is on the left: A -> B
                source_nodes, target_nodes = nodes_a, nodes_b
            else:
                # B is on the left: B -> A
                source_nodes, target_nodes = nodes_b, nodes_a
        elif a_has_output and not a_has_input and not b_has_output:
            # A has only outputs, B has none: A -> B
            source_nodes, target_nodes = nodes_a, nodes_b
        elif b_has_output and not b_has_input and not a_has_output:
            # B has only outputs, A has none: B -> A
            source_nodes, target_nodes = nodes_b, nodes_a
        elif a_has_output and not b_has_input:
            # A has outputs, B has no inputs: A -> B
            source_nodes, target_nodes = nodes_a, nodes_b
        elif b_has_output and not a_has_input:
            # B has outputs, A has no inputs: B -> A
            source_nodes, target_nodes = nodes_b, nodes_a
        else:
            self.report({'ERROR'}, tr("Cannot determine connection direction. Please check the node socket configuration."))
            return {'CANCELLED'}

        # Check that the target nodes have input sockets
        for node in target_nodes:
            if len(node.inputs) == 0:
                self.report({'ERROR'}, tr("Node '{node_name}' has no input socket").format(node_name=node.name))
                return {'CANCELLED'}

        # Clear existing links
        for source_node in source_nodes:
            for output in source_node.outputs:
                for link in output.links:
                    if link.to_node in target_nodes:
                        node_tree.links.remove(link)

        # Sort by position (left to right, top to bottom)
        source_nodes.sort(key=lambda n: (n.location.x, -n.location.y))
        target_nodes.sort(key=lambda n: (n.location.x, -n.location.y))

        # One-to-one connection
        connection_info = []
        for i in range(min(len(source_nodes), len(target_nodes))):
            source_node = source_nodes[i]
            target_node = target_nodes[i]

            # Find an available input socket
            available_input = None
            for input_socket in target_node.inputs:
                if not input_socket.is_linked:
                    available_input = input_socket
                    break

            # No free input socket: try creating a new one
            if not available_input:
                try:
                    if hasattr(target_node, 'update'):
                        target_node.inputs.new('MIMISocketObject', "Input {count}".format(count=len(target_node.inputs) + 1))
                        available_input = target_node.inputs[-1]
                except Exception:
                    self.report({'WARNING'}, tr("Node '{node_name}' has no available input socket").format(node_name=target_node.name))
                    continue

            # Create the link
            if available_input and len(source_node.outputs) > 0:
                node_tree.links.new(source_node.outputs[0], available_input)
                connection_info.append(f"{source_node.name} -> {target_node.name}")

        # Trigger node updates
        for node in target_nodes:
            if hasattr(node, 'update'):
                node.update()

        # Report the result
        total_connections = len(connection_info)
        self.report({'INFO'}, tr("One-to-one connection: successfully connected {count} node pairs").format(count=total_connections))
        print(f"One-to-one connection complete: created {total_connections} connections:")
        for info in connection_info:
            print(f"  {info}")

        return {'FINISHED'}

    def connect_many_to_one(self, selected_nodes, type_count_dict, node_tree):
        """Many-to-one connection mode"""
        # Identify the majority and minority nodes
        type_items = list(type_count_dict.items())
        type_items.sort(key=lambda x: x[1], reverse=True)
        
        majority_type, majority_count = type_items[0]
        minority_type, minority_count = type_items[1]

        # Group the nodes by type
        majority_nodes = [node for node in selected_nodes if node.bl_idname == majority_type]
        minority_nodes = [node for node in selected_nodes if node.bl_idname == minority_type]

        # Check that the nodes have suitable input/output sockets
        for node in majority_nodes:
            if len(node.outputs) == 0:
                self.report({'ERROR'}, tr("Majority node '{node_name}' has no output socket").format(node_name=node.name))
                return {'CANCELLED'}

        for node in minority_nodes:
            if len(node.inputs) == 0:
                self.report({'ERROR'}, tr("Minority node '{node_name}' has no input socket").format(node_name=node.name))
                return {'CANCELLED'}

        # Clear existing links (only those between the selected nodes)
        for node in majority_nodes:
            for output in node.outputs:
                for link in output.links:
                    if link.to_node in minority_nodes:
                        node_tree.links.remove(link)

        # Sort the nodes top to bottom (descending Y)
        majority_nodes.sort(key=lambda n: -n.location.y)
        minority_nodes.sort(key=lambda n: -n.location.y)

        # Distribute the majority nodes evenly across the minority nodes
        nodes_per_target = majority_count // minority_count
        remainder = majority_count % minority_count

        connection_info = []
        majority_index = 0

        for minority_index, minority_node in enumerate(minority_nodes):
            # Number of majority nodes the current minority node should connect
            current_batch_size = nodes_per_target + (1 if minority_index < remainder else 0)

            for i in range(current_batch_size):
                if majority_index >= len(majority_nodes):
                    break

                majority_node = majority_nodes[majority_index]

                # Find an available input socket
                available_input = None
                for input_socket in minority_node.inputs:
                    if not input_socket.is_linked:
                        available_input = input_socket
                        break

                # No free input socket: try creating a new one (for nodes with dynamic sockets)
                if not available_input:
                    try:
                        # Some nodes (such as Group, Output) support dynamically added sockets
                        if hasattr(minority_node, 'update'):
                            minority_node.inputs.new('MIMISocketObject', "Input {count}".format(count=len(minority_node.inputs) + 1))
                            available_input = minority_node.inputs[-1]
                    except Exception:
                        self.report({'WARNING'}, tr("Node '{node_name}' has no available input socket").format(node_name=minority_node.name))
                        majority_index += 1
                        continue

                # Create the link
                if available_input and len(majority_node.outputs) > 0:
                    node_tree.links.new(majority_node.outputs[0], available_input)
                    connection_info.append(f"{majority_node.name} -> {minority_node.name}")

                majority_index += 1

        # Trigger node updates
        for node in minority_nodes:
            if hasattr(node, 'update'):
                node.update()

        # Report success
        total_connections = len(connection_info)
        self.report({'INFO'}, tr("Many-to-one connection: successfully connected {count} node pairs").format(count=total_connections))
        print(f"Many-to-one connection complete: created {total_connections} connections:")
        for info in connection_info:
            print(f"  {info}")

        return {'FINISHED'}
def draw_node_add_menu(self, context):
    if not isinstance(context.space_data, bpy.types.SpaceNodeEditor):
        return
    if context.space_data.tree_type != 'MIMIBlueprintTreeType':
        return
    
    layout = self.layout
    layout.operator("node.add_node", text=tr("Object Info"), icon='OBJECT_DATAMODE').type = "MIMINode_Object_Info"
    layout.operator("node.add_node", text=tr("Group"), icon='GROUP').type = "MIMINode_Object_Group"
    layout.operator("node.add_node", text=tr("Generate Mod"), icon='EXPORT').type = "MIMINode_Result_Output"
    layout.operator("node.add_node", text=tr("Export Face Mod"), icon='MOD_MASK').type = "MIMINode_Face_Mod_Export"
    layout.operator("node.add_node", text=tr("Switch Key"), icon='GROUP').type = "MIMINode_SwitchKey"
    layout.separator()

    # The Frame node has no functionality of its own; it is a built-in Blender helper
    # for organizing and grouping nodes in the node editor. Just treat it as a section divider.
    layout.operator("node.add_node", text=tr("Frame"), icon='FILE_PARENT').type = "NodeFrame"
    layout.separator()



def draw_node_context_menu(self, context):
    """Add batch connection options to the node editor context menu"""
    if not isinstance(context.space_data, bpy.types.SpaceNodeEditor):
        return
    if context.space_data.tree_type != 'MIMIBlueprintTreeType':
        return
    
    layout = self.layout
    layout.separator()
    layout.operator("mimi.make_group", text=tr("Make Group"), icon='NODETREE')
    layout.operator("mimi.align_nodes", text=tr("Align Nodes in Grid"), icon='GRID')
    layout.operator("mimi.batch_connect_nodes", text=tr("Batch Connect Nodes"), icon='LINKED')
    layout.operator("mimi.refresh_blueprint_submesh_list", text=tr("Refresh Submesh List"), icon='FILE_REFRESH')
    layout.operator("mimi.batch_set_selected_object_node_submesh", text=tr("Batch Set Selected Nodes to Submesh"), icon='OUTLINER_COLLECTION')
    layout.separator()
    layout.operator("mimi.refresh_node_object_ids", text=tr("Refresh Object Node Info"), icon='FILE_REFRESH')


def register():
    bpy.utils.register_class(SSMT_OT_CreateGroupFromSelection)
    bpy.utils.register_class(SSMT_OT_CreateInternalSwitch)
    bpy.utils.register_class(SSMT_OT_RefreshBlueprintSubmeshList)
    bpy.utils.register_class(SSMT_OT_BatchSetSelectedObjectNodeSubmesh)
    bpy.utils.register_class(SSMT_OT_ApplySelectedObjectNodeSubmesh)
    bpy.utils.register_class(SSMT_OT_AlignNodes)
    bpy.utils.register_class(SSMT_OT_BatchConnectNodes)
    bpy.utils.register_class(MIMIMT_ObjectContextMenuSub)
    bpy.types.NODE_MT_add.prepend(draw_node_add_menu)
    # Add to the 3D viewport object context menu
    bpy.types.VIEW3D_MT_object_context_menu.append(draw_objects_context_menu_add)
    # Add to the node editor context menu
    bpy.types.NODE_MT_context_menu.append(draw_node_context_menu)
    wm = bpy.context.window_manager
    keyconfig = wm.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')
        if not any(
            item.idname == 'mimi.make_group' and item.type == 'G' and item.ctrl
            for item in keymap.keymap_items
        ):
            keymap.keymap_items.new('mimi.make_group', 'G', 'PRESS', ctrl=True)
        if not any(item.idname == 'mimi.group_tab' and item.type == 'TAB' for item in keymap.keymap_items):
            keymap.keymap_items.new('mimi.group_tab', 'TAB', 'PRESS')

def unregister():
    wm = bpy.context.window_manager
    keyconfig = wm.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.get('Node Editor')
        if keymap:
            for item in list(keymap.keymap_items):
                if (
                    (item.idname == 'mimi.make_group' and item.type == 'G' and item.ctrl)
                    or (item.idname == 'mimi.group_tab' and item.type == 'TAB')
                ):
                    keymap.keymap_items.remove(item)
    bpy.types.NODE_MT_context_menu.remove(draw_node_context_menu)
    bpy.types.NODE_MT_add.remove(draw_node_add_menu)
    bpy.types.VIEW3D_MT_object_context_menu.remove(draw_objects_context_menu_add)

    bpy.utils.unregister_class(MIMIMT_ObjectContextMenuSub)
    bpy.utils.unregister_class(SSMT_OT_BatchConnectNodes)
    bpy.utils.unregister_class(SSMT_OT_AlignNodes)
    bpy.utils.unregister_class(SSMT_OT_ApplySelectedObjectNodeSubmesh)
    bpy.utils.unregister_class(SSMT_OT_BatchSetSelectedObjectNodeSubmesh)
    bpy.utils.unregister_class(SSMT_OT_RefreshBlueprintSubmeshList)
    bpy.utils.unregister_class(SSMT_OT_CreateInternalSwitch)
    bpy.utils.unregister_class(SSMT_OT_CreateGroupFromSelection)
