
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

from ..blueprint.blueprint_node_texture import SSMTNode_Texture
from ..blueprint.blueprint_node_custom_shader import SSMTNode_CustomShader
from ..blueprint.blueprint_node_group import (
    GROUP_INPUT_IDNAME,
    GROUP_NODE_IDNAME,
    GROUP_OUTPUT_IDNAME,
    _group_socket_for_interface,
)
from ..common.m_texture_helper import HashTextureBinding
from ..common.m_custom_shader_helper import M_CustomShaderHelper


class BluePrintModel:

    _KEY_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
    
    def __init__(self, tree=None, context=None, output_node=None):
        M_CustomShaderHelper.begin_export()
        # 全局按键名称和按键属性字典
        self.keyname_mkey_dict:dict[str,M_Key] = {} 

        # 全局obj_model列表，主要是obj_model里装了每个obj的生效条件。
        self.ordered_draw_obj_data_model_list:list[DrawCallModel] = [] 

        # 通过 Hash 出口参与蓝图链路的 Texture 节点
        self.hash_texture_node_list:list[HashTextureBinding] = []

        # UniComponent 拆分产生的临时物体，导出后需清理
        self._unico_temp_objects: list[bpy.types.Object] = []
        self._group_instance_stack: list[bpy.types.Node] = []

        # 从输出节点开始递归解析所有的节点
        tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not tree:
            raise ValueError("未找到当前蓝图树，请先打开正确的蓝图编辑器")

        # Nodes sharing an explicit alias share one INI variable.  Its period
        # is the LCM of the participating nodes' branch counts.
        self._switch_alias_state_counts = self._collect_switch_alias_state_counts(tree)

        print(tree)
        output_node = output_node or BlueprintExportHelper.get_node_from_bl_idname(
            tree, SSMTNode_Result_Output.bl_idname
        )
        if not output_node:
            raise ValueError("当前蓝图缺少 Generate Mod 输出节点")

        print("BluePrintModel: 输出节点连接的节点数量: " + str(len(BlueprintExportHelper.get_connected_nodes(output_node))))
        self.parse_current_node(output_node, [])

    @classmethod
    def _normalize_switch_key_alias(cls, switch_node: bpy.types.Node) -> str:
        alias = str(getattr(switch_node, "key_alias", "") or "").strip()
        if alias == "":
            return ""
        if cls._KEY_ALIAS_PATTERN.fullmatch(alias) is None:
            raise ValueError("按键切换节点的变量别名只能包含英文字母和数字: " + alias)
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
            raise ValueError("按键切换节点的变量名重复: " + key_name)
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
        这个是递归方法
        解析当前节点，获取其连接的所有节点的信息,分类进行解析
        '''
        
        if unknown_node.mute:
            return

        if unknown_node.bl_idname == GROUP_NODE_IDNAME:
            self._parse_custom_group(unknown_node, chain_key_list)

        elif unknown_node.bl_idname == SSMTNode_Object_Group.bl_idname:
            # 如果是单纯的分组节点，则不进行任何处理直接传递下去
            self.parse_current_node(unknown_node, chain_key_list)

        elif unknown_node.bl_idname == SSMTNode_SwitchKey.bl_idname:
            # 如果是按键切换节点，则该节点所有的分支节点，并逐个处理
            # 这里我们直接遍历所有的inputs，而不是get_connected_nodes，
            # 因为get_connected_nodes会忽略未连接(空)的端口，导致分支数量计算错误
            
            # 获取有效的分支数量（除去最后一个为了方便添加而存在的空端口）
            # 只有当最后一个端口确实没有连接的时候才能排除，虽然Node定义里是这样写的逻辑，但最好判断一下link
            # valid_input_sockets = unknown_node.inputs[:-1] if (len(unknown_node.inputs) > 1 and not unknown_node.inputs[-1].is_linked) else unknown_node.inputs[:]
            
            # 修正：对于SwitchKey节点，所有的Input都是有效的分支，因为可以手动添加/删除Socket，且空Socket代表空状态（什么都不显示）
            valid_input_sockets = unknown_node.inputs[:]
            
            # 如果所有端口都没有连接，则直接跳过
            is_all_socket_linked = False
            for sock in valid_input_sockets:
                if sock.is_linked:
                    is_all_socket_linked = True
                    break
            
            if not is_all_socket_linked:
                # 如果没有任何连接，不做处理
                return

            if len(valid_input_sockets) == 1:
                # 如果只有 1 个有效分支端口：
                # 1. 如果它是连接的 -> 视为 Group 节点透传
                # 2. 如果它是断开的 -> 视为无意义，不做处理(上面all_socket_linked已过滤)
                if valid_input_sockets[0].is_linked:
                        for link in valid_input_sockets[0].links:
                            self.parse_single_node(link.from_node, chain_key_list)
            else:
                # 如果有 > 1 个有效分支端口，则必须创建 Key，哪怕某些端口是空的（代表空分支）
                m_key = M_Key()
                current_add_key_index = len(self.keyname_mkey_dict.keys())
                m_key.key_name, uses_auto_key_name = self._allocate_switch_key_name(unknown_node)

                state_count = self._switch_alias_state_counts.get(
                    m_key.key_name, len(valid_input_sockets)
                )
                m_key.value_list = list(range(state_count))

                m_key.initialize_vk_str = unknown_node.key_name
                m_key.initialize_value = 0  # 默认选择第一个分支

                # 设置备注信息
                m_key.comment = getattr(unknown_node, 'comment', '')

                # 显式同别名只创建一份全局 Key；LCM 状态数已在预扫描确定。
                existing_key = self.keyname_mkey_dict.get(m_key.key_name)
                if existing_key is None:
                    self.keyname_mkey_dict[m_key.key_name] = m_key
                else:
                    m_key = existing_key

                # 更新全局key索引
                if uses_auto_key_name and len(self.keyname_mkey_dict.keys()) > current_add_key_index:
                    GlobalConfig.global_key_index = GlobalConfig.global_key_index + 1

                # 逐个处理每个分支节点（包括空分支）
                for branch_index, socket in enumerate(valid_input_sockets):
                    # 无论这个 socket 是否连接了节点，或者是空的，都对应一个 key value
                    
                    if socket.is_linked:
                        # 如果连接了节点，则需要把这个 value 对应的 key 传递下去解析
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
                        # 如果是空端口（没有连接），则代表这个 value 对应的是空物体
                        # 我们不需要做任何 parse 操作，因为没有任何 obj 需要在这个条件下生成
                        # 这个 key value 存在于 key.value_list 中，但没有任何 obj 的 condition 会匹配到这个 value
                        # 这样就实现了“切换到这个分支时，什么都不显示”的效果
                        pass

        elif unknown_node.bl_idname == SSMTNode_Object_Info.bl_idname:
            obj = bpy.data.objects.get(unknown_node.object_name)
            custom_shader_nodes = self._get_custom_shader_nodes(unknown_node)

            # 解析蓝图时提前过滤空网格，避免后续导出阶段触发全部顶点组已被锁定错误。
            if obj is None or obj.type != 'MESH' or obj.data is None or len(obj.data.vertices) == 0:
                LOG.info("BluePrintModel: 跳过空网格或无效对象: " + str(unknown_node.object_name))
                return

            # UniComponent 模式：自动检测并拆分物体
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
                    LOG.info(f"BluePrintModel: UniComponent 拆分 '{unknown_node.object_name}' → "
                             f"submesh='{submesh_name}' parsed='{obj_model.match_submesh_name}' "
                             f"draw_ib='{obj_model.match_draw_ib}' (临时物体: '{temp_obj.name}')")
            else:
                # 传统模式：直接使用原物体
                obj_model = DrawCallModel(
                    obj_name=unknown_node.object_name,
                    submesh_name=getattr(unknown_node, 'submesh_name', ''),
                )
                
                if hasattr(unknown_node, 'original_object_name') and unknown_node.original_object_name:
                    obj_model.display_name = unknown_node.original_object_name

                obj_model.work_key_list = copy.deepcopy(chain_key_list)

                # 收集通过 Slot 出口连接上来的 Texture 节点
                for idx, item in enumerate(getattr(unknown_node, 'texture_slot_items', [])):
                    socket = unknown_node._get_texture_socket_by_item_index(idx)
                    if socket is None or not socket.is_linked:
                        continue
                    for link in socket.links:
                        texture_node = link.from_node
                        if getattr(texture_node, "bl_idname", "") == SSMTNode_Texture.bl_idname:
                            # 携带 slot item，导出时按 effective_slot_key 生成键名
                            obj_model.slot_texture_node_list.append((item, texture_node))

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

        elif unknown_node.bl_idname == SSMTNode_Texture.bl_idname:
            # Texture 节点：Hash 出口沿蓝图链路传递，因此也必须保留当前分支条件。
            hash_socket = unknown_node.outputs.get("Hash")
            if hash_socket and hash_socket.is_linked:
                hash_binding = HashTextureBinding(
                    texture_node=unknown_node,
                    work_key_list=copy.deepcopy(chain_key_list),
                )
                condition_str = hash_binding.get_condition_str()
                if not any(
                    item.texture_node is unknown_node
                    and item.get_condition_str() == condition_str
                    for item in self.hash_texture_node_list
                ):
                    self.hash_texture_node_list.append(hash_binding)

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
        UniComponent 拆分：将 Merged 物体的顶点按 Submesh 的 VG 范围拆分。

        从节点绑定的 submesh_name 推导出 draw_ib，
        加载该 DrawIB 下所有 Submesh 的 SubmeshJson，
        构建 submesh→VG 映射后调用 VertexGroupUtils.split_merged_object_by_submesh_vg_ranges()。

        Returns:
            [(submesh_name, temp_split_object), ...]
        """
        from ..workspace.ssmt_workspace import SSMTWorkSpace
        from ..workspace.submesh_json import SubmeshJson

        # 从节点 submesh_name 解析 draw_ib
        # submesh_name 格式: "LOD0.94517393-0" 或 "94517393-0"
        normalized_name = str(node_submesh_name or "").strip()
        if not normalized_name:
            LOG.warning(f"BluePrintModel: UniComponent 节点 '{obj.name}' 未设置 Submesh，跳过拆分")
            return []

        # 去掉 LOD 前缀获取 bare name
        if normalized_name.upper().startswith("LOD") and "." in normalized_name:
            bare_name = normalized_name.split(".", 1)[1]
        else:
            bare_name = normalized_name

        # 提取 draw_ib (第一个 '-' 之前的部分)
        draw_ib = bare_name.split("-")[0] if "-" in bare_name else ""
        if not draw_ib:
            LOG.warning(f"BluePrintModel: 无法从 submesh_name '{node_submesh_name}' 解析 draw_ib")
            return []

        # 获取该 DrawIB 下所有 Submesh 名称
        all_submesh_names = SSMTWorkSpace.get_ordered_submesh_name_list_by_drawib(draw_ib)
        if not all_submesh_names:
            LOG.warning(f"BluePrintModel: DrawIB '{draw_ib}' 没有找到任何 Submesh")
            return []

        LOG.info(f"BluePrintModel: 共找到 {len(all_submesh_names)} 个 Submesh: {all_submesh_names}")

        # 加载每个 Submesh 的 VGMap，构建 submesh→VG 映射
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
                LOG.warning(f"BluePrintModel: 加载 Submesh '{sm_name}' 的 VGMap 失败: {e}")
                continue

        if not submesh_vg_map:
            LOG.warning(f"BluePrintModel: DrawIB '{draw_ib}' 的所有 Submesh 均无 VGMap，无法拆分")
            return []

        # --- 过滤：只拆到有独有 VG 的 Submesh（或节点绑定的 Submesh 作为兜底）---
        # 计算共享 VG（出现在多个 Submesh VGMap 中的 VG）
        vg_occurrence: dict[int, set[str]] = {}
        for sm_name, vg_set in submesh_vg_map.items():
            for vg_id in vg_set:
                vg_occurrence.setdefault(vg_id, set()).add(sm_name)

        # 物体实际 VG
        obj_vg_ids = set()
        for vg in obj.vertex_groups:
            try:
                obj_vg_ids.add(int(vg.name))
            except ValueError:
                pass

        # 只保留有意义的 Submesh
        filtered_vg_map: dict[str, set[int]] = {}
        for sm_name, vg_set in submesh_vg_map.items():
            unique_vgs = {vg for vg in vg_set if len(vg_occurrence.get(vg, set())) == 1}
            has_unique = bool(unique_vgs & obj_vg_ids)
            is_node_submesh = (sm_name == node_submesh_name)
            if has_unique or is_node_submesh:
                filtered_vg_map[sm_name] = vg_set

        LOG.info(f"BluePrintModel: UniComponent 拆分 '{obj.name}' "
                 f"(顶点: {len(obj.data.vertices)}, VG: {len(obj.vertex_groups)})")
        LOG.info(f"  节点 Submesh: '{node_submesh_name}', draw_ib: '{draw_ib}'")
        LOG.info(f"  物体 VG: {sorted(obj_vg_ids)}")
        LOG.info(f"  将拆分到: {list(filtered_vg_map.keys())} "
                 f"(已过滤掉无独有 VG 的 Submesh)")

        if not filtered_vg_map:
            LOG.warning(f"BluePrintModel: 无有效 Submesh 可拆分，跳过")
            return []
        filtered_reverse_map = {k: v for k, v in submesh_reverse_vg_map.items() if k in filtered_vg_map}

        # 构建独有 VG 映射（用于精确判定顶点归属）
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
        从当前 BluePrintModel 解析出 SubMeshModel 列表。
        将相同 submesh_name 的 DrawCallModel 分在一起，每个组创建一个 SubMeshModel。
        """
        from ..workspace.ssmt_workspace import WorkSpaceModel

        submesh_model_list: list[SubMeshModel] = []
        draw_call_model_dict: dict[str, list[DrawCallModel]] = {}

        for draw_call_model in self.ordered_draw_obj_data_model_list:
            submesh_name = draw_call_model.get_submesh_name()
            draw_call_model_list = draw_call_model_dict.get(submesh_name, [])
            draw_call_model_list.append(draw_call_model)
            draw_call_model_dict[submesh_name] = draw_call_model_list

        # 创建 WorkSpaceModel 用于修正新格式的 IndexCount/FirstIndex
        workspace_model = WorkSpaceModel()

        for submesh_name, draw_call_model_list in draw_call_model_dict.items():
            submesh_model = SubMeshModel(drawcall_model_list=draw_call_model_list)
            # 新格式下 match_index_count/match_first_index 初始为 -1，用 WorkSpaceModel 修正
            submesh_model.fix_indices_from_workspace(workspace_model)
            submesh_model_list.append(submesh_model)

        # 按 match_first_index 升序排序，确保 DrawIB-0 (FirstIndex 最小的) 排在前面
        # match_first_index 为 -1（未设置）的排到最后
        submesh_model_list.sort(key=lambda sm: sm.match_first_index if sm.match_first_index >= 0 else float('inf'))

        return submesh_model_list

    def parse_drawib_model_list(self, combine_ib: bool = False) -> list[DrawIBModel]:
        """
        从当前 BluePrintModel 解析出 DrawIBModel 列表。
        适用于需要将多个 SubMesh 组合成一个 DrawIB 导出的游戏。
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
