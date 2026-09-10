import collections
import copy
import math
from .d3d11_gametype import D3D11GameType
from ..model.draw_call_model import DrawCallModel


from ..utils.format_utils import FormatUtils
from ..utils.vertexgroup_utils import VertexGroupUtils
from ..utils.timer_utils import TimerUtils
from ..utils.tbn_codec import TBNCodec
from ..utils.ssmt_error_utils import SSMTErrorUtils
from .d3d11_semantics import D3D11Semantic, D3D11Format
from .global_config import LogicName
from .global_config import GlobalConfig
from .global_properties import GlobalProperties
from .raw_vertex_attributes import (
    RAW_COLOR_ALPHA_ATTRIBUTE_PREFIX,
    RAW_NORMAL_W_ATTRIBUTE_PREFIX,
    RAW_TANGENT_ATTRIBUTE_PREFIX,
    load_raw_bytes,
)
from ..utils.obj_utils import ObjUtils
from ..utils.log_utils import LOG


import bpy
import numpy

class ObjBufferHelper:
    '''
    Helper class: since abstract data types are used,
    it is grouped under the Helper classes.
    '''

    @staticmethod
    def check_and_verify_attributes(obj:bpy.types.Object, d3d11_game_type:D3D11GameType):
        '''
        Validate and fill in missing elements
        COLOR
        TEXCOORD, TEXCOORD1, TEXCOORD2, TEXCOORD3
        '''
        for d3d11_element_name in d3d11_game_type.OrderedFullElementList:
            d3d11_element = d3d11_game_type.ElementNameD3D11ElementDict[d3d11_element_name]
            # Validate and fill in every missing COLOR
            if d3d11_element_name.startswith(D3D11Semantic.COLOR):
                color_coll = obj.data.color_attributes
                if d3d11_element_name not in color_coll:
                    obj.data.color_attributes.new(name=d3d11_element_name, type='BYTE_COLOR', domain='CORNER')
                    print("Current obj ["+ obj.name +"] is missing the game-rendering COLOR: ["+  D3D11Semantic.COLOR + "], already auto-completed")
            
            # Check whether the TEXCOORD exists
            if d3d11_element_name.startswith(D3D11Semantic.TEXCOORD):
                if d3d11_element_name + ".xy" not in obj.data.uv_layers:
                    # If there is only one UV at this point, rename it to TEXCOORD.xy
                    if len(obj.data.uv_layers) == 1 and d3d11_element_name == D3D11Semantic.TEXCOORD:
                            obj.data.uv_layers[0].name = d3d11_element_name + ".xy"
                    else:
                        # Otherwise, add a UV automatically so calc_tangents won't fail later
                        obj.data.uv_layers.new(name=d3d11_element_name + ".xy")
            
            # Check if BLENDINDICES exists
            if d3d11_element_name.startswith("BLENDINDICES"):
                if not obj.vertex_groups:
                    SSMTErrorUtils.raise_fatal("your object [" +obj.name + "] need at leat one valid Vertex Group, Please check if your model's Vertex Group is correct.")

    @staticmethod
    def get_ordered_obj_models_by_draw_ib(ordered_draw_obj_data_model_list:list[DrawCallModel], draw_ib:str):
        '''
        Return only the obj list that matches the given draw_ib
        This method exists to support the MergedObj used by Wuthering Waves
        It merely fetches the matching obj list by IB; nothing else needs computing, since WWMI calculates after merging.
        '''
        final_ordered_draw_obj_model_list:list[DrawCallModel] = []

        for obj_model in ordered_draw_obj_data_model_list:
            # Keep only the data of the given DrawIB
            if obj_model.match_draw_ib != draw_ib:
                continue

            final_ordered_draw_obj_model_list.append(copy.deepcopy(obj_model))

        return final_ordered_draw_obj_model_list


    @staticmethod
    def _parse_position(mesh_vertices, mesh_vertices_length, loop_vertex_indices, d3d11_element):
        vertex_coords = numpy.empty(mesh_vertices_length * 3, dtype=numpy.float32)
        # Follow WWMI-Tools: fetch the undeformed vertex coordinates and do
        # not apply mirroring or dtype conversion at extraction stage.
        # mesh_vertices.foreach_get('undeformed_co', vertex_coords)
        mesh_vertices.foreach_get('co', vertex_coords)
        positions = vertex_coords.reshape(-1, 3)[loop_vertex_indices]

        if d3d11_element.Format == 'R32G32B32A32_FLOAT':
            # If format expects 4 components, add a zero alpha column (float32)
            new_array = numpy.zeros((positions.shape[0], 4), dtype=numpy.float32)
            new_array[:, :3] = positions
            positions = new_array
        elif d3d11_element.Format == 'R16G16B16A16_FLOAT':
            # If format expects 4 components, add a W column (float16).
            # Expand the 3-component positions into the first 3 slots
            # and set the 4th (W) component to 1.0 (homogeneous coord).
            new_array = numpy.zeros((positions.shape[0], 4), dtype=numpy.float16)
            new_array[:, :3] = positions.astype(numpy.float16)
            new_array[:, 3] = numpy.ones(positions.shape[0], dtype=numpy.float16)
            positions = new_array
        return positions

    @staticmethod
    def _load_raw_point_element(mesh, prefix, d3d11_element, loop_vertex_indices):
        """Rebuild an imported element from its lossless point attributes."""
        raw_bytes = load_raw_bytes(mesh, prefix, d3d11_element.ByteWidth)
        scalar_type = FormatUtils.get_nptype_from_format(d3d11_element.Format)
        scalar_size = numpy.dtype(scalar_type).itemsize
        if raw_bytes is None or d3d11_element.ByteWidth % scalar_size:
            return None
        component_count = d3d11_element.ByteWidth // scalar_size
        values = raw_bytes.view(scalar_type).reshape(len(mesh.vertices), component_count)
        return values[loop_vertex_indices].copy()

    @staticmethod
    def _restore_raw_fourth_component(mesh, prefix, d3d11_element, loop_vertex_indices, data):
        """Restore a game-owned fourth component after Blender-derived parsing."""
        if data is None or data.ndim < 2 or data.shape[1] < 4:
            return data

        scalar_type = FormatUtils.get_nptype_from_format(d3d11_element.Format)
        scalar_size = numpy.dtype(scalar_type).itemsize
        if d3d11_element.ByteWidth != scalar_size * data.shape[1]:
            return data

        raw_bytes = load_raw_bytes(mesh, prefix, scalar_size)
        if raw_bytes is None:
            return data

        component = raw_bytes.view(scalar_type).reshape(len(mesh.vertices))[loop_vertex_indices]
        result = data.copy()
        result[:, 3] = component
        return result

    @staticmethod
    def _parse_normal(mesh_loops, mesh_loops_length, d3d11_element, has_encoded_data=False):
        # Fetch the normal data uniformly
        normals = numpy.empty(mesh_loops_length * 3, dtype=numpy.float32)
        mesh_loops.foreach_get('normal', normals)

        if d3d11_element.Format == 'R16G16B16A16_FLOAT':
            result = numpy.ones(mesh_loops_length * 4, dtype=numpy.float32)
            result[0::4] = normals[0::3]
            result[1::4] = normals[1::3]
            result[2::4] = normals[2::3]
            result = result.reshape(-1, 4)

            result = result.astype(numpy.float16)
            return result

        elif d3d11_element.Format == 'R32G32B32A32_FLOAT':
            
            result = numpy.ones(mesh_loops_length * 4, dtype=numpy.float32)
            result[0::4] = normals[0::3]
            result[1::4] = normals[1::3]
            result[2::4] = normals[2::3]
            result = result.reshape(-1, 4)

            result = result.astype(numpy.float32)
            return result

        elif d3d11_element.Format == D3D11Format.R8G8B8A8_SNORM:
            # WWMI: NORMAL has already been confirmed good here

            result = numpy.ones(mesh_loops_length * 4, dtype=numpy.float32)
            result[0::4] = normals[0::3]
            result[1::4] = normals[1::3]
            result[2::4] = normals[2::3]
            
            if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
                bitangent_signs = numpy.empty(mesh_loops_length, dtype=numpy.float32)
                mesh_loops.foreach_get("bitangent_sign", bitangent_signs)
                result[3::4] = bitangent_signs * -1
                # print("Unreal: Set NORMAL.W to bitangent_sign")
            
            result = result.reshape(-1, 4)

            return FormatUtils.convert_4x_float32_to_r8g8b8a8_snorm(result)


        elif d3d11_element.Format == D3D11Format.R8G8B8A8_UNORM:
            # Since normal data is in [-1,1], if it must be exported as UNORM it must have been normalized to [0,1]
            
            result = numpy.ones(mesh_loops_length * 4, dtype=numpy.float32)
            

            # YYSLS: the last component w is fixed to 0
            if GlobalConfig.logic_name == LogicName.YYSLS:
                result = numpy.zeros(mesh_loops_length * 4, dtype=numpy.float32)
                
            result[0::4] = normals[0::3]
            result[1::4] = normals[1::3]
            result[2::4] = normals[2::3]
            result = result.reshape(-1, 4)

            # Normalize (thanks to QiuQiu for developing this code)
            def DeConvert(nor):
                return (nor + 1) * 0.5

            for i in range(len(result)):
                result[i][0] = DeConvert(result[i][0])
                result[i][1] = DeConvert(result[i][1])
                result[i][2] = DeConvert(result[i][2])

            return FormatUtils.convert_4x_float32_to_r8g8b8a8_unorm(result)

        elif d3d11_element.Format == "R32_UINT" and GlobalConfig.logic_name == LogicName.EFMI:
            print("Endfield normal encoding - using TBNCodec")
            raw_normals = normals.reshape(-1, 3)
            tangents = numpy.empty(mesh_loops_length * 3, dtype=numpy.float32)
            mesh_loops.foreach_get("tangent", tangents)
            tangents = tangents.reshape(-1, 3)

            bitangent_signs = numpy.empty(mesh_loops_length, dtype=numpy.float32)
            mesh_loops.foreach_get("bitangent_sign", bitangent_signs)

            new_normals = TBNCodec.encode_efmi_tools_r32_uint_from_tbn(
                raw_normals,
                tangents,
                bitangent_signs,
                flip_texcoord_v=True,
                flip_bitangent_sign=True,
            ).reshape(-1, 1)
            
            return new_normals
        else:
            # Reshape the 1-D array into a 2-D array of shape (mesh_loops_length, 3)
            result = normals.reshape(-1, 3)

            return result

    @staticmethod
    def _parse_tangent(mesh_loops, mesh_loops_length, d3d11_element):
        result = numpy.empty(mesh_loops_length * 4, dtype=numpy.float32)

        # Batch-fetch tangent and bitangent sign data with foreach_get
        tangents = numpy.empty(mesh_loops_length * 3, dtype=numpy.float32)
        mesh_loops.foreach_get("tangent", tangents)

        # Place the components into the output array
        result[0::4] = tangents[0::3]  # x component
        result[1::4] = tangents[1::3]  # y component
        result[2::4] = tangents[2::3]  # z component

        if GlobalConfig.logic_name == LogicName.YYSLS:
            # YYSLS: TANGENT.w is fixed to 1
            tangent_w = numpy.ones(mesh_loops_length, dtype=numpy.float32)
            result[3::4] = tangent_w
        elif GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            # In the Unreal engine this must be set to a fixed 1
            tangent_w = numpy.ones(mesh_loops_length, dtype=numpy.float32)
            result[3::4] = tangent_w
        else:
            # print("Other games flip TANGENT's W component")
            # By default, flip BITANGENT's W; most Unity games need this
            bitangent_signs = numpy.empty(mesh_loops_length, dtype=numpy.float32)
            mesh_loops.foreach_get("bitangent_sign", bitangent_signs)
            # XXX Multiply the bitangent sign by -1
            # The flip here (flip means *= -1) is required for correct rendering in Unity games: TANGENT's W must be flipped
            bitangent_signs *= -1
            result[3::4] = bitangent_signs  # w component (bitangent sign)
        # Reshape output_tangents into a 2-D array of shape (mesh_loops_length, 4)
        result = result.reshape(-1, 4)

        if d3d11_element.Format == 'R16G16B16A16_FLOAT':
            result = result.astype(numpy.float16)

        elif d3d11_element.Format == D3D11Format.R8G8B8A8_SNORM:
            # print("WWMI TANGENT To SNORM")
            result = FormatUtils.convert_4x_float32_to_r8g8b8a8_snorm(result)

        elif d3d11_element.Format == D3D11Format.R8G8B8A8_UNORM:
            result = FormatUtils.convert_4x_float32_to_r8g8b8a8_unorm(result)
        
        # IdentityV format
        elif d3d11_element.Format == D3D11Format.R32G32B32_FLOAT:
            result = numpy.empty(mesh_loops_length * 3, dtype=numpy.float32)

            result[0::3] = tangents[0::3]  # x component
            result[1::3] = tangents[1::3]  # y component
            result[2::3] = tangents[2::3]  # z component

            result = result.reshape(-1, 3)
        
        # YYSLS format
        elif d3d11_element.Format == D3D11Format.R16G16B16A16_SNORM:
            result = FormatUtils.convert_4x_float32_to_r16g16b16a16_snorm(result)
        
        return result

    @staticmethod
    def _parse_binormal(mesh_loops, mesh_loops_length, d3d11_element):
        result = numpy.empty(mesh_loops_length * 4, dtype=numpy.float32)

        # Batch-fetch tangent and bitangent sign data with foreach_get
        binormals = numpy.empty(mesh_loops_length * 3, dtype=numpy.float32)
        mesh_loops.foreach_get("bitangent", binormals)
        
        if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            # Wuthering Waves reverse flip: Binormal (-x, -y, z)
            binormals[0::3] *= -1
            binormals[1::3] *= -1

        # Place the components into the output array
        # Flipping BINORMAL entirely yields the same effect as in the YYSLS game.
        result[0::4] = binormals[0::3]  # x component
        result[1::4] = binormals[1::3]   # y component
        result[2::4] = binormals[2::3]  # z component
        binormal_w = numpy.ones(mesh_loops_length, dtype=numpy.float32)
        result[3::4] = binormal_w
        result = result.reshape(-1, 4)

        if d3d11_element.Format == D3D11Format.R16G16B16A16_SNORM:
            #  YYSLS format
            result = FormatUtils.convert_4x_float32_to_r16g16b16a16_snorm(result)
            
        return result


    @staticmethod
    def _parse_color(mesh, mesh_loops_length, d3d11_element_name, d3d11_element):
        if d3d11_element_name in mesh.color_attributes:
            color_data = mesh.color_attributes[d3d11_element_name].data
        else:
            color_data = None

        if color_data is not None:
            # Blender's color-layer read API always returns 0-1 RGBA floats; handle the intermediate result as float32 here.
            result = numpy.zeros(mesh_loops_length, dtype=(numpy.float32, 4))
            # result = numpy.zeros((mesh_loops_length,4), dtype=(numpy.float32))

            color_data.foreach_get("color", result.ravel())
            
            if d3d11_element.Format == 'R16G16B16A16_FLOAT':
                result = result.astype(numpy.float16)
            elif d3d11_element.Format == "R16G16_UNORM":
                # Wuthering Waves stores smooth normals in UV; WWMI converts them to R16G16_UNORM.
                # However, there may well be a conversion issue here.
                result = result.astype(numpy.float16)
                result = result[:, :2]
                result = FormatUtils.convert_2x_float32_to_r16g16_unorm(result)
            # TODO add code for octahedral-compressed normals stored as R32_UINT

            elif d3d11_element.Format == "R16G16_FLOAT":
                # 
                result = result[:, :2]
            elif d3d11_element.Format == D3D11Format.R8G8B8A8_UNORM:
                result = FormatUtils.convert_4x_float32_to_r8g8b8a8_unorm(result)

            print(d3d11_element.Format)
            print(d3d11_element_name)
    
            return result
        return None

    @staticmethod
    def _parse_texcoord(mesh, mesh_loops_length, d3d11_element_name, d3d11_element):
        result = None
        # TimerUtils.Start("GET TEXCOORD")
        for uv_name in ('%s.xy' % d3d11_element_name, '%s.zw' % d3d11_element_name):
            if uv_name in mesh.uv_layers:
                uvs_array = numpy.empty(mesh_loops_length ,dtype=(numpy.float32,2))
                mesh.uv_layers[uv_name].data.foreach_get("uv",uvs_array.ravel())
                uvs_array[:,1] = 1.0 - uvs_array[:,1]

                if d3d11_element.Format == D3D11Format.R16G16_FLOAT:
                    uvs_array = uvs_array.astype(numpy.float16)
                
                # Reshape uvs_array into a 2-D array of shape (mesh_loops_length, 2)
                # uvs_array = uvs_array.reshape(-1, 2)

                result = uvs_array 
        # TimerUtils.End("GET TEXCOORD")
        return result

    @staticmethod
    def _parse_blendindices(blendindices_dict, d3d11_element):
        blendindices = blendindices_dict.get(d3d11_element.SemanticIndex,None)
        # print("blendindices: " + str(len(blendindices_dict)))
        # If blendindices for the current index is None, use index 0's data and zero it all out
        if blendindices is None:
            blendindices_0 = blendindices_dict.get(0, None)
            if blendindices_0 is not None:
                # Create an all-zero array with the same shape as blendindices_0, keeping the same data type
                blendindices = numpy.zeros_like(blendindices_0)
            else:
                SSMTErrorUtils.raise_fatal("Cannot find any valid BLENDINDICES data in this model, Please check if your model's Vertex Group is correct.")
        # print(len(blendindices))
        if d3d11_element.Format == "R32G32B32A32_SINT":
            return blendindices
        elif d3d11_element.Format == "R16G16B16A16_UINT":
            return blendindices
        elif d3d11_element.Format == "R32G32B32A32_UINT":
            return blendindices
        elif d3d11_element.Format == "R32G32_UINT":
            return blendindices[:, :2]
        elif d3d11_element.Format == "R32G32_SINT":
            return blendindices[:, :2]
        elif d3d11_element.Format == "R32_UINT":
            return blendindices[:, :1]
        elif d3d11_element.Format == "R32_SINT":
            return blendindices[:, :1]
        elif d3d11_element.Format == D3D11Format.R8G8B8A8_SNORM:
            return FormatUtils.convert_4x_float32_to_r8g8b8a8_snorm(blendindices)
        elif d3d11_element.Format == D3D11Format.R8G8B8A8_UNORM:
            return FormatUtils.convert_4x_float32_to_r8g8b8a8_unorm(blendindices)
        elif d3d11_element.Format == D3D11Format.R8G8B8A8_UINT:
            # R8G8B8A8_UINT: 4 packed uint8 values.
            # If max_index >= 256, keep the original dtype and rely on replace_remapped_blendindices
            # to remap them into 0-255 before assigning to the uint8 field.
            max_index = numpy.max(blendindices)
            if max_index > 255:
                print("BLENDINDICES exceeds 255, max value: " + str(max_index) + "; keeping the original type, relying on blend remap to remap")
            else:
                if blendindices.dtype != numpy.uint8:
                    blendindices = blendindices.astype(numpy.uint8)
            return blendindices
        elif d3d11_element.Format == "R8_UINT":
            # R8_UINT: multiple independent uint8 values; ByteWidth decides the number of VGs.
            max_index = numpy.max(blendindices)
            if max_index > 255:
                print("BLENDINDICES exceeds 255, max value: " + str(max_index) + "; keeping the original type, relying on blend remap to remap")
            else:
                format_len = int(d3d11_element.ByteWidth / numpy.dtype(numpy.uint8).itemsize)
                if blendindices.dtype != numpy.uint8:
                    blendindices = blendindices[:, :format_len].astype(numpy.uint8)
                else:
                    blendindices = blendindices[:, :format_len]
                return blendindices
            # max_index > 255: keep and return all original columns; let remap handle it
            return blendindices
        elif d3d11_element.Format == "R16_UINT":
            # R16_UINT: multiple independent uint16 values.
            if blendindices.dtype != numpy.uint16:
                blendindices = blendindices.astype(numpy.uint16)
            format_len = int(d3d11_element.ByteWidth / numpy.dtype(numpy.uint16).itemsize)
            return blendindices[:, :format_len]
        else:
            # print(blendindices.shape)
            SSMTErrorUtils.raise_fatal("Unknown BLENDINDICES format")

    @staticmethod
    def _parse_blendweight(blendweights_dict, d3d11_element):
        blendweights = blendweights_dict.get(d3d11_element.SemanticIndex, None)
        if blendweights is None:
            # print("Encountered the None case!")
            blendweights_0 = blendweights_dict.get(0, None)
            if blendweights_0 is not None:
                # Create an all-zero array with the same shape as blendweights_0, keeping the same data type
                blendweights = numpy.zeros_like(blendweights_0)
            else:
                SSMTErrorUtils.raise_fatal("Cannot find any valid BLENDWEIGHT data in this model, Please check if your model's Vertex Group is correct.")
        # print(len(blendweights))
        if d3d11_element.Format == "R32G32B32A32_FLOAT":
            return blendweights
        elif d3d11_element.Format == "R32G32_FLOAT":
            return blendweights[:, :2]
        elif d3d11_element.Format == D3D11Format.R8G8B8A8_SNORM:
            # print("BLENDWEIGHT R8G8B8A8_SNORM")
            return FormatUtils.convert_4x_float32_to_r8g8b8a8_snorm(blendweights)
        elif d3d11_element.Format == D3D11Format.R8G8B8A8_UNORM:
            # print("BLENDWEIGHT R8G8B8A8_UNORM")
            return FormatUtils.convert_4x_float32_to_r8g8b8a8_unorm_blendweights(blendweights)
        elif d3d11_element.Format == 'R16G16B16A16_FLOAT':
            return blendweights.astype(numpy.float16)
        elif d3d11_element.Format == 'R16G16B16A16_UNORM':
            return FormatUtils.convert_4x_float32_to_r16g16b16a16_unorm(blendweights)
        elif d3d11_element.Format == "R8_UNORM" and d3d11_element.ByteWidth == 8:
            # TimerUtils.Start("WWMI BLENDWEIGHT R8_UNORM special handling")
            blendweights = FormatUtils.convert_4x_float32_to_r8g8b8a8_unorm_blendweights(blendweights)
            # original_elementname_data_dict[d3d11_element_name] = blendweights
            print("WWMI R8_UNORM special handling")
            # TimerUtils.End("WWMI BLENDWEIGHT R8_UNORM special handling")
            return blendweights

        else:
            print(blendweights.shape)
            SSMTErrorUtils.raise_fatal("Unknown BLENDWEIGHTS format")

    @staticmethod
    def parse_elementname_data_dict(mesh:bpy.types.Mesh, d3d11_game_type:D3D11GameType):
        '''
        - Note: data here is fetched from mesh.loops, not from mesh.vertices
        - So later code must use the mesh.loop indices to fetch data
        '''

        original_elementname_data_dict: dict = {}

        mesh_loops = mesh.loops
        mesh_loops_length = len(mesh.loops)
        mesh_vertices = mesh.vertices
        mesh_vertices_length = len(mesh.vertices)

        loop_vertex_indices = numpy.empty(mesh_loops_length, dtype=int)
        mesh_loops.foreach_get("vertex_index", loop_vertex_indices)

        # Preset number of weights, i.e. how many weights affect each vertex
        blend_size = 4

        if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            blend_size = d3d11_game_type.get_blendindices_count_wwmi()

        normalize_weights = "Blend" in d3d11_game_type.OrderedCategoryNameList

        # normalize_weights = False
        if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            # print("Wuthering Waves test-only weight handling:")
            blendweights_dict, blendindices_dict = VertexGroupUtils.get_blendweights_blendindices_v4_fast(mesh=mesh,normalize_weights = normalize_weights,blend_size=blend_size)

        elif GlobalConfig.logic_name == LogicName.SnowBreak:
            print("SnowBreak weight processing")
            blendweights_dict, blendindices_dict = VertexGroupUtils.get_blendweights_blendindices_v4_fast(mesh=mesh,normalize_weights = normalize_weights,blend_size=blend_size)
        else:
            blendweights_dict, blendindices_dict = VertexGroupUtils.get_blendweights_blendindices_v3(mesh=mesh,normalize_weights = normalize_weights)


        # Check whether an ENCODEDDATA element exists (used for EFMI's TBN encoding)
        has_encoded_data = 'ENCODEDDATA' in d3d11_game_type.ElementNameD3D11ElementDict

        # Fetch the corresponding data for every element
        for d3d11_element_name in d3d11_game_type.OrderedFullElementList:
            d3d11_element = d3d11_game_type.ElementNameD3D11ElementDict[d3d11_element_name]
            
            data = None

            if d3d11_element_name == 'POSITION':
                data = ObjBufferHelper._parse_position(mesh_vertices, mesh_vertices_length, loop_vertex_indices, d3d11_element)

            elif d3d11_element_name == 'NORMAL':
                if has_encoded_data and (GlobalConfig.logic_name == LogicName.EFMI ):
                    pass
                else:
                    data = ObjBufferHelper._parse_normal(mesh_loops, mesh_loops_length, d3d11_element, has_encoded_data)
                    # Only the raw-byte round-trip presets (GIMI and SRMI)
                    # restore the raw NORMAL w component stored on import;
                    # all other presets keep the legacy parsing result untouched.
                    if LogicName.uses_raw_vertex_attributes(GlobalConfig.logic_name):
                        data = ObjBufferHelper._restore_raw_fourth_component(
                            mesh, RAW_NORMAL_W_ATTRIBUTE_PREFIX, d3d11_element, loop_vertex_indices, data
                        )

            elif d3d11_element_name == 'TANGENT':
                if has_encoded_data and (GlobalConfig.logic_name == LogicName.EFMI ):
                    pass
                elif LogicName.uses_raw_vertex_attributes(GlobalConfig.logic_name):
                    # Raw-byte round-trip path (GIMI and SRMI): prefer the
                    # lossless raw TANGENT bytes stored on import, and only fall
                    # back to Blender loop tangents when no raw payload exists
                    # on this mesh.
                    data = ObjBufferHelper._load_raw_point_element(
                        mesh, RAW_TANGENT_ATTRIBUTE_PREFIX, d3d11_element, loop_vertex_indices
                    )
                    if data is None:
                        data = ObjBufferHelper._parse_tangent(mesh_loops, mesh_loops_length, d3d11_element)
                else:
                    # Legacy path for every other game preset: always parse the
                    # tangent from Blender loop data, exactly as before.
                    data = ObjBufferHelper._parse_tangent(mesh_loops, mesh_loops_length, d3d11_element)

            elif d3d11_element_name.startswith('BINORMAL'):
                if has_encoded_data and (GlobalConfig.logic_name == LogicName.EFMI):
                    pass
                else:
                    data = ObjBufferHelper._parse_binormal(mesh_loops, mesh_loops_length, d3d11_element)
            
            elif d3d11_element_name.startswith('COLOR'):
                data = ObjBufferHelper._parse_color(mesh, mesh_loops_length, d3d11_element_name, d3d11_element)
                # Only the raw-byte round-trip presets (GIMI and SRMI) restore
                # the raw COLOR alpha component stored on import; all other
                # presets keep the legacy result.
                if LogicName.uses_raw_vertex_attributes(GlobalConfig.logic_name):
                    data = ObjBufferHelper._restore_raw_fourth_component(
                        mesh,
                        RAW_COLOR_ALPHA_ATTRIBUTE_PREFIX + ":" + d3d11_element_name,
                        d3d11_element,
                        loop_vertex_indices,
                        data,
                    )

            elif d3d11_element_name.startswith('TEXCOORD') and d3d11_element.Format.endswith('FLOAT'):
                data = ObjBufferHelper._parse_texcoord(mesh, mesh_loops_length, d3d11_element_name, d3d11_element)
            
            elif d3d11_element_name.startswith('BLENDINDICES'):
                data = ObjBufferHelper._parse_blendindices(blendindices_dict, d3d11_element)
                
            elif d3d11_element_name.startswith('BLENDWEIGHT'):
                data = ObjBufferHelper._parse_blendweight(blendweights_dict, d3d11_element)

            # elif d3d11_element_name == 'ENCODEDDATA':
            #     if GlobalConfig.logic_name == LogicName.EFMI:
            #         data = ObjBufferHelper._parse_encoded_tbn(mesh_loops, mesh_loops_length, d3d11_element)
            #     else:
            #         print(f"Warning: ENCODEDDATA is only supported in the EFMI format; current game type: {GlobalConfig.logic_name}")
            #         data = None

            if data is not None:
                original_elementname_data_dict[d3d11_element_name] = data

        return original_elementname_data_dict


    @staticmethod
    def convert_to_element_vertex_ndarray(
        d3d11_game_type:D3D11GameType, 
        mesh:bpy.types.Mesh,
        original_elementname_data_dict:dict,
        final_elementname_data_dict:dict):

        total_structured_dtype:numpy.dtype = d3d11_game_type.get_total_structured_dtype()

        # Create the element array with the original dtype (matching ByteWidth)
        element_vertex_ndarray = numpy.zeros(len(mesh.loops), dtype=total_structured_dtype)
        # For each expected element, prefer the remapped/modified value in
        # `final_elementname_data_dict` if present; otherwise use the parsed
        # value from `original_elementname_data_dict`.
        for d3d11_element_name in d3d11_game_type.OrderedFullElementList:
            if d3d11_element_name in final_elementname_data_dict:
                data = final_elementname_data_dict[d3d11_element_name]
            else:
                data = original_elementname_data_dict.get(d3d11_element_name, None)

            if data is None:
                # Missing data is a fatal condition — better to raise so caller
                # can diagnose than to silently write zeros for an expected
                # element (which would corrupt downstream buffers).
                SSMTErrorUtils.raise_fatal(f"Missing element data for '{d3d11_element_name}' when packing vertex ndarray")
            print("Attempting to assign Element: " + d3d11_element_name)
            element_vertex_ndarray[d3d11_element_name] = data
        
        return element_vertex_ndarray
    

    @staticmethod
    def calc_index_vertex_buffer_wwmi_v2(
        mesh:bpy.types.Mesh, 
        element_vertex_ndarray:numpy.ndarray, 
        dtype:numpy.dtype,
        d3d11_game_type:D3D11GameType):
        '''
        - Use numpy to view the structured vertices as rows of bytes, avoiding per-vertex bytes() calls and dict hashing.
        - numpy.unique(..., axis=0, return_index=True, return_inverse=True) deduplicates and builds the inverse mapping at the C level.
        - Only a little Python slicing is used when building the per-polygon IB, greatly improving overall efficiency.
        - When the structured dtype is not contiguous, one internal copy (ascontiguousarray) is made; usually cheaper than per-vertex hashing.
        '''

        # (1) loop -> vertex mapping
        loops = mesh.loops
        n_loops = len(loops)
        loop_vertex_indices = numpy.empty(n_loops, dtype=int)
        loops.foreach_get("vertex_index", loop_vertex_indices)

        # (2) Ensure element_vertex_ndarray is contiguous and view it as an (n_loops, row_bytes) uint8 matrix
        vb = numpy.ascontiguousarray(element_vertex_ndarray)
        row_size = vb.dtype.itemsize
        try:
            row_bytes = vb.view(numpy.uint8).reshape(n_loops, row_size)
        except Exception:
            raw = vb.tobytes()
            row_bytes = numpy.frombuffer(raw, dtype=numpy.uint8).reshape(n_loops, row_size)

        # WWMI-Tools deduplicates loop rows including the loop's VertexId -> they
        # effectively perform uniqueness on loop attributes + VertexId treated as
        # a field. To replicate that reliably (preserving structured field layout
        # and alignment) we build a structured array that copies all existing
        # fields and appends a 'VERTEXID' uint32 field, then call numpy.unique on it.
        # Afterwards we select unique rows from the original `row_bytes` using
        # the indices returned by numpy.unique to preserve exact original layout.

        # Build 4-byte vertex index array (little-endian) and concatenate to row bytes
        # to form combined rows: [row_bytes | vid_bytes]. Use numpy.unique on combined
        # rows to get uniqueness, then reorder unique results to match insertion
        # order (first occurrence). This vectorized path keeps behavior identical
        # to the OrderedDict+bytes approach but runs much faster in numpy.
        # Build 4-byte vertex index array (little-endian)
        vid_bytes = loop_vertex_indices.astype(numpy.uint32).view(numpy.uint8).reshape(n_loops, 4)

        # Combine row bytes + vid bytes, but to make numpy.unique faster we pad the
        # combined row to a multiple of 8 bytes and view it as uint64 blocks.
        total_bytes = row_size + 4
        pad = (-total_bytes) % 8
        padded_width = total_bytes + pad

        # Allocate padded combined buffer and fill
        combined_padded = numpy.zeros((n_loops, padded_width), dtype=numpy.uint8)
        combined_padded[:, :row_size] = row_bytes
        combined_padded[:, row_size:row_size+4] = vid_bytes

        # View as uint64 blocks (shape: n_loops x n_blocks)
        n_blocks = padded_width // 8
        combined_u64 = combined_padded.view(numpy.uint64).reshape(n_loops, n_blocks)

        # Create a structured view so numpy.unique treats each row as a single record
        dtype_descr = [(f'f{i}', numpy.uint64) for i in range(n_blocks)]
        structured = combined_u64.view(numpy.dtype(dtype_descr)).reshape(n_loops)

        unique_struct, unique_first_indices, inverse = numpy.unique(
            structured, return_index=True, return_inverse=True
        )

        # Remap unique ids to insertion order (first occurrence order)
        order = numpy.argsort(unique_first_indices)
        new_id = numpy.empty_like(order)
        new_id[order] = numpy.arange(len(order), dtype=new_id.dtype)
        inverse = new_id[inverse]

        unique_first_indices_insertion = unique_first_indices[order]

        # Pick original unique rows from row_bytes using insertion-ordered indices
        unique_rows = row_bytes[unique_first_indices_insertion]

        # Expose the loop indices (first-occurrence loop indices) used to select
        # the unique rows. Callers can sample per-loop original arrays using
        # these indices to reconstruct per-unique-row original element values.
        unique_first_loop_indices = unique_first_indices_insertion

        # Reconstruct a structured ndarray of the unique element rows.
        # This lets callers access element fields by name for the unique
        # vertex set (useful for debugging or further processing).
        # Ensure the byte width matches the dtype itemsize.
        if unique_rows.shape[1] != dtype.itemsize:
            SSMTErrorUtils.raise_fatal(f"Unique row byte-size ({unique_rows.shape[1]}) does not match structured dtype itemsize ({dtype.itemsize})")

        n_unique = unique_rows.shape[0]
        unique_rows_contig = numpy.ascontiguousarray(unique_rows)
        try:
            # Zero-copy view where possible
            unique_element_vertex_ndarray = unique_rows_contig.view(dtype).reshape(n_unique)
        except Exception:
            # Fallback to a safe copy-based reconstruction
            unique_element_vertex_ndarray = numpy.frombuffer(unique_rows_contig.tobytes(), dtype=dtype).reshape(n_unique)

        # Expose for downstream use: structure-aligned unique vertex records
        # self.unique_element_vertex_ndarray = unique_element_vertex_ndarray

        # Build index -> original vertex id (from the vertex of each unique row's first loop)
        original_vertex_ids = loop_vertex_indices[unique_first_indices_insertion]
        index_vertex_id_dict = dict(enumerate(original_vertex_ids.astype(int).tolist()))

        # (4) Build the IB for every polygon (via the inverse mapping)
        # inverse is already ordered by loops; concatenating polygon slices in
        # polygon order is equivalent to taking inverse in sequence.
        flattened_ib_arr = inverse.astype(numpy.int32)

        # (5) Slice the byte stream per category from unique_rows
        category_stride_dict = d3d11_game_type.get_real_category_stride_dict()
        category_buffer_dict = {}
        stride_offset = 0
        for cname, cstride in category_stride_dict.items():
            category_buffer_dict[cname] = unique_rows[:, stride_offset:stride_offset + cstride].flatten()
            stride_offset += cstride

        # (6) Flip triangle winding (efficient)
        # Wuthering Waves needs this flip
        flat_arr = flattened_ib_arr
        if flat_arr.size % 3 == 0:
            flipped = flat_arr.reshape(-1, 3)[:, ::-1].flatten().tolist()
        else:
            # Rare irregular case: fallback to python loop on numpy array
            flipped = []
            iarr = flat_arr.tolist()
            for i in range(0, len(iarr), 3):
                tri = iarr[i:i + 3]
                flipped.extend(tri[::-1])

        ib = flipped
        return ib, category_buffer_dict, index_vertex_id_dict, unique_element_vertex_ndarray,unique_first_loop_indices


    @staticmethod
    def average_normal_color(obj,indexed_vertices,d3d11_game_type:D3D11GameType,dtype):
        '''
        Nico: arithmetic-average normalized normals; the method used by HI3 2.0 characters
        '''
        if D3D11Semantic.COLOR not in d3d11_game_type.OrderedFullElementList:
            return indexed_vertices
        allow_calc = False
        if GlobalProperties.recalculate_color():
            allow_calc = True
        elif obj.get("3DMigoto:RecalculateCOLOR",False): 
            allow_calc = True
        if not allow_calc:
            return indexed_vertices

        # Start recalculating COLOR
        TimerUtils.Start("Recalculate COLOR")

        # No need to worry about the efficiency of this conversion; it is very fast
        vb = bytearray()
        for vertex in indexed_vertices:
            vb += bytes(vertex)
        vb = numpy.frombuffer(vb, dtype = dtype)

        # First extract all unique positions and create an index mapping
        unique_positions, position_indices = numpy.unique(
            [tuple(val['POSITION']) for val in vb], 
            return_inverse=True, 
            axis=0
        )

        # Initialize the accumulated normals and counters to zero
        accumulated_normals = numpy.zeros((len(unique_positions), 3), dtype=float)
        counts = numpy.zeros(len(unique_positions), dtype=int)

        # Accumulate normals and increment the counters (vb is assumed to be a list here)
        for i, val in enumerate(vb):
            accumulated_normals[position_indices[i]] += numpy.array(val['NORMAL'], dtype=float)
            counts[position_indices[i]] += 1

        # Normalize the normals of all positions in one pass
        mask = counts > 0
        average_normals = numpy.zeros_like(accumulated_normals)
        average_normals[mask] = (accumulated_normals[mask] / counts[mask][:, None])

        # Normalize into [0,1], then map to color values
        normalized_normals = ((average_normals + 1) / 2 * 255).astype(numpy.uint8)

        # Update the color data
        new_color = []
        for i, val in enumerate(vb):
            color = [0, 0, 0, val['COLOR'][3]]  # Preserve the original Alpha channel
            
            if mask[position_indices[i]]:
                color[:3] = normalized_normals[position_indices[i]]

            new_color.append(color)

        # Convert the new color list into a NumPy array
        new_color_array = numpy.array(new_color, dtype=numpy.uint8)

        # Update the color data in vb
        for i, val in enumerate(vb):
            val['COLOR'] = new_color_array[i]

        TimerUtils.End("Recalculate COLOR")
        return vb

    @staticmethod
    def _decode_normalized_field(values):
        values = numpy.asarray(values)
        value_dtype = values.dtype
        if numpy.issubdtype(value_dtype, numpy.signedinteger):
            return values.astype(numpy.float32) / numpy.iinfo(value_dtype).max
        if numpy.issubdtype(value_dtype, numpy.unsignedinteger):
            return values.astype(numpy.float32) / numpy.iinfo(value_dtype).max * 2.0 - 1.0
        return values.astype(numpy.float32)

    @staticmethod
    def _encode_normalized_field(values, target_dtype):
        """Pack normalized directions for a structured vertex-buffer field."""
        values = numpy.asarray(values, dtype=numpy.float32)
        target_dtype = numpy.dtype(target_dtype)
        if numpy.issubdtype(target_dtype, numpy.signedinteger):
            scale = numpy.iinfo(target_dtype).max
            return numpy.rint(numpy.clip(values, -1.0, 1.0) * scale).astype(target_dtype)
        if numpy.issubdtype(target_dtype, numpy.unsignedinteger):
            scale = numpy.iinfo(target_dtype).max
            return numpy.rint((numpy.clip(values, -1.0, 1.0) * 0.5 + 0.5) * scale).astype(target_dtype)
        return values.astype(target_dtype)
    


    @staticmethod
    def average_normal_tangent(obj,indexed_vertices,d3d11_game_type,dtype):
        '''
        Nico: every miHoYo/HoYoverse game can use this, as can the old GPU-PreSkinning GF2; except HI3 2.0's new characters.
        Although it can achieve a similar effect, it still cannot perfectly recover the model's own TANGENT data; body outlines only reach about 99% similarity.
        Tests show that hair outlines are neither a simple vector normalization nor an arithmetic-average normalization.
        '''
        # TimerUtils.Start("Recalculate TANGENT")

        if D3D11Semantic.TANGENT not in d3d11_game_type.OrderedFullElementList:
            return indexed_vertices
        allow_calc = False
        if GlobalProperties.recalculate_tangent():
            allow_calc = True
        elif obj.get("3DMigoto:RecalculateTANGENT",False): 
            allow_calc = True
        
        if not allow_calc:
            return indexed_vertices
        
        # No need to worry about the efficiency of this conversion; it is very fast
        vb = bytearray()
        for vertex in indexed_vertices:
            vb += bytes(vertex)
        vb = numpy.frombuffer(vb, dtype = dtype)

        # Start recalculating TANGENT
        positions = numpy.array([val['POSITION'] for val in vb])
        normals = numpy.array([val['NORMAL'] for val in vb], dtype=float)

        # Sort the positions so that identical positions end up adjacent
        sort_indices = numpy.lexsort(positions.T)
        sorted_positions = positions[sort_indices]
        sorted_normals = normals[sort_indices]

        # Find where the position changes, i.e. where we need to split groups
        group_indices = numpy.flatnonzero(numpy.any(sorted_positions[:-1] != sorted_positions[1:], axis=1))
        group_indices = numpy.r_[0, group_indices + 1, len(sorted_positions)]

        # Accumulate normals and compute the counts
        unique_positions = sorted_positions[group_indices[:-1]]
        accumulated_normals = numpy.add.reduceat(sorted_normals, group_indices[:-1], axis=0)
        counts = numpy.diff(group_indices)

        # Normalize the accumulated normal vectors
        normalized_normals = accumulated_normals / numpy.linalg.norm(accumulated_normals, axis=1)[:, numpy.newaxis]
        normalized_normals[numpy.isnan(normalized_normals)] = 0  # Handle division-by-zero errors that any zero vector could cause

        # Build the result dictionary
        position_normal_dict = dict(zip(map(tuple, unique_positions), normalized_normals))

        # TimerUtils.End("Recalculate TANGENT")

        # Fetch all positions and convert them to tuples for dictionary lookup
        positions = [tuple(pos) for pos in vb['POSITION']]

        # Fetch the matching normalized normals from the dictionary
        normalized_normals = numpy.array([position_normal_dict[pos] for pos in positions])

        # Compute w and adjust the tangent's fourth component
        if LogicName.uses_raw_vertex_attributes(GlobalConfig.logic_name):
            # Raw-byte round-trip path (GIMI and SRMI): decode/encode through
            # the normalized-field helpers so that integer (SNORM/UNORM)
            # TANGENT formats stay lossless.
            tangent_dtype = vb['TANGENT'].dtype
            tangent_values = ObjBufferHelper._decode_normalized_field(vb['TANGENT'])
            w = numpy.where(tangent_values[:, 3] >= 0, -1.0, 1.0)

            vb['TANGENT'][:, :3] = ObjBufferHelper._encode_normalized_field(normalized_normals, tangent_dtype)
            vb['TANGENT'][:, 3] = ObjBufferHelper._encode_normalized_field(w, tangent_dtype)
        else:
            # Legacy path for every other game preset: treat the TANGENT field
            # as plain float and write the values back directly.
            w = numpy.where(vb['TANGENT'][:, 3] >= 0, -1.0, 1.0)

            # Update the TANGENT components; note that this slicing assumes
            # the TANGENT field has exactly four components.
            vb['TANGENT'][:, :3] = normalized_normals
            vb['TANGENT'][:, 3] = w

        # TimerUtils.End("Recalculate TANGENT")

        return vb

    @staticmethod
    def average_normal_tangent_xxmi(obj, indexed_vertices, flattened_ib, d3d11_game_type, dtype, rounding_precision: int = 4):
        '''
        Recalculate TANGENT.xyz with XXMI's angle-weighted outline approach.
        Only xyz is replaced here; w keeps the handling convention of the current export path.
        '''
        if D3D11Semantic.TANGENT not in d3d11_game_type.OrderedFullElementList:
            return indexed_vertices

        allow_calc = False
        if GlobalProperties.recalculate_tangent():
            allow_calc = True
        elif obj.get("3DMigoto:RecalculateTANGENT",False):
            allow_calc = True

        if not allow_calc:
            return indexed_vertices

        vb = bytearray()
        for vertex in indexed_vertices:
            vb += bytes(vertex)
        vb = numpy.frombuffer(vb, dtype=dtype)

        if len(vb) == 0 or len(flattened_ib) < 3 or D3D11Semantic.POSITION not in vb.dtype.names or D3D11Semantic.TANGENT not in vb.dtype.names:
            return vb

        positions = numpy.asarray(vb['POSITION'], dtype=numpy.float32)

        # Only the raw-byte round-trip presets (GIMI and SRMI) handle integer
        # (SNORM/UNORM) TANGENT formats through the lossless decode/encode
        # helpers. Every other game preset must keep the legacy float-only
        # behavior completely unchanged.
        use_lossless_fields = LogicName.uses_raw_vertex_attributes(GlobalConfig.logic_name)
        if use_lossless_fields:
            tangent_dtype = vb['TANGENT'].dtype
            tangents = ObjBufferHelper._decode_normalized_field(vb['TANGENT'])
        else:
            tangents = numpy.asarray(vb['TANGENT'], dtype=numpy.float32)

        if positions.ndim != 2 or positions.shape[1] < 3 or tangents.ndim != 2 or tangents.shape[1] < 3:
            return vb

        def unit_vector(vector_array: numpy.ndarray) -> numpy.ndarray:
            norms = numpy.linalg.norm(vector_array, axis=1, keepdims=True)
            norms = numpy.where(norms == 0, 1, norms)
            return vector_array / norms

        def calc_angle(edge_a: numpy.ndarray, edge_b: numpy.ndarray) -> numpy.ndarray:
            vector_a = numpy.abs(unit_vector(edge_a))
            vector_b = numpy.abs(unit_vector(edge_b))
            return numpy.arccos(
                numpy.clip(
                    numpy.einsum("ij,ij->i", vector_a, vector_b),
                    -1,
                    1,
                )
            )

        ib_data = numpy.asarray(flattened_ib, dtype=numpy.int32)
        valid_triangle_index_count = (len(ib_data) // 3) * 3
        if valid_triangle_index_count == 0:
            return vb

        ib_data = ib_data[:valid_triangle_index_count]
        if ib_data.max(initial=-1) >= len(vb) or ib_data.min(initial=0) < 0:
            return vb

        loops_coord = positions[ib_data, 0:3]
        triangles = loops_coord.reshape(-1, 3, 3)

        edge0 = triangles[:, 1] - triangles[:, 2]
        edge1 = triangles[:, 2] - triangles[:, 0]
        edge2 = triangles[:, 0] - triangles[:, 1]

        angle0 = calc_angle(edge2, edge1)
        angle1 = calc_angle(edge0, edge2)
        angle2 = calc_angle(edge1, edge0)

        loops_angle = numpy.zeros((len(triangles), 3), dtype=numpy.float32)
        loops_angle[:, 0] = angle0
        loops_angle[:, 1] = angle1
        loops_angle[:, 2] = angle2

        faces_normal = unit_vector(numpy.cross(edge0, edge1))
        loops_face_normal = faces_normal.repeat(3, axis=0)

        loops_round_coord = numpy.round(loops_coord, rounding_precision)
        loops_weighted_normal = loops_face_normal * loops_angle.reshape(-1, 1)

        _, unique_indices, unique_inverse = numpy.unique(
            loops_round_coord,
            axis=0,
            return_index=True,
            return_inverse=True,
        )

        accumulated_normals = numpy.zeros((len(unique_indices), 3), dtype=numpy.float32)
        numpy.add.at(accumulated_normals, unique_inverse, loops_weighted_normal)

        accumulated_magnitudes = numpy.linalg.norm(accumulated_normals, axis=1, keepdims=True)
        fallback_normals = loops_face_normal[unique_indices]
        accumulated_normals = numpy.where(
            accumulated_magnitudes < 1e-6,
            fallback_normals,
            accumulated_normals,
        )

        outline_vectors = tangents[:, 0:3].copy()
        outline_vectors[ib_data] = unit_vector(accumulated_normals[unique_inverse])

        if use_lossless_fields:
            # Raw-byte round-trip path (GIMI and SRMI): re-encode through the
            # normalized-field helper so that integer TANGENT formats
            # round-trip without precision loss.
            vb['TANGENT'][:, :3] = ObjBufferHelper._encode_normalized_field(outline_vectors, tangent_dtype)
        else:
            # Legacy path: write the float outline vectors back directly.
            vb['TANGENT'][:, :3] = outline_vectors

        if tangents.shape[1] >= 4:
            if use_lossless_fields:
                w = numpy.where(tangents[:, 3] >= 0, -1.0, 1.0)
                vb['TANGENT'][:, 3] = ObjBufferHelper._encode_normalized_field(w, tangent_dtype)
            else:
                # Legacy path: read and write the fourth component as plain float.
                w = numpy.where(vb['TANGENT'][:, 3] >= 0, -1.0, 1.0)
                vb['TANGENT'][:, 3] = w

        return vb

    @staticmethod
    def calc_index_vertex_buffer_universal(element_vertex_ndarray,mesh,obj,d3d11_game_type,dtype):
        '''
        Compute the IndexBuffer and CategoryBufferDict and return them

        This is the speed bottleneck: tested with 230k vertices, fetching the mesh data took only 1.5 s
        but these two steps together take 6 s, about 4/5 of the total runtime.
        It is sufficient for now, so leave it alone.
        '''
        # TimerUtils.Start("Calc IB VB")
        # (1) Deduplicate the model's vertices and build the index list
        '''
        When identical vertices do not need to be preserved, still use the classic, fast approach
        '''
        # print("calc ivb universal")
        indexed_vertices = collections.OrderedDict()
        ib = [[indexed_vertices.setdefault(element_vertex_ndarray[blender_lvertex.index].tobytes(), len(indexed_vertices))
                for blender_lvertex in mesh.loops[poly.loop_start:poly.loop_start + poly.loop_total]
                    ]for poly in mesh.polygons] 
            
        flattened_ib = [item for sublist in ib for item in sublist]
        # TimerUtils.End("Calc IB VB")

        # Recalculate TANGENT step
        indexed_vertices = ObjBufferHelper.average_normal_tangent_xxmi(
            obj=obj,
            indexed_vertices=indexed_vertices,
            flattened_ib=flattened_ib,
            d3d11_game_type=d3d11_game_type,
            dtype=dtype,
        )
        
        # Recalculate COLOR step
        indexed_vertices = ObjBufferHelper.average_normal_color(obj=obj, indexed_vertices=indexed_vertices, d3d11_game_type=d3d11_game_type,dtype=dtype)

        # print("indexed_vertices:")
        # print(str(len(indexed_vertices)))

        # (2) Convert to CategoryBufferDict
        # TimerUtils.Start("Calc CategoryBuffer")
        category_stride_dict = d3d11_game_type.get_real_category_stride_dict()
        category_buffer_dict:dict[str,list] = {}
        for categoryname,category_stride in d3d11_game_type.CategoryStrideDict.items():
            category_buffer_dict[categoryname] = []

        data_matrix = numpy.array([numpy.frombuffer(byte_data,dtype=numpy.uint8) for byte_data in indexed_vertices])
        stride_offset = 0
        for categoryname,category_stride in category_stride_dict.items():
            category_buffer_dict[categoryname] = data_matrix[:,stride_offset:stride_offset + category_stride].flatten()
            stride_offset += category_stride

        ib = flattened_ib
        if GlobalConfig.logic_name == LogicName.YYSLS:
            print("Flipping face winding during export")

            flipped_indices = []
            # print(flattened_ib[0],flattened_ib[1],flattened_ib[2])
            for i in range(0, len(flattened_ib), 3):
                triangle = flattened_ib[i:i+3]
                flipped_triangle = triangle[::-1]
                flipped_indices.extend(flipped_triangle)
            # print(flipped_indices[0],flipped_indices[1],flipped_indices[2])
            ib = flipped_indices


        
        category_buffer_dict = category_buffer_dict
        index_vertex_id_dict = None

        return ib,category_buffer_dict,index_vertex_id_dict



    @staticmethod
    def calc_index_vertex_buffer_girlsfrontline2(
        mesh:bpy.types.Mesh, 
        element_vertex_ndarray:numpy.ndarray, 
        d3d11_game_type:D3D11GameType,
        dtype:numpy.dtype):
        '''
        [Special mode: Girls' Frontline 2 (GF2) only] Forced index-alignment mode
        --------------------------------------------------
        Core logic:
        - Force "game engine vertex count" == "Blender vertex count".
        - Ignore splits caused by hard edges and UV seams; merge them forcibly.
        
        Use cases:
        - GF2's special render pipeline, or models that are already preprocessed (where every hard edge/UV seam truly is a physically split vertex).
        - Generating ShapeKeys is extremely simple in this mode, since indices are one-to-one.
        
        Drawbacks:
        - If the model has hard edges or UV seams, data is overwritten (merged), which may cause rendering errors (e.g. over-smoothed normals, broken UVs).
        
        1. Blender's "vertex count" = len(mesh.vertices); any position difference counts as a separate vertex.
        2. Pre-allocate a slot list of the same length; slot index == vertex index, guaranteeing a one-to-one mapping.
        3. While iterating loops, write the real data into the matching slot; slots no loop references keep a dummy (coordinates set correctly, everything else 0).
        4. Finally, pack the slots in order into a byte array; its length necessarily equals len(mesh.vertices), so the exported count matches Blender's status bar exactly.
        '''
        print("calc ivb gf2")

        loops = mesh.loops
        v_cnt = len(mesh.vertices)
        loop_vidx = numpy.empty(len(loops), dtype=int)
        loops.foreach_get("vertex_index", loop_vidx)

        # 1. Pre-allocate one record per Blender vertex, starting with an "empty" record
        dummy = numpy.zeros(1, dtype=element_vertex_ndarray.dtype)
        vertex_buffer = [dummy.copy() for _ in range(v_cnt)]   # list[ndarray]
        # 2. Mark which vertices are actually referenced by loops
        used_mask = numpy.zeros(v_cnt, dtype=bool)
        used_mask[loop_vidx] = True

        # 3. Shared TANGENT dictionary
        pos_normal_key = {}   # (position_tuple, normal_tuple) -> tangent

        # 4. First fill the "used" vertices with real data
        for lp in loops:
            v_idx = lp.vertex_index
            if used_mask[v_idx]:          # always True in practice; kept for readability
                data = element_vertex_ndarray[lp.index].copy()
                pn_key = (tuple(data['POSITION']), tuple(data['NORMAL']))
                if pn_key in pos_normal_key:
                    data['TANGENT'] = pos_normal_key[pn_key]
                else:
                    pos_normal_key[pn_key] = data['TANGENT']
                vertex_buffer[v_idx] = data

        # 5. Give "dead" vertices a dummy as well, but their positions must be right
        for v_idx in range(v_cnt):
            if not used_mask[v_idx]:
                vertex_buffer[v_idx]['POSITION'] = mesh.vertices[v_idx].co
                # Keep the remaining fields at 0

        # 6. Now vertex_buffer's length == v_cnt; just convert it to bytes
        indexed_vertices = [arr.tobytes() for arr in vertex_buffer]

        # 7. Rebuild the index buffer (IB)
        ib = []
        for poly in mesh.polygons:
            ib.append([v_idx for lp in loops[poly.loop_start:poly.loop_start + poly.loop_total]
                    for v_idx in [lp.vertex_index]])

        flattened_ib = [i for sub in ib for i in sub]

        # 8. Split into CategoryBuffers
        category_stride_dict = d3d11_game_type.get_real_category_stride_dict()
        category_buffer_dict = {name: [] for name in d3d11_game_type.CategoryStrideDict}
        data_matrix = numpy.array([numpy.frombuffer(b, dtype=numpy.uint8) for b in indexed_vertices])
        stride_offset = 0
        for name, stride in category_stride_dict.items():
            category_buffer_dict[name] = data_matrix[:, stride_offset:stride_offset + stride].flatten()
            stride_offset += stride

        # print("length:", v_cnt)          
        ib = flattened_ib
        index_vertex_id_dict = None

        return ib, category_buffer_dict, index_vertex_id_dict
 


    @staticmethod
    def calc_index_vertex_buffer_unified(
        mesh:bpy.types.Mesh, 
        element_vertex_ndarray:numpy.ndarray, 
        obj:bpy.types.Object, 
        d3d11_game_type:D3D11GameType,
        dtype:numpy.dtype):
        '''
        [Universal mode] Standard graphics export logic
        --------------------------------------------------
        Core logic:
        - Treat "(data content + Blender original vertex index)" as the unique key.
        - Handle hard edges and UV seams automatically: if a vertex's normals/UVs differ across loops, it is automatically split into multiple game vertices.
        - Handle ShapeKey safety automatically: even if two points share coordinates, they are never merged as long as their Blender indices differ.
        
        Use cases:
        - The standard export pipeline of the vast majority of modern games.
        - Guarantees rendering correctness (normals, UVs, vertex colors).
        
        Cost:
        - The exported vertex count usually exceeds Blender's vertex count (because of splitting).
        - An index_vertex_id_dict mapping is returned so the original correspondence can be recovered when generating the ShapeKey Buffer later.

        Compute the IndexBuffer and CategoryBufferDict and return them
        If the model has Shape Keys, applying any Shape Key value between 0 and 1 never changes the vertex count due to vertex merging.
        '''
        # TimerUtils.Start("Calc IB VB")
        
        # Unified logic: always treat (data + vertex index) as the unique key
        # 1. Fully solve the ShapeKey problem: prevent vertices that coincide in the Basis but separate in Morphs from being wrongly merged.
        # 2. Keep the topology: ensure points that differ in Blender still differ after export.
        unique_map = collections.OrderedDict()
        
        # KEY: unique_vertex_index (buffer index), VALUE: first_loop_index
        # Record which original Loop each generated Buffer vertex maps to
        # This is critical for Shape Key normal export, since normals are stored on Loops
        unique_loop_map = {} 

        ib = []
        for poly in mesh.polygons:
            poly_indices = []
            for loop_index in range(poly.loop_start, poly.loop_start + poly.loop_total):
                loop = mesh.loops[loop_index]
                data = element_vertex_ndarray[loop.index].tobytes()
                
                # Core: the Key always includes the vertex_index (data, index)
                # Thus an index is shared only when "the data is fully identical" and "it is the same vertex (split only by hard edges/UVs)"
                key = (data, loop.vertex_index)
                
                if key in unique_map:
                    idx = unique_map[key]
                else:
                    idx = len(unique_map)
                    unique_map[key] = idx
                    unique_loop_map[idx] = loop.index
                
                poly_indices.append(idx)
            ib.append(poly_indices)
        
        # Extract the data the vertex buffer needs (i.e. the data part of each key)
        # vertex_data_list = [k[0] for k in unique_map.keys()]

        # Also build the index -> blender_loop_index mapping
        # This is critical for generating the ShapeKey Buffer later: we must know which Blender Loop the i-th generated point corresponds to
        # Loop Index can be converted to Vertex Index, but Vertex Index cannot be reversed into a unique Loop Index (Split Normals)
        vertex_data_list = []
        for i, (data_bytes, blender_v_idx) in enumerate(unique_map.keys()):
            vertex_data_list.append(data_bytes)
        
        index_loop_id_dict = unique_loop_map

        flattened_ib = [item for sublist in ib for item in sublist]
        # TimerUtils.End("Calc IB VB")

        # Recalculate TANGENT step
        indexed_vertices = ObjBufferHelper.average_normal_tangent_xxmi(
            obj=obj,
            indexed_vertices=vertex_data_list,
            flattened_ib=flattened_ib,
            d3d11_game_type=d3d11_game_type,
            dtype=dtype,
        )
        
        # Recalculate COLOR step
        indexed_vertices = ObjBufferHelper.average_normal_color(obj=obj, indexed_vertices=indexed_vertices, d3d11_game_type=d3d11_game_type,dtype=dtype)

        # (2) Convert to CategoryBufferDict
        # TimerUtils.Start("Calc CategoryBuffer")
        category_stride_dict = d3d11_game_type.get_real_category_stride_dict()
        category_buffer_dict:dict[str,list] = {}
        for categoryname,category_stride in d3d11_game_type.CategoryStrideDict.items():
            category_buffer_dict[categoryname] = []

        data_matrix = numpy.array([numpy.frombuffer(byte_data,dtype=numpy.uint8) for byte_data in indexed_vertices])
        stride_offset = 0
        for categoryname,category_stride in category_stride_dict.items():
            category_buffer_dict[categoryname] = data_matrix[:,stride_offset:stride_offset + category_stride].flatten()
            stride_offset += category_stride

        # Set ib and get ready to return
        ib = flattened_ib
        # YYSLS/SnowBreak need the face winding flipped during export
        if GlobalConfig.logic_name == LogicName.YYSLS or GlobalConfig.logic_name == LogicName.SnowBreak:
            flipped_indices = []
            # print(flattened_ib[0],flattened_ib[1],flattened_ib[2])
            for i in range(0, len(flattened_ib), 3):
                triangle = flattened_ib[i:i+3]
                flipped_triangle = triangle[::-1]
                flipped_indices.extend(flipped_triangle)
            # print(flipped_indices[0],flipped_indices[1],flipped_indices[2])
            ib = flipped_indices

        return ib, category_buffer_dict,index_loop_id_dict
