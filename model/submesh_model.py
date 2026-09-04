from dataclasses import dataclass, field
from .draw_call_model import DrawCallModel

from ..utils.export_utils import ExportUtils
from ..utils.obj_utils import ObjUtils
from ..utils.shapekey_utils import ShapeKeyUtils
from ..utils.collection_utils import CollectionUtils
from ..utils.json_utils import JsonUtils
from ..common.global_config import LogicName
from ..common.global_config import GlobalConfig
from ..common.d3d11_gametype import D3D11GameType
from ..common.obj_buffer_helper import ObjBufferHelper
from ..workspace.ssmt_workspace import SSMTWorkSpace
from ..workspace.submesh_json import SubmeshJson


import bpy
import math
import os


@dataclass
class SubMeshModel:
    # 初始化时需要填入此属性
    drawcall_model_list:list[DrawCallModel] = field(default_factory=list)

    # post_init中计算得到这些属性
    match_draw_ib:str = field(init=False, default="")
    match_first_index:int = field(init=False, default=-1)
    match_index_count:int = field(init=False, default=-1)
    match_cs:str = field(init=False, default="")
    match_uav_bytes:int = field(init=False, default=0)
    submesh_name:str = field(init=False, default="")

    # 调用组合obj并计算ib和vb得到这些属性
    vertex_count:int = field(init=False, default=0)
    index_count:int = field(init=False, default=0)

    # 读取工作空间中的 Import.json 选择数据类型目录，再从对应的 SubmeshJson 获取 d3d11GameType
    d3d11_game_type:D3D11GameType = field(init=False,repr=False,default=None)

    # 用于文件名生成（别名应用后）。
    # 默认等于 submesh_name；如果用户在「自定义Submesh名称」节点中设置了别名，
    # 由 DrawIBModel.apply_alias_dict() 在导出前更新为 "{lod_prefix}.{alias}"。
    display_str:str = field(init=False, default="")

    ib:list = field(init=False,repr=False,default_factory=list)
    category_buffer_dict:dict = field(init=False,repr=False,default_factory=dict)
    index_vertex_id_dict:dict = field(init=False,repr=False,default_factory=dict)
    shape_key_buffer_dict:dict = field(init=False,repr=False,default_factory=dict)
    ntemi_bone_palette:list = field(init=False,repr=False,default_factory=list)

    def get_slot_texture_node_list(self) -> list[tuple]:
        """聚合该 SubMesh 下所有 DrawCallModel 的 slot texture 节点。

        返回列表元素为 (slot_item, texture_node)，其中 slot_item 是
        SSMTTextureSlotItem 的引用，可通过 effective_slot_key 获取生成键名。
        """
        result = []
        seen = set()
        for drawcall_model in self.drawcall_model_list:
            for slot_item, texture_node in getattr(drawcall_model, "slot_texture_node_list", []):
                key = (id(slot_item), id(texture_node))
                if key in seen:
                    continue
                seen.add(key)
                result.append((slot_item, texture_node))
        return result


    def __post_init__(self):

        # 因为列表里的每个DrawCallModel的draw_ib,first_index,index_count都是一样的，所以直接取第一个就行了
        if len(self.drawcall_model_list) > 0:
            first_model = self.drawcall_model_list[0]
            self.match_draw_ib = first_model.match_draw_ib
            # 新格式下 match_index_count 可能为空字符串 → 先设 0，后续由 WorkSpaceModel 修正
            try:
                self.match_first_index = int(first_model.match_first_index) if first_model.match_first_index else -1
            except (ValueError, TypeError):
                self.match_first_index = -1
            try:
                self.match_index_count = int(first_model.match_index_count) if first_model.match_index_count else -1
            except (ValueError, TypeError):
                self.match_index_count = -1
            self.submesh_name = first_model.get_submesh_name()
        
        # display_str 默认等于 submesh_name，导出前可被 apply_alias_dict 覆盖
        self.display_str = self.submesh_name
        
        self.calc_buffer()

    def fix_indices_from_workspace(self, workspace_model):
        '''
        使用 WorkSpaceModel 修正 match_index_count 和 match_first_index。
        适用于新格式名称（submesh_name 为 "LOD0.94517393-0" 之类）的场景，
        此时 match_index_count 初始为 -1，需要从 WorkSpaceModel 的旧文件夹名解析真实值。
        旧格式名称已自带正确值，此方法不会覆盖。
        '''
        from ..workspace.ssmt_workspace import WorkSpaceModel

        # 如果 match_index_count 已经 >= 0，说明是旧格式，无需修正
        if self.match_index_count >= 0 and self.match_first_index >= 0:
            return

        if not self.submesh_name or not self.match_draw_ib:
            return

        # 尝试解析 submesh_name
        parsed = workspace_model.parse_new_format_name(self.submesh_name)
        if parsed is None:
            return

        # 从 WorkSpaceModel 获取真实值
        _, ic, fi = workspace_model.resolve_component_info(
            parsed["lod"], parsed["draw_ib"], parsed["component"]
        )
        if ic > 0 or fi >= 0:
            self.match_index_count = ic
            self.match_first_index = fi

    def calc_buffer(self):
        # 对每个obj都创建一个临时对象进行处理，这样不影响原本的对象

        submesh_json_path = SSMTWorkSpace.check_and_get_submesh_json_path(self.submesh_name)
        submesh_json = SubmeshJson(submesh_json_path)
        self.match_cs = submesh_json.MatchCS
        self.match_uav_bytes = submesh_json.MatchUAVBytes
        self.d3d11_game_type = D3D11GameType.from_submesh_json_dict(
            submesh_json.JsonDict, submesh_json_path
        )
        
        index_offset = 0
        submesh_temp_obj_list = []
        temp_collection_list = []
        for draw_call_model in self.drawcall_model_list:
            # 获取到原本的obj
            source_obj = ObjUtils.get_obj_by_name(draw_call_model.obj_name)

            temp_collection = CollectionUtils.create_new_collection("TEMP_SUBMESH_COLLECTION_" + self.submesh_name)
            bpy.context.scene.collection.children.link(temp_collection)
            temp_collection_list.append(temp_collection)


            # 创建一个新的obj
            temp_obj = ObjUtils.copy_object(
                context=bpy.context,
                obj=source_obj,
                name=source_obj.name + "_temp",
                collection= temp_collection
            )
            ShapeKeyUtils.reset_all_shapekey_values(temp_obj)

            self._normalize_temp_obj_for_export(temp_obj)

            # 因为导入时根据LogicName进行了翻转，所以导出时对临时对象进行翻转才能得到游戏原本坐标系
            self._apply_export_rotation_for_logic(temp_obj)

            # 三角化obj
            ObjUtils.triangulate_object(bpy.context, temp_obj)

            # 计算其额外属性，因为for里拿到的是引用，所以原地修改即可
            draw_call_model.vertex_count = len(temp_obj.data.vertices)
            # 因为三角化了，所以每个面都是3个索引，所以 *3 就没问题
            # 所以上面那一步三角化是必须的，否则概率报错
            draw_call_model.index_count = len(temp_obj.data.polygons) * 3
            draw_call_model.index_offset = index_offset

            index_offset += draw_call_model.index_count

            # 这里赋值的意义在于，后续可能会合并到DrawIB级别
            # 这里就可以直接复用了
            self.vertex_count += draw_call_model.vertex_count
            self.index_count += draw_call_model.index_count

            # 临时对象放到列表里，后续进行合并
            submesh_temp_obj_list.append(temp_obj)

        # 接下来合并obj，合并的意义在于可以减少IB和VB的计算次数，在大批量导出时节省很多时间
        # 确保选中第一个，否则join_objects会报错
        if submesh_temp_obj_list:
            # 取消选中所有物体
            bpy.ops.object.select_all(action='DESELECT')

            # 选中第一个物体并设置为活动物体
            target_active = submesh_temp_obj_list[0]
            target_active.select_set(True)
            bpy.context.view_layer.objects.active = target_active

        # 执行物体合并
        ObjUtils.join_objects(bpy.context, submesh_temp_obj_list)
        
        # 因为合并到第一个obj上了，所以这里直接拿到这个obj
        submesh_merged_obj = submesh_temp_obj_list[0]

        # 重命名为指定名称，等待后续操作
        merged_obj_name = "TEMP_SUBMESH_MERGED_" + self.submesh_name
        ObjUtils.rename_object(submesh_merged_obj, merged_obj_name)

        # 检查并校验是否有缺少的元素
        ObjBufferHelper.check_and_verify_attributes(obj=submesh_merged_obj, d3d11_game_type=self.d3d11_game_type)

        obj_buffer_result = ExportUtils.build_unity_obj_buffer_result(
            obj=submesh_merged_obj,
            d3d11_game_type=self.d3d11_game_type,
        )
        self.ib = obj_buffer_result.ib
        self.category_buffer_dict = obj_buffer_result.category_buffer_dict
        self.index_vertex_id_dict = obj_buffer_result.index_loop_id_dict
        self.shape_key_buffer_dict = obj_buffer_result.shape_key_buffer_dict

        if GlobalConfig.logic_name == LogicName.NTEMI:
            self.ntemi_bone_palette = [int(vg.name) for vg in submesh_merged_obj.vertex_groups]

        # 4.计算完成后，删除临时obj
        bpy.data.objects.remove(submesh_merged_obj, do_unlink=True)

        # 顺便把刚才创建的临时集合也删掉
        for temp_collection in temp_collection_list:
            if temp_collection.name in bpy.data.collections:
                if temp_collection.name in bpy.context.scene.collection.children:
                    bpy.context.scene.collection.children.unlink(temp_collection)
                bpy.data.collections.remove(temp_collection)

        print("SubMeshModel: " + self.submesh_name + " 计算完成，临时对象已删除")

    def _normalize_temp_obj_for_export(self, temp_obj: bpy.types.Object):
        if self.d3d11_game_type is None:
            return

        if "Blend" not in self.d3d11_game_type.OrderedCategoryNameList:
            return

        # Missing groups may have been filled with empty groups.  A component
        # whose vertices already sum to one (including a single full-weight
        # group) needs no adjustment, and Normalize All can fail for locked
        # groups even though the data is valid.
        if ObjUtils.are_vertex_weights_normalized(temp_obj):
            return

        if ObjUtils.is_all_vertex_groups_locked(temp_obj):
            return

        ObjUtils.normalize_all(temp_obj)

    def _apply_export_rotation_for_logic(self, temp_obj: bpy.types.Object):
        if (GlobalConfig.logic_name == LogicName.SRMI
            or GlobalConfig.logic_name == LogicName.GIMI
            or GlobalConfig.logic_name == LogicName.HIMI
            or GlobalConfig.logic_name == LogicName.YYSLS
            or GlobalConfig.logic_name == LogicName.IdentityV):
            ObjUtils.select_obj(temp_obj)
            temp_obj.rotation_euler[0] = math.radians(-90)
            temp_obj.rotation_euler[1] = 0
            temp_obj.rotation_euler[2] = 0
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        
        elif GlobalConfig.logic_name == LogicName.NTEMI or GlobalConfig.logic_name == LogicName.SnowBreak:
            # NTEMI/SnowBreak import: Z rotate 180°, scale 0.01 → reverse: scale 100, Z rotate ±180°
            ObjUtils.select_obj(temp_obj)
            temp_obj.scale = (100.0, 100.0, 100.0)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            temp_obj.rotation_euler[0] = 0
            temp_obj.rotation_euler[1] = 0
            temp_obj.rotation_euler[2] = math.radians(180)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

        elif GlobalConfig.logic_name == LogicName.EFMI or GlobalConfig.logic_name == LogicName.Naraka:
            ObjUtils.select_obj(temp_obj)
            temp_obj.rotation_euler[0] = 0
            temp_obj.rotation_euler[1] = 0
            temp_obj.rotation_euler[2] = 0
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
