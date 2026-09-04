
from dataclasses import field, dataclass
import os

from ..common.d3d11_gametype import D3D11GameType
from ..common.global_config import GlobalConfig

from ..utils.json_utils import JsonUtils
from ..workspace.texture_metadata_helper import TextureMetadataResolver
from ..workspace.submesh_json import SubmeshJson
from ..workspace.ssmt_workspace import SSMTWorkSpace
from ..common.buffer_export_helper import BufferExportHelper

import numpy

from .submesh_model import SubMeshModel

@dataclass
class DrawIBModel:
    '''
    - DrawIBModel是一个更高层次的模型，包含一个或多个SubMeshModel
    - 适用于米游、Unity等需要将多个SubMesh组合成一个DrawIB进行导出的游戏
    - 要使用DrawIBModle，必须确保每个SubMesh的数据类型是相同的，才能组合在一起
    '''
    submesh_model_list:list[SubMeshModel]
    combine_ib:bool = True

    draw_ib:str = field(init=False, default="")
    draw_ib_alias:str = field(init=False, default="")

    vertex_count:int = field(init=False, default=0)
    index_count:int = field(init=False, default=0)

    # 这里的d3d11_game_type有一个隐含条件
    # DrawIBModel一旦创建，就默认它里面的每个SubmeshModel的d3d11_game_type都是一样的
    # 否则不可能通过组合buffer数据来正确导出
    # 所以这里的d3d11_game_type可以直接取submesh_model_list中第一个SubMeshModel的d3d11_game_type
    d3d11_game_type:D3D11GameType = field(init=False,repr=False,default=None)

    import_json_path:str = field(init=False,repr=False,default="")
    import_json_dict:dict = field(init=False,repr=False,default_factory=dict)
    category_hash_dict:dict = field(init=False,repr=False,default_factory=dict)
    submesh_texturemarkinfolist_dict:dict = field(init=False,repr=False,default_factory=dict)
    vertex_limit_hash:str = field(init=False,repr=False,default="")
    cs_output_vertex_limit_hash:str = field(init=False,repr=False,default="")
    original_vertex_count:int = field(init=False,repr=False,default=0)

    ib:list = field(init=False,repr=False,default_factory=list)
    submesh_ib_dict:dict = field(init=False,repr=False,default_factory=dict)
    category_buffer_dict:dict = field(init=False,repr=False,default_factory=dict)
    index_vertex_id_dict:dict = field(init=False,repr=False,default_factory=dict)
    obj_name_draw_offset:dict = field(init=False,repr=False,default_factory=dict)
    shapekey_name_bytelist_dict:dict = field(init=False,repr=False,default_factory=dict)


    def __post_init__(self):
        # 因为初始化时传入的SubMeshModel列表中的每个SubMeshModel的match_draw_ib都是一样的，所以直接取第一个就行了
        self.draw_ib = self.submesh_model_list[0].match_draw_ib if len(self.submesh_model_list) > 0 else ""
        self.draw_ib_alias = self.draw_ib
        self.d3d11_game_type = self.submesh_model_list[0].d3d11_game_type if len(self.submesh_model_list) > 0 else None
        self._load_import_metadata_from_first_submesh()

        category_buffer_dict, submesh_vertex_base_dict, index_vertex_id_dict, vertex_count = self._assemble_category_buffers()

        self.vertex_count = vertex_count
        self.category_buffer_dict = category_buffer_dict
        self.index_vertex_id_dict = index_vertex_id_dict
        self.shapekey_name_bytelist_dict = self._assemble_shape_key_buffers()

        if self.combine_ib:
            total_ib, obj_name_draw_offset = self._assemble_combined_ib_and_draw_offset(submesh_vertex_base_dict)
            self.ib = total_ib
            self.submesh_ib_dict = {}
            self.obj_name_draw_offset = obj_name_draw_offset
            self.index_count = len(total_ib)
        else:
            submesh_ib_dict, obj_name_draw_offset, total_index_count = self._assemble_split_ib_and_draw_offset(submesh_vertex_base_dict)
            self.ib = []
            self.submesh_ib_dict = submesh_ib_dict
            self.obj_name_draw_offset = obj_name_draw_offset
            self.index_count = total_index_count

    def _load_import_metadata_from_first_submesh(self):
        if not self.submesh_model_list:
            print("DrawIBModel: submesh_model_list 为空，无法读取导入元数据")
            return

        first_submesh = self.submesh_model_list[0]
        folder_name = first_submesh.submesh_name
        print("DrawIBModel: 开始读取导出元数据，DrawIB: " + self.draw_ib + "，submesh_name: " + folder_name)

        submesh_json = SubmeshJson(SSMTWorkSpace.check_and_get_submesh_json_path(folder_name))
        self.import_json_path = submesh_json.JsonFilePath
        self.import_json_dict = dict(submesh_json.JsonDict)
        print("DrawIBModel: 已读取 SubmeshJson: " + self.import_json_path)

        if self.import_json_dict:
            self.category_hash_dict = dict(self.import_json_dict.get("CategoryHash", {}))
            self.submesh_texturemarkinfolist_dict = TextureMetadataResolver.load_submesh_texture_markup_info_from_all_submeshes(
                draw_ib_model=self,
            )
            self.vertex_limit_hash = self.import_json_dict.get("VertexLimitVB", "")
            self.cs_output_vertex_limit_hash = self.load_cs_output_vertex_limit_hash()
            self.original_vertex_count = self.import_json_dict.get("OriginalVertexCount", 0)
            print(
                "DrawIBModel: 已使用新结构元数据，贴图标记SubMesh数量: "
                + str(len(self.submesh_texturemarkinfolist_dict))
            )
            return

        print("DrawIBModel: 未读取到 SubmeshJson 元数据，贴图标记信息为空，DrawIB: " + self.draw_ib)

    def load_cs_output_vertex_limit_hash(self) -> str:
        for submesh_model in self.submesh_model_list:
            try:
                submesh_json = SubmeshJson(SSMTWorkSpace.check_and_get_submesh_json_path(submesh_model.submesh_name))
            except Exception as ex:
                print(
                    "DrawIBModel: failed to read CSOutputVertexLimitVB, Submesh: "
                    + submesh_model.submesh_name
                    + ", error: "
                    + str(ex)
                )
                continue

            cs_output_vertex_limit_hash = str(submesh_json.CSOutputVertexLimitVB or "").strip()
            if cs_output_vertex_limit_hash:
                return cs_output_vertex_limit_hash

        return ""

    def _assemble_category_buffers(self) -> tuple[dict, dict, dict, int]:
        total_category_buffer_chunks = {}
        total_index_vertex_id_dict = {}
        submesh_vertex_base_dict = {}
        vertex_offset = 0

        for submesh_model in self.submesh_model_list:
            submesh_vertex_base_dict[submesh_model.submesh_name] = vertex_offset

            for category, category_buf in submesh_model.category_buffer_dict.items():
                if category not in total_category_buffer_chunks:
                    total_category_buffer_chunks[category] = []
                total_category_buffer_chunks[category].append(category_buf)

            if submesh_model.index_vertex_id_dict:
                for local_index, vertex_id in submesh_model.index_vertex_id_dict.items():
                    total_index_vertex_id_dict[local_index + vertex_offset] = vertex_id

            vertex_offset += self._get_exported_vertex_count(submesh_model)

        total_category_buffer_dict = {
            category: numpy.concatenate(category_chunks)
            for category, category_chunks in total_category_buffer_chunks.items()
            if category_chunks
        }
        return total_category_buffer_dict, submesh_vertex_base_dict, total_index_vertex_id_dict, vertex_offset

    def _assemble_combined_ib_and_draw_offset(self, submesh_vertex_base_dict: dict) -> tuple[list, dict]:
        total_ib = []
        obj_name_draw_offset = {}
        submesh_index_offset = 0

        for submesh_model in self.submesh_model_list:
            vertex_base = submesh_vertex_base_dict.get(submesh_model.submesh_name, 0)
            total_ib.extend(index + vertex_base for index in submesh_model.ib)

            for draw_call_model in submesh_model.drawcall_model_list:
                obj_name_draw_offset[draw_call_model.obj_name] = submesh_index_offset + draw_call_model.index_offset

            submesh_index_offset += len(submesh_model.ib)

        return total_ib, obj_name_draw_offset

    def _assemble_split_ib_and_draw_offset(self, submesh_vertex_base_dict: dict) -> tuple[dict, dict, int]:
        submesh_ib_dict = {}
        obj_name_draw_offset = {}
        total_index_count = 0

        for submesh_model in self.submesh_model_list:
            vertex_base = submesh_vertex_base_dict.get(submesh_model.submesh_name, 0)
            remapped_ib = [index + vertex_base for index in submesh_model.ib]
            submesh_ib_dict[submesh_model.submesh_name] = remapped_ib
            total_index_count += len(remapped_ib)

            for draw_call_model in submesh_model.drawcall_model_list:
                obj_name_draw_offset[draw_call_model.obj_name] = draw_call_model.index_offset

        return submesh_ib_dict, obj_name_draw_offset, total_index_count

    def _assemble_shape_key_buffers(self) -> dict:
        if self.d3d11_game_type is None:
            return {}

        position_stride = self.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        if position_stride <= 0:
            return {}

        position_offset = self._get_category_byte_offset("Position")
        ordered_shapekey_names = []
        seen_shapekey_names = set()

        for submesh_model in self.submesh_model_list:
            for shapekey_name in submesh_model.shape_key_buffer_dict.keys():
                if shapekey_name in seen_shapekey_names:
                    continue
                seen_shapekey_names.add(shapekey_name)
                ordered_shapekey_names.append(shapekey_name)

        if not ordered_shapekey_names:
            return {}

        shapekey_chunks = {shapekey_name: [] for shapekey_name in ordered_shapekey_names}

        for submesh_model in self.submesh_model_list:
            base_position_buffer = submesh_model.category_buffer_dict.get("Position")

            for shapekey_name in ordered_shapekey_names:
                shape_key_buffer_result = submesh_model.shape_key_buffer_dict.get(shapekey_name)

                if shape_key_buffer_result is None:
                    if base_position_buffer is not None:
                        shapekey_chunks[shapekey_name].append(base_position_buffer)
                    continue

                position_bytes = self._extract_position_bytes_from_shape_key(
                    shape_key_buffer_result.element_vertex_ndarray,
                    position_offset,
                    position_stride,
                )
                shapekey_chunks[shapekey_name].append(position_bytes)

        return {
            shapekey_name: numpy.concatenate(chunks)
            for shapekey_name, chunks in shapekey_chunks.items()
            if chunks
        }

    def _get_category_byte_offset(self, target_category: str) -> int:
        byte_offset = 0

        for category_name in self.d3d11_game_type.OrderedCategoryNameList:
            if category_name == target_category:
                return byte_offset
            byte_offset += self.d3d11_game_type.CategoryStrideDict.get(category_name, 0)

        return byte_offset

    def _extract_position_bytes_from_shape_key(
        self,
        element_vertex_ndarray: numpy.ndarray,
        position_offset: int,
        position_stride: int,
    ) -> numpy.ndarray:
        if len(element_vertex_ndarray) == 0:
            return numpy.array([], dtype=numpy.uint8)

        full_byte_view = element_vertex_ndarray.view(numpy.uint8).reshape(len(element_vertex_ndarray), -1)
        return full_byte_view[:, position_offset:position_offset + position_stride].reshape(-1)

    def _get_exported_vertex_count(self, submesh_model: SubMeshModel) -> int:
        if submesh_model.index_vertex_id_dict:
            return len(submesh_model.index_vertex_id_dict)

        position_buffer = submesh_model.category_buffer_dict.get("Position")
        if position_buffer is None or self.d3d11_game_type is None:
            return 0

        position_stride = self.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        if position_stride <= 0:
            return 0

        return int(len(position_buffer) / position_stride)

    @property
    def draw_number(self) -> int:
        return self.vertex_count

    @property
    def d3d11GameType(self) -> D3D11GameType:
        return self.d3d11_game_type

    def get_submesh_part_name(self, submesh_model: SubMeshModel) -> str:
        return submesh_model.submesh_name

    def apply_drawib_alias(self):
        '''从工作空间读取并应用当前 DrawIB 的别名。'''
        alias_name = SSMTWorkSpace.get_drawib_aliasname_dict().get(self.draw_ib, "").strip()
        if alias_name:
            self.draw_ib_alias = alias_name

    def get_submesh_unique_key(self, submesh_model: SubMeshModel) -> str:
        return submesh_model.display_str.replace("-", "_")

    def get_submesh_ib_resource_name(self, submesh_model: SubMeshModel) -> str:
        unique_key = self.get_submesh_unique_key(submesh_model)
        if unique_key:
            return "Resource_" + unique_key + "_Index"

        part_name = self.get_submesh_part_name(submesh_model)
        if part_name is not None:
            return "Resource_" + self.draw_ib + "_Component" + part_name

        return ""

    def get_submesh_texture_override_suffix(self, submesh_model: SubMeshModel) -> str:
        unique_key = self.get_submesh_unique_key(submesh_model)
        if unique_key:
            return unique_key

        part_name = self.get_submesh_part_name(submesh_model)
        if part_name is not None:
            return "IB_" + self.draw_ib + "_" + self.draw_ib_alias + "_Component" + part_name

        return ""

    def get_submesh_texture_markup_info_list(self, submesh_model: SubMeshModel) -> list:
        return self.submesh_texturemarkinfolist_dict.get(submesh_model.submesh_name, [])

    def generate_buffer_files(self, output_folder: str):
        for submesh_model in self.submesh_model_list:
            ib = self.submesh_ib_dict.get(submesh_model.submesh_name, [])
            if ib:
                ib_filename = submesh_model.display_str + "-Index.buf"
                BufferExportHelper.write_buf_ib_r32_uint(ib, os.path.join(output_folder, ib_filename))

        for category, category_buf in self.category_buffer_dict.items():
            category_buf_filename = self.draw_ib + "-" + category + ".buf"
            filepath = os.path.join(output_folder, category_buf_filename)
            with open(filepath, 'wb') as f:
                category_buf.tofile(f)

        for shapekey_name, shapekey_buf in self.shapekey_name_bytelist_dict.items():
            shapekey_buf_filename = self.draw_ib + "-Position." + shapekey_name + ".buf"
            filepath = os.path.join(output_folder, shapekey_buf_filename)
            with open(filepath, 'wb') as f:
                shapekey_buf.tofile(f)

    @property
    def part_name_submesh_dict(self) -> dict:
        mapping = {}
        for submesh_model in self.submesh_model_list:
            mapping[submesh_model.submesh_name] = submesh_model
        return mapping

