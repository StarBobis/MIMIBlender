import bpy
import itertools
import math
import numpy
import os

from bpy_extras.io_utils import unpack_list, axis_conversion

from ..utils.format_utils import Fatal, FormatUtils
from ..utils.mesh_utils import MeshUtils
from ..utils.obj_utils import ObjUtils
from ..workspace.texture_metadata_helper import TextureMetadataResolver
from ..utils.timer_utils import TimerUtils
from ..utils.vertexgroup_utils import VertexGroupUtils

from .global_config import GlobalConfig
from .global_properties import GlobalProperties
from .global_config import LogicName
from .gimi_high_fidelity_material import GIMIHighFidelityMaterial
from .gimi_body_outline import GIMIBodyOutline, OutlineError
from .d3d11_element import D3D11Element
from .raw_vertex_attributes import (
    RAW_COLOR_ALPHA_ATTRIBUTE_PREFIX,
    RAW_NORMAL_W_ATTRIBUTE_PREFIX,
    RAW_TANGENT_ATTRIBUTE_PREFIX,
    store_raw_bytes,
)


class MeshCreateHelper:

    @staticmethod
    def create_mesh_object(
        mesh_name:str,
        source_path:str,
        logic_name:str,
        gametypename:str,
        elements:list[D3D11Element],
        vb_data:dict,
        ib_data,
        vb_vertex_count:int,
        ib_count:int,
        ib_polygon_count:int,
        local_bounding_box_min:list | None = None,
        local_bounding_box_max:list | None = None,
        vertex_compression_params:list | None = None,
        import_collection:bpy.types.Collection | None = None,
        wwmi_shapekey_buffers:dict | None = None,
        shapekey_position_data:dict | None = None,
        wwmi_vertex_offset:int = 0,
        wwmi_vertex_count:int = -1,
        wwmi_vg_map:dict | None = None,
        wwmi_vg_offset:int = 0,
    ):
        TimerUtils.Start("Import 3Dmigoto Raw")
        print("导入模型: " + mesh_name)

        if vb_vertex_count == 0:
            raise Fatal("VB vertex count is zero, skip import.")
        if ib_count == 0:
            raise Fatal("IB count is zero, skip import.")

        if import_collection is None:
            import_collection = bpy.context.scene.collection

        mesh = bpy.data.meshes.new(mesh_name)
        obj = bpy.data.objects.new(mesh.name, mesh)

        MeshCreateHelper.set_import_coordinate(obj=obj)
        MeshCreateHelper.set_import_attributes(obj=obj, gametypename=gametypename)
        MeshCreateHelper.initialize_mesh(
            mesh=mesh,
            ib_data=ib_data,
            ib_count=ib_count,
            ib_polygon_count=ib_polygon_count,
            logic_name=logic_name,
            vb_vertex_count=vb_vertex_count,
        )

        blend_indices = {}
        blend_weights = {}
        texcoords = {}
        shapekeys = {}
        use_normals = False
        normals = []

        for element in elements:
            data = vb_data[element.ElementName]
            TimerUtils.Start(f"Process Element: {element.ElementName}")
            print("当前Element: " + element.ElementName)
            print("当前数据转换前 Shape: " + str(data.shape))

            # Blender has no native representation for these game-specific
            # components. Keep their source bytes on vertices before conversion.
            if element.SemanticName == "TANGENT":
                store_raw_bytes(mesh, RAW_TANGENT_ATTRIBUTE_PREFIX, data, element.ByteWidth)
            elif data.ndim > 1 and data.shape[1] >= 4:
                component_width = element.ByteWidth // data.shape[1]
                if element.SemanticName.startswith("NORMAL"):
                    store_raw_bytes(mesh, RAW_NORMAL_W_ATTRIBUTE_PREFIX, data[:, 3:4], component_width)
                elif element.SemanticName.startswith("COLOR"):
                    store_raw_bytes(mesh, RAW_COLOR_ALPHA_ATTRIBUTE_PREFIX + ":" + element.ElementName, data[:, 3:4], component_width)

            
            data = FormatUtils.apply_format_conversion(data, element.Format)
            print("当前数据转换后 Shape: " + str(data.shape))

            if element.SemanticName == "POSITION":
                if len(data[0]) == 4:
                    if not all(x[3] in (0, 1) for x in data):
                        raise Fatal('Positions are 4D')

                positions = [(x[0], x[1], x[2]) for x in data]
                mesh.vertices.foreach_set('co', unpack_list(positions))
            elif element.SemanticName.startswith("COLOR"):
                # 用 numpy 向量化构建 (num_loops, 4) 的 RGBA 数组，再用 foreach_set 批量写入。
                # 避免逐元素 Python 循环——在 Blender 5.1 中 vertex_colors 兼容层极慢。
                num_loops = len(mesh.loops)
                loop_vertex_indices = numpy.empty(num_loops, dtype=numpy.int32)
                mesh.loops.foreach_get('vertex_index', loop_vertex_indices)

                colors_flat = numpy.zeros((num_loops, 4), dtype=numpy.float32)
                if data.ndim > 1:
                    actual_channels = min(data.shape[1], 4)
                    colors_flat[:, :actual_channels] = data[loop_vertex_indices, :actual_channels].astype(numpy.float32)
                else:
                    colors_flat[:, 0] = data[loop_vertex_indices].astype(numpy.float32)

                # WWMI/EFMI 使用 FLOAT_COLOR，其他游戏使用 BYTE_COLOR。
                color_type = 'FLOAT_COLOR' if logic_name in (LogicName.WWMI, LogicName.EFMI) else 'BYTE_COLOR'
                color_attr = mesh.color_attributes.new(name=element.ElementName, type=color_type, domain='CORNER')
                color_attr.data.foreach_set('color', colors_flat.ravel())
            elif element.SemanticName == "BLENDINDICES":
                if data.ndim == 1:
                    blend_indices[element.SemanticIndex] = numpy.array([(x,) for x in data])
                else:
                    blend_indices[element.SemanticIndex] = data
            elif element.SemanticName == "BLENDWEIGHT" or element.SemanticName == "BLENDWEIGHTS":
                blend_weights[element.SemanticIndex] = data
            elif element.SemanticName.startswith("TEXCOORD"):
                texcoords[element.SemanticIndex] = data
            elif element.SemanticName.startswith("SHAPEKEY"):
                shapekeys[element.SemanticIndex] = data
            elif element.SemanticName.startswith("NORMAL"):
                use_normals = True
                if logic_name == LogicName.YYSLS:
                    print("燕云十六声法线处理")
                    normals = [(x[0] * 2 - 1, x[1] * 2 - 1, x[2] * 2 - 1) for x in data]
                elif logic_name == LogicName.EFMI and element.Format == "R32_UINT":
                    print("终末地压缩法线处理(Endfield Packed Normals) - 使用 TBNCodec")
                    raw = data
                    if raw.dtype != numpy.uint32:
                        raw = raw.view(numpy.uint32)
                    if raw.ndim > 1:
                        raw = raw[:, 0]

                    from ..utils.tbn_codec import TBNCodec
                    normals = TBNCodec.decode_octahedral_r32_uint(raw).tolist()
                    print("终末地压缩法线处理完成")
                else:
                    normals = [(x[0], x[1], x[2]) for x in data]
            elif element.SemanticName == "ENCODEDDATA":
                if logic_name == LogicName.EFMI:
                    print("终末地 ENCODEDDATA 处理 - 使用 TBNCodec 解码 TBN 数据")
                    use_normals = True

                    raw = data
                    if raw.dtype != numpy.uint32:
                        raw = raw.view(numpy.uint32)
                    if raw.ndim > 1:
                        raw = raw[:, 0]

                    from ..utils.tbn_codec import TBNCodec
                    normals = TBNCodec.decode_octahedral_r32_uint(raw).tolist()
                    print("终末地 ENCODEDDATA 处理完成")
                else:
                    print(f"警告: ENCODEDDATA 元素仅在 EFMI 格式中支持，当前游戏类型: {logic_name}")
            elif element.SemanticName == "TANGENT":
                pass
            elif element.SemanticName == "BINORMAL":
                pass
            elif element.SemanticName == "BITANGENT":
                pass
            elif element.SemanticName == "RAWDATA":
                # EFMI 逆向产物中的保留区字节（input layout 未声明的 stride
                # 间隙，EFMI-Tools fill_missing_semantics 标记；逆向端正式
                # 命名为 RAWDATA）：读取以维持 stride 对齐与顶点数一致，
                # 不建立任何 Blender 属性——它没有可映射的语义。
                pass
            else:
                raise Fatal("Unknown ElementName: " + element.ElementName)
            
            TimerUtils.End(f"Process Element: {element.ElementName}")

        if len(blend_weights) == 0 and len(blend_indices) != 0:
            print("检测到BLENDWEIGHTS为空，但是含有BLENDINDICES数据，特殊情况，默认补充1,0,0,0的BLENDWEIGHTS")
            for semantic_index, blendindices_tuple in blend_indices.items():
                new_list = []
                for _indices in blendindices_tuple:
                    new_list.append((1.0, 0, 0, 0))
                blend_weights[semantic_index] = new_list

        MeshCreateHelper.import_uv_layers(mesh, obj, texcoords)

        print("导入顶点组")
        # Merged模式：用VGMap将local blend index重映射为global bone ID
        if wwmi_vg_map:
            import types as _types
            _vg_component = _types.SimpleNamespace(
                vg_map={str(k): int(v) for k, v in wwmi_vg_map.items()},
                vg_offset=wwmi_vg_offset,
            )
        else:
            _vg_component = None
        MeshCreateHelper.import_vertex_groups(mesh, obj, blend_indices, blend_weights, _vg_component)
        print("导入顶点组完毕")

        MeshCreateHelper.import_shapekeys(mesh, obj, shapekeys)

        if shapekey_position_data:
            MeshCreateHelper.import_shapekey_positions(mesh, obj, shapekey_position_data)

        if wwmi_shapekey_buffers is not None:
            MeshCreateHelper.import_shapekeys_wwmi(mesh, obj, wwmi_shapekey_buffers, wwmi_vertex_offset, wwmi_vertex_count)

        mesh.validate(verbose=False, clean_customdata=False)
        mesh.update()
        if use_normals:
            MeshUtils.set_import_normals_v2(mesh=mesh, normals=normals)

        MeshCreateHelper.create_bsdf_with_diffuse_linked(
            obj=obj,
            mesh_name=mesh_name,
            directory=os.path.dirname(source_path),
            logic_name=logic_name,
        )

        if logic_name == LogicName.WWMI or logic_name == LogicName.NTEMI or logic_name == LogicName.SnowBreak:
            obj.rotation_euler[0] = 0
            obj.rotation_euler[1] = 0
            obj.rotation_euler[2] = math.radians(180)
            obj.scale = (0.01, 0.01, 0.01)

        print("导入模型完成: " + logic_name)
        if LogicName.is_zzmi_family(logic_name) or logic_name == LogicName.Naraka:
            obj.rotation_euler[0] = 0
            obj.rotation_euler[1] = 0
            obj.rotation_euler[2] = 0

        if logic_name == LogicName.EFMI:
            obj.rotation_euler[0] = 0
            obj.rotation_euler[1] = 0
            obj.rotation_euler[2] = 0

        if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            if GlobalProperties.import_skip_empty_vertex_groups():
                VertexGroupUtils.remove_unused_vertex_groups(obj)

        import_collection.objects.link(obj)
        ObjUtils.select_obj(obj)

        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

        if GlobalProperties.use_mirror_workflow():
            print(f"非镜像工作流：对 {obj.name} 应用镜像变换和面朝向翻转")
            ObjUtils.apply_mirror_workflow(obj)

        bpy.context.view_layer.update()
        if not bpy.app.background:
            try:
                if bpy.ops.wm.redraw_timer.poll():
                    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            except RuntimeError:
                pass

        TimerUtils.End("Import 3Dmigoto Raw")
        return obj

    @staticmethod
    def set_import_attributes(obj, gametypename:str):
        obj["3DMigoto:RecalculateTANGENT"] = False
        obj["3DMigoto:RecalculateCOLOR"] = False
        obj['3DMigoto:GameTypeName'] = gametypename

    @staticmethod
    def set_import_coordinate(obj):
        obj.matrix_world = axis_conversion(from_forward='-Z', from_up='Y').to_4x4()

    @staticmethod
    def initialize_mesh(mesh, ib_data, ib_count:int, ib_polygon_count:int, logic_name:str, vb_vertex_count:int):
        if logic_name == LogicName.WWMI or logic_name == LogicName.NTEMI or logic_name == LogicName.YYSLS or logic_name == LogicName.SnowBreak:
            flipped_indices = []
            for i in range(0, len(ib_data), 3):
                triangle = ib_data[i:i + 3]
                flipped_indices.extend(triangle[::-1])
            ib_data = flipped_indices

        mesh.loops.add(ib_count)
        mesh.polygons.add(ib_polygon_count)
        mesh.loops.foreach_set('vertex_index', ib_data)
        mesh.polygons.foreach_set('loop_start', [x * 3 for x in range(ib_polygon_count)])
        mesh.polygons.foreach_set('loop_total', [3] * ib_polygon_count)
        mesh.vertices.add(vb_vertex_count)
        mesh.update()

    @staticmethod
    def import_uv_layers(mesh, obj, texcoords):
        loops = mesh.loops
        vertex_indices = numpy.array([loop.vertex_index for loop in loops], dtype=numpy.int32)

        for texcoord, data in sorted(texcoords.items()):
            data_np = numpy.array(data, dtype=numpy.float32)
            dim = data_np.shape[1]

            if dim == 4:
                components_list = ('xy', 'zw')
            elif dim == 2:
                components_list = ('xy',)
            else:
                raise Fatal(f'Unhandled TEXCOORD dimension: {dim}')

            cmap = {'x': 0, 'y': 1, 'z': 2, 'w': 3}

            for components in components_list:
                uv_name = f'TEXCOORD{texcoord if texcoord else ""}.{components}'
                mesh.uv_layers.new(name=uv_name)
                blender_uvs = mesh.uv_layers[uv_name]

                c0 = cmap[components[0]]
                c1 = cmap[components[1]]

                uvs = numpy.empty((len(data_np), 2), dtype=numpy.float32)
                uvs[:, 0] = data_np[:, c0]
                uvs[:, 1] = 1.0 - data_np[:, c1]

                max_index = numpy.max(vertex_indices) if len(vertex_indices) > 0 else 0
                if max_index >= len(uvs):
                    print(f"Warning: UV data too short. Max index: {max_index}, UV data len: {len(uvs)}.Padding with zeros.")
                    padding_length = max_index - len(uvs) + 1
                    padding = numpy.zeros((padding_length, 2), dtype=numpy.float32)
                    uvs = numpy.vstack((uvs, padding))

                uv_array = uvs[vertex_indices].ravel()
                blender_uvs.data.foreach_set('uv', uv_array)

    @staticmethod
    def import_vertex_groups(mesh, obj, blend_indices, blend_weights, component):
        for semantic_index, bone_indices_list in blend_indices.items():
            arr = numpy.asarray(bone_indices_list)
            if arr.dtype.kind == 'f':
                arr = numpy.rint(arr).astype(numpy.int64)
            else:
                arr = arr.astype(numpy.int64, copy=False)

            arr[arr == 65535] = -1
            blend_indices[semantic_index] = arr

        assert len(blend_indices) == len(blend_weights)
        if blend_indices:
            max_valid_group_id = -1
            for bone_indices_array in blend_indices.values():
                flattened_indices = numpy.asarray(bone_indices_array, dtype=numpy.int64).ravel()
                non_negative_indices = flattened_indices[flattened_indices >= 0]
                if non_negative_indices.size > 0:
                    max_valid_group_id = max(max_valid_group_id, int(non_negative_indices.max()))

            if max_valid_group_id < 0:
                return

            if component is None:
                num_vertex_groups = max_valid_group_id + 1
            else:
                mapped_group_ids = {int(group_id) for group_id in component.vg_map.values()}
                vg_offset = getattr(component, 'vg_offset', 0)
                max_global = max(mapped_group_ids) if mapped_group_ids else -1
                max_global = max(max_global, vg_offset + max_valid_group_id)
                if max_global < 0:
                    return
                num_vertex_groups = max_global + 1

            print("num_vertex_groups: " + str(num_vertex_groups))

            if num_vertex_groups > 10000:
                raise Fatal("检测到在当前导入的数据类型" + obj.get('3DMigoto:GameTypeName', "") + "描述下，BLENDINDICES顶点组数量为: " + str(num_vertex_groups) + " 基本不可能是正常情况，请更换其他数据类型重新导入")

            vertex_group_by_id = {}
            for i in range(num_vertex_groups):
                vertex_group_by_id[i] = obj.vertex_groups.new(name=str(i))

            for vertex in mesh.vertices:
                for semantic_index in sorted(blend_indices.keys()):
                    for i, w in zip(blend_indices[semantic_index][vertex.index], blend_weights[semantic_index][vertex.index]):
                        if i < 0 or w == 0.0:
                            continue

                        if component is None:
                            target_group_id = int(i)
                        else:
                            mapped_group_id = component.vg_map.get(str(int(i)))
                            if mapped_group_id is None:
                                target_group_id = component.vg_offset + int(i)
                            else:
                                target_group_id = int(mapped_group_id)

                        if target_group_id < 0:
                            continue

                        vertex_group = vertex_group_by_id.get(target_group_id)
                        if vertex_group is None:
                            vertex_group = obj.vertex_groups.get(str(target_group_id))
                            if vertex_group is None:
                                vertex_group = obj.vertex_groups.new(name=str(target_group_id))
                            vertex_group_by_id[target_group_id] = vertex_group

                        vertex_group.add((vertex.index,), float(w), 'REPLACE')

    @staticmethod
    def import_shapekeys(mesh, obj, shapekeys):
        if not shapekeys:
            return

        basis = obj.shape_key_add(name='Basis')
        basis.interpolation = 'KEY_LINEAR'
        obj.data.shape_keys.use_relative = True
        try:
            basis.value = 0.0
        except Exception:
            pass

        vert_count = len(obj.data.vertices)
        basis_co = numpy.empty(vert_count * 3, dtype=numpy.float32)
        basis.data.foreach_get('co', basis_co)
        basis_co = basis_co.reshape(-1, 3)

        for sk_id, offsets in shapekeys.items():
            new_sk = obj.shape_key_add(name=f'Deform {sk_id}')
            new_sk.interpolation = 'KEY_LINEAR'
            try:
                new_sk.value = 0.0
            except Exception:
                pass

            offset_arr = numpy.array(offsets, dtype=numpy.float32).reshape(-1, 3)
            new_co = basis_co + offset_arr
            new_sk.data.foreach_set('co', new_co.ravel())
            try:
                new_sk.value = 0.0
            except Exception:
                pass
            del new_sk

        del basis_co, offset_arr, new_co

    @staticmethod
    def import_shapekey_positions(mesh, obj, shapekey_position_data: dict):
        '''
        导入 ShapeKeyPositionBufferList 形态的命名形态键。

        每个条目存储的是与基础 POSITION 同一坐标空间下的绝对顶点坐标
        （布局与 Position 分类Buffer一致），因此直接作为相对形态键的 co 写入，
        与 Basis 的写入方式完全相同。
        '''
        if not shapekey_position_data:
            return

        if obj.data.shape_keys is None:
            basis = obj.shape_key_add(name='Basis')
            basis.interpolation = 'KEY_LINEAR'
            obj.data.shape_keys.use_relative = True
            try:
                basis.value = 0.0
            except Exception:
                pass

        vert_count = len(obj.data.vertices)

        for shapekey_name, position_data in shapekey_position_data.items():
            co = numpy.asarray(position_data, dtype=numpy.float32)
            if co.ndim == 1:
                co = co.reshape(-1, 3)
            elif co.ndim == 2 and co.shape[1] > 3:
                # 与 POSITION 元素一致，仅取 xyz 分量。
                co = co[:, :3]

            if co.ndim != 2 or co.shape[1] != 3 or co.shape[0] != vert_count:
                print(
                    "ShapeKeyPosition 导入：形态键 " + str(shapekey_name)
                    + " 顶点数据形状 " + str(co.shape) + " 与网格顶点数 " + str(vert_count)
                    + " 不一致，已跳过"
                )
                continue

            new_sk = obj.shape_key_add(name=shapekey_name if shapekey_name else "ShapeKey")
            new_sk.interpolation = 'KEY_LINEAR'
            new_sk.data.foreach_set('co', numpy.ascontiguousarray(co).ravel())
            try:
                new_sk.value = 0.0
            except Exception:
                pass
            del new_sk

        print("ShapeKeyPosition 导入完成，共导入 " + str(len(shapekey_position_data)) + " 个命名形态键")

    @staticmethod
    def import_shapekeys_wwmi(mesh, obj, shapekey_buffers: dict, vertex_offset: int, vertex_count: int):
        sk_offset_raw = shapekey_buffers.get("ShapeKeyOffset")
        sk_vertex_id_raw = shapekey_buffers.get("ShapeKeyVertexId")
        sk_vertex_offset_raw = shapekey_buffers.get("ShapeKeyVertexOffset")

        if sk_offset_raw is None or sk_vertex_id_raw is None or sk_vertex_offset_raw is None:
            return

        offsets = sk_offset_raw.view(numpy.uint32)
        if len(offsets) < 128:
            return
        offsets = offsets[:128]

        vertex_id_buffer = sk_vertex_id_raw.view(numpy.uint32)
        vertex_offset_buffer = sk_vertex_offset_raw.view(numpy.float16)

        total_entries = int(offsets[127])
        if total_entries == 0:
            return

        if obj.data.shape_keys is None:
            basis = obj.shape_key_add(name='Basis')
            basis.interpolation = 'KEY_LINEAR'
            obj.data.shape_keys.use_relative = True
            try:
                basis.value = 0.0
            except Exception:
                pass
        else:
            basis = obj.data.shape_keys.key_blocks.get('Basis') or obj.data.shape_keys.key_blocks[0]

        vert_count = len(obj.data.vertices)
        basis_co = numpy.empty(vert_count * 3, dtype=numpy.float32)
        basis.data.foreach_get('co', basis_co)
        basis_co = basis_co.reshape(-1, 3)

        print(f"WWMI ShapeKey 导入：{total_entries} 个受影响顶点条目，vertex_offset={vertex_offset}")

        for sk_id in range(127):
            first_entry = int(offsets[sk_id])
            last_entry = int(offsets[sk_id + 1])
            if first_entry >= last_entry:
                break

            entries = numpy.arange(first_entry, last_entry, dtype=numpy.int64)
            valid_mask = entries < len(vertex_id_buffer)
            entries = entries[valid_mask]
            if len(entries) == 0:
                continue

            global_vids = vertex_id_buffer[entries].astype(numpy.int64)
            local_vids = global_vids - vertex_offset
            local_mask = (local_vids >= 0) & (local_vids < vertex_count)
            entries = entries[local_mask]
            local_vids = local_vids[local_mask]
            if len(entries) == 0:
                continue

            dx_idx = entries * 6
            dy_idx = dx_idx + 1
            dz_idx = dx_idx + 2

            valid_idx_mask = dz_idx < len(vertex_offset_buffer)
            entries = entries[valid_idx_mask]
            local_vids = local_vids[valid_idx_mask]
            dx_idx = entries * 6
            dy_idx = dx_idx + 1
            dz_idx = dx_idx + 2

            new_co = basis_co.copy()
            numpy.add.at(new_co[:, 0], local_vids, vertex_offset_buffer[dx_idx].astype(numpy.float32))
            numpy.add.at(new_co[:, 1], local_vids, vertex_offset_buffer[dy_idx].astype(numpy.float32))
            numpy.add.at(new_co[:, 2], local_vids, vertex_offset_buffer[dz_idx].astype(numpy.float32))

            sk = obj.shape_key_add(name=f'Deform {sk_id}')
            sk.interpolation = 'KEY_LINEAR'
            sk.data.foreach_set('co', new_co.ravel())
            try:
                sk.value = 0.0
            except Exception:
                pass

        print(f"WWMI ShapeKey 导入完成")

    @staticmethod
    def get_import_texture_paths(mesh_name:str, directory:str):
        if "." in mesh_name:
            mesh_name_split = str(mesh_name).split(".")[0].split("-")
        else:
            mesh_name_split = str(mesh_name).split("-")

        if len(mesh_name_split) < 2:
            return None, None

        texture_prefix = mesh_name_split[0] + "-" + mesh_name_split[1] + "-"

        texture_path = MeshCreateHelper._find_gimi_texture(texture_prefix, "-DiffuseMap", directory)
        normal_path = MeshCreateHelper._find_gimi_texture(texture_prefix, "-NormalMap", directory)

        return texture_path, normal_path

    @staticmethod
    def get_gimi_lightmap_path(mesh_name: str, directory: str):
        if "." in mesh_name:
            mesh_name_split = str(mesh_name).split(".")[0].split("-")
        else:
            mesh_name_split = str(mesh_name).split("-")
        if len(mesh_name_split) < 2:
            return None
        texture_prefix = mesh_name_split[0] + "-" + mesh_name_split[1] + "-"
        return MeshCreateHelper._find_gimi_texture(texture_prefix, "-LightMap", directory)

    @staticmethod
    def _find_gimi_texture(texture_prefix: str, texture_stem: str, directory: str):
        """Resolve GIMI maps across the formats emitted by different dumpers."""
        # DDS/PNG/TGA preserve the alpha masks consumed by the GIMI shader.
        # JPG remains a compatibility fallback for ordinary material imports.
        for extension in (".dds", ".png", ".tga", ".jpg", ".jpeg"):
            path = TextureMetadataResolver.find_texture(
                texture_prefix, texture_stem + extension, directory
            )
            if path is not None:
                return path
        return None

    @staticmethod
    def get_material_output_node(nodes):
        output = nodes.get("Material Output")
        if output is None:
            output = next((node for node in nodes if node.bl_idname == 'ShaderNodeOutputMaterial'), None)
        if output is None:
            output = nodes.new(type='ShaderNodeOutputMaterial')
        return output

    @staticmethod
    def get_principled_bsdf_node(material):
        nodes = material.node_tree.nodes
        links = material.node_tree.links

        bsdf = nodes.get("原理化 BSDF")
        if not bsdf:
            bsdf = nodes.get("原理化BSDF")
        if not bsdf:
            bsdf = nodes.get("Principled BSDF")
        if not bsdf:
            bsdf = next((node for node in nodes if node.bl_idname == 'ShaderNodeBsdfPrincipled'), None)
        if not bsdf:
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)
            output = MeshCreateHelper.get_material_output_node(nodes)
            if not any(link.from_node == bsdf and link.to_node == output for link in links):
                links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

        return bsdf

    @staticmethod
    def apply_diffuse_texture(node_tree, bsdf, texture_path:str, use_alpha:bool=True):
        tex_image = node_tree.nodes.new('ShaderNodeTexImage')
        tex_image.image = bpy.data.images.load(texture_path)
        tex_image.image.alpha_mode = "NONE"
        tex_image.location.x = bsdf.location.x - 400
        tex_image.location.y = bsdf.location.y
        node_tree.links.new(bsdf.inputs['Base Color'], tex_image.outputs['Color'])
        if use_alpha:
            node_tree.links.new(bsdf.inputs['Alpha'], tex_image.outputs['Alpha'])
        return tex_image

    @staticmethod
    def create_identity_v_normal_map(node_tree, bsdf, normal_path:str):
        norm_image = node_tree.nodes.new('ShaderNodeTexImage')
        norm_image.image = bpy.data.images.load(normal_path)
        norm_image.location.x = bsdf.location.x - 1200
        norm_image.location.y = bsdf.location.y - 300
        norm_image.image.colorspace_settings.is_data = True
        norm_image.image.colorspace_settings.name = 'Non-Color'

        norm_separate = node_tree.nodes.new('ShaderNodeSeparateColor')
        norm_separate.location.x = bsdf.location.x - 800
        norm_separate.location.y = bsdf.location.y - 450
        if hasattr(norm_separate, 'mode'):
            norm_separate.mode = 'RGB'

        rgb_curve = node_tree.nodes.new('ShaderNodeRGBCurve')
        rgb_curve.location.x = bsdf.location.x - 800
        rgb_curve.location.y = bsdf.location.y - 100
        if 'Fac' in rgb_curve.inputs:
            rgb_curve.inputs['Fac'].default_value = 1.0
        if hasattr(rgb_curve, 'mapping'):
            rgb_curve.mapping.initialize()
            green_curve = rgb_curve.mapping.curves[1]
            if len(green_curve.points) >= 2:
                green_curve.points[0].location = (0.0, 1.0)
                green_curve.points[1].location = (1.0, 0.0)
            rgb_curve.mapping.update()

        norm_map = node_tree.nodes.new('ShaderNodeNormalMap')
        norm_map.location.x = bsdf.location.x - 400
        norm_map.location.y = bsdf.location.y - 100
        norm_map.uv_map = "TEXCOORD.xy"
        if hasattr(norm_map, 'space'):
            norm_map.space = 'TANGENT'
        if 'Strength' in norm_map.inputs:
            norm_map.inputs['Strength'].default_value = 1.0

        node_tree.links.new(norm_separate.inputs['Color'], norm_image.outputs['Color'])
        node_tree.links.new(rgb_curve.inputs['Color'], norm_image.outputs['Color'])
        node_tree.links.new(bsdf.inputs['Alpha'], norm_separate.outputs['Blue'])
        node_tree.links.new(norm_map.inputs['Color'], rgb_curve.outputs['Color'])
        node_tree.links.new(bsdf.inputs['Normal'], norm_map.outputs['Normal'])

    @staticmethod
    def create_standard_normal_map(node_tree, bsdf, normal_path:str):
        norm_image = node_tree.nodes.new('ShaderNodeTexImage')
        norm_image.image = bpy.data.images.load(normal_path)
        norm_image.location.x = bsdf.location.x - 800
        norm_image.location.y = bsdf.location.y - 400
        norm_image.image.colorspace_settings.is_data = True
        norm_image.image.colorspace_settings.name = 'Non-Color'

        norm_map = node_tree.nodes.new('ShaderNodeNormalMap')
        norm_map.location.x = bsdf.location.x - 400
        norm_map.location.y = bsdf.location.y - 400
        norm_map.uv_map = "TEXCOORD.xy"
        node_tree.links.new(norm_map.inputs['Color'], norm_image.outputs['Color'])
        node_tree.links.new(bsdf.inputs['Normal'], norm_map.outputs['Normal'])

    @staticmethod
    def create_zzmi_gimi_normal_map(node_tree, bsdf, normal_path:str):
        norm_image = node_tree.nodes.new('ShaderNodeTexImage')
        norm_image.image = bpy.data.images.load(normal_path)
        norm_image.location.x = bsdf.location.x - 1200
        norm_image.location.y = bsdf.location.y - 400
        norm_image.image.colorspace_settings.is_data = True
        norm_image.image.colorspace_settings.name = 'Non-Color'

        norm_separate = node_tree.nodes.new('ShaderNodeSeparateColor')
        norm_separate.location.x = bsdf.location.x - 800
        norm_separate.location.y = bsdf.location.y - 400
        node_tree.links.new(norm_separate.inputs['Color'], norm_image.outputs['Color'])

        norm_combine = node_tree.nodes.new('ShaderNodeCombineColor')
        norm_combine.location.x = bsdf.location.x - 600
        norm_combine.location.y = bsdf.location.y - 400
        node_tree.links.new(norm_combine.inputs['Red'], norm_separate.outputs['Red'])
        node_tree.links.new(norm_combine.inputs['Green'], norm_separate.outputs['Green'])

        norm_math = node_tree.nodes.new('ShaderNodeMath')
        norm_math.location.x = bsdf.location.x - 400
        norm_math.location.y = bsdf.location.y - 600
        norm_math.operation = 'SQRT'
        norm_math.use_clamp = True

        norm_math_2 = node_tree.nodes.new('ShaderNodeMath')
        norm_math_2.location.x = bsdf.location.x - 600
        norm_math_2.location.y = bsdf.location.y - 800
        norm_math_2.operation = 'SUBTRACT'
        norm_math_2.inputs[0].default_value = 1.0
        norm_math_2.use_clamp = True

        norm_math_r2 = node_tree.nodes.new('ShaderNodeMath')
        norm_math_r2.location.x = bsdf.location.x - 800
        norm_math_r2.location.y = bsdf.location.y - 600
        norm_math_r2.operation = 'POWER'
        norm_math_r2.inputs[1].default_value = 2.0

        norm_math_g2 = node_tree.nodes.new('ShaderNodeMath')
        norm_math_g2.location.x = bsdf.location.x - 800
        norm_math_g2.location.y = bsdf.location.y - 800
        norm_math_g2.operation = 'POWER'
        norm_math_g2.inputs[1].default_value = 2.0

        norm_math_add_r_g = node_tree.nodes.new('ShaderNodeMath')
        norm_math_add_r_g.location.x = bsdf.location.x - 600
        norm_math_add_r_g.location.y = bsdf.location.y - 600
        norm_math_add_r_g.operation = 'ADD'

        node_tree.links.new(norm_math_r2.inputs[0], norm_separate.outputs['Red'])
        node_tree.links.new(norm_math_g2.inputs[0], norm_separate.outputs['Green'])
        node_tree.links.new(norm_math_add_r_g.inputs[0], norm_math_r2.outputs['Value'])
        node_tree.links.new(norm_math_add_r_g.inputs[1], norm_math_g2.outputs['Value'])
        node_tree.links.new(norm_math_2.inputs[1], norm_math_add_r_g.outputs['Value'])
        node_tree.links.new(norm_math.inputs[0], norm_math_2.outputs['Value'])
        node_tree.links.new(norm_combine.inputs['Blue'], norm_math.outputs['Value'])

        norm_map = node_tree.nodes.new('ShaderNodeNormalMap')
        norm_map.location.x = bsdf.location.x - 400
        norm_map.location.y = bsdf.location.y - 400
        norm_map.uv_map = "TEXCOORD.xy"
        node_tree.links.new(norm_map.inputs['Color'], norm_combine.outputs['Color'])
        node_tree.links.new(bsdf.inputs['Normal'], norm_map.outputs['Normal'])

    @staticmethod
    def apply_normal_texture(node_tree, bsdf, normal_path:str, logic_name:str):
        if logic_name == LogicName.IdentityV:
            MeshCreateHelper.create_identity_v_normal_map(node_tree, bsdf, normal_path)
            return

        if not LogicName.is_zzmi_family(logic_name) and logic_name != LogicName.GIMI:
            MeshCreateHelper.create_standard_normal_map(node_tree, bsdf, normal_path)
            return

        MeshCreateHelper.create_zzmi_gimi_normal_map(node_tree, bsdf, normal_path)

    @staticmethod
    def assign_material(obj, material):
        if obj.data.materials:
            obj.data.materials[0] = material
        else:
            obj.data.materials.append(material)

    @staticmethod
    def create_bsdf_with_diffuse_linked(obj, mesh_name:str, directory:str, logic_name:str | None = None):
        material_name = f"{mesh_name}_Material"
        if logic_name is None:
            logic_name = GlobalConfig.logic_name
        texture_path, normal_path = MeshCreateHelper.get_import_texture_paths(mesh_name, directory)

        high_fidelity_gimi = (
            GlobalProperties.gimi_high_fidelity_rendering()
            and GIMIHighFidelityMaterial.is_genshin_workspace(logic_name=logic_name)
        )
        if texture_path is None and not high_fidelity_gimi:
            return

        material = bpy.data.materials.new(name=material_name)
        material.use_nodes = True

        if high_fidelity_gimi:
            try:
                GIMIHighFidelityMaterial.build_character(
                    material=material,
                    diffuse_path=texture_path,
                    normal_path=normal_path,
                    lightmap_path=MeshCreateHelper.get_gimi_lightmap_path(mesh_name, directory),
                    directory=directory,
                )
                MeshCreateHelper.assign_material(obj, material)
                # The current high-fidelity builder only targets Body/Clothes.
                # Hash-named GIMI texture dumps carry no reliable Body token.
                try:
                    GIMIBodyOutline.ensure(
                        obj,
                        enabled=GlobalProperties.gimi_body_outline_enabled(),
                        width_ratio=GlobalProperties.gimi_body_outline_width_ratio(),
                    )
                except OutlineError as error:
                    print(f"[GIMI Outline] WARNING: {obj.name}: {error}")
                return
            except Exception as error:
                # High-fidelity mode must never silently become a Principled
                # material.  Preserve the error for the importer to report.
                raise Fatal(f"GIMI 高拟真节点构建失败: {error}") from error

        bsdf = MeshCreateHelper.get_principled_bsdf_node(material)
        MeshCreateHelper.apply_diffuse_texture(
            node_tree=material.node_tree,
            bsdf=bsdf,
            texture_path=texture_path,
            use_alpha=logic_name != LogicName.IdentityV,
        )

        if normal_path is not None and GlobalProperties.use_normal_map():
            MeshCreateHelper.apply_normal_texture(
                node_tree=material.node_tree,
                bsdf=bsdf,
                normal_path=normal_path,
                logic_name=logic_name,
            )

        MeshCreateHelper.assign_material(obj, material)
