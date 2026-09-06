import bpy
import json
import math
import bmesh
import os

from mathutils import *
from math import * 

from typing import List, Dict, Union
from dataclasses import dataclass, field, asdict

from .format_utils import Fatal
from operator import attrgetter, itemgetter


@dataclass
class UserContext:
    active_object: bpy.types.Object
    selected_objects: bpy.types.Object
    mode: str


class OpenObjects:
    def __init__(self, context, objects, mode='OBJECT'):
        self.mode = mode
        self.objects = [ObjUtils.assert_object(obj) for obj in objects]
        self.context = context
        self.user_context = ObjUtils.get_user_context(context)

    def __enter__(self):

        ObjUtils.deselect_all_objects()
        
        for obj in self.objects:
            ObjUtils.unhide_object(obj)
            ObjUtils.select_object(obj)
            if obj.mode == 'EDIT':
                obj.update_from_editmode()
            
        ObjUtils.set_active_object(bpy.context, self.objects[0])

        ObjUtils.set_mode(self.context, mode=self.mode)

        return self.objects

    def __exit__(self, *args):
        ObjUtils.set_user_context(self.context, self.user_context)


@dataclass
class TempObject:
    name: str
    object: bpy.types.Object
    vertex_count: int = 0
    index_count: int = 0
    index_offset: int = 0


@dataclass
class MergedObjectComponent:
    objects: List[TempObject]
    vertex_count: int = 0
    index_count: int = 0

@dataclass
class MergedObjectShapeKeys:
    vertex_count: int = 0


@dataclass
class MergedObject:
    object: bpy.types.Object
    mesh: bpy.types.Mesh
    components: List[MergedObjectComponent]
    shapekeys: MergedObjectShapeKeys
    vertex_count: int = 0
    index_count: int = 0
    vg_count: int = 0


class OpenObject:
    def __init__(self, context, obj, mode='OBJECT'):
        self.mode = mode
        self.object = ObjUtils.assert_object(obj)
        self.context = context
        self.user_context = ObjUtils.get_user_context(context)
        self.was_hidden = ObjUtils.object_is_hidden(self.object)

    def __enter__(self):
        ObjUtils.deselect_all_objects()

        ObjUtils.unhide_object(self.object)
        ObjUtils.select_object(self.object)
        ObjUtils.set_active_object(bpy.context, self.object)

        if self.object.mode == 'EDIT':
            self.object.update_from_editmode()

        ObjUtils.set_mode(self.context, mode=self.mode)

        return self.object

    def __exit__(self, *args):
        if self.was_hidden:
            ObjUtils.hide_object(self.object)
        else:
            ObjUtils.unhide_object(self.object)
        ObjUtils.set_user_context(self.context, self.user_context)


class ObjUtils:

    @staticmethod
    def rename_object(obj, obj_name):
        obj = ObjUtils.assert_object(obj)
        obj.name = obj_name

    @staticmethod
    def join_objects(context, objects):
        '''
        Nico: Damn, it actually uses the plain join operator; my earlier approach of reading the
        buffer attribute of each obj and splicing it together was buggy.
        So WWMI's per-Component vertex-group statistics need this join technique after all.
        '''
        if len(objects) == 1:
            return
        unused_meshes = []
        with OpenObject(context, objects[0], mode='OBJECT'):
            for obj in objects[1:]:
                unused_meshes.append(obj.data)
                ObjUtils.select_object(obj)  
                bpy.ops.object.join()
        for mesh in unused_meshes:
            ObjUtils.remove_mesh(mesh)

    @staticmethod
    def get_vertex_groups(obj):
        obj = ObjUtils.assert_object(obj)
        return obj.vertex_groups

    @staticmethod
    def triangulate_object(context, obj):
        with OpenObject(context, obj, mode='OBJECT') as obj:
            me = obj.data
            bm = bmesh.new()
            bm.from_mesh(me)
            bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
            bm.to_mesh(me)
            bm.free()

    @staticmethod
    def assert_object(obj)->bpy.types.Object:
        if isinstance(obj, str):
            obj = ObjUtils.get_object(obj)
        elif obj not in bpy.data.objects.values():
            raise ValueError('Not of object type: %s' % str(obj))
        return obj


    @staticmethod
    def get_object(obj_name)->bpy.types.Object:
        return bpy.data.objects[obj_name]

    @staticmethod
    def select_obj(target_obj:bpy.types.Object):
        # Assume obj_copy is the object you have just created/copied
        view_layer = bpy.context.view_layer

        # 1. Clear all current selections (optional, but usually needed)
        # bpy.ops.object.select_all(action='DESELECT')
        # Nico: note that bpy.ops.object.select_all(action='DESELECT') cannot be used here,
        # because that operator has a poll() check,
        # bpy.ops.object.select_all 
        # and it usually requires the current context to be a 3D viewport.
        # If the script runs in a button callback of another panel (e.g. the Properties panel), or in the background,
        # the current Context may not satisfy this requirement, causing the poll() check to fail.
        # Fix:
        # Do not use operators that depend on the Context, such as bpy.ops.object.select_all(action='DESELECT');
        # instead, modify the object selection state directly with Blender's data API.
        # This is lower-level, not restricted by the Context, and more stable.
        for obj in bpy.context.selected_objects:
            obj.select_set(False)

        # 2. Set the active object
        view_layer.objects.active = target_obj

        # 3. Select it
        target_obj.select_set(True)

        # 4. Force a refresh (needed in some modes)
        view_layer.update()

    @staticmethod
    def get_obj_by_name(name: str) -> bpy.types.Object | None:
        """Get the Object by name; return None if not found"""
        return bpy.data.objects.get(name)          # Equivalent to bpy.data.objects[name], but without raising KeyError
    
    @staticmethod
    def get_mesh_evaluate_from_obj(obj:bpy.types.Object) -> bpy.types.Mesh:
        '''
        Nico: evaluated_get returns a new mesh meant for export; it does not affect the original Mesh
        '''
        return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()

    @staticmethod
    def split_obj_by_loose_parts_to_collection(obj,collection_name:str):
        
        new_collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(new_collection)

        # Copy the original object and link it to the new collection
        obj_copy = obj.copy()
        obj_copy.data = obj.data.copy()
        new_collection.objects.link(obj_copy)
        
        # Deselect the original object
        obj.select_set(False)
        
        # Make the copy the active object and enter Edit Mode
        bpy.context.view_layer.objects.active = obj_copy
        obj_copy.select_set(True)  # ensure the copy is selected
        bpy.ops.object.mode_set(mode='EDIT')
        
        # Separate into loose parts
        bpy.ops.mesh.separate(type='LOOSE')
        
        # Return to Object Mode
        bpy.ops.object.mode_set(mode='OBJECT')

        # Cleanup: deselect the copy so it does not affect later operations
        obj_copy.select_set(False)

        # After separating, remove the extra Basis.001 (Blender may auto-create duplicate Basis shape keys when copying)
        for coll_obj in new_collection.objects:
            if coll_obj.type == 'MESH' and coll_obj.data.shape_keys:
                sk_to_remove = []
                for sk in coll_obj.data.shape_keys.key_blocks:
                    if sk.name != 'Basis' and sk.name.startswith('Basis'):
                        sk_to_remove.append(sk.name)
                for sk_name in sk_to_remove:
                    coll_obj.shape_key_remove(coll_obj.data.shape_keys.key_blocks[sk_name])

    @staticmethod
    def merge_objects(obj_list, target_collection=None):
        """
        Merge the given list of objects.
        
        :param obj_list: list of objects to merge
        :param target_collection: target collection; if None, use the active collection of the current scene
        """
        # Make sure there is at least one object to merge
        if len(obj_list) < 1:
            print("Not enough objects to merge")
            return
        
        # If no target collection was given, use the default collection of the current scene
        if target_collection is None:
            target_collection = bpy.context.collection
        
        # Deselect all objects
        bpy.ops.object.select_all(action='DESELECT')

        # Select and make one of the objects in the list active
        for obj in obj_list:
            obj.select_set(True)
            if obj.name in bpy.context.view_layer.objects:
                bpy.context.view_layer.objects.active = obj
        
        # Ensure the active object is set to one of the objects to be merged
        active_obj = bpy.context.view_layer.objects.active
        
        # Perform the join operation
        bpy.ops.object.join()

        # After joining, the result is a single object. We can rename it if needed.
        joined_obj = bpy.context.view_layer.objects.active
        joined_obj.name = "MeshObject"
        
        # Optionally move the merged object to the specified collection
        for col in joined_obj.users_collection:
            col.objects.unlink(joined_obj)
        target_collection.objects.link(joined_obj)

    @classmethod
    def normalize_all(cls,obj):
        # Before calling this, make sure obj is selected, i.e. it is the current active object
        cls.select_obj(obj)

        # print("Normalize All Weights For: " + obj.name)
        # Select the object to operate on; this assumes the scene contains a single imported OBJ object
        if obj and obj.type == 'MESH':
            # Check whether all vertex groups are locked
            if cls.is_all_vertex_groups_locked(obj):
                print(f"Warning: All vertex groups of object {obj.name} are locked; unlocking them to run normalization...")
                for vg in obj.vertex_groups:
                    vg.lock_weight = False

            # Enter Weight Paint mode (if needed)
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            
            # Make sure the object is active and selected
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            
            # Apply Normalize All to all vertex groups
            bpy.ops.object.vertex_group_normalize_all()

            # Return to Object Mode
            bpy.ops.object.mode_set(mode='OBJECT')
        else:
            print("No suitable mesh object found to perform normalization.")

    @staticmethod
    def mesh_triangulate(me:bpy.types.Mesh):
        '''
        Triangulate a mesh
        Note that after this the mesh becomes the new triangulated mesh
        '''
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=bm.faces, quad_method='BEAUTY', ngon_method='BEAUTY')
        bm.to_mesh(me)
        bm.free()

    @staticmethod
    def get_bpy_context_object():
        '''
        Get the current scene's obj object; raise Fatal if it is None
        '''
        obj = bpy.context.object
        if obj is None:
            # Do not export when it is None
            raise Fatal('No object selected')
        
        return obj

    @staticmethod
    def selected_obj_delete_loose():
        
        # Get the currently selected objects
        selected_objects = bpy.context.selected_objects
        # Check whether a Mesh object is selected
        for obj in selected_objects:
            if obj.type == 'MESH':
                # Make the current object active (otherwise Edit Mode cannot be entered later and it errors out)
                bpy.context.view_layer.objects.active = obj
                # Get the selected mesh object
                bpy.ops.object.mode_set(mode='EDIT')
                # Select all vertices
                bpy.ops.mesh.select_all(action='SELECT')
                # Run the delete-loose-vertices operator
                bpy.ops.mesh.delete_loose()
                # Switch back to Object Mode
                bpy.ops.object.mode_set(mode='OBJECT')

    @staticmethod
    def is_contains_locked_weights(obj):
        locked_groups = []
        # Restrict to MESH objects, since only they have vertex groups
        if obj.type == 'MESH':
            # Iterate over all of the object's vertex groups
            for vg in obj.vertex_groups:
                # Collect the locked vertex groups into a list
                if vg.lock_weight:
                    locked_groups.append(vg.name)
        if len(locked_groups) != 0:
            return True
        else:
            return False
        
    @staticmethod
    def is_all_vertex_groups_locked(obj):
        '''
        Return whether all vertex groups are locked, since Normalize All cannot be run on the weights while every group is locked
        '''
        vgs_number = 0
        locked_groups = []
        # Restrict to MESH objects, since only they have vertex groups
        if obj.type == 'MESH':
            # Iterate over all of the object's vertex groups
            for vg in obj.vertex_groups:
                vgs_number = vgs_number + 1
                # Collect the locked vertex groups into a list
                if vg.lock_weight:
                    locked_groups.append(vg.name)
        if len(locked_groups) == vgs_number:
            return True
        else:
            return False

    @staticmethod
    def are_vertex_weights_normalized(obj, epsilon=1e-5):
        """Return whether every mesh vertex already has a unit weight sum.

        Empty groups created to fill vertex-group index gaps do not contribute
        to ``vertex.groups``.  Consequently a vertex assigned fully to one
        group is already normalized and must not be passed through Blender's
        Normalize All operator (which can fail when the groups are locked).
        """
        if obj is None or getattr(obj, "type", None) != 'MESH':
            return False

        vertices = getattr(getattr(obj, "data", None), "vertices", None)
        if vertices is None:
            return False

        for vertex in vertices:
            groups = getattr(vertex, "groups", ())
            if not groups:
                return False
            weight_sum = sum(group.weight for group in groups)
            if not math.isfinite(weight_sum) or abs(weight_sum - 1.0) > epsilon:
                return False
        return True

    @staticmethod
    def copy_object(context, obj, name=None, collection=None):
        '''
        collection is where the copy is linked after duplication
        '''
        with OpenObject(context, obj, mode='OBJECT') as obj:
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            if name:
                ObjUtils.rename_object(new_obj, name)
            if collection:
                ObjUtils.link_object_to_collection(new_obj, collection)
            return new_obj
    
    
    @staticmethod
    def reset_obj_rotation(obj):
        if obj.type == "MESH":
            # Reset the rotation to zero
            obj.rotation_euler[0] = 0.0  # X axis
            obj.rotation_euler[1] = 0.0  # Y axis
            obj.rotation_euler[2] = 0.0  # Z axis

    @staticmethod
    def reset_obj_location(obj):
        if obj.type == "MESH":
            # Reset the location to zero
            obj.location[0] = 0.0  # X axis
            obj.location[1] = 0.0  # Y axis
            obj.location[2] = 0.0  # Z axis

    @staticmethod
    def apply_mirror_transform(obj):
        '''
        Apply the mirror transform: set Scale X to -1 and apply the scale transform,
        using Blender's built-in apply-transform feature
        '''
        if obj.type != 'MESH':
            return
        
        original_active = bpy.context.view_layer.objects.active
        original_selected = list(bpy.context.selected_objects)
        original_mode = obj.mode
        
        try:
            if original_mode == 'EDIT':
                bpy.ops.object.mode_set(mode='OBJECT')
            
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            
            obj.scale[0] = -obj.scale[0]
            
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            
        finally:
            if original_mode == 'EDIT':
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(True)
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')
                except Exception:
                    pass
            
            bpy.ops.object.select_all(action='DESELECT')
            for sel_obj in original_selected:
                if sel_obj:
                    try:
                        sel_obj.select_set(True)
                    except Exception:
                        pass
            if original_active:
                try:
                    bpy.context.view_layer.objects.active = original_active
                except Exception:
                    pass

    @staticmethod
    def flip_face_normals(obj):
        '''
        Flip face orientation using Blender's built-in flip-normals feature
        '''
        if obj.type != 'MESH':
            return
        
        original_active = bpy.context.view_layer.objects.active
        original_selected = list(bpy.context.selected_objects)
        original_mode = obj.mode
        
        try:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            
            bpy.ops.object.mode_set(mode='EDIT')
            
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.flip_normals()
            bpy.ops.object.mode_set(mode='OBJECT')
            
        finally:
            if original_mode == 'EDIT':
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(True)
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')
                except Exception:
                    pass
            
            bpy.ops.object.select_all(action='DESELECT')
            for sel_obj in original_selected:
                if sel_obj:
                    try:
                        sel_obj.select_set(True)
                    except Exception:
                        pass
            if original_active:
                try:
                    bpy.context.view_layer.objects.active = original_active
                except Exception:
                    pass

    @classmethod
    def prepare_copy_for_mirror_workflow(cls, copy_obj):
        '''
        Prepare the copy for the non-mirror workflow
        Run this before triangulation
        
        Optimizations:
        1. Only inspect enabled armature modifiers
        2. Disabled modifiers are removed inside _apply_all_modifiers
        
        Case 1: object has an enabled armature binding but no shape keys
          - Apply all modifiers
        
        Case 2: object has both an enabled armature binding and shape keys
          - Zero the shape keys to obtain the base state
          - Apply the modifiers
          - Re-apply the shape keys (keeping their original values)
        
        Case 3: object has no enabled armature binding
          - Skip it; other modifiers are handled later
        '''
        if copy_obj.type != 'MESH':
            return
        
        has_enabled_armature = any(
            mod.type == 'ARMATURE' and mod.show_viewport 
            for mod in copy_obj.modifiers
        )
        has_shape_keys = copy_obj.data.shape_keys is not None
        
        if not has_enabled_armature:
            print(f"Object {copy_obj.name} has no enabled armature binding; no preprocessing needed")
            return
        
        if has_shape_keys:
            print(f"Object {copy_obj.name} has an enabled armature binding and shape keys; running special preprocessing")
            cls._prepare_with_shape_keys(copy_obj)
        else:
            print(f"Object {copy_obj.name} has an enabled armature binding but no shape keys; applying modifiers")
            cls._apply_all_modifiers(copy_obj)
    
    @staticmethod
    def _prepare_with_shape_keys(obj):
        '''
        Handle a bound object (armature-deformed) that has shape keys
        1. Remove disabled modifiers (optimization: do not apply unneeded ones)
        2. Save the shape key values
        3. Zero out the shape keys
        4. Apply the modifiers (using the optimized routine)
        5. Re-apply the shape keys (preserving the original values)
        '''
        if obj.type != 'MESH':
            return
        
        if obj.data.shape_keys is None:
            return
        
        disabled_modifiers = [mod for mod in obj.modifiers if not mod.show_viewport]
        for mod in reversed(disabled_modifiers):
            print(f"Removing disabled modifier: {mod.name} ({mod.type})")
            obj.modifiers.remove(mod)
        
        if not obj.modifiers:
            print(f"Object {obj.name} has no enabled modifiers; skipping apply")
            return
        
        shape_key_values = {}
        for kb in obj.data.shape_keys.key_blocks:
            shape_key_values[kb.name] = kb.value
        
        from .shapekey_utils import ShapeKeyUtils
        ShapeKeyUtils.reset_all_shapekey_values(obj)
        
        modifier_names = [mod.name for mod in obj.modifiers]
        if modifier_names:
            ShapeKeyUtils.apply_modifiers_for_object_with_shape_keys_optimized(
                bpy.context,
                modifier_names,
                disable_armatures=False
            )
        
        if obj.data.shape_keys:
            for kb in obj.data.shape_keys.key_blocks:
                if kb.name in shape_key_values:
                    kb.value = shape_key_values[kb.name]
    
    @classmethod
    def apply_mirror_workflow(cls, obj):
        '''
        Apply the non-mirror workflow: Scale X = -1 + flip face orientation
        Note: if the object has an armature binding, the modifiers are applied first to bake the bone deformation into the mesh
        '''
        if obj.type != 'MESH':
            return
        
        has_armature = any(mod.type == 'ARMATURE' for mod in obj.modifiers)
        
        if has_armature:
            cls._apply_all_modifiers(obj)
        
        cls.apply_mirror_transform(obj)
        cls.flip_face_normals(obj)
    
    @staticmethod
    def _apply_all_modifiers(obj):
        '''
        Apply all modifiers on the object.
        Bake the modifier effects into the mesh data.
        If the object has shape keys, handle them in a special way.
        
        Optimizations:
        1. Remove disabled modifiers first (they are not applied)
        2. Apply only the enabled modifiers
        '''
        if obj.type != 'MESH':
            return
        
        if not obj.modifiers:
            return
        
        original_active = bpy.context.view_layer.objects.active
        original_selected = list(bpy.context.selected_objects)
        original_mode = obj.mode
        
        try:
            if original_mode == 'EDIT':
                bpy.ops.object.mode_set(mode='OBJECT')
            
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            
            disabled_modifiers = [mod for mod in obj.modifiers if not mod.show_viewport]
            for mod in reversed(disabled_modifiers):
                print(f"Removing disabled modifier: {mod.name} ({mod.type})")
                obj.modifiers.remove(mod)
            
            if not obj.modifiers:
                print(f"Object {obj.name} has no enabled modifiers")
                return
            
            from .shapekey_utils import ShapeKeyUtils
            
            has_shape_keys = obj.data.shape_keys is not None
            
            if has_shape_keys:
                print(f"Object {obj.name} has shape keys; applying modifiers in a special way")
                modifier_names = [mod.name for mod in obj.modifiers]
                ShapeKeyUtils.apply_modifiers_for_object_with_shape_keys(
                    bpy.context, 
                    modifier_names, 
                    disable_armatures=False
                )
            else:
                print(f"Object {obj.name} has no shape keys; applying modifiers directly")
                for modifier in obj.modifiers[:]:
                    try:
                        bpy.ops.object.modifier_apply(modifier=modifier.name)
                    except Exception as e:
                        print(f"Warning: Could not apply modifier {modifier.name}: {e}")
            
        finally:
            if original_mode == 'EDIT':
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(True)
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')
                except Exception:
                    pass
            
            bpy.ops.object.select_all(action='DESELECT')
            for sel_obj in original_selected:
                if sel_obj:
                    try:
                        sel_obj.select_set(True)
                    except Exception:
                        pass
            if original_active:
                try:
                    bpy.context.view_layer.objects.active = original_active
                except Exception:
                    pass

    @classmethod
    def apply_mirror_workflow_to_objects(cls, obj_list):
        '''
        Apply the non-mirror workflow to multiple objects
        '''
        for obj in obj_list:
            if obj and obj.type == 'MESH':
                cls.apply_mirror_workflow(obj)

    @staticmethod
    def create_backup_object(obj):
        '''
        Create a complete backup of the object (including its mesh data).
        Return the backup object.
        '''
        if obj.type != 'MESH':
            return None
        
        backup_obj = obj.copy()
        backup_obj.data = obj.data.copy()
        backup_obj.name = f"__backup_{obj.name}"
        
        backup_collection = bpy.data.collections.get("__export_backup__")
        if not backup_collection:
            backup_collection = bpy.data.collections.new("__export_backup__")
            bpy.context.scene.collection.children.link(backup_collection)
        
        backup_collection.objects.link(backup_obj)
        
        return backup_obj

    @staticmethod
    def restore_from_backup(original_obj, backup_obj):
        '''
        Restore the original object's mesh data from the backup object
        '''
        if not original_obj or not backup_obj:
            return
        
        if original_obj.type != 'MESH' or backup_obj.type != 'MESH':
            return
        
        original_obj.data = backup_obj.data.copy()

    @staticmethod
    def delete_backup_object(backup_obj):
        '''
        Delete the backup object
        '''
        if not backup_obj:
            return
        
        mesh_data = backup_obj.data
        
        if backup_obj.name in bpy.data.objects:
            bpy.data.objects.remove(backup_obj, do_unlink=True)
        
        if mesh_data and mesh_data.name in bpy.data.meshes:
            bpy.data.meshes.remove(mesh_data, do_unlink=True)

    @classmethod
    def create_backup_objects(cls, obj_list):
        '''
        Create backups for multiple objects.
        Return a dictionary mapping {original object: backup object}.
        '''
        backup_dict = {}
        for obj in obj_list:
            if obj and obj.type == 'MESH':
                backup_obj = cls.create_backup_object(obj)
                if backup_obj:
                    backup_dict[obj] = backup_obj
        return backup_dict

    @classmethod
    def restore_and_cleanup_backups(cls, backup_dict):
        '''
        Restore all objects from their backups and clean up the backup data
        '''
        for original_obj, backup_obj in backup_dict.items():
            cls.restore_from_backup(original_obj, backup_obj)
            cls.delete_backup_object(backup_obj)
        
        backup_collection = bpy.data.collections.get("__export_backup__")
        if backup_collection:
            try:
                bpy.data.collections.remove(backup_collection)
            except Exception:
                pass

    # ============================================================
    #  Consolidation of standalone functions - the following are static utility methods moved in from module level
    # ============================================================

    @staticmethod
    def get_mode(context):
        if context.active_object:
            return context.active_object.mode

    @staticmethod
    def set_mode(context, mode):
        active_object = ObjUtils.get_active_object(context)
        if active_object is not None and mode is not None:
            if not ObjUtils.object_is_hidden(active_object):
                bpy.ops.object.mode_set(mode=mode)

    @staticmethod
    def get_user_context(context):
        return UserContext(
            active_object=ObjUtils.get_active_object(context),
            selected_objects=ObjUtils.get_selected_objects(context),
            mode=ObjUtils.get_mode(context),
        )

    @staticmethod
    def set_user_context(context, user_context):
        ObjUtils.deselect_all_objects()
        for obj in user_context.selected_objects:
            try:
                ObjUtils.select_object(obj)
            except ReferenceError:
                pass
        if user_context.active_object:
            ObjUtils.set_active_object(context, user_context.active_object)
            ObjUtils.set_mode(context, user_context.mode)

    @staticmethod
    def get_active_object(context):
        return context.view_layer.objects.active

    @staticmethod
    def get_selected_objects(context):
        return context.selected_objects

    @staticmethod
    def link_object_to_scene(context, obj):
        context.scene.collection.objects.link(obj)

    @staticmethod
    def unlink_object_from_scene(context, obj):
        context.scene.collection.objects.unlink(obj)

    @staticmethod
    def object_exists(obj_name):
        return obj_name in bpy.data.objects.keys()

    @staticmethod
    def link_object_to_collection(obj, col):
        obj = ObjUtils.assert_object(obj)
        col = ObjUtils.assert_collection(col)
        col.objects.link(obj)

    @staticmethod
    def unlink_object_from_collection(obj, col):
        obj = ObjUtils.assert_object(obj)
        col = ObjUtils.assert_collection(col)
        col.objects.unlink(obj)

    @staticmethod
    def select_object(obj):
        obj = ObjUtils.assert_object(obj)
        obj.select_set(True)

    @staticmethod
    def deselect_object(obj):
        obj = ObjUtils.assert_object(obj)
        obj.select_set(False)

    @staticmethod
    def deselect_all_objects():
        for obj in bpy.context.selected_objects:
            ObjUtils.deselect_object(obj)
        bpy.context.view_layer.objects.active = None

    @staticmethod
    def object_is_selected(obj):
        return obj.select_get()

    @staticmethod
    def set_active_object(context, obj):
        obj = ObjUtils.assert_object(obj)
        context.view_layer.objects.active = obj

    @staticmethod
    def object_is_hidden(obj):
        return obj.hide_get()

    @staticmethod
    def hide_object(obj):
        obj = ObjUtils.assert_object(obj)
        obj.hide_set(True)

    @staticmethod
    def unhide_object(obj):
        obj = ObjUtils.assert_object(obj)
        obj.hide_set(False)

    @staticmethod
    def set_custom_property(obj, property_name, value):
        obj = ObjUtils.assert_object(obj)
        obj[property_name] = value

    @staticmethod
    def remove_object(obj):
        obj = ObjUtils.assert_object(obj)
        bpy.data.objects.remove(obj, do_unlink=True)

    @staticmethod
    def get_modifiers(obj):
        obj = ObjUtils.assert_object(obj)
        return obj.modifiers

    @staticmethod
    def assert_vertex_group(obj, vertex_group):
        obj = ObjUtils.assert_object(obj)
        if isinstance(vertex_group, bpy.types.VertexGroup):
            vertex_group = vertex_group.name
        return obj.vertex_groups[vertex_group]

    @staticmethod
    def remove_vertex_groups(obj, vertex_groups):
        obj = ObjUtils.assert_object(obj)
        for vg in vertex_groups:
            obj.vertex_groups.remove(ObjUtils.assert_vertex_group(obj, vg))

    @staticmethod
    def normalize_all_weights(context, obj):
        with OpenObject(context, obj, mode='WEIGHT_PAINT') as o:
            bpy.ops.object.vertex_group_normalize_all()

    @staticmethod
    def assert_mesh(mesh):
        if isinstance(mesh, str):
            mesh = ObjUtils.get_mesh(mesh)
        elif mesh not in bpy.data.meshes.values():
            raise ValueError('Not of mesh type: %s' % str(mesh))
        return mesh

    @staticmethod
    def get_mesh(mesh_name):
        return bpy.data.meshes[mesh_name]

    @staticmethod
    def remove_mesh(mesh):
        mesh = ObjUtils.assert_mesh(mesh)
        bpy.data.meshes.remove(mesh, do_unlink=True)

    @staticmethod
    def mesh_triangulate_raw(me):
        '''Triangulate a mesh (pure data operation, no context involved)'''
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=bm.faces, quad_method='BEAUTY', ngon_method='BEAUTY')
        bm.to_mesh(me)
        bm.free()

    @staticmethod
    def mesh_triangulate_beauty(obj):
        '''
        Triangulate with Blender's built-in BEAUTY algorithm.
        Uses bpy.ops.mesh.quads_convert_to_tris to guarantee consistent triangulation results.
        '''
        if obj.type != 'MESH':
            return

        original_active = bpy.context.view_layer.objects.active
        original_selected = list(bpy.context.selected_objects)
        original_mode = obj.mode

        def deselect_all_safe():
            for o in bpy.context.selected_objects:
                o.select_set(False)

        try:
            deselect_all_safe()
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            if original_mode != 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
            bpy.ops.object.mode_set(mode='OBJECT')

        finally:
            if original_mode == 'EDIT':
                try:
                    deselect_all_safe()
                    obj.select_set(True)
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')
                except Exception:
                    pass

            deselect_all_safe()
            for sel_obj in original_selected:
                if sel_obj:
                    try:
                        sel_obj.select_set(True)
                    except Exception:
                        pass
            if original_active:
                try:
                    bpy.context.view_layer.objects.active = original_active
                except Exception:
                    pass

    @staticmethod
    def get_vertex_groups_from_bmesh(bm):
        layer_deform = bm.verts.layers.deform.active
        return [sorted(vert[layer_deform].items(), key=itemgetter(1), reverse=True) for vert in bm.verts]

    @staticmethod
    def get_collection(col_name):
        return bpy.data.collections[col_name]

    @staticmethod
    def get_layer_collection(col, layer_col=None):
        col_name = ObjUtils.assert_collection(col).name
        if layer_col is None:
            layer_col = bpy.context.view_layer.layer_collection
        if layer_col.name == col_name:
            return layer_col
        for sublayer_col in layer_col.children:
            found = ObjUtils.get_layer_collection(col_name, layer_col=sublayer_col)
            if found:
                return found

    @staticmethod
    def collection_exists(col_name):
        return col_name in bpy.data.collections.keys()

    @staticmethod
    def assert_collection(col):
        if isinstance(col, str):
            col = ObjUtils.get_collection(col)
        elif not isinstance(col, bpy.types.Collection):
            raise ValueError('Not of collection type: %s' % str(col))
        return col

    @staticmethod
    def get_collection_objects(col):
        col = ObjUtils.assert_collection(col)
        return col.objects

    @staticmethod
    def link_collection(col, col_parent):
        col = ObjUtils.assert_collection(col)
        col_parent = ObjUtils.assert_collection(col_parent)
        col_parent.children.link(col)

    @staticmethod
    def new_collection(col_name, col_parent=None, allow_duplicate=True):
        if not allow_duplicate:
            try:
                col = ObjUtils.get_collection(col_name)
                if col is not None:
                    raise ValueError('Collection already exists: %s' % str(col_name))
            except Exception:
                pass
        new_col = bpy.data.collections.new(col_name)
        if col_parent:
            ObjUtils.link_collection(new_col, col_parent)
        else:
            bpy.context.scene.collection.children.link(new_col)
        return new_col

    @staticmethod
    def hide_collection(col):
        col = ObjUtils.assert_collection(col)
        ObjUtils.get_layer_collection(col).hide_viewport = True

    @staticmethod
    def unhide_collection(col):
        col = ObjUtils.assert_collection(col)
        ObjUtils.get_layer_collection(col).hide_viewport = False

    @staticmethod
    def collection_is_hidden(col):
        col = ObjUtils.assert_collection(col)
        return ObjUtils.get_layer_collection(col).hide_viewport

    @staticmethod
    def get_scene_collections():
        return bpy.context.scene.collection.children
