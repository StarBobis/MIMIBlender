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
    # This attribute must be filled in at initialization
    drawcall_model_list:list[DrawCallModel] = field(default_factory=list)

    # These attributes are computed in post_init
    match_draw_ib:str = field(init=False, default="")
    match_first_index:int = field(init=False, default=-1)
    match_index_count:int = field(init=False, default=-1)
    match_cs:str = field(init=False, default="")
    match_uav_bytes:int = field(init=False, default=0)
    submesh_name:str = field(init=False, default="")

    # These attributes result from merging the objs and computing ib and vb
    vertex_count:int = field(init=False, default=0)
    index_count:int = field(init=False, default=0)

    # Pick the data type directory from the workspace's Import.json, then take d3d11GameType from the matching SubmeshJson
    d3d11_game_type:D3D11GameType = field(init=False,repr=False,default=None)

    # Used for file name generation (after aliases are applied).
    # Defaults to submesh_name; when the user sets an alias on the Custom Submesh Name node,
    # DrawIBModel.apply_alias_dict() updates it to "{lod_prefix}.{alias}" before export.
    display_str:str = field(init=False, default="")

    ib:list = field(init=False,repr=False,default_factory=list)
    category_buffer_dict:dict = field(init=False,repr=False,default_factory=dict)
    index_vertex_id_dict:dict = field(init=False,repr=False,default_factory=dict)
    shape_key_buffer_dict:dict = field(init=False,repr=False,default_factory=dict)
    ntemi_bone_palette:list = field(init=False,repr=False,default_factory=list)

    def get_slot_texture_node_list(self) -> list[tuple]:
        """Aggregate the slot texture nodes of all DrawCallModels under this SubMesh.

        Each returned element is a (slot_item, texture_node) pair, where slot_item is
        an SSMTTextureSlotItem reference whose effective_slot_key yields the generated key name.
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

        # Every DrawCallModel in the list shares the same draw_ib, first_index and index_count, so just take the first one
        if len(self.drawcall_model_list) > 0:
            first_model = self.drawcall_model_list[0]
            self.match_draw_ib = first_model.match_draw_ib
            # In the new format match_index_count can be an empty string -> set 0 first; WorkSpaceModel corrects it later
            try:
                self.match_first_index = int(first_model.match_first_index) if first_model.match_first_index else -1
            except (ValueError, TypeError):
                self.match_first_index = -1
            try:
                self.match_index_count = int(first_model.match_index_count) if first_model.match_index_count else -1
            except (ValueError, TypeError):
                self.match_index_count = -1
            self.submesh_name = first_model.get_submesh_name()
        
        # display_str defaults to submesh_name; apply_alias_dict can override it before export
        self.display_str = self.submesh_name
        
        self.calc_buffer()

    def fix_indices_from_workspace(self, workspace_model):
        '''
        Fix match_index_count and match_first_index using WorkSpaceModel for
        new-format names (submesh_name like "LOD0.94517393-0"), where values
        start at -1 and are parsed from WorkSpaceModel's legacy folder name.
        Old-format names already carry correct values, so never overwritten.
        '''
        from ..workspace.ssmt_workspace import WorkSpaceModel

        # If match_index_count is already >= 0, this is an old-format name that needs no fix
        if self.match_index_count >= 0 and self.match_first_index >= 0:
            return

        if not self.submesh_name or not self.match_draw_ib:
            return

        # Try to parse submesh_name
        parsed = workspace_model.parse_new_format_name(self.submesh_name)
        if parsed is None:
            return

        # Get the true values from WorkSpaceModel
        _, ic, fi = workspace_model.resolve_component_info(
            parsed["lod"], parsed["draw_ib"], parsed["component"]
        )
        if ic > 0 or fi >= 0:
            self.match_index_count = ic
            self.match_first_index = fi

    def calc_buffer(self):
        # Process each obj through its own temporary object so the original ones stay untouched

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
            # Fetch the original obj
            source_obj = ObjUtils.get_obj_by_name(draw_call_model.obj_name)

            temp_collection = CollectionUtils.create_new_collection("TEMP_SUBMESH_COLLECTION_" + self.submesh_name)
            bpy.context.scene.collection.children.link(temp_collection)
            temp_collection_list.append(temp_collection)


            # Create a new obj
            temp_obj = ObjUtils.copy_object(
                context=bpy.context,
                obj=source_obj,
                name=source_obj.name + "_temp",
                collection= temp_collection
            )
            ShapeKeyUtils.reset_all_shapekey_values(temp_obj)

            self._normalize_temp_obj_for_export(temp_obj)

            # Import flipped the object per LogicName, so flipping the temp object back at export restores the game's original coordinate system
            self._apply_export_rotation_for_logic(temp_obj)

            # Triangulate the obj
            ObjUtils.triangulate_object(bpy.context, temp_obj)

            # Compute the extra attributes; the loop holds references, so modifying them in place is enough
            draw_call_model.vertex_count = len(temp_obj.data.vertices)
            # After triangulation each face has exactly 3 indices, so *3 is safe
            # This is why the triangulation step above is mandatory, otherwise errors are likely
            draw_call_model.index_count = len(temp_obj.data.polygons) * 3
            draw_call_model.index_offset = index_offset

            index_offset += draw_call_model.index_count

            # Accumulate here so the values can be reused directly
            # if everything is merged up to the DrawIB level later
            self.vertex_count += draw_call_model.vertex_count
            self.index_count += draw_call_model.index_count

            # Collect the temp objects in the list for the merge that follows
            submesh_temp_obj_list.append(temp_obj)

        # Merge the objs next; merging cuts the number of IB and VB computations, saving much time on batch exports
        # Make sure the first one is selected, otherwise join_objects will fail
        if submesh_temp_obj_list:
            # Deselect all objects
            bpy.ops.object.select_all(action='DESELECT')

            # Select the first object and set it as the active object
            target_active = submesh_temp_obj_list[0]
            target_active.select_set(True)
            bpy.context.view_layer.objects.active = target_active

        # Merge the objects
        ObjUtils.join_objects(bpy.context, submesh_temp_obj_list)
        
        # The merge lands on the first obj, so grab that obj directly
        submesh_merged_obj = submesh_temp_obj_list[0]

        # Rename it to the expected name for the steps that follow
        merged_obj_name = "TEMP_SUBMESH_MERGED_" + self.submesh_name
        ObjUtils.rename_object(submesh_merged_obj, merged_obj_name)

        # Check and verify that no attributes are missing
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

        # 4. Once the computation is done, delete the temporary obj
        bpy.data.objects.remove(submesh_merged_obj, do_unlink=True)

        # Also delete the temporary collections created earlier
        for temp_collection in temp_collection_list:
            if temp_collection.name in bpy.data.collections:
                if temp_collection.name in bpy.context.scene.collection.children:
                    bpy.context.scene.collection.children.unlink(temp_collection)
                bpy.data.collections.remove(temp_collection)

        print("SubMeshModel: " + self.submesh_name + " computation finished, temp objects deleted")

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
