import bpy
import bmesh
import numpy

from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty

from ..utils.obj_utils import ObjUtils
from ..utils.collection_utils import CollectionUtils
from ..utils.vertexgroup_utils import VertexGroupUtils
from ..utils.shapekey_utils import ShapeKeyUtils
from ..utils.algorithm_utils import AlgorithmUtils
from ..utils.mesh_mirror_utils import MeshMirrorUtils

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
    bl_label = "Split Model by UV Loose Parts"
    bl_description = "Similar to Edit mode's Split => Split by Loose Parts, but it splits the model into loose parts and stores them in a new collection."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        # Create a new collection named after the original object
        collection_name = f"{obj.name}_LooseParts"
        ObjUtils.split_obj_by_loose_parts_to_collection(obj=obj,collection_name=collection_name)

        self.report({'INFO'}, "Split Model by UV Loose Parts Success!")
        return {'FINISHED'}


class ModelSplitByVertexGroup(bpy.types.Operator):
    bl_idname = "panel_model.split_by_vertex_group"
    bl_label = "Split Model by Shared and Isolated Vertex Groups"
    bl_description = "Splits the model apart by shared vertex groups so small parts on the body can be quickly separated and will not interfere with later weight painting."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        # Create a new collection named after the original object
        collection_name = f"{obj.name}_Splits"
        ObjUtils.split_obj_by_loose_parts_to_collection(obj=obj,collection_name=collection_name)
        
        collection = CollectionUtils.get_collection_by_name(collection_name=collection_name)

        # Select all objects of the current collection
        CollectionUtils.select_collection_objects(collection)

        # Keep them in a list for later use
        selected_objects = bpy.context.selected_objects

        number_vgnameset_dict = {}
        number_objlist_dict = {}

        for obj in selected_objects:

            # First remove unused vertex groups from each part
            VertexGroupUtils.remove_unused_vertex_groups(obj)
             
            # Get the list of vertex group names of the object
            vertex_group_names = [vg.name for vg in obj.vertex_groups]

            vgname_set = set()

            # Iterate over every vertex group name
            for vgname in vertex_group_names:
                    vgname_set.add(vgname)

            if len(number_vgnameset_dict) == 0:
                # If nothing has been recorded yet, store it directly
                number_vgnameset_dict[1] = vgname_set
                number_objlist_dict[1] = [obj]
            else:
                exists = False
                for number, tmp_vgname_set in number_vgnameset_dict.items():
                    # Intersect the two sets
                    vgname_jiaoji = tmp_vgname_set & vgname_set

                    if len(vgname_jiaoji) != 0:
                        # Take the union of the two sets
                        vgname_quanji = tmp_vgname_set.union(vgname_set)

                        # If they intersect, put the union back
                        number_vgnameset_dict[number] = vgname_quanji

                        exists = True
                        # Once there is an intersection, store the union and exit the loop
                        break
                
                if not exists:
                    # If no intersection is found, add a new entry
                    number_objlist_dict[len(number_objlist_dict) + 1] = [obj]
                    number_vgnameset_dict[len(number_vgnameset_dict) + 1] = vgname_set
                else:
                    # If an intersection is found, append this object to that entry
                    number_objlist_dict[number].append(obj)

        # Print for inspection 
        # print(number_vgnameset_dict.keys())
        # print("======================================")
        # for number in number_vgnameset_dict.keys():
        #     print(number_vgnameset_dict[number])
        # print("======================================")
        # for number, objlist in number_objlist_dict.items():
        #     print("Number: " + str(number) + " ObjList: " + str(objlist))
        #     print("---")

        # From here the objects can be merged
        for number, objlist in number_objlist_dict.items():
            ObjUtils.merge_objects(obj_list=objlist,target_collection=collection)
        self.report({'INFO'}, "Split Model by Vertex Group Success!")
        return {'FINISHED'}
    

class ModelDeleteLoosePoint(bpy.types.Operator):
    bl_idname = "panel_model.delete_loose_point"
    bl_label = "Delete Loose Points"
    bl_description = "Deletes loose points in the model to keep them from affecting subsequent model processing."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        
        ObjUtils.selected_obj_delete_loose()

        self.report({'INFO'}, "Delete Loose Points Success!")
        return {'FINISHED'}
    
class ModelClearCustomSplitNormals(bpy.types.Operator):
    bl_idname = "panel_model.clear_custom_split_normals"
    bl_label = "Clear Custom Split Normals"
    bl_description = "Models ripped with WWMI sometimes have skewed vertex normals; just run this to fix them."
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        sel = context.selected_objects
        if not sel:
            self.report({'ERROR'}, "No object selected.")
            return {'CANCELLED'}
        for obj in sel:
            if obj.type == 'MESH':
                context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
        return {'FINISHED'}
    
class KeepOneTriangleInSelectedSubmesh(bpy.types.Operator):
    bl_idname = "object.keep_one_triangle_in_selected_submesh"
    bl_label = "Keep One Triangle Face of the Selected Submesh"
    bl_description = "Keeps one triangle face of each selected Submesh in place; all other vertices and faces are removed"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, "No Mesh/Submesh objects selected.")
            return {'CANCELLED'}

        processed_count = 0
        for obj in mesh_objects:
            try:
                keep_one_triangle_in_mesh_object(obj)
                processed_count += 1
            except Exception as e:
                self.report({'ERROR'}, obj.name + ": " + str(e))
                return {'CANCELLED'}

        self.report({'INFO'}, "Reduced " + str(processed_count) + " Submesh(es) to a single triangle face")
        return {'FINISHED'}


class ModelRenameVertexGroupNameWithTheirSuffix(bpy.types.Operator):
    bl_idname = "panel_model.rename_vertex_group_name_with_their_suffix"
    bl_label = "Rename Vertex Groups with Model Name Prefix"
    bl_description = "Renames the vertex groups of each mesh using the model name as a prefix, so that same-named vertex groups will not conflict once the parts are merged into one object, which makes one-click rigging easier later."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        
        # Iterate over all selected objects
        for obj in context.selected_objects:
            # Only process mesh objects
            if obj.type == 'MESH':
                model_name = obj.name
                
                # Iterate over the vertex groups and rename them
                for vertex_group in obj.vertex_groups:
                    original_name = vertex_group.name
                    new_name = f"{model_name}_{original_name}"
                    vertex_group.name = new_name

        self.report({'INFO'}, "Rename Vertex Groups with Model Name Prefix Success!")
        return {'FINISHED'}
    

class RemoveAllVertexGroupOperator(bpy.types.Operator):
    bl_idname = "object.remove_all_vertex_group"
    bl_label = "Remove All Vertex Groups"
    bl_description = "Removes all vertex groups of the currently selected obj"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.remove_all_vertex_groups(obj)
        self.report({'INFO'}, "Remove All Vertex Groups Success!")
        return {'FINISHED'}



class RemoveUnusedVertexGroupOperator(bpy.types.Operator):
    bl_idname = "object.remove_unused_vertex_group"
    bl_label = "Remove Unused Empty Vertex Groups"
    bl_description = "Removes all empty vertex groups of the currently selected obj, i.e. the unused vertex groups"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        
        # Original design from https://blenderartists.org/t/batch-delete-vertex-groups-script/449881/23
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.remove_unused_vertex_groups(obj)
        self.report({'INFO'}, "Remove Unused Empty Vertex Groups Success!")
        return {'FINISHED'}
    

class MergeVertexGroupsWithSameNumber(bpy.types.Operator):
    bl_idname = "object.merge_vertex_group_with_same_number"
    bl_label = "Merge Vertex Groups with the Same Numeric Prefix"
    bl_description = "Merges all vertex groups of the currently selected obj that share the same numeric prefix name"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        VertexGroupUtils.merge_vertex_groups_with_same_number_v2()
        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}

class FillVertexGroupGaps(bpy.types.Operator):
    bl_idname = "object.fill_vertex_group_gaps"
    bl_label = "Fill Numeric Vertex Group Gaps"
    bl_description = "Fills the gaps in the numeric vertex groups of the currently selected obj with empty vertex groups named by number; e.g. groups 1,2,5,8 become 1,2,3,4,5,6,7,8"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        VertexGroupUtils.fill_vertex_group_gaps()
        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}
    

class AddBoneFromVertexGroupV2(bpy.types.Operator):
    bl_idname = "object.add_bone_from_vertex_group_v2"
    bl_label = "Generate Basic Bones from Vertex Groups"
    bl_description = "Creates a bone at a default position for every vertex group of the currently selected obj, so you can then adjust bone positions and parenting to rig it. Improved version by Hongxi"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        VertexGroupUtils.create_armature_from_vertex_groups()
        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}


class RemoveNotNumberVertexGroup(bpy.types.Operator):
    bl_idname = "object.remove_not_number_vertex_group"
    bl_label = "Remove Non-Numeric Vertex Groups"
    bl_description = "Removes every vertex group of the currently selected obj whose name is not purely numeric"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.remove_not_number_vertex_groups(obj)
        
        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}
    

class SplitMeshByCommonVertexGroup(bpy.types.Operator):
    bl_idname = "object.split_mesh_by_common_vertex_group"
    bl_label = "Break Model into Loose Parts by Vertex Groups"
    bl_description = "Splits the currently selected obj by its vertex groups; suited to workflows where parts are carefully weight-painted and then reassembled into a model"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            VertexGroupUtils.split_mesh_by_vertex_group(obj)
        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}
    


class SplitMeshByEachVertexGroup(bpy.types.Operator):
    bl_idname = "object.split_mesh_by_each_vertex_group"
    bl_label = "Split Model by Vertex Group"
    bl_description = "Splits the currently selected obj into separate meshes, one per vertex group, preserving all attributes (UVs, weights, colors, normals, shape keys, etc.); the results go into a '{obj_name}_Split' collection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        if obj.type != 'MESH':
            self.report({'ERROR'}, "The selected object is not a mesh!")
            return {'CANCELLED'}
        try:
            collection = VertexGroupUtils.split_mesh_by_each_vertex_group(obj)
            self.report({'INFO'}, f"Split into independent meshes by vertex group, {len(collection.objects)} objects in total")
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class SplitMeshByEachVertexGroupCluster(bpy.types.Operator):
    bl_idname = "object.split_mesh_by_each_vertex_group_cluster"
    bl_label = "Split by Loose Parts and Cluster"
    bl_description = "After splitting by loose parts, merges loose parts whose VG sets are similar (Jaccard similarity) and that are spatially adjacent into one part; the results go into a '{obj_name}_SplitCluster' collection"
    bl_options = {'REGISTER', 'UNDO'}

    vg_similarity_threshold: bpy.props.FloatProperty(
        name="VG Similarity Threshold",
        description="Jaccard similarity (intersection/union); two loose parts are merged when the similarity of their VG sets is >= this value and they are spatially adjacent",
        default=0.7,
        min=0.1,
        max=1.0,
    ) # type: ignore

    bbox_distance_threshold: bpy.props.FloatProperty(
        name="BBox Distance Threshold",
        description="Two loose parts are considered spatially adjacent when their bounding-box distance is <= this value",
        default=0.01,
        min=0.0001,
        soft_max=1.0,
    ) # type: ignore

    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        obj = bpy.context.selected_objects[0]
        if obj.type != 'MESH':
            self.report({'ERROR'}, "The selected object is not a mesh!")
            return {'CANCELLED'}
        try:
            collection = VertexGroupUtils.split_by_loose_parts_and_cluster(
                obj,
                vg_similarity_threshold=self.vg_similarity_threshold,
                bbox_distance_threshold=self.bbox_distance_threshold,
            )
            self.report({'INFO'}, f"Split by loose parts and clustered, {len(collection.objects)} objects in total")
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MMTResetRotation(bpy.types.Operator):
    bl_idname = "object.mmt_reset_rotation"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Reset Model Rotation on X, Y, Z to 0"
    bl_description = "Resets the X, Y, Z rotation of the currently selected obj to 0"
    
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            ObjUtils.reset_obj_rotation(obj=obj)

        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}

class SmoothNormalSaveToUV(bpy.types.Operator):
    bl_idname = "object.smooth_normal_save_to_uv"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Store Smooth Normals in UV (Approximate)"
    bl_description = "Smooth normal to UV storage algorithm; can repair certain UVs from ZZZ and WWMI (approximate implementation, only about 60% as effective)" 

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
    bl_label = "Apply Modifiers on a Model with Shape Keys"
    bl_description = "Applies the selected modifiers on a model with shape keys and removes them from the stack, solving the issue that \"a modifier cannot be applied to a mesh with shape keys\"."
 
    def item_list(self, context):
        return [(modifier.name, modifier.name, modifier.name) for modifier in bpy.context.object.modifiers]
    
    my_collection: CollectionProperty(
        type=PropertyCollectionModifierItem
    ) # type: ignore
    
    disable_armatures: BoolProperty(
        name="Exclude Armature Deformation",
        default=True,
    ) # type: ignore
 
    def execute(self, context):
        ob = bpy.context.object
        bpy.ops.object.select_all(action='DESELECT')
        context.view_layer.objects.active = ob
        ob.select_set(True)
        
        selectedModifiers = [o.name for o in self.my_collection if o.checked]
        
        if not selectedModifiers:
            self.report({'ERROR'}, 'No modifiers selected!')
            return {'FINISHED'}
        
        success, errorInfo = ShapeKeyUtils.apply_modifiers_for_object_with_shape_keys(context, selectedModifiers, self.disable_armatures)
        
        if not success:
            self.report({'ERROR'}, errorInfo)
        
        return {'FINISHED'}
        
    def draw(self, context):
        if context.object.data.shape_keys and context.object.data.shape_keys.animation_data:
            self.layout.separator()
            self.layout.label(text="Warning:")
            self.layout.label(text="              The shape keys of this object contain animation data")
            self.layout.label(text="              (e.g. drivers, keyframes, etc.)")
            self.layout.label(text="              These data will be lost after the modifiers are applied!")
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
    bl_label = "Recalculate TANGENT with Vector-Sum Normalization"
    bl_description = "Approximate outline-repair algorithm that can reach 99% outline similarity; suited to the older characters of GI, HSR, ZZZ and pre-2.0 HI3" 
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                if obj.get("3DMigoto:RecalculateTANGENT",False):
                    obj["3DMigoto:RecalculateTANGENT"] = not obj["3DMigoto:RecalculateTANGENT"]
                else:
                    obj["3DMigoto:RecalculateTANGENT"] = True
                self.report({'INFO'},"Recalculate TANGENT set to: " + str(obj["3DMigoto:RecalculateTANGENT"]))
        return {'FINISHED'}


class RecalculateCOLORWithVectorNormalizedNormal(bpy.types.Operator):
    bl_idname = "object.recalculate_color_arithmetic_average_normal"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Recalculate COLOR with Arithmetic-Average Normalization"
    bl_description = "Approximate outline-repair algorithm that can reach 99% outline similarity; suited only to the new characters of HI3 2.0" 

    def execute(self, context):
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                if obj.get("3DMigoto:RecalculateCOLOR",False):
                    obj["3DMigoto:RecalculateCOLOR"] = not obj["3DMigoto:RecalculateCOLOR"]
                else:
                    obj["3DMigoto:RecalculateCOLOR"] = True
                self.report({'INFO'},"Recalculate COLOR set to: " + str(obj["3DMigoto:RecalculateCOLOR"]))
        return {'FINISHED'}
    


class RenameAmatureFromGame(bpy.types.Operator):
    bl_idname = "object.rename_amature_from_game"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Rename Bones of Selected Armature (GI) (Test)"
    bl_description = "Renames the bones unpacked from the game so they can be bound to the extracted Mod model in one click; thanks to Leotorrez."
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
        # Mirroring here is needed because our 3Dmigoto-extracted models are inherently mirrored
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
    bl_idname = "mimiblender.model_reset_location"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Reset Model Location on X, Y, Z to 0"
    bl_description = "Resets the location of the currently selected obj on the X, Y, Z axes to 0, moving the model back to the world origin"
    
    def execute(self, context):
        for obj in bpy.context.selected_objects:
            ObjUtils.reset_obj_location(obj=obj)

        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}
    
class ModelSortVertexGroupByName(bpy.types.Operator):
    bl_idname = "object.sort_vertex_group_by_name"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Sort Vertex Groups by Name"
    bl_description = "Same as Blender's built-in Sort => By Name next to the vertex group weights; placed here for quick access"
    def execute(self, context):
        if len(bpy.context.selected_objects) == 0:
            self.report({'ERROR'}, "No objects selected.")
            return {'CANCELLED'}
        
        # for obj in bpy.context.selected_objects:
        bpy.ops.object.vertex_group_sort(sort_type='NAME')
        
        self.report({'INFO'}, self.bl_label + " Success!")
        return {'FINISHED'}
    
class ModelVertexGroupRenameByLocation(bpy.types.Operator):
    bl_idname = "mimiblender.vertex_group_rename_by_location"
    bl_options = {'REGISTER', 'UNDO'}
    bl_label = "Rename Target Object Vertex Groups by Positional Mapping"
    bl_description = "Select a source obj first, then a target obj, then click this button: the target obj's vertex groups are renamed according to their positional correspondence with the source obj's vertex groups. Target groups located near a source group are renamed to that source group's name, and groups that cannot be identified are named unknown"

    def execute(self, context):
        if len(bpy.context.selected_objects) < 2:
            self.report({'ERROR'}, "Not enough objs selected! Select the source obj first, then the target obj. Usually the target obj is your own model and the source obj is the game's original model")
            return {'CANCELLED'}
        
        active_obj = bpy.context.view_layer.objects.active
        selected_objs = bpy.context.selected_objects

        # Determine which object was selected last (the active object)
        if active_obj in selected_objs:
            target_obj = active_obj
            source_obj = [obj for obj in selected_objs if obj != target_obj][0]
        
        VertexGroupUtils.match_vertex_groups(target_obj, source_obj)
        self.report({'INFO'}, self.bl_label + " Success!")

        return {'FINISHED'}
    

class ExtractSubmeshOperator(bpy.types.Operator):
    bl_idname = "mesh.extract_submesh"
    bl_label = "Split Model by DrawIndexed Values"
    bl_options = {'REGISTER', 'UNDO'}

    start_index: bpy.props.IntProperty(
        name="Start Index",
        description="Start index inside the index buffer",
        default=0,
        min=0
    ) # type: ignore

    index_count: bpy.props.IntProperty(
        name="Index Count",
        description="Number of indices to take; must be a multiple of 3",
        default=3,
        min=3
    ) # type: ignore

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object")
            return {'CANCELLED'}

        # Get the original mesh
        original_mesh = obj.data
        original_mesh.calc_loop_triangles()
        
        start = self.start_index
        count = self.index_count
        end_index = start + count - 1
        
        # Validate the input
        if start + count > len(original_mesh.loops):
            self.report({'ERROR'}, f"Index range exceeds the buffer; maximum loop count is: {len(original_mesh.loops)}")
            return {'CANCELLED'}
            
        if count % 3 != 0:
            self.report({'ERROR'}, "Index count must be a multiple of 3")
            return {'CANCELLED'}

        # Create a mesh copy
        new_mesh_name = original_mesh.name +  ".Split-" + str(start) + "_" + str(end_index)
        new_mesh = original_mesh.copy()
        new_mesh.name = new_mesh_name
        
        # Process the mesh with BMesh
        bm = bmesh.new()
        bm.from_mesh(new_mesh)
        
        # Get all faces
        faces = list(bm.faces)
        
        # Determine which faces to keep
        faces_to_keep = set()
        for i in range(0, count, 3):
            # Compute the face index
            face_index = (start + i) // 3
            if face_index < len(faces):
                faces_to_keep.add(faces[face_index])
        
        # Delete the unneeded faces
        for face in list(bm.faces):
            if face not in faces_to_keep:
                bm.faces.remove(face)
        
        # Remove isolated vertices
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
        
        # Write the edited mesh back
        bm.to_mesh(new_mesh)
        bm.free()
        
        # Clean up the mesh
        new_mesh.validate()
        new_mesh.update()
        
        # Create the new object
        new_obj = bpy.data.objects.new(new_mesh_name, new_mesh)
        new_obj.matrix_world = obj.matrix_world
        
        # Copy the materials
        if obj.material_slots:
            for slot in obj.material_slots:
                new_obj.data.materials.append(slot.material)
        
        # Create or get the collection
        collection_name = new_mesh_name
        collection = bpy.data.collections.get(collection_name)
        if not collection:
            collection = bpy.data.collections.new(collection_name)
            context.scene.collection.children.link(collection)
        
        # Link the object to the collection
        collection.objects.link(new_obj)
        
        # Unlink it from any other collections
        for coll in new_obj.users_collection:
            if coll != collection:
                coll.objects.unlink(new_obj)
        
        # Select and activate the new object
        context.view_layer.objects.active = new_obj
        new_obj.select_set(True)
        obj.select_set(False)
        
        return {'FINISHED'}

class MirrorMeshOperator(bpy.types.Operator):
    bl_idname = "mimiblender.mirror_mesh"
    bl_label = "Mirror Mesh (Perfect)"
    bl_description = ("Mirrors selected mesh objects by baking the flip into the real geometry. "
                      "Unlike setting scale.x = -1 it keeps normals correct, resets the object scale "
                      "to (1, 1, 1), follows shape keys, and can swap L/R vertex group names. "
                      "Mode / axis / UV options are in the redo panel (F9).")
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        description="What to do with every selected mesh object",
        default="COPY",
        items=[
            ("COPY", "Mirrored Copy",
             "Keep every selected object and create a clean mirrored copy next to it"),
            ("FLIP", "Flip In Place",
             "Mirror every selected object in place; click again to swap the side back"),
            ("BAKE", "Bake & Fix",
             "Fix an old object that was already mirrored with a negative scale: bake the scale "
             "into the mesh, repair the normals, reset the scale to 1, but keep the current look"),
        ],
    ) # type: ignore

    axis: EnumProperty(
        name="Mirror Axis",
        description="The mirror plane is the axis plane through the object origin "
                    "(the same plane a negative scale on that axis would use)",
        default="X",
        items=[
            ("X", "X Axis", "Mirror left / right"),
            ("Y", "Y Axis", "Mirror front / back"),
            ("Z", "Z Axis", "Mirror top / bottom"),
        ],
    ) # type: ignore

    recalc_normals: BoolProperty(
        name="Recalculate Normals (Outward)",
        description="Also recalculate all normals to point outside, which repairs faces "
                    "that were already inside-out before the mirror (Blender Ctrl+N behavior)",
        default=True,
    ) # type: ignore

    mirror_uv: EnumProperty(
        name="Mirror UV",
        description="Mirror the UV maps around the middle of the UV tile. Default (None) gives "
                    "the usual mirror image look. Use U for an X mirror or V for a Z mirror when "
                    "the mirrored copy must keep the texture reading direction of the original",
        default="NONE",
        items=[
            ("NONE", "None", "Keep UV maps as they are (mirror image look)"),
            ("U", "Flip U", "u becomes 1 - u, texture direction is kept readable"),
            ("V", "Flip V", "v becomes 1 - v, texture direction is kept readable"),
        ],
    ) # type: ignore

    swap_side_groups: BoolProperty(
        name="Swap L/R Vertex Group Names",
        description="Rename mirrored vertex groups so symmetric rigs deform the copy correctly "
                    "(for example arm.L becomes arm.R and arm.R becomes arm.L). Only affects "
                    "groups whose names end with a recognized L/R suffix; disable it when the "
                    "vertex groups do not follow symmetric naming",
        default=True,
    ) # type: ignore

    copy_suffix: StringProperty(
        name="Copy Name Suffix",
        description="Name suffix of the created mirrored copies (only used in Mirrored Copy mode)",
        default="_mirror",
    ) # type: ignore

    def execute(self, context):
        # The mirror works on the mesh data, so it needs object mode.
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Only mesh objects can be mirrored by this operator.
        mesh_objects = [
            obj for obj in context.selected_objects if obj.type == "MESH"
        ]
        if len(mesh_objects) == 0:
            self.report({'ERROR'}, "Select at least one mesh object to mirror.")
            return {'CANCELLED'}

        mirrored_objects = []
        errors = []
        for obj in mesh_objects:
            try:
                result = MeshMirrorUtils.mirror_mesh_object(
                    obj,
                    mode=self.mode,
                    axis=self.axis,
                    recalc_normals=self.recalc_normals,
                    mirror_uv=self.mirror_uv,
                    swap_side_groups=self.swap_side_groups,
                    copy_suffix=self.copy_suffix,
                )
                mirrored_objects.append(result)
            except Exception as exc:
                # One broken object must not stop the others.
                errors.append(f"{obj.name}: {exc}")

        if self.mode == "COPY" and len(mirrored_objects) > 0:
            # Keep the originals selected and add the new copies, so the
            # user sees right away what was created.
            for mirrored_obj in mirrored_objects:
                mirrored_obj.select_set(True)
            context.view_layer.objects.active = mirrored_objects[-1]

        for error in errors:
            self.report({'WARNING'}, f"Mirror skipped - {error}")

        if len(mirrored_objects) > 0:
            self.report({'INFO'}, f"Mirror success: {len(mirrored_objects)} object(s).")
            return {'FINISHED'}
        self.report({'ERROR'}, "Nothing was mirrored.")
        return {'CANCELLED'}


class PanelModelProcess(bpy.types.Panel):
    '''
    Having a copy here matters because beginners have no idea the right-click menu can trigger these features; unless it is handed to them on a plate, beginners will not discover them.
    So the panel also holds a copy for the convenience of beginners. Of course, it is collapsed by default so it does not affect the visuals, and once a beginner has used it enough to become an expert, they use the right-click menu options instead.
    '''
    bl_label = "Model Processing Panel" 
    bl_idname = "VIEW3D_PT_MIMI_ModelProcess_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator(MirrorMeshOperator.bl_idname)
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
    Keeping these only in the MIMITools panel is not enough either, because users with a lot of add-ons installed often cannot see the MIMITools panel at all
    So a copy is also placed in the right-click 3Dmigoto menu, which makes them easier to find.
    '''
    bl_idname = "VIEW3D_MT_object_3Dmigoto"
    bl_label = "3Dmigoto"
    bl_description = "Common features for making 3Dmigoto Mods."
    
    def draw(self, context):
        layout = self.layout
        layout.operator(MirrorMeshOperator.bl_idname)
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
    bpy.utils.register_class(MirrorMeshOperator)
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
    bpy.utils.unregister_class(MirrorMeshOperator)
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
