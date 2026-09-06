
import bpy
import copy
import math
import re

from ..utils.log_utils import LOG
from ..utils.vertexgroup_utils import VertexGroupUtils

from ..common.m_key import M_Key
from ..common.global_properties import GlobalProperties
from .draw_call_model import DrawCallModel
from .submesh_model import SubMeshModel
from .drawib_model import DrawIBModel
from ..common.global_config import GlobalConfig
from ..blueprint.blueprint_export_helper import BlueprintExportHelper

from ..blueprint.blueprint_node_obj import SSMTNode_Object_Group, SSMTNode_SwitchKey, SSMTNode_Object_Info, SSMTNode_Result_Output

from ..blueprint.blueprint_node_custom_shader import SSMTNode_CustomShader
from ..blueprint.blueprint_node_group import (
    GROUP_INPUT_IDNAME,
    GROUP_NODE_IDNAME,
    GROUP_OUTPUT_IDNAME,
    _group_socket_for_interface,
)
from ..common.m_custom_shader_helper import M_CustomShaderHelper


class BluePrintModel:

    _KEY_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
    
    def __init__(self, tree=None, context=None, output_node=None):
        M_CustomShaderHelper.begin_export()
        # Global key name and key attribute dict
        self.keyname_mkey_dict:dict[str,M_Key] = {} 

        # Global obj_model list; each obj_model stores the active condition of its obj.
        self.ordered_draw_obj_data_model_list:list[DrawCallModel] = [] 

        # Temporary objects created by UniComponent splitting; must be cleaned up after export
        self._unico_temp_objects: list[bpy.types.Object] = []
        self._group_instance_stack: list[bpy.types.Node] = []

        # Recursively parse all nodes starting from the output node
        tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not tree:
            raise ValueError("No blueprint tree found; please open the correct blueprint editor")

        # Nodes sharing an explicit alias share one INI variable.  Its period
        # is the LCM of the participating nodes' branch counts.
        self._switch_alias_state_counts = self._collect_switch_alias_state_counts(tree)

        print(tree)
        output_node = output_node or BlueprintExportHelper.get_node_from_bl_idname(
            tree, SSMTNode_Result_Output.bl_idname
        )
        if not output_node:
            raise ValueError("The current blueprint is missing the Generate Mod output node")

        print("BluePrintModel: number of nodes connected to the output node: " + str(len(BlueprintExportHelper.get_connected_nodes(output_node))))
        self.parse_current_node(output_node, [])

    @classmethod
    def _normalize_switch_key_alias(cls, switch_node: bpy.types.Node) -> str:
        alias = str(getattr(switch_node, "key_alias", "") or "").strip()
        if alias == "":
            return ""
        if cls._KEY_ALIAS_PATTERN.fullmatch(alias) is None:
            raise ValueError("The variable alias of a key switch node may only contain English letters and digits: " + alias)
        return "$" + alias

    def _allocate_switch_key_name(self, switch_node: bpy.types.Node) -> tuple[str, bool]:
        key_alias = self._normalize_switch_key_alias(switch_node)
        if key_alias:
            return key_alias, False

        key_name = "$swapkey" + str(GlobalConfig.global_key_index)
        while (
            key_name in self.keyname_mkey_dict
            or key_name in self._switch_alias_state_counts
        ):
            GlobalConfig.global_key_index = GlobalConfig.global_key_index + 1
            key_name = "$swapkey" + str(GlobalConfig.global_key_index)

        if key_name in self.keyname_mkey_dict:
            raise ValueError("Duplicate variable name of a key switch node: " + key_name)
        return key_name, True

    @classmethod
    def _collect_switch_alias_state_counts(cls, root_tree) -> dict[str, int]:
        counts: dict[str, list[int]] = {}
        visited_trees = set()

        def visit(tree):
            if tree is None or id(tree) in visited_trees:
                return
            visited_trees.add(id(tree))
            for node in getattr(tree, "nodes", []):
                if getattr(node, "bl_idname", "") == SSMTNode_SwitchKey.bl_idname:
                    alias = cls._normalize_switch_key_alias(node)
                    branch_count = len(getattr(node, "inputs", []))
                    if alias and branch_count > 1:
                        counts.setdefault(alias, []).append(branch_count)
                if getattr(node, "bl_idname", "") == GROUP_NODE_IDNAME:
                    visit(getattr(node, "node_tree", None))

        visit(root_tree)
        return {
            alias: math.lcm(*branch_counts)
            for alias, branch_counts in counts.items()
        }

    def parse_current_node(self, current_node:bpy.types.Node, chain_key_list:list[M_Key]):
        for input_socket in current_node.inputs:
            for link in input_socket.links:
                if link.from_node.bl_idname == GROUP_INPUT_IDNAME:
                    self._parse_group_input(link.from_node, link.from_socket, chain_key_list)
                else:
                    self.parse_single_node(link.from_node, chain_key_list)

    def parse_single_node(self, unknown_node:bpy.types.Node, chain_key_list:list[M_Key]):
        '''
        Recursive method.
        Parse the current node, gathering info about all nodes connected to it and parsing them by type.
        '''
        
        if unknown_node.mute:
            return

        if unknown_node.bl_idname == GROUP_NODE_IDNAME:
            self._parse_custom_group(unknown_node, chain_key_list)

        elif unknown_node.bl_idname == SSMTNode_Object_Group.bl_idname:
            # If it is a plain group node, pass through without further processing
            self.parse_current_node(unknown_node, chain_key_list)

        elif unknown_node.bl_idname == SSMTNode_SwitchKey.bl_idname:
            # If it is a key switch node, take all of its branch nodes and process them one by one.
            # Here we iterate over all inputs directly instead of using get_connected_nodes,
            # because get_connected_nodes ignores unconnected (empty) sockets and would compute a wrong branch count.
            
            # Get the effective branches (excluding the trailing empty socket kept for easier editing).
            # The last socket counts only when it is truly unconnected; the Node definition says so, but check the links anyway.
            # valid_input_sockets = unknown_node.inputs[:-1] if (len(unknown_node.inputs) > 1 and not unknown_node.inputs[-1].is_linked) else unknown_node.inputs[:]
            
            # Correction: every Input of a SwitchKey node is an effective branch, since sockets can be added/removed manually and an empty socket means an empty state (nothing is shown)
            valid_input_sockets = unknown_node.inputs[:]
            
            # If no sockets are connected at all, skip this node entirely
            is_all_socket_linked = False
            for sock in valid_input_sockets:
                if sock.is_linked:
                    is_all_socket_linked = True
                    break
            
            if not is_all_socket_linked:
                # If nothing is connected, do nothing
                return

            if len(valid_input_sockets) == 1:
                # If there is only 1 effective branch socket:
                # 1. If it is connected -> treat it as a Group node pass-through
                # 2. If it is disconnected -> ignore it (already filtered by all_socket_linked above)
                if valid_input_sockets[0].is_linked:
                        for link in valid_input_sockets[0].links:
                            self.parse_single_node(link.from_node, chain_key_list)
            else:
                # With more than 1 effective branch socket, a Key must be created even when some sockets are empty (they stand for empty branches)
                m_key = M_Key()
                current_add_key_index = len(self.keyname_mkey_dict.keys())
                m_key.key_name, uses_auto_key_name = self._allocate_switch_key_name(unknown_node)

                state_count = self._switch_alias_state_counts.get(
                    m_key.key_name, len(valid_input_sockets)
                )
                m_key.value_list = list(range(state_count))

                m_key.initialize_vk_str = unknown_node.key_name
                m_key.initialize_value = 0  # Select the first branch by default

                # Set the comment field
                m_key.comment = getattr(unknown_node, 'comment', '')

                # Nodes sharing an explicit alias create one global Key; the LCM state count was already determined in the pre-scan.
                existing_key = self.keyname_mkey_dict.get(m_key.key_name)
                if existing_key is None:
                    self.keyname_mkey_dict[m_key.key_name] = m_key
                else:
                    m_key = existing_key

                # Update the global key index
                if uses_auto_key_name and len(self.keyname_mkey_dict.keys()) > current_add_key_index:
                    GlobalConfig.global_key_index = GlobalConfig.global_key_index + 1

                # Process each branch socket in turn (including empty branches)
                for branch_index, socket in enumerate(valid_input_sockets):
                    # Whether a socket is connected to a node or left empty, it always maps to one key value
                    
                    if socket.is_linked:
                        # If a socket is connected to a node, propagate the key for this value downstream for parsing
                        matching_states = range(branch_index, state_count, len(valid_input_sockets))
                        for state in matching_states:
                            # Nested nodes with the same alias intersect the
                            # existing state instead of emitting contradictions.
                            existing_state = next(
                                (key.tmp_value for key in chain_key_list if key.key_name == m_key.key_name),
                                None,
                            )
                            if existing_state is not None and existing_state != state:
                                continue
                            for link in socket.links:
                                tmp_chain_key_list = copy.deepcopy(chain_key_list)
                                if existing_state is None:
                                    chain_tmp_key = copy.deepcopy(m_key)
                                    chain_tmp_key.tmp_value = state
                                    tmp_chain_key_list.append(chain_tmp_key)
                                self.parse_single_node(link.from_node, tmp_chain_key_list)
                    else:
                        # An empty (unconnected) socket means this value maps to an empty object
                        # No parsing is needed here because no obj has to be generated under this condition
                        # The key value stays in key.value_list, yet no obj condition will ever match it
                        # This achieves the effect of "switching to this branch displays nothing"
                        pass

        elif unknown_node.bl_idname == SSMTNode_Object_Info.bl_idname:
            obj = bpy.data.objects.get(unknown_node.object_name)
            custom_shader_nodes = self._get_custom_shader_nodes(unknown_node)

            # Filter empty meshes early while parsing the blueprint, so the later export step never hits the "all vertex groups locked" error.
            if obj is None or obj.type != 'MESH' or obj.data is None or len(obj.data.vertices) == 0:
                LOG.info("BluePrintModel: skipping empty mesh or invalid object: " + str(unknown_node.object_name))
                return

            # UniComponent mode: automatically detect and split the object
            if GlobalProperties.is_unico_component():
                split_results = self._unico_split_object(
                    obj=obj,
                    node_submesh_name=getattr(unknown_node, 'submesh_name', ''),
                )
                for submesh_name, temp_obj in split_results:
                    obj_model = DrawCallModel(
                        obj_name=temp_obj.name,
                        submesh_name=submesh_name,
                    )
                    obj_model.work_key_list = copy.deepcopy(chain_key_list)
                    obj_model.custom_shader_node_list.extend(custom_shader_nodes)
                    self.ordered_draw_obj_data_model_list.append(obj_model)
                    self._unico_temp_objects.append(temp_obj)
                    LOG.info(f"BluePrintModel: UniComponent split '{unknown_node.object_name}' -> "
                             f"submesh='{submesh_name}' parsed='{obj_model.match_submesh_name}' "
                             f"draw_ib='{obj_model.match_draw_ib}' (temporary object: '{temp_obj.name}')")
            else:
                # Legacy mode: use the original object directly
                obj_model = DrawCallModel(
                    obj_name=unknown_node.object_name,
                    submesh_name=getattr(unknown_node, 'submesh_name', ''),
                )
                
                if hasattr(unknown_node, 'original_object_name') and unknown_node.original_object_name:
                    obj_model.display_name = unknown_node.original_object_name

                obj_model.work_key_list = copy.deepcopy(chain_key_list)

                obj_model.custom_shader_node_list.extend(custom_shader_nodes)
                
                self.ordered_draw_obj_data_model_list.append(obj_model)

        elif unknown_node.bl_idname == SSMTNode_Result_Output.bl_idname:
            # Result Output nodes are pass-through nodes when chained.  The
            # selected output is handled as the root by __init__; upstream
            # output nodes are intentionally boundaries for that INI layer.
            return

        elif unknown_node.bl_idname == "SSMTNode_Face_Mod_Export":
            # Face Output is an INI composition boundary, just like the
            # regular Result Output.  Its generated Face.ini is linked through
            # [Include]; parsing its mesh inputs here would duplicate them in
            # the regular output layer.
            return

    def _parse_custom_group(self, group_node: bpy.types.Node, chain_key_list: list[M_Key]):
        """Expand an SSMT group through its Group Output nodes."""
        group_tree = getattr(group_node, "node_tree", None)
        if group_tree is None:
            return
        self._group_instance_stack.append(group_node)
        try:
            for output_node in group_tree.nodes:
                if getattr(output_node, "bl_idname", "") == GROUP_OUTPUT_IDNAME:
                    self.parse_current_node(output_node, chain_key_list)
        finally:
            self._group_instance_stack.pop()

    def _parse_group_input(
        self,
        group_input: bpy.types.Node,
        output_socket: bpy.types.NodeSocket,
        chain_key_list: list[M_Key],
    ):
        """Resolve an inner Group Input socket to its caller's linked input."""
        if not self._group_instance_stack:
            return
        group_node = self._group_instance_stack[-1]
        interface_items = [
            item for item in group_node.node_tree.interface.items_tree
            if getattr(item, "item_type", "") == "SOCKET" and item.in_out == "INPUT"
        ]
        try:
            index = list(group_input.outputs).index(output_socket)
        except ValueError:
            return
        parent_socket = (
            _group_socket_for_interface(group_node, group_node.node_tree, interface_items[index], "INPUT")
            if index < len(interface_items) else None
        )
        if parent_socket is None:
            return
        for link in parent_socket.links:
            self.parse_single_node(link.from_node, chain_key_list)

    @staticmethod
    def _get_custom_shader_nodes(object_node):
        result = []
        for socket in getattr(object_node, 'inputs', []):
            if getattr(socket, 'bl_idname', '') != 'SSMTSocketCustomShader' or not socket.is_linked:
                continue
            for link in socket.links:
                node = link.from_node
                if (
                    getattr(node, 'bl_idname', '') == SSMTNode_CustomShader.bl_idname
                    and not getattr(node, 'mute', False)
                    and node not in result
                ):
                    result.append(node)
        return result

    def _unico_split_object(
        self,
        obj: bpy.types.Object,
        node_submesh_name: str,
    ) -> list[tuple[str, bpy.types.Object]]:
        """
        UniComponent split: split the Merged object's vertices per each Submesh's VG range.

        Derives the draw_ib from the submesh_name bound to the node, loads the SubmeshJson
        of every Submesh under that DrawIB, builds a submesh -> VG mapping, then calls
        VertexGroupUtils.split_merged_object_by_submesh_vg_ranges().

        Returns:
            [(submesh_name, temp_split_object), ...]
        """
        from ..workspace.ssmt_workspace import SSMTWorkSpace
        from ..workspace.submesh_json import SubmeshJson

        # Derive draw_ib from the node's submesh_name
        # submesh_name format: "LOD0.94517393-0" or "94517393-0"
        normalized_name = str(node_submesh_name or "").strip()
        if not normalized_name:
            LOG.warning(f"BluePrintModel: UniComponent node '{obj.name}' has no Submesh set; skipping the split")
            return []

        # Strip the LOD prefix to get the bare name
        if normalized_name.upper().startswith("LOD") and "." in normalized_name:
            bare_name = normalized_name.split(".", 1)[1]
        else:
            bare_name = normalized_name

        # Extract draw_ib (the part before the first '-')
        draw_ib = bare_name.split("-")[0] if "-" in bare_name else ""
        if not draw_ib:
            LOG.warning(f"BluePrintModel: cannot parse draw_ib from submesh_name '{node_submesh_name}'")
            return []

        # Get the names of all Submeshes under this DrawIB
        all_submesh_names = SSMTWorkSpace.get_ordered_submesh_name_list_by_drawib(draw_ib)
        if not all_submesh_names:
            LOG.warning(f"BluePrintModel: no Submesh found under DrawIB '{draw_ib}'")
            return []

        LOG.info(f"BluePrintModel: found {len(all_submesh_names)} Submeshes: {all_submesh_names}")

        # Load each Submesh's VGMap and build the submesh -> VG mapping
        submesh_vg_map: dict[str, set[int]] = {}
        submesh_reverse_vg_map: dict[str, dict[int, int]] = {}

        for sm_name in all_submesh_names:
            try:
                sm_path = SSMTWorkSpace.check_and_get_submesh_json_path(sm_name)
                sm_json = SubmeshJson(sm_path)
                vg_map = sm_json.VGMap  # {local_idx: global_bone_id}
                LOG.info(f"BluePrintModel:   Submesh '{sm_name}' VGMap = {dict(vg_map)}")
                if not vg_map:
                    continue

                global_vg_set = set(int(v) for v in vg_map.values())
                reverse_map = {int(v): int(k) for k, v in vg_map.items()}

                submesh_vg_map[sm_name] = global_vg_set
                submesh_reverse_vg_map[sm_name] = reverse_map
            except Exception as e:
                LOG.warning(f"BluePrintModel: failed to load the VGMap of Submesh '{sm_name}': {e}")
                continue

        if not submesh_vg_map:
            LOG.warning(f"BluePrintModel: none of the Submeshes under DrawIB '{draw_ib}' has a VGMap; cannot split")
            return []

        # --- Filter: split only into Submeshes with unique VGs (falling back to the node-bound Submesh) ---
        # Compute shared VGs (VGs appearing in more than one Submesh VGMap)
        vg_occurrence: dict[int, set[str]] = {}
        for sm_name, vg_set in submesh_vg_map.items():
            for vg_id in vg_set:
                vg_occurrence.setdefault(vg_id, set()).add(sm_name)

        # The VGs actually present on the object
        obj_vg_ids = set()
        for vg in obj.vertex_groups:
            try:
                obj_vg_ids.add(int(vg.name))
            except ValueError:
                pass

        # Keep only the Submeshes that matter
        filtered_vg_map: dict[str, set[int]] = {}
        for sm_name, vg_set in submesh_vg_map.items():
            unique_vgs = {vg for vg in vg_set if len(vg_occurrence.get(vg, set())) == 1}
            has_unique = bool(unique_vgs & obj_vg_ids)
            is_node_submesh = (sm_name == node_submesh_name)
            if has_unique or is_node_submesh:
                filtered_vg_map[sm_name] = vg_set

        LOG.info(f"BluePrintModel: UniComponent split of '{obj.name}' "
                 f"(vertices: {len(obj.data.vertices)}, VG: {len(obj.vertex_groups)})")
        LOG.info(f"  node Submesh: '{node_submesh_name}', draw_ib: '{draw_ib}'")
        LOG.info(f"  object VG: {sorted(obj_vg_ids)}")
        LOG.info(f"  splitting into: {list(filtered_vg_map.keys())} "
                 f"(Submeshes without unique VGs were filtered out)")

        if not filtered_vg_map:
            LOG.warning(f"BluePrintModel: no valid Submesh to split into; skipping")
            return []
        filtered_reverse_map = {k: v for k, v in submesh_reverse_vg_map.items() if k in filtered_vg_map}

        # Build the unique-VG mapping (used to determine vertex ownership precisely)
        filtered_unique_vg_map: dict[str, set[int]] = {}
        for sm_name in filtered_vg_map:
            unique = {vg for vg in submesh_vg_map[sm_name] if len(vg_occurrence.get(vg, set())) == 1}
            filtered_unique_vg_map[sm_name] = unique

        return VertexGroupUtils.split_merged_object_by_submesh_vg_ranges(
            obj=obj,
            submesh_vg_map=filtered_vg_map,
            submesh_reverse_vg_map=filtered_reverse_map,
            submesh_unique_vg_map=filtered_unique_vg_map,
        )

    def parse_submesh_model_list(self) -> list[SubMeshModel]:
        """
        Parse a SubMeshModel list out of the current BluePrintModel.
        DrawCallModels sharing the same submesh_name are grouped together, with one SubMeshModel per group.
        """
        from ..workspace.ssmt_workspace import WorkSpaceModel

        submesh_model_list: list[SubMeshModel] = []
        draw_call_model_dict: dict[str, list[DrawCallModel]] = {}

        for draw_call_model in self.ordered_draw_obj_data_model_list:
            submesh_name = draw_call_model.get_submesh_name()
            draw_call_model_list = draw_call_model_dict.get(submesh_name, [])
            draw_call_model_list.append(draw_call_model)
            draw_call_model_dict[submesh_name] = draw_call_model_list

        # Create a WorkSpaceModel to correct the new format's IndexCount/FirstIndex
        workspace_model = WorkSpaceModel()

        for submesh_name, draw_call_model_list in draw_call_model_dict.items():
            submesh_model = SubMeshModel(drawcall_model_list=draw_call_model_list)
            # In the new format match_index_count/match_first_index start at -1; correct them with WorkSpaceModel
            submesh_model.fix_indices_from_workspace(workspace_model)
            submesh_model_list.append(submesh_model)

        # Sort by match_first_index ascending so DrawIB-0 (the smallest FirstIndex) comes first
        # Submeshes whose match_first_index is -1 (unset) are pushed to the end
        submesh_model_list.sort(key=lambda sm: sm.match_first_index if sm.match_first_index >= 0 else float('inf'))

        return submesh_model_list

    def parse_drawib_model_list(self, combine_ib: bool = False) -> list[DrawIBModel]:
        """
        Parse a DrawIBModel list out of the current BluePrintModel.
        Intended for games that need several SubMeshes combined into a single exported DrawIB.
        """
        drawib_model_list: list[DrawIBModel] = []
        draw_ib_submesh_model_list_dict: dict[str, list[SubMeshModel]] = {}

        for submesh_model in self.parse_submesh_model_list():
            draw_ib = submesh_model.match_draw_ib
            tmp_submesh_model_list = draw_ib_submesh_model_list_dict.get(draw_ib, [])
            tmp_submesh_model_list.append(submesh_model)
            draw_ib_submesh_model_list_dict[draw_ib] = tmp_submesh_model_list

        for draw_ib, submesh_model_list in draw_ib_submesh_model_list_dict.items():
            drawib_model = DrawIBModel(submesh_model_list=submesh_model_list, combine_ib=combine_ib)
            drawib_model_list.append(drawib_model)

        return drawib_model_list
