import math
import os
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TypedDict

import bpy
import numpy

from ..common.global_properties import GlobalProperties
from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from ..utils.export_utils import ExportUtils, ObjElementContext, WWMIBufferBuildResult
from ..utils.log_utils import LOG
from ..utils.obj_utils import (
    MergedObject,
    MergedObjectComponent,
    MergedObjectShapeKeys,
    ObjUtils,
    OpenObject,
    TempObject,
)
from ..utils.shapekey_utils import ShapeKeyUtils
from ..utils.vertexgroup_utils import VertexGroupUtils
from ..workspace.wwmi_info import WWMIInfoObject, WWMIInfoHelper
from ..common.buffer_export_helper import BufferExportHelper
from ..common.obj_buffer_helper import ObjBufferHelper
from ..workspace.ssmt_workspace import SSMTWorkSpace
from ..common.d3d11_gametype import D3D11GameType
from .blueprint_model import BluePrintModel
from .draw_call_model import DrawCallModel
from ..workspace.submesh_json import SubmeshJson
from ..workspace.texture_metadata_helper import TextureMetadataResolver


class BlendRemapEntry(TypedDict):
    forward: list[int]
    reverse: dict[int, int]


@dataclass
class DrawIBModelWWMI:
    draw_ib: str # 当前DrawIB
    blueprint_model: BluePrintModel # 当前DrawIBModel对应的BlueprintModel

    draw_ib_alias: str = field(init=False, default="") # 当前DrawIB的别名
    d3d11_game_type: D3D11GameType = field(init=False, repr=False) # 当前DrawIB的数据类型，因为WWMI中每个DrawIB只可能是一个数据类型
    wwmi_info: WWMIInfoObject = field(init=False, repr=False) 

    ordered_drawcall_model_list: list[DrawCallModel] = field(init=False, default_factory=list, repr=False)
    submesh_drawcall_groups: list[list[DrawCallModel]] = field(init=False, default_factory=list, repr=False)

    mesh_vertex_count: int = field(init=False, default=0)
    merged_object: MergedObject | None = field(init=False, default=None, repr=False)
    blend_remap: bool = field(init=False, default=False)
    obj_buffer_model_wwmi: WWMIBufferBuildResult | None = field(init=False, default=None, repr=False)
    blend_remap_maps: dict[str, BlendRemapEntry] = field(init=False, default_factory=dict, repr=False)
    blend_remap_used: dict[str, bool] = field(init=False, default_factory=dict, repr=False)
    component_real_vg_count_dict: dict[int, int] = field(init=False, default_factory=dict, repr=False)

    submesh_model_list: list = field(init=False, default_factory=list, repr=False)
    submesh_texturemarkinfolist_dict: dict = field(init=False, default_factory=dict, repr=False)

    blend_remap_forward_buffer: numpy.ndarray | None = field(init=False, default=None, repr=False)
    blend_remap_reverse_buffer: numpy.ndarray | None = field(init=False, default=None, repr=False)
    blend_remap_vertex_vg_buffer: numpy.ndarray | None = field(init=False, default=None, repr=False)

    def __post_init__(self):
        # 从工作空间获取别名列表
        drawib_aliasname_dict: dict[str, str] = SSMTWorkSpace.get_drawib_aliasname_dict()

        # 设置别名
        self.draw_ib_alias = drawib_aliasname_dict.get(self.draw_ib, self.draw_ib)

        # 获取当前DrawIB包含的DrawCallModel列表
        self.ordered_drawcall_model_list = ObjBufferHelper.get_ordered_obj_models_by_draw_ib(
            ordered_draw_obj_data_model_list=self.blueprint_model.ordered_draw_obj_data_model_list,
            draw_ib=self.draw_ib,
        )

        # 如果一个DrawCallModel都没有，说明这个DrawIB没有可导出的对象，抛出错误
        if len(self.ordered_drawcall_model_list) == 0:
            raise ValueError("当前 DrawIB 没有可导出的 DrawCallModel")

        # 从第一个DrawCallModel获取对应的SubmeshJson，解析出当前DrawIB的数据类型
        # 之所以是第一个，因为对于WWMI来说，整个DrawIB的数据类型是使用共同的唯一的一个的
        first_submesh_name = self.ordered_drawcall_model_list[0].get_submesh_name()
        first_json_path = SSMTWorkSpace.check_and_get_submesh_json_path(first_submesh_name)
        first_submesh_json = SubmeshJson(first_json_path)
        self.d3d11_game_type = D3D11GameType.from_submesh_json_dict(first_submesh_json.JsonDict, first_json_path)

        self.submesh_drawcall_groups = []

        # 从工作空间获取当前 DrawIB 所有 submesh 的排序列表
        ordered_submesh_name_list = SSMTWorkSpace.get_ordered_submesh_name_list_by_drawib(self.draw_ib)

        # 预加载 SubmeshJson 并按排序后的顺序构建分组 + wwmi_info
        ordered_submesh_json_list: list[SubmeshJson] = []
        for submesh_name in ordered_submesh_name_list:
            ordered_submesh_json_list.append(SubmeshJson(SSMTWorkSpace.check_and_get_submesh_json_path(submesh_name)))
            # 收集当前 submesh 对应的所有 DrawCall
            drawcall_group = []
            for drawcall_model in self.ordered_drawcall_model_list:
                if drawcall_model.get_submesh_name() == submesh_name:
                    drawcall_group.append(drawcall_model)
            self.submesh_drawcall_groups.append(drawcall_group)
        
        # 根据有序的 SubmeshJson 列表构建 WWMIInfoObject，
        # 这个对象包含了当前 DrawIB 的所有组件信息，后续构建 MergedObject 和导出时都会用到
        self.wwmi_info = WWMIInfoHelper.build_from_json_list(ordered_submesh_json_list)
        
        self.merged_object = self.build_merged_object()

        obj_name_temp_object_dict: dict[str, TempObject] = {}
        for component in self.merged_object.components:
            for temp_object in component.objects:
                obj_name_temp_object_dict[temp_object.name] = temp_object

        for idx, drawcall_model_list in enumerate(self.submesh_drawcall_groups):
            updated_drawcall_model_list: list[DrawCallModel] = []
            for drawcall_model in drawcall_model_list:
                temp_object = obj_name_temp_object_dict.get(drawcall_model.obj_name)
                if temp_object is not None:
                    drawcall_model.index_count = temp_object.index_count
                    drawcall_model.index_offset = temp_object.index_offset
                    drawcall_model.vertex_count = temp_object.vertex_count
                updated_drawcall_model_list.append(drawcall_model)
            self.submesh_drawcall_groups[idx] = updated_drawcall_model_list

        # 构建 submesh_model_list 和纹理标记字典，供 M_IniHelper 纹理导出使用
        # 注意：需要按 match_first_index（即 ComponentIndex / FirstIndex）从小到大排序，
        # 确保 DrawIB-0 (Component 0) 在 DrawIB-1 (Component 1) 前面，
        # 并且同一个 submesh 只保留一个条目（去重），避免蓝图节点排列顺序影响导出结果。
        self.submesh_model_list = []
        submesh_seen: dict[str, int] = {}  # submesh_name → match_first_index
        for drawcall_model in self.ordered_drawcall_model_list:
            submesh_name = drawcall_model.match_submesh_name
            if not submesh_name:
                continue
            if submesh_name in submesh_seen:
                continue  # 已处理过该 submesh
            try:
                mfi_int = int(drawcall_model.match_first_index)
            except (TypeError, ValueError):
                mfi_int = 0
            submesh_seen[submesh_name] = mfi_int

        for submesh_name, mfi_int in sorted(submesh_seen.items(), key=lambda item: item[1]):
            self.submesh_model_list.append(SimpleNamespace(
                submesh_name=submesh_name,
                display_str=submesh_name,  # 初始等于 submesh_name，后续由 apply_alias_dict 覆盖
                match_first_index=mfi_int,
                d3d11_game_type=self.d3d11_game_type,
            ))

        if self.submesh_model_list:
            self.submesh_texturemarkinfolist_dict = TextureMetadataResolver.load_submesh_texture_markup_info_from_all_submeshes(draw_ib_model=self)

        ObjBufferHelper.check_and_verify_attributes(obj=self.merged_object.object, d3d11_game_type=self.d3d11_game_type)

        element_context = ExportUtils.build_obj_element_context(
            d3d11_game_type=self.d3d11_game_type,
            obj=self.merged_object.object,
        )

        if self.blend_remap:
            self.replace_remapped_blendindices(element_context)

        element_context.element_vertex_ndarray = ObjBufferHelper.convert_to_element_vertex_ndarray(
            mesh=element_context.mesh,
            original_elementname_data_dict=element_context.original_elementname_data_dict,
            final_elementname_data_dict=element_context.final_elementname_data_dict,
            d3d11_game_type=self.d3d11_game_type,
        )

        self.obj_buffer_model_wwmi = ExportUtils.build_wwmi_obj_buffer_result(element_context)

        position_stride: int = self.d3d11_game_type.CategoryStrideDict["Position"]
        position_bytelength: int = len(self.obj_buffer_model_wwmi.category_buffer_dict["Position"])
        self.mesh_vertex_count = int(position_bytelength / position_stride)

        if self.blend_remap:
            self.blend_remap_vertex_vg_buffer = self._build_blend_remap_vertex_vg_buffer(element_context)

        bpy.data.objects.remove(self.merged_object.object, do_unlink=True)

    def _build_blend_remap_vertex_vg_buffer(self, element_context: ObjElementContext) -> numpy.ndarray | None:
        index_vertex_id_dict = self.obj_buffer_model_wwmi.index_vertex_id_dict
        if not index_vertex_id_dict:
            return None

        original_blendindices = element_context.original_elementname_data_dict.get("BLENDINDICES")
        unique_first_loop_indices = getattr(self.obj_buffer_model_wwmi, "unique_first_loop_indices", None)
        if original_blendindices is None or unique_first_loop_indices is None:
            return None

        num_vgs = self.d3d11_game_type.get_blendindices_count_wwmi()
        vg_array = numpy.zeros((len(index_vertex_id_dict), num_vgs), dtype=numpy.uint16)

        sampled_blendindices = original_blendindices[unique_first_loop_indices]
        if getattr(sampled_blendindices, "ndim", 1) == 1:
            sampled_blendindices = sampled_blendindices.reshape(-1, 1)

        for index in range(min(num_vgs, sampled_blendindices.shape[1])):
            vg_array[:, index] = sampled_blendindices[:, index].astype(numpy.uint16)

        return vg_array

    def write_buffer_files(self):
        if self.obj_buffer_model_wwmi is None:
            return

        BufferExportHelper.write_buf_ib_r32_uint(self.obj_buffer_model_wwmi.ib, self.draw_ib + "-Component1.buf")
        BufferExportHelper.write_category_buffer_files(self.obj_buffer_model_wwmi.category_buffer_dict, self.draw_ib)
        for shapekey_name, position_buffer in self.obj_buffer_model_wwmi.shapekey_position_buffer_dict.items():
            safe_shapekey_name = self.get_safe_shapekey_name(shapekey_name)
            BufferExportHelper.write_numpy_buffer(
                position_buffer,
                self.draw_ib + "-Position." + safe_shapekey_name + ".buf",
            )
        for shapekey_name, vector_buffer in self.obj_buffer_model_wwmi.shapekey_vector_buffer_dict.items():
            safe_shapekey_name = self.get_safe_shapekey_name(shapekey_name)
            BufferExportHelper.write_numpy_buffer(
                vector_buffer,
                self.draw_ib + "-Vector." + safe_shapekey_name + ".buf",
            )

        if self.obj_buffer_model_wwmi.export_shapekey:
            BufferExportHelper.write_buf_shapekey_offsets(self.obj_buffer_model_wwmi.shapekey_offsets, self.draw_ib + "-ShapeKeyOffset.buf")
            BufferExportHelper.write_buf_shapekey_vertex_ids(self.obj_buffer_model_wwmi.shapekey_vertex_ids, self.draw_ib + "-ShapeKeyVertexId.buf")
            BufferExportHelper.write_buf_shapekey_vertex_offsets(self.obj_buffer_model_wwmi.shapekey_vertex_offsets, self.draw_ib + "-ShapeKeyVertexOffset.buf")

        if self.blend_remap_forward_buffer is not None and self.blend_remap_forward_buffer.size != 0:
            BufferExportHelper.write_buf_blendindices_uint16(self.blend_remap_forward_buffer, self.draw_ib + "-BlendRemapForward.buf")

        if self.blend_remap_reverse_buffer is not None and self.blend_remap_reverse_buffer.size != 0:
            BufferExportHelper.write_buf_blendindices_uint16(self.blend_remap_reverse_buffer, self.draw_ib + "-BlendRemapReverse.buf")

        if self.blend_remap_vertex_vg_buffer is not None and self.blend_remap_vertex_vg_buffer.size != 0:
            BufferExportHelper.write_buf_blendindices_uint16(self.blend_remap_vertex_vg_buffer, self.draw_ib + "-BlendRemapVertexVG.buf")

    def build_merged_object(self) -> MergedObject:
        components: list[MergedObjectComponent] = []
        for _component in self.wwmi_info.components:
            components.append(MergedObjectComponent(objects=[], index_count=0))

        workspace_collection = bpy.context.collection
        processed_obj_name_list: list[str] = []

        for component_id, component_drawcall_model_list in enumerate(self.submesh_drawcall_groups):
            for drawcall_model in component_drawcall_model_list:
                obj_name = drawcall_model.obj_name
                if obj_name in processed_obj_name_list:
                    continue

                processed_obj_name_list.append(obj_name)

                source_obj = ObjUtils.get_obj_by_name(obj_name)
                temp_obj = ObjUtils.copy_object(
                    bpy.context,
                    source_obj,
                    name=f"TEMP_{source_obj.name}",
                    collection=workspace_collection,
                )

                components[component_id].objects.append(
                    TempObject(
                        name=source_obj.name,
                        object=temp_obj,
                    )
                )

        self.component_real_vg_count_dict = {}
        index_offset = 0

        for component_id, component in enumerate(components):
            component.objects.sort(key=lambda temp_object: temp_object.name)

            for temp_object in component.objects:
                temp_obj = temp_object.object

                if GlobalProperties.ignore_muted_shape_keys() and temp_obj.data.shape_keys:
                    muted_shape_keys = []
                    for shapekey_id in range(len(temp_obj.data.shape_keys.key_blocks)):
                        shape_key = temp_obj.data.shape_keys.key_blocks[shapekey_id]
                        if shape_key.mute:
                            muted_shape_keys.append(shape_key)
                    for shape_key in muted_shape_keys:
                        temp_obj.shape_key_remove(shape_key)

                if GlobalProperties.apply_all_modifiers():
                    with OpenObject(bpy.context, temp_obj) as opened_obj:
                        selected_modifiers = [modifier.name for modifier in ObjUtils.get_modifiers(opened_obj)]
                        ShapeKeyUtils.apply_modifiers_for_object_with_shape_keys(bpy.context, selected_modifiers, None)

                ObjUtils.triangulate_object(bpy.context, temp_obj)

                vertex_groups = ObjUtils.get_vertex_groups(temp_obj)
                if GlobalProperties.import_merged_vgmap() == 'MERGED':
                    total_vg_count = sum(ec.vg_count for ec in self.wwmi_info.components)
                    ignore_list = [
                        vertex_group
                        for vertex_group in vertex_groups
                        if "ignore" in vertex_group.name.lower() or vertex_group.index >= total_vg_count
                    ]
                else:
                    # PER_COMPONENT 或 UNICOMPONENT：使用组件本地 VG 范围
                    extracted_component = self.wwmi_info.components[component_id]
                    total_vg_count = len(extracted_component.vg_map)
                    ignore_list = [
                        vertex_group
                        for vertex_group in vertex_groups
                        if "ignore" in vertex_group.name.lower() or vertex_group.index >= total_vg_count
                    ]
                ObjUtils.remove_vertex_groups(temp_obj, ignore_list)

                temp_object.vertex_count = len(temp_obj.data.vertices)
                temp_object.index_count = len(temp_obj.data.polygons) * 3
                temp_object.index_offset = index_offset
                index_offset += temp_object.index_count
                component.vertex_count += temp_object.vertex_count
                component.index_count += temp_object.index_count

        drawib_merged_object: list[bpy.types.Object] = []
        drawib_vertex_count: int = 0
        drawib_index_count: int = 0
        component_obj_list: list[bpy.types.Object] = []

        for component_index, component in enumerate(components):
            component_merged_object = [temp_object.object for temp_object in component.objects]

            if len(component_merged_object) == 0:
                continue

            ObjUtils.join_objects(bpy.context, component_merged_object)
            component_obj = component_merged_object[0]

            if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
                ObjUtils.select_obj(component_obj)
                component_obj.rotation_euler[0] = 0
                component_obj.rotation_euler[1] = 0
                component_obj.rotation_euler[2] = math.radians(180)
                component_obj.scale = (100, 100, 100)
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

            if GlobalProperties.export_add_missing_vertex_groups():
                ObjUtils.select_obj(component_obj)
                VertexGroupUtils.fill_vertex_group_gaps()
                component_obj.select_set(False)

            component.remap_key_name = component_obj.name
            component_obj_list.append(component_obj)
            drawib_merged_object.append(component_obj)

            used_vg_indices = set()
            for vertex in component_obj.data.vertices:
                for group in vertex.groups:
                    if group.weight > 0.0:
                        used_vg_indices.add(group.group)
            self.component_real_vg_count_dict[component_index] = len(used_vg_indices)

            drawib_vertex_count += component.vertex_count
            drawib_index_count += component.index_count

        self.export_blendremap_forward_and_reverse(component_obj_list)

        if drawib_merged_object:
            bpy.ops.object.select_all(action='DESELECT')
            active_object = drawib_merged_object[0]
            active_object.select_set(True)
            bpy.context.view_layer.objects.active = active_object

        ObjUtils.join_objects(bpy.context, drawib_merged_object)
        merged_obj = drawib_merged_object[0]
        ObjUtils.rename_object(merged_obj, "TEMP_EXPORT_OBJECT")

        if GlobalProperties.export_add_missing_vertex_groups():
            ObjUtils.select_obj(merged_obj)
            VertexGroupUtils.merge_vertex_groups_with_same_number_v2()
            merged_obj.select_set(False)

        ObjUtils.deselect_all_objects()
        ObjUtils.select_object(merged_obj)
        ObjUtils.set_active_object(bpy.context, merged_obj)

        mesh = ObjUtils.get_mesh_evaluate_from_obj(merged_obj)
        merged_object = MergedObject(
            object=merged_obj,
            mesh=mesh,
            components=components,
            vertex_count=len(merged_obj.data.vertices),
            index_count=len(merged_obj.data.polygons) * 3,
            vg_count=len(ObjUtils.get_vertex_groups(merged_obj)),
            shapekeys=MergedObjectShapeKeys(),
        )

        if drawib_vertex_count != merged_object.vertex_count:
            raise ValueError("vertex_count mismatch between merged object and its components")

        if drawib_index_count != merged_object.index_count:
            raise ValueError("index_count mismatch between merged object and its components")

        LOG.newline()
        return merged_object

    def export_blendremap_forward_and_reverse(self, component_objects: list[bpy.types.Object]):
        num_vgs = self.d3d11_game_type.get_blendindices_count_wwmi()

        blend_remap_forward: numpy.ndarray = numpy.empty(0, dtype=numpy.uint16)
        blend_remap_reverse: numpy.ndarray = numpy.empty(0, dtype=numpy.uint16)
        remap_maps: dict[str, BlendRemapEntry] = {}
        remap_used: dict[str, bool] = {}

        for component_obj in component_objects:
            used_vg_set: set[int] = set()

            for vertex in component_obj.data.vertices:
                groups = [(group.group, group.weight) for group in vertex.groups]
                if len(groups) == 0:
                    continue

                groups.sort(key=lambda item: item[1], reverse=True)
                for group_index, weight in groups[:num_vgs]:
                    if weight > 0:
                        used_vg_set.add(int(group_index))

            max_used = max(used_vg_set) if len(used_vg_set) else 0
            if len(used_vg_set) == 0 or max_used < 256:
                remap_maps[component_obj.name] = {"forward": [], "reverse": {}}
                remap_used[component_obj.name] = False
                continue

            self.blend_remap = True

            obj_vg_ids = numpy.array(sorted(used_vg_set), dtype=numpy.uint16)
            forward = numpy.zeros(512, dtype=numpy.uint16)
            forward[:len(obj_vg_ids)] = obj_vg_ids

            reverse = numpy.zeros(512, dtype=numpy.uint16)
            reverse[obj_vg_ids] = numpy.arange(len(obj_vg_ids), dtype=numpy.uint16)

            blend_remap_forward = numpy.concatenate((blend_remap_forward, forward), axis=0)
            blend_remap_reverse = numpy.concatenate((blend_remap_reverse, reverse), axis=0)

            forward_list = [int(value) for value in obj_vg_ids.tolist()]
            reverse_map: dict[int, int] = {int(value): int(index) for index, value in enumerate(forward_list)}
            remap_maps[component_obj.name] = {"forward": forward_list, "reverse": reverse_map}
            remap_used[component_obj.name] = True

        self.blend_remap_maps = remap_maps
        self.blend_remap_used = remap_used
        self.blend_remap_forward_buffer = blend_remap_forward
        self.blend_remap_reverse_buffer = blend_remap_reverse

    def replace_remapped_blendindices(self, element_context: ObjElementContext):
        if not hasattr(self, "blend_remap_maps") or not self.blend_remap_maps:
            return

        mesh = element_context.mesh
        loops_len = len(mesh.loops)

        loop_to_poly = numpy.empty(loops_len, dtype=numpy.int32)
        for poly in mesh.polygons:
            start = poly.loop_start
            end = start + poly.loop_total
            loop_to_poly[start:end] = poly.index

        arr: numpy.ndarray | None = None
        if "BLENDINDICES" in getattr(element_context, "original_elementname_data_dict", {}):
            arr = element_context.original_elementname_data_dict["BLENDINDICES"].copy()
        elif element_context.element_vertex_ndarray is not None and "BLENDINDICES" in element_context.element_vertex_ndarray.dtype.names:
            arr = element_context.element_vertex_ndarray["BLENDINDICES"].copy()

        if arr is None:
            return

        poly_count = len(mesh.polygons)
        polygon_to_objname: list[str | None] = [None] * poly_count

        for component in self.merged_object.components:
            component_remap_key_name = getattr(component, "remap_key_name", None)
            for temp_obj in component.objects:
                if not hasattr(temp_obj, "index_offset") or not hasattr(temp_obj, "index_count"):
                    continue
                poly_start = int(temp_obj.index_offset // 3)
                poly_end = poly_start + int(temp_obj.index_count // 3)
                for poly_index in range(poly_start, poly_end):
                    if 0 <= poly_index < poly_count:
                        polygon_to_objname[poly_index] = component_remap_key_name or temp_obj.name

        width = 1 if getattr(arr, "ndim", 1) == 1 else arr.shape[1]

        for loop_index in range(loops_len):
            poly_idx = int(loop_to_poly[loop_index])
            component_obj_name = polygon_to_objname[poly_idx] if 0 <= poly_idx < len(polygon_to_objname) else None
            if not component_obj_name:
                continue
            remap_entry = self.blend_remap_maps.get(component_obj_name)
            if not remap_entry:
                continue
            reverse_map = remap_entry.get("reverse", {})

            if width == 1:
                original_value = int(arr[loop_index])
                arr[loop_index] = reverse_map.get(original_value, original_value)
            else:
                for value_index in range(width):
                    original_value = int(arr[loop_index, value_index])
                    arr[loop_index, value_index] = reverse_map.get(original_value, original_value)

        element_context.final_elementname_data_dict["BLENDINDICES"] = arr

    @property
    def part_name_submesh_dict(self) -> dict:
        mapping = {}
        for submesh_model in self.submesh_model_list:
            mapping[submesh_model.submesh_name] = submesh_model
        return mapping

    def get_submesh_part_name(self, submesh_model):
        return submesh_model.submesh_name

    def get_submesh_texture_markup_info_list(self, submesh_model):
        return self.submesh_texturemarkinfolist_dict.get(submesh_model.submesh_name, [])

    def apply_drawib_alias(self):
        """从工作空间读取并应用当前 DrawIB 的别名（WWMI 版）。"""
        alias_name = SSMTWorkSpace.get_drawib_aliasname_dict().get(self.draw_ib, "").strip()
        if alias_name:
            self.draw_ib_alias = alias_name

    @staticmethod
    def get_safe_shapekey_name(shapekey_name: str) -> str:
        return re.sub(r"[^0-9A-Za-z_.-]+", "_", shapekey_name).strip("._") or "ShapeKey"
