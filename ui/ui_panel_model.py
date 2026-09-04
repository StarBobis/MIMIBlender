import bpy
import bmesh
import numpy

from bpy.props import BoolProperty,  CollectionProperty

from ..utils.obj_utils import ObjUtils
from ..utils.collection_utils import CollectionUtils
from ..utils.vertexgroup_utils import VertexGroupUtils
from ..utils.shapekey_utils import ShapeKeyUtils
from ..utils.algorithm_utils import AlgorithmUtils

def keep_one_triangle_in_mesh_object(obj):
    if obj.type != 'MESH':
        raise ValueError("Selected object is not a mesh.")

    mesh = obj.data
    if len(mesh.polygons) == 0:
        raise ValueError(obj.name + " has no faces.")

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    tri_face = next((face for face in bm.faces if len(face.verts) == 3), None)
    if tri_face is None:
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        tri_face = bm.faces[0] if bm.faces else None

    if tri_face is None:
        bm.free()
        raise ValueError(obj.name + " has no triangle face.")

    keep_verts = set(tri_face.verts)
    bmesh.ops.delete(
        bm,
        geom=[face for face in bm.faces if face != tri_face],
        context='FACES_ONLY',
    )
    bmesh.ops.delete(
        bm,
        geom=[vert for vert in bm.verts if vert not in keep_verts],
        context='VERTS',
    )

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.validate()
    mesh.update()


class ModelSplitByLoosePart(bpy.types.Operator):
    bl_idname = "panel_model.split_by_loose_part"
    bl_label = "根据UV松散块儿分割模型"
    bl_description = "功能与Edit界面的Split => Split by Loose Parts相似，但是分割模型为松散块儿并放入新集合。"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        # 创建一个新的集合，以原对象名命名
        collection_name = f"{obj.name}_LooseParts"
        ObjUtils.split_obj_by_loose_parts_to_collection(obj=obj,collection_name=collection_name)

        self.report({'INFO'}, "根据UV松散块儿分割模型成功!")
        return {'FINISHED'}


class ModelSplitByVertexGroup(bpy.types.Operator):
    bl_idname = "panel_model.split_by_vertex_group"
    bl_label = "根据共享与孤立顶点组分割模型"
    bl_description = "把模型根据共享的顶点组分开，方便快速分离身体上的小物件，方便后续刷权重不受小物件影响。"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        # 创建一个新的集合，以原对象名命名
        collection_name = f"{obj.name}_Splits"
        ObjUtils.split_obj_by_loose_parts_to_collection(obj=obj,collection_name=collection_name)
        
        collection = CollectionUtils.get_collection_by_name(collection_name=collection_name)

        # 获取当前选中集合的所有obj
        CollectionUtils.select_collection_objects(collection)

        # 放列表里备用
        selected_objects = bpy.context.selected_objects

        number_vgnameset_dict = {}
        number_objlist_dict = {}

        for obj in selected_objects:

            # 先清除相同的顶点组
            VertexGroupUtils.remove_unused_vertex_groups(obj)
             
            # 获取对象的顶点组名称列表
            vertex_group_names = [vg.name for vg in obj.vertex_groups]

            vgname_set = set()

            # 遍历每个顶点组名称
            for vgname in vertex_group_names:
                    vgname_set.add(vgname)

            if len(number_vgnameset_dict) == 0:
                # 一个都没有的时候直接放进去
                number_vgnameset_dict[1] = vgname_set
                number_objlist_dict[1] = [obj]
            else:
                exists = False
                for number, tmp_vgname_set in number_vgnameset_dict.items():
                    # 取交集
                    vgname_jiaoji = tmp_vgname_set & vgname_set

                    if len(vgname_jiaoji) != 0:
                        # 取全集
                        vgname_quanji = tmp_vgname_set.union(vgname_set)

                        # 如果有交集就把全集放进来
                        number_vgnameset_dict[number] = vgname_quanji

                        exists = True
                        # 如果有交集，用全集替换后直接退出循环即可
                        break
                
                if not exists:
                    # 如果没找到交集，就新增一个进去
                    number_objlist_dict[len(number_objlist_dict) + 1] = [obj]
                    number_vgnameset_dict[len(number_vgnameset_dict) + 1] = vgname_set
                else:
                    # 如果找到了交集，就把这个对象放进去
                    number_objlist_dict[number].append(obj)

        # 输出查看一下 
        # print(number_vgnameset_dict.keys())
        # print("======================================")
        # for number in number_vgnameset_dict.keys():
        #     print(number_vgnameset_dict[number])
        # print("======================================")
        # for number, objlist in number_objlist_dict.items():
        #     print("Number: " + str(number) + " ObjList: " + str(objlist))
        #     print("---")

        # 到这里就可以合并obj了
        for number, objlist in number_objlist_dict.items():
            ObjUtils.merge_objects(obj_list=objlist,target_collection=collection)
        self.report({'INFO'}, "根据顶点组分割模型成功!")
        return {'FINISHED'}
    

class ModelDeleteLoosePoint(bpy.types.Operator):
    bl_idname = "panel_model.delete_loose_point"
    bl_label = "删除模型中的松散点"
    bl_description = "删除模型中的松散点，避免影响后续的模型处理。"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        
        ObjUtils.selected_obj_delete_loose()

        self.report({'INFO'}, "删除松散点成功!")
        return {'FINISHED'}
    
class ModelClearCustomSplitNormals(bpy.types.Operator):
    bl_idname = "panel_model.clear_custom_split_normals"
    bl_label = "清除自定义拆分法向"
    bl_description = "WWMI 逆向得到的模型，有时顶点法线会歪，用这个处理一下就行。"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        sel = context.selected_objects
        if not sel:
            self.report({'ERROR'}, "未选中对象！")
            return {'CANCELLED'}
        for obj in sel:
            if obj.type == 'MESH':
                context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
        return {'FINISHED'}
    
class KeepOneTriangleInSelectedSubmesh(bpy.types.Operator):
    bl_idname = "object.keep_one_triangle_in_selected_submesh"
    bl_label = "保留选中Submesh的一个三角面"
    bl_description = "把选中的 Submesh 原地精简为一个三角面，其它顶点和面都会被移除"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, "没有选中任何 Mesh/Submesh 对象")
            return {'CANCELLED'}

        processed_count = 0
        for obj in mesh_objects:
            try:
                keep_one_triangle_in_mesh_object(obj)
                processed_count += 1
            except Exception as e:
                self.report({'ERROR'}, obj.name + ": " + str(e))
                return {'CANCELLED'}

        self.report({'INFO'}, "已将 " + str(processed_count) + " 个 Submesh 精简为单个三角面")
        return {'FINISHED'}


class ModelRenameVertexGroupNameWithTheirSuffix(bpy.types.Operator):
    bl_idname = "panel_model.rename_vertex_group_name_with_their_suffix"
    bl_label = "用模型名称作为前缀重命名顶点组"
    bl_description = "用模型名称作为前缀重命名顶点组，方便后续合并到一个物体后同名称的顶点组不会合在一起冲突，便于后续一键绑定骨骼。"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        
        # 遍历所有选中的对象
        for obj in context.selected_objects:
            # 仅处理网格对象
            if obj.type == 'MESH':
                model_name = obj.name
                
                # 遍历顶点组并重命名
                for vertex_group in obj.vertex_groups:
                    original_name = vertex_group.name
                    new_name = f"{model_name}_{original_name}"
                    vertex_group.name = new_name

        self.report({'INFO'}, "用模型名称作为前缀重命名顶点组成功!")
        return {'FINISHED'}
    

class RemoveAllVertexGroupOperator(bpy.types.Operator):
    bl_idname = "object.remove_all_vertex_group"
    bl_label = "移除所有顶点组"
    bl_description = "移除当前选中obj的所有顶点组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.remove_all_vertex_groups(obj)
        self.report({'INFO'}, "移除所有顶点组成功!")
        return {'FINISHED'}



class RemoveUnusedVertexGroupOperator(bpy.types.Operator):
    bl_idname = "object.remove_unused_vertex_group"
    bl_label = "移除未使用的空顶点组"
    bl_description = "移除当前选中obj的所有空顶点组，也就是移除未使用的顶点组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        
        # Original design from https://blenderartists.org/t/batch-delete-vertex-groups-script/449881/23
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.remove_unused_vertex_groups(obj)
        self.report({'INFO'}, "移除未使用的空顶点组成功!")
        return {'FINISHED'}
    

class MergeVertexGroupsWithSameNumber(bpy.types.Operator):
    bl_idname = "object.merge_vertex_group_with_same_number"
    bl_label = "合并具有相同数字前缀名称的顶点组"
    bl_description = "把当前选中obj的所有数字前缀名称相同的顶点组进行合并"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        VertexGroupUtils.merge_vertex_groups_with_same_number_v2()
        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}

class FillVertexGroupGaps(bpy.types.Operator):
    bl_idname = "object.fill_vertex_group_gaps"
    bl_label = "填充数字顶点组的间隙"
    bl_description = "把当前选中obj的所有数字顶点组的间隙用数字命名的空顶点组填补上，比如有顶点组1,2,5,8则填补后得到1,2,3,4,5,6,7,8"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        VertexGroupUtils.fill_vertex_group_gaps()
        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}
    

class AddBoneFromVertexGroupV2(bpy.types.Operator):
    bl_idname = "object.add_bone_from_vertex_group_v2"
    bl_label = "根据顶点组生成基础骨骼"
    bl_description = "把当前选中的obj的每个顶点组都生成一个默认位置的骨骼，方便接下来手动调整骨骼位置和父级关系来绑骨，虹汐哥改进版本"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        VertexGroupUtils.create_armature_from_vertex_groups()
        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}


class RemoveNotNumberVertexGroup(bpy.types.Operator):
    bl_idname = "object.remove_not_number_vertex_group"
    bl_label = "移除非数字名称的顶点组"
    bl_description = "把当前选中的obj的所有不是纯数字命名的顶点组都移除"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.remove_not_number_vertex_groups(obj)
        
        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}
    

class SplitMeshByCommonVertexGroup(bpy.types.Operator):
    bl_idname = "object.split_mesh_by_common_vertex_group"
    bl_label = "根据顶点组将模型打碎为松散块儿"
    bl_description = "把当前选中的obj按顶点组进行分割，适用于部分精细刷权重并重新组合模型的场景"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.split_mesh_by_vertex_group(obj)
        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}
    


class SplitMeshByEachVertexGroup(bpy.types.Operator):
    bl_idname = "object.split_mesh_by_each_vertex_group"
    bl_label = "按顶点组分割模型"
    bl_description = "把当前选中的obj按每个顶点组分割为独立网格，保留所有属性（UV、权重、颜色、法线、形态键等），结果放入'{obj名}_Split'集合"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        if obj.type != 'MESH':
            self.report({'ERROR'}, "选中的对象不是网格！")
            return {'CANCELLED'}
        try:
            collection = VertexGroupUtils.split_mesh_by_each_vertex_group(obj)
            self.report({'INFO'}, f"已按顶点组拆分为独立网格，共 {len(collection.objects)} 个物体")
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class SplitMeshByEachVertexGroupCluster(bpy.types.Operator):
    bl_idname = "object.split_mesh_by_each_vertex_group_cluster"
    bl_label = "根据松散块儿分割并聚类"
    bl_description = "按松散块儿分割后，将 VG 集合近似（Jaccard 相似度）且空间邻接的松散块儿合并为一个部位，结果放入'{obj名}_SplitCluster'集合"
    bl_options = {'REGISTER', 'UNDO'}

    vg_similarity_threshold: bpy.props.FloatProperty(
        name="VG 相似度阈值",
        description="Jaccard 相似度（交集/并集），两个松散块儿的 VG 集合相似度 >= 此值且空间邻接时合并",
        default=0.7,
        min=0.1,
        max=1.0,
    ) # type: ignore

    bbox_distance_threshold: bpy.props.FloatProperty(
        name="包围盒距离阈值",
        description="两个松散块儿的包围盒距离 <= 此值时视为空间邻接",
        default=0.01,
        min=0.0001,
        soft_max=1.0,
    ) # type: ignore

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        if obj.type != 'MESH':
            self.report({'ERROR'}, "选中的对象不是网格！")
            return {'CANCELLED'}
        try:
            collection = VertexGroupUtils.split_by_loose_parts_and_cluster(
                obj,
                vg_similarity_threshold=self.vg_similarity_threshold,
                bbox_distance_threshold=self.bbox_distance_threshold,
            )
            self.report({'INFO'}, f"已根据松散块儿分割并聚类，共 {len(collection.objects)} 个物体")
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MMTResetRotation(bpy.types.Operator):
    bl_idname = "object.mmt_reset_rotation"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "重置模型x,y,z的旋转角度为0"
    bl_description = "把当前选中的obj的x,y,z的旋转角度全部归0"
    
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            ObjUtils.reset_obj_rotation(obj=obj)

        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}

class SmoothNormalSaveToUV(bpy.types.Operator):
    bl_idname = "object.smooth_normal_save_to_uv"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "平滑法线存UV(近似)"
    bl_description = "平滑法线存UV算法，可用于修复ZZZ,WWMI的某些UV(只是近似实现60%的效果)" 

    def execute(self, context):
        AlgorithmUtils.smooth_normal_save_to_uv()
        return {'FINISHED'}
    


        
class PropertyCollectionModifierItem(bpy.types.PropertyGroup):
    checked: BoolProperty(
        name="", 
        default=False
    ) # type: ignore
bpy.utils.register_class(PropertyCollectionModifierItem)

class WWMI_ApplyModifierForObjectWithShapeKeysOperator(bpy.types.Operator):
    bl_idname = "wwmi_tools.apply_modifier_for_object_with_shape_keys"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "在有形态键的模型上应用修改器"
    bl_description = "在带有形态键的模型上应用选中的修改器，并将其从堆栈中移除，用于解决“带形态键的网格无法应用修改器”的问题。"
 
    def item_list(self, context):
        return [(modifier.name, modifier.name, modifier.name) for modifier in bpy.context.object.modifiers]
    
    my_collection: CollectionProperty(
        type=PropertyCollectionModifierItem
    ) # type: ignore
    
    disable_armatures: BoolProperty(
        name="不包含骨架变形",
        default=True,
    ) # type: ignore
 
    def execute(self, context):
        ob = bpy.context.object
        bpy.ops.object.select_all(action='DESELECT')
        context.view_layer.objects.active = ob
        ob.select_set(True)
        
        selectedModifiers = [o.name for o in self.my_collection if o.checked]
        
        if not selectedModifiers:
            self.report({'ERROR'}, '未选择任何修改器！')
            return {'FINISHED'}
        
        success, errorInfo = ShapeKeyUtils.apply_modifiers_for_object_with_shape_keys(context, selectedModifiers, self.disable_armatures)
        
        if not success:
            self.report({'ERROR'}, errorInfo)
        
        return {'FINISHED'}
        
    def draw(self, context):
        if context.object.data.shape_keys and context.object.data.shape_keys.animation_data:
            self.layout.separator()
            self.layout.label(text="警告:")
            self.layout.label(text="              该物体的形态键包含动画数据")
            self.layout.label(text="              （例如驱动、关键帧等）")
            self.layout.label(text="              应用修改器后这些数据会丢失！")
            self.layout.separator()
        #self.layout.prop(self, "my_enum")
        box = self.layout.box()
        for prop in self.my_collection:
            box.prop(prop, "checked", text=prop["name"])
        #box.prop(self, "my_collection")
        self.layout.prop(self, "disable_armatures")
 
    def invoke(self, context, event):
        self.my_collection.clear()
        for i in range(len(bpy.context.object.modifiers)):
            item = self.my_collection.add()
            item.name = bpy.context.object.modifiers[i].name
            item.checked = False
        return context.window_manager.invoke_props_dialog(self)
    

class RecalculateTANGENTWithVectorNormalizedNormal(bpy.types.Operator):
    bl_idname = "object.recalculate_tangent_arithmetic_average_normal"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "使用向量相加归一化算法重计算TANGENT"
    bl_description = "近似修复轮廓线算法，可以达到99%的轮廓线相似度，适用于GI,HSR,ZZZ,HI3 2.0之前的老角色" 
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                if obj.get("3DMigoto:RecalculateTANGENT",False):
                    obj["3DMigoto:RecalculateTANGENT"] = not obj["3DMigoto:RecalculateTANGENT"]
                else:
                    obj["3DMigoto:RecalculateTANGENT"] = True
                self.report({'INFO'},"重计算TANGENT设为:" + str(obj["3DMigoto:RecalculateTANGENT"]))
        return {'FINISHED'}


class RecalculateCOLORWithVectorNormalizedNormal(bpy.types.Operator):
    bl_idname = "object.recalculate_color_arithmetic_average_normal"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "使用算术平均归一化算法重计算COLOR"
    bl_description = "近似修复轮廓线算法，可以达到99%的轮廓线相似度，仅适用于HI3 2.0新角色" 

    def execute(self, context):
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                if obj.get("3DMigoto:RecalculateCOLOR",False):
                    obj["3DMigoto:RecalculateCOLOR"] = not obj["3DMigoto:RecalculateCOLOR"]
                else:
                    obj["3DMigoto:RecalculateCOLOR"] = True
                self.report({'INFO'},"重计算COLOR设为:" + str(obj["3DMigoto:RecalculateCOLOR"]))
        return {'FINISHED'}
    


class RenameAmatureFromGame(bpy.types.Operator):
    bl_idname = "object.rename_amature_from_game"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "重命名选中Amature的骨骼名称(GI)(测试)"
    bl_description = "用于把游戏里解包出来的骨骼重命名，方便我们直接一键绑定到提取出的Mod模型上，感谢 Leotorrez。"
    def execute(self, context):
        # Copied from https://github.com/zeroruka/GI-Bones 
        # Select the armature and then run script
        armature_name = bpy.context.active_object.name

        object_name_original = 'Body'
        if not bpy.context.active_object:
            raise RuntimeError("The selected object is not an armature.")
        if bpy.context.active_object.type != "ARMATURE" or armature_name not in bpy.data.objects:
            raise RuntimeError("Error: No object selected.")

        bpy.ops.object.scale_clear()
        bpy.context.view_layer.objects.active = bpy.data.objects[armature_name]
        bpy.ops.object.mode_set(mode='OBJECT')
        # 这里mirror是因为我们的3Dmigoto提取出来的模型天生就是相反的方向
        bpy.ops.transform.mirror(constraint_axis=(True, False, False))
        bpy.ops.object.transform_apply(scale=True, rotation=False)

        vertex_groups = [vg.name for vg in bpy.data.objects[object_name_original].vertex_groups]
        pairs = {old:new for old,new in zip(vertex_groups, sorted(vertex_groups))}
        name_mapping = {new: str(i) for i, (_, new) in enumerate(pairs.items())}
        for vertex_group in bpy.data.objects[object_name_original].vertex_groups:
            armature_obj = bpy.data.objects[armature_name].data
            armature_obj.bones[vertex_group.name].name = vertex_group.name = name_mapping[vertex_group.name]

        new_armature_name = f"{armature_name}_sorted"
        bpy.data.objects[armature_name].name = new_armature_name
        bpy.context.view_layer.objects.active = bpy.data.objects[new_armature_name]
        obj = bpy.data.objects.get(new_armature_name)
        obj.parent = None
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        obj.rotation_euler[0] = -1.5708
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        obj.rotation_euler[0] = 1.5708

        for obj in bpy.data.objects:
            if obj.name != new_armature_name:
                for child in obj.children:
                    bpy.data.objects.remove(child)
                bpy.data.objects.remove(obj)
        return {'FINISHED'}

class ModelResetLocation(bpy.types.Operator):
    bl_idname = "herta.model_reset_location"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "重置模型在x,y,z轴上的位置为0"
    bl_description = "把当前选中的obj的x,y,z轴上的位置全部重置为0，使模型回到坐标原点"
    
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            ObjUtils.reset_obj_location(obj=obj)

        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}
    
class ModelSortVertexGroupByName(bpy.types.Operator):
    bl_idname = "object.sort_vertex_group_by_name"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "根据顶点组名称对顶点组进行排序"
    bl_description = "和Blender顶点组权重那里自带的Sort=>By Name功能一样，放在这里方便快速调用"
    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "没有选中的对象！")
            return {'CANCELLED'}
        
        # for obj in bpy.context.selected_objects:
        bpy.ops.object.vertex_group_sort(sort_type='NAME')
        
        self.report({'INFO'}, self.bl_label + " 成功!")
        return {'FINISHED'}
    
class ModelVertexGroupRenameByLocation(bpy.types.Operator):
    bl_idname = "herta.vertex_group_rename_by_location"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "将目标obj的顶点组按位置对应关系改名"
    bl_description = "先选中一个源obj，再选中一个目标obj，再点击此按钮，会根据顶点组对应位置把目标obj的顶点组改名为源obj的顶点组名称，目标obj的顶点组中，和源obj顶点组位置相近的顶点组将被改名为源obj对应位置的顶点组的名称，未能识别的顶点组将被命名为unknown"

    def execute(self, context):
        if len(bpy.context.selected_objects) < 2:
            self.report({'ERROR'}, "选中的obj数量不足!请先选中源obj，再选中目标obj，一般目标obj就是你自己的模型，源obj就是游戏源模型")
            return {'CANCELLED'}
        
        active_obj = bpy.context.view_layer.objects.active
        selected_objs = bpy.context.selected_objects

        # 判断哪个是后选的（即激活对象）
        if active_obj in selected_objs:
            target_obj = active_obj
            source_obj = [obj for obj in selected_objs if obj != target_obj][0]
        
        VertexGroupUtils.match_vertex_groups(target_obj, source_obj)
        self.report({'INFO'}, self.bl_label + " 成功!")

        return {'FINISHED'}
    

class ExtractSubmeshOperator(bpy.types.Operator):
    bl_idname = "mesh.extract_submesh"
    bl_label = "根据DrawIndexed值分割模型"
    bl_options = {'REGISTER', 'UNDO'}

    start_index: bpy.props.IntProperty(
        name="起始索引",
        description="索引缓冲区中的起始索引",
        default=0,
        min=0
    ) # type: ignore

    index_count: bpy.props.IntProperty(
        name="索引数量",
        description="要包含的索引数量，必须是 3 的倍数",
        default=3,
        min=3
    ) # type: ignore

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "请选择一个网格对象")
            return {'CANCELLED'}

        # 获取原始网格
        original_mesh = obj.data
        original_mesh.calc_loop_triangles()
        
        start = self.start_index
        count = self.index_count
        end_index = start + count - 1
        
        # 验证输入
        if start + count > len(original_mesh.loops):
            self.report({'ERROR'}, f"索引范围超出缓冲区，最大 loop 数量为: {len(original_mesh.loops)}")
            return {'CANCELLED'}
            
        if count % 3 != 0:
            self.report({'ERROR'}, "索引数量必须是 3 的倍数")
            return {'CANCELLED'}

        # 创建网格副本
        new_mesh_name = original_mesh.name +  ".Split-" + str(start) + "_" + str(end_index)
        new_mesh = original_mesh.copy()
        new_mesh.name = new_mesh_name
        
        # 使用BMesh处理网格
        bm = bmesh.new()
        bm.from_mesh(new_mesh)
        
        # 获取所有面
        faces = list(bm.faces)
        
        # 确定要保留的面
        faces_to_keep = set()
        for i in range(0, count, 3):
            # 计算面的索引
            face_index = (start + i) // 3
            if face_index < len(faces):
                faces_to_keep.add(faces[face_index])
        
        # 删除不需要的面
        for face in list(bm.faces):
            if face not in faces_to_keep:
                bm.faces.remove(face)
        
        # 删除孤立的顶点
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
        
        # 更新网格
        bm.to_mesh(new_mesh)
        bm.free()
        
        # 清理网格
        new_mesh.validate()
        new_mesh.update()
        
        # 创建新对象
        new_obj = bpy.data.objects.new(new_mesh_name, new_mesh)
        new_obj.matrix_world = obj.matrix_world
        
        # 复制材质
        if obj.material_slots:
            for slot in obj.material_slots:
                new_obj.data.materials.append(slot.material)
        
        # 创建或获取集合
        collection_name = new_mesh_name
        collection = bpy.data.collections.get(collection_name)
        if not collection:
            collection = bpy.data.collections.new(collection_name)
            context.scene.collection.children.link(collection)
        
        # 链接对象到集合
        collection.objects.link(new_obj)
        
        # 取消在其他集合中的链接
        for coll in new_obj.users_collection:
            if coll != collection:
                coll.objects.unlink(new_obj)
        
        # 选择并激活新对象
        context.view_layer.objects.active = new_obj
        new_obj.select_set(True)
        obj.select_set(False)
        
        return {'FINISHED'}

class PanelModelProcess(bpy.types.Panel):
    '''
    在这里放一份的意义是萌新根本不知道右键菜单能触发这些功能，萌新的话如果你不给他送到嘴边，他是不会吃的。
    所以面板里放一份方便萌新使用，当然默认是关闭状态也不影响视觉，萌新用的多了成为大佬之后就会用右键菜单里的选项了。
    '''
    bl_label = "模型处理面板" 
    bl_idname = "VIEW3D_PT_Herta_ModelProcess_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TheHerta4'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator(ModelResetLocation.bl_idname)
        layout.operator(MMTResetRotation.bl_idname)
        layout.operator(ModelDeleteLoosePoint.bl_idname)
        layout.operator(ModelClearCustomSplitNormals.bl_idname)
        layout.operator(KeepOneTriangleInSelectedSubmesh.bl_idname)
        layout.separator()



        layout.operator(RemoveAllVertexGroupOperator.bl_idname)
        layout.operator(RemoveUnusedVertexGroupOperator.bl_idname)
        layout.operator(RemoveNotNumberVertexGroup.bl_idname)
        layout.separator()

        layout.operator(ModelSortVertexGroupByName.bl_idname)
        layout.operator(FillVertexGroupGaps.bl_idname)
        layout.operator(MergeVertexGroupsWithSameNumber.bl_idname)
        layout.operator(ModelVertexGroupRenameByLocation.bl_idname)
        layout.separator()

        layout.operator(ModelRenameVertexGroupNameWithTheirSuffix.bl_idname)
        layout.operator(AddBoneFromVertexGroupV2.bl_idname)
        layout.separator()

        layout.operator(WWMI_ApplyModifierForObjectWithShapeKeysOperator.bl_idname)
        layout.operator(SmoothNormalSaveToUV.bl_idname)
        layout.operator(RenameAmatureFromGame.bl_idname)
        layout.separator()
        
        layout.operator(RecalculateTANGENTWithVectorNormalizedNormal.bl_idname)
        layout.operator(RecalculateCOLORWithVectorNormalizedNormal.bl_idname)
        layout.separator()
        
        layout.operator(ModelSplitByLoosePart.bl_idname)
        layout.operator(SplitMeshByCommonVertexGroup.bl_idname)
        layout.operator(ModelSplitByVertexGroup.bl_idname)
        layout.operator(SplitMeshByEachVertexGroup.bl_idname)
        layout.operator(SplitMeshByEachVertexGroupCluster.bl_idname)



class CatterRightClickMenu(bpy.types.Menu):
    '''
    光在Herta面板上放着也不行，因为部分用户的插件数量特别多的时候根本看不到Herta面板
    所以在右键的3Dmigoto菜单中也放上一份，这样方便查找。
    '''
    bl_idname = "VIEW3D_MT_object_3Dmigoto"
    bl_label = "3Dmigoto"
    bl_description = "适用于3Dmigoto Mod制作的常用功能"
    
    def draw(self, context):
        layout = self.layout
        layout.operator(ModelResetLocation.bl_idname)
        layout.operator(MMTResetRotation.bl_idname)
        layout.operator(ModelDeleteLoosePoint.bl_idname)
        layout.operator(ModelClearCustomSplitNormals.bl_idname)
        layout.operator(KeepOneTriangleInSelectedSubmesh.bl_idname)
        layout.separator()

        layout.operator(ModelSplitByLoosePart.bl_idname)
        layout.operator(SplitMeshByCommonVertexGroup.bl_idname)
        layout.operator(ModelSplitByVertexGroup.bl_idname)
        layout.operator(SplitMeshByEachVertexGroup.bl_idname)
        layout.operator(SplitMeshByEachVertexGroupCluster.bl_idname)
        layout.separator()

        layout.operator(RemoveAllVertexGroupOperator.bl_idname)
        layout.operator(RemoveUnusedVertexGroupOperator.bl_idname)
        layout.operator(RemoveNotNumberVertexGroup.bl_idname)
        layout.separator()

        layout.operator(ModelSortVertexGroupByName.bl_idname)
        layout.operator(FillVertexGroupGaps.bl_idname)
        layout.operator(MergeVertexGroupsWithSameNumber.bl_idname)
        layout.operator(ModelVertexGroupRenameByLocation.bl_idname)
        layout.separator()

        layout.operator(ModelRenameVertexGroupNameWithTheirSuffix.bl_idname)
        layout.operator(AddBoneFromVertexGroupV2.bl_idname)
        layout.separator()


        layout.operator(WWMI_ApplyModifierForObjectWithShapeKeysOperator.bl_idname)
        layout.operator(SmoothNormalSaveToUV.bl_idname)
        
        layout.operator(RenameAmatureFromGame.bl_idname)
        layout.separator()
        layout.operator(RecalculateTANGENTWithVectorNormalizedNormal.bl_idname)
        layout.operator(RecalculateCOLORWithVectorNormalizedNormal.bl_idname)
        


def menu_func_migoto_right_click(self, context):
    self.layout.separator()
    self.layout.menu(CatterRightClickMenu.bl_idname)

def register():
    bpy.utils.register_class(RemoveAllVertexGroupOperator)
    bpy.utils.register_class(RemoveUnusedVertexGroupOperator)
    bpy.utils.register_class(MergeVertexGroupsWithSameNumber)
    bpy.utils.register_class(FillVertexGroupGaps)
    bpy.utils.register_class(AddBoneFromVertexGroupV2)
    bpy.utils.register_class(RemoveNotNumberVertexGroup)
    bpy.utils.register_class(MMTResetRotation)
    bpy.utils.register_class(CatterRightClickMenu)
    bpy.utils.register_class(SplitMeshByCommonVertexGroup)
    bpy.utils.register_class(SplitMeshByEachVertexGroup)
    bpy.utils.register_class(SplitMeshByEachVertexGroupCluster)
    bpy.utils.register_class(RecalculateTANGENTWithVectorNormalizedNormal)
    bpy.utils.register_class(RecalculateCOLORWithVectorNormalizedNormal)
    bpy.utils.register_class(WWMI_ApplyModifierForObjectWithShapeKeysOperator)
    bpy.utils.register_class(SmoothNormalSaveToUV)
    bpy.utils.register_class(RenameAmatureFromGame)
    bpy.utils.register_class(ModelSplitByLoosePart)
    bpy.utils.register_class(ModelSplitByVertexGroup)
    bpy.utils.register_class(ModelDeleteLoosePoint)
    bpy.utils.register_class(ModelClearCustomSplitNormals)
    bpy.utils.register_class(KeepOneTriangleInSelectedSubmesh)
    bpy.utils.register_class(ModelRenameVertexGroupNameWithTheirSuffix)
    bpy.utils.register_class(ModelResetLocation)
    bpy.utils.register_class(ModelSortVertexGroupByName)
    bpy.utils.register_class(ModelVertexGroupRenameByLocation)
    bpy.utils.register_class(ExtractSubmeshOperator)
    bpy.utils.register_class(PanelModelProcess)

    bpy.types.VIEW3D_MT_object_context_menu.append(menu_func_migoto_right_click)

    bpy.types.Scene.submesh_start = bpy.props.IntProperty(
        name="Start Index",
        default=0,
        min=0
    )
    bpy.types.Scene.submesh_count = bpy.props.IntProperty(
        name="Index Count",
        default=3,
        min=3
    )

def unregister():
    del bpy.types.Scene.submesh_start
    del bpy.types.Scene.submesh_count

    bpy.types.VIEW3D_MT_object_context_menu.remove(menu_func_migoto_right_click)

    bpy.utils.unregister_class(PanelModelProcess)
    bpy.utils.unregister_class(ExtractSubmeshOperator)
    bpy.utils.unregister_class(ModelVertexGroupRenameByLocation)
    bpy.utils.unregister_class(ModelSortVertexGroupByName)
    bpy.utils.unregister_class(ModelResetLocation)
    bpy.utils.unregister_class(ModelRenameVertexGroupNameWithTheirSuffix)
    bpy.utils.unregister_class(ModelClearCustomSplitNormals)
    bpy.utils.unregister_class(KeepOneTriangleInSelectedSubmesh)
    bpy.utils.unregister_class(ModelDeleteLoosePoint)
    bpy.utils.unregister_class(ModelSplitByVertexGroup)
    bpy.utils.unregister_class(ModelSplitByLoosePart)
    bpy.utils.unregister_class(RenameAmatureFromGame)
    bpy.utils.unregister_class(SmoothNormalSaveToUV)
    bpy.utils.unregister_class(WWMI_ApplyModifierForObjectWithShapeKeysOperator)
    bpy.utils.unregister_class(RecalculateCOLORWithVectorNormalizedNormal)
    bpy.utils.unregister_class(RecalculateTANGENTWithVectorNormalizedNormal)
    bpy.utils.unregister_class(SplitMeshByEachVertexGroup)
    bpy.utils.unregister_class(SplitMeshByEachVertexGroupCluster)
    bpy.utils.unregister_class(SplitMeshByCommonVertexGroup)
    bpy.utils.unregister_class(CatterRightClickMenu)
    bpy.utils.unregister_class(MMTResetRotation)
    bpy.utils.unregister_class(RemoveNotNumberVertexGroup)
    bpy.utils.unregister_class(AddBoneFromVertexGroupV2)
    bpy.utils.unregister_class(FillVertexGroupGaps)
    bpy.utils.unregister_class(MergeVertexGroupsWithSameNumber)
    bpy.utils.unregister_class(RemoveUnusedVertexGroupOperator)
    bpy.utils.unregister_class(RemoveAllVertexGroupOperator)
