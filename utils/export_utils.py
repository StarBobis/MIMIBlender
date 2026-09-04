import bpy
import numpy

from dataclasses import dataclass, field
from typing import Optional

from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from .obj_utils import ObjUtils
from .shapekey_utils import ShapeKeyUtils
from .timer_utils import TimerUtils

from ..common.d3d11_gametype import D3D11GameType
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..common.obj_buffer_helper import ObjBufferHelper


@dataclass
class ObjElementContext:
    obj: bpy.types.Object
    mesh: bpy.types.Mesh
    d3d11_game_type: D3D11GameType
    obj_name: str
    total_structured_dtype: numpy.dtype
    original_elementname_data_dict: dict = field(default_factory=dict)
    final_elementname_data_dict: dict = field(default_factory=dict)
    element_vertex_ndarray: Optional[numpy.ndarray] = field(default=None, repr=False)


@dataclass
class UnityBufferBuildResult:
    obj_name: str
    dtype: numpy.dtype
    element_vertex_ndarray: numpy.ndarray = field(repr=False)
    ib: list = field(default_factory=list)
    category_buffer_dict: dict = field(default_factory=dict, repr=False)
    index_loop_id_dict: Optional[dict] = field(default=None, repr=False)
    shape_key_buffer_dict: dict = field(default_factory=dict, repr=False)


@dataclass
class ShapeKeyBufferBuildResult:
    name: str
    element_vertex_ndarray: numpy.ndarray = field(repr=False)


@dataclass
class WWMIBufferBuildResult:
    obj: bpy.types.Object = field(repr=False)
    mesh: bpy.types.Mesh = field(repr=False)
    d3d11_game_type: D3D11GameType = field(repr=False)
    obj_name: str
    dtype: numpy.dtype
    element_vertex_ndarray: numpy.ndarray = field(repr=False)
    ib: list = field(default_factory=list)
    category_buffer_dict: dict = field(default_factory=dict, repr=False)
    index_vertex_id_dict: Optional[dict] = field(default=None, repr=False)
    shapekey_offsets: list = field(default_factory=list, repr=False)
    shapekey_vertex_ids: list = field(default_factory=list, repr=False)
    shapekey_vertex_offsets: list = field(default_factory=list, repr=False)
    export_shapekey: bool = False
    unique_element_vertex_ndarray: Optional[numpy.ndarray] = field(default=None, repr=False)
    unique_first_loop_indices: Optional[numpy.ndarray] = field(default=None, repr=False)
    shapekey_position_buffer_dict: dict = field(default_factory=dict, repr=False)
    shapekey_vector_buffer_dict: dict = field(default_factory=dict, repr=False)


class ExportUtils:
    @staticmethod
    def build_obj_element_context(
        d3d11_game_type: D3D11GameType,
        obj: Optional[bpy.types.Object] = None,
        obj_name: str = "",
        final_elementname_data_dict: Optional[dict] = None,
    ) -> ObjElementContext:
        resolved_obj = obj or ObjUtils.get_obj_by_name(name=obj_name)

        ShapeKeyUtils.reset_all_shapekey_values(resolved_obj)

        mesh = ObjUtils.get_mesh_evaluate_from_obj(obj=resolved_obj)
        if len(mesh.polygons) > 0:
            try:
                mesh.calc_tangents()
            except RuntimeError:
                ObjUtils.mesh_triangulate(mesh)
                mesh.calc_tangents()

        original_elementname_data_dict = ObjBufferHelper.parse_elementname_data_dict(
            mesh=mesh,
            d3d11_game_type=d3d11_game_type,
        )

        return ObjElementContext(
            obj=resolved_obj,
            mesh=mesh,
            d3d11_game_type=d3d11_game_type,
            obj_name=resolved_obj.name,
            total_structured_dtype=d3d11_game_type.get_total_structured_dtype(),
            original_elementname_data_dict=original_elementname_data_dict,
            final_elementname_data_dict=final_elementname_data_dict or {},
        )

    @staticmethod
    def pack_element_vertex_ndarray(
        d3d11_game_type: D3D11GameType,
        mesh: bpy.types.Mesh,
        original_elementname_data_dict: dict,
        final_elementname_data_dict: Optional[dict] = None,
    ) -> numpy.ndarray:
        return ObjBufferHelper.convert_to_element_vertex_ndarray(
            d3d11_game_type=d3d11_game_type,
            mesh=mesh,
            original_elementname_data_dict=original_elementname_data_dict,
            final_elementname_data_dict=final_elementname_data_dict or {},
        )

    @staticmethod
    def build_unity_obj_buffer_result(
        obj: bpy.types.Object,
        d3d11_game_type: D3D11GameType,
    ) -> UnityBufferBuildResult:
        ObjBufferHelper.check_and_verify_attributes(obj=obj, d3d11_game_type=d3d11_game_type)

        element_context = ExportUtils.build_obj_element_context(
            d3d11_game_type=d3d11_game_type,
            obj=obj,
        )
        element_vertex_ndarray = ExportUtils.pack_element_vertex_ndarray(
            d3d11_game_type=d3d11_game_type,
            mesh=element_context.mesh,
            original_elementname_data_dict=element_context.original_elementname_data_dict,
            final_elementname_data_dict=element_context.final_elementname_data_dict,
        )

        ib, category_buffer_dict, index_loop_id_dict = ExportUtils.build_unity_index_buffers(
            obj=obj,
            mesh=element_context.mesh,
            element_vertex_ndarray=element_vertex_ndarray,
            d3d11_game_type=d3d11_game_type,
            dtype=element_context.total_structured_dtype,
        )
        shape_key_buffer_dict = ExportUtils.build_unity_shape_key_buffer_dict(
            obj=obj,
            d3d11_game_type=d3d11_game_type,
            dtype=element_context.total_structured_dtype,
            index_loop_id_dict=index_loop_id_dict,
        )

        return UnityBufferBuildResult(
            obj_name=element_context.obj_name,
            dtype=element_context.total_structured_dtype,
            element_vertex_ndarray=element_vertex_ndarray,
            ib=ib,
            category_buffer_dict=category_buffer_dict,
            index_loop_id_dict=index_loop_id_dict,
            shape_key_buffer_dict=shape_key_buffer_dict,
        )

    @staticmethod
    def build_unity_index_buffers(
        obj: bpy.types.Object,
        mesh: bpy.types.Mesh,
        element_vertex_ndarray: numpy.ndarray,
        d3d11_game_type: D3D11GameType,
        dtype: numpy.dtype,
    ):
        if (
            GlobalConfig.logic_name == LogicName.GF2
            and "TANGENT" in d3d11_game_type.OrderedFullElementList
        ):
            return ObjBufferHelper.calc_index_vertex_buffer_girlsfrontline2(
                mesh=mesh,
                element_vertex_ndarray=element_vertex_ndarray,
                d3d11_game_type=d3d11_game_type,
                dtype=dtype,
            )

        return ObjBufferHelper.calc_index_vertex_buffer_unified(
            mesh=mesh,
            element_vertex_ndarray=element_vertex_ndarray,
            d3d11_game_type=d3d11_game_type,
            dtype=dtype,
            obj=obj,
        )

    @staticmethod
    def build_unity_shape_key_buffer_dict(
        obj: bpy.types.Object,
        d3d11_game_type: D3D11GameType,
        dtype: numpy.dtype,
        index_loop_id_dict: Optional[dict],
    ) -> dict:
        shape_key_buffer_dict = {}

        shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
        if len(shapekeyname_mkey_dict.keys()) == 0:
            return shape_key_buffer_dict

        if not obj.data.shape_keys or not obj.data.shape_keys.key_blocks:
            return shape_key_buffer_dict

        shapekey_names = list(shapekeyname_mkey_dict.keys())
        shape_keys = [
            sk for sk in obj.data.shape_keys.key_blocks if sk.name in shapekey_names
        ]
        if not shape_keys:
            return shape_key_buffer_dict

        TimerUtils.Start(f"Processing {len(shape_keys)} ShapeKeys for {obj.name}")
        try:
            if index_loop_id_dict is not None:
                target_count = len(index_loop_id_dict)
                indices_map = numpy.zeros(target_count, dtype=int)
                indices_map[:] = list(index_loop_id_dict.values())
            else:
                target_count = len(obj.data.vertices)
                indices_map = numpy.arange(target_count, dtype=int)

            base_shape_vertex_ndarray = numpy.zeros(target_count, dtype=dtype)

            for shapekey in shape_keys:
                shapekey_name = shapekey.name
                ShapeKeyUtils.reset_shapekey_values(
                    obj,
                    configured_shapekey_names=shapekey_names,
                    current_shapekey_name=shapekey_name,
                )
                shapekey.value = 1.0

                mesh_eval = ObjUtils.get_mesh_evaluate_from_obj(obj=obj)
                mesh_eval.calc_tangents()

                shape_key_buffer_dict[shapekey_name] = ExportUtils.build_shape_key_buffer_result(
                    name=shapekey_name,
                    base_element_vertex_ndarray=base_shape_vertex_ndarray,
                    mesh=mesh_eval,
                    indices_map=indices_map,
                    d3d11_game_type=d3d11_game_type,
                )
        finally:
            ShapeKeyUtils.reset_all_shapekey_values(obj)
            TimerUtils.End(f"Processing {len(shape_keys)} ShapeKeys for {obj.name}")

        return shape_key_buffer_dict

    @staticmethod
    def build_shape_key_buffer_result(
        name: str,
        base_element_vertex_ndarray: numpy.ndarray,
        indices_map: numpy.ndarray,
        d3d11_game_type: D3D11GameType,
        mesh: Optional[bpy.types.Mesh] = None,
    ) -> ShapeKeyBufferBuildResult:
        element_vertex_ndarray = base_element_vertex_ndarray.copy()

        if mesh is None:
            return ShapeKeyBufferBuildResult(
                name=name,
                element_vertex_ndarray=element_vertex_ndarray,
            )

        loop_indices = indices_map
        loop_vertex_indices = None
        target_category = "Position"

        for d3d11_element in d3d11_game_type.D3D11ElementList:
            if d3d11_element.Category != target_category:
                continue

            elem_name = d3d11_element.ElementName
            data = None

            if elem_name == "POSITION":
                if loop_vertex_indices is None:
                    all_loop_vertex_indices = numpy.empty(len(mesh.loops), dtype=int)
                    mesh.loops.foreach_get("vertex_index", all_loop_vertex_indices)
                    loop_vertex_indices = all_loop_vertex_indices[loop_indices]

                data = ObjBufferHelper._parse_position(
                    mesh_vertices=mesh.vertices,
                    mesh_vertices_length=len(mesh.vertices),
                    loop_vertex_indices=loop_vertex_indices,
                    d3d11_element=d3d11_element,
                )

            elif elem_name == "NORMAL":
                all_normals = ObjBufferHelper._parse_normal(
                    mesh_loops=mesh.loops,
                    mesh_loops_length=len(mesh.loops),
                    d3d11_element=d3d11_element,
                )
                data = all_normals[loop_indices]

            elif elem_name == "TANGENT":
                all_tangents = ObjBufferHelper._parse_tangent(
                    mesh_loops=mesh.loops,
                    mesh_loops_length=len(mesh.loops),
                    d3d11_element=d3d11_element,
                )
                data = all_tangents[loop_indices]

            elif elem_name.startswith("BINORMAL"):
                all_binormals = ObjBufferHelper._parse_binormal(
                    mesh_loops=mesh.loops,
                    mesh_loops_length=len(mesh.loops),
                    d3d11_element=d3d11_element,
                )
                data = all_binormals[loop_indices]

            if data is not None:
                element_vertex_ndarray[elem_name] = data

        return ShapeKeyBufferBuildResult(
            name=name,
            element_vertex_ndarray=element_vertex_ndarray,
        )

    @staticmethod
    def build_wwmi_index_buffers(
        mesh: bpy.types.Mesh,
        element_vertex_ndarray: numpy.ndarray,
        dtype: numpy.dtype,
        d3d11_game_type: D3D11GameType,
    ):
        return ObjBufferHelper.calc_index_vertex_buffer_wwmi_v2(
            mesh=mesh,
            element_vertex_ndarray=element_vertex_ndarray,
            dtype=dtype,
            d3d11_game_type=d3d11_game_type,
        )

    @staticmethod
    def build_wwmi_shapekey_payload(obj: bpy.types.Object, index_vertex_id_dict: dict):
        if obj.data.shape_keys is None or len(getattr(obj.data.shape_keys, "key_blocks", [])) == 0:
            return [], [], [], False

        shapekey_offsets, shapekey_vertex_ids, shapekey_vertex_offsets = ShapeKeyUtils.extract_shapekey_data(
            merged_obj=obj,
            index_vertex_id_dict=index_vertex_id_dict,
        )
        return shapekey_offsets, shapekey_vertex_ids, shapekey_vertex_offsets, True

    @staticmethod
    def build_wwmi_shape_key_category_buffer_dict(
        obj: bpy.types.Object,
        unique_first_loop_indices: numpy.ndarray,
        d3d11_game_type: D3D11GameType,
    ) -> dict:
        shape_key_category_buffer_dict = {}
        shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
        if len(shapekeyname_mkey_dict.keys()) == 0:
            return shape_key_category_buffer_dict

        if obj.data.shape_keys is None or not getattr(obj.data.shape_keys, "key_blocks", None):
            return shape_key_category_buffer_dict

        shapekey_names = list(shapekeyname_mkey_dict.keys())
        shape_keys = [
            shapekey for shapekey in obj.data.shape_keys.key_blocks
            if shapekey.name in shapekey_names
        ]
        if not shape_keys:
            return shape_key_category_buffer_dict

        try:
            for shapekey in shape_keys:
                ShapeKeyUtils.reset_shapekey_values(
                    obj,
                    configured_shapekey_names=shapekey_names,
                    current_shapekey_name=shapekey.name,
                )
                shapekey.value = 1.0

                mesh_eval = ObjUtils.get_mesh_evaluate_from_obj(obj=obj)
                if len(mesh_eval.polygons) > 0:
                    try:
                        mesh_eval.calc_tangents()
                    except RuntimeError:
                        ObjUtils.mesh_triangulate(mesh_eval)
                        mesh_eval.calc_tangents()

                element_data = ObjBufferHelper.parse_elementname_data_dict(
                    mesh=mesh_eval,
                    d3d11_game_type=d3d11_game_type,
                )
                shape_key_category_buffer_dict[shapekey.name] = {
                    "Position": element_data["POSITION"][unique_first_loop_indices].astype(numpy.float32).reshape(-1),
                }

                vector_parts = []
                for element_name in ("TANGENT", "NORMAL"):
                    if element_name in element_data:
                        vector_parts.append(element_data[element_name][unique_first_loop_indices])
                if vector_parts:
                    shape_key_category_buffer_dict[shapekey.name]["Vector"] = numpy.concatenate(vector_parts, axis=1).reshape(-1)
        finally:
            ShapeKeyUtils.reset_all_shapekey_values(obj)

        return shape_key_category_buffer_dict

    @staticmethod
    def build_wwmi_obj_buffer_result(element_context: ObjElementContext) -> WWMIBufferBuildResult:
        element_vertex_ndarray = element_context.element_vertex_ndarray
        if element_vertex_ndarray is None:
            element_vertex_ndarray = ExportUtils.pack_element_vertex_ndarray(
                d3d11_game_type=element_context.d3d11_game_type,
                mesh=element_context.mesh,
                original_elementname_data_dict=element_context.original_elementname_data_dict,
                final_elementname_data_dict=element_context.final_elementname_data_dict,
            )

        ib, category_buffer_dict, index_vertex_id_dict, unique_element_vertex_ndarray, unique_first_loop_indices = ExportUtils.build_wwmi_index_buffers(
            mesh=element_context.mesh,
            element_vertex_ndarray=element_vertex_ndarray,
            dtype=element_context.total_structured_dtype,
            d3d11_game_type=element_context.d3d11_game_type,
        )
        shapekey_offsets, shapekey_vertex_ids, shapekey_vertex_offsets, export_shapekey = ExportUtils.build_wwmi_shapekey_payload(
            obj=element_context.obj,
            index_vertex_id_dict=index_vertex_id_dict,
        )
        shapekey_category_buffer_dict = ExportUtils.build_wwmi_shape_key_category_buffer_dict(
            obj=element_context.obj,
            unique_first_loop_indices=unique_first_loop_indices,
            d3d11_game_type=element_context.d3d11_game_type,
        )

        return WWMIBufferBuildResult(
            obj=element_context.obj,
            mesh=element_context.mesh,
            d3d11_game_type=element_context.d3d11_game_type,
            obj_name=element_context.obj_name,
            dtype=element_context.total_structured_dtype,
            element_vertex_ndarray=element_vertex_ndarray,
            ib=ib,
            category_buffer_dict=category_buffer_dict,
            index_vertex_id_dict=index_vertex_id_dict,
            shapekey_offsets=shapekey_offsets,
            shapekey_vertex_ids=shapekey_vertex_ids,
            shapekey_vertex_offsets=shapekey_vertex_offsets,
            export_shapekey=export_shapekey,
            unique_element_vertex_ndarray=unique_element_vertex_ndarray,
            unique_first_loop_indices=unique_first_loop_indices,
            shapekey_position_buffer_dict={
                name: category_buffers["Position"]
                for name, category_buffers in shapekey_category_buffer_dict.items()
                if "Position" in category_buffers
            },
            shapekey_vector_buffer_dict={
                name: category_buffers["Vector"]
                for name, category_buffers in shapekey_category_buffer_dict.items()
                if "Vector" in category_buffers
            },
        )
