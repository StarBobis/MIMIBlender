import bpy
import itertools
import numpy
import math

from mathutils import Vector,Matrix

from .format_utils import Fatal
from .obj_utils import ObjUtils


class VertexGroupUtils:
    @staticmethod
    def remove_unused_vertex_groups(obj):
        '''
        Remove the unused vertex groups of the given obj
        '''
        if obj.type == "MESH":
            # obj = bpy.context.active_object
            obj.update_from_editmode()
            vgroup_used = {i: False for i, k in enumerate(obj.vertex_groups)}

            for v in obj.data.vertices:
                for g in v.groups:
                    if g.weight > 0.0:
                        vgroup_used[g.group] = True

            for i, used in sorted(vgroup_used.items(), reverse=True):
                if not used:
                    obj.vertex_groups.remove(obj.vertex_groups[i])

    @staticmethod
    def remove_all_vertex_groups(obj):
        '''
        Remove all vertex groups of the given obj
        '''
        if obj.type == "MESH":
            for x in obj.vertex_groups:
                obj.vertex_groups.remove(x)

    # @classmethod
    # def merge_vertex_groups_with_same_number(cls):
    #     # Author: SilentNightSound#7430
    #     # Combines vertex groups with the same prefix into one, a fast alternative to the Vertex Weight Mix that works for multiple groups
    #     # You will likely want to use blender_fill_vg_gaps.txt after this to fill in any gaps caused by merging groups together
    #     # Nico: we only need mode 3 here.

    #     selected_obj = [obj for obj in bpy.context.selected_objects]
    #     vgroup_names = []

    #     ##### USAGE INSTRUCTIONS
    #     # MODE 1: Runs the merge on a specific list of vertex groups in the selected object(s). Can add more names or fewer to the list - change the names to what you need
    #     # MODE 2: Runs the merge on a range of vertex groups in the selected object(s). Replace smallest_group_number with the lower bound, and largest_group_number with the upper bound
    #     # MODE 3 (DEFAULT): Runs the merge on ALL vertex groups in the selected object(s)

    #     # Select the mode you want to run:
    #     mode = 3

    #     # Required data for MODE 1:
    #     vertex_groups = ["replace_with_first_vertex_group_name", "second_vertex_group_name", "third_name_etc"]

    #     # Required data for MODE 2:
    #     smallest_group_number = 000
    #     largest_group_number = 999

    #     ######

    #     if mode == 1:
    #         vgroup_names = [vertex_groups]
    #     elif mode == 2:
    #         vgroup_names = [[f"{i}" for i in range(smallest_group_number, largest_group_number + 1)]]
    #     elif mode == 3:
    #         vgroup_names = [[x.name.split(".")[0] for x in y.vertex_groups] for y in selected_obj]
    #     else:
    #         raise Fatal("Mode not recognized, exiting")

    #     if not vgroup_names:
    #         raise Fatal(
    #             "No vertex groups found, please double check an object is selected and required data has been entered")

    #     for cur_obj, cur_vgroup in zip(selected_obj, itertools.cycle(vgroup_names)):
    #         for vname in cur_vgroup:
    #             relevant = [x.name for x in cur_obj.vertex_groups if x.name.split(".")[0] == f"{vname}"]

    #             if relevant:

    #                 vgroup = cur_obj.vertex_groups.new(name=f"x{vname}")

    #                 for vert_id, vert in enumerate(cur_obj.data.vertices):
    #                     available_groups = [v_group_elem.group for v_group_elem in vert.groups]

    #                     combined = 0
    #                     for v in relevant:
    #                         if cur_obj.vertex_groups[v].index in available_groups:
    #                             combined += cur_obj.vertex_groups[v].weight(vert_id)

    #                     if combined > 0:
    #                         vgroup.add([vert_id], combined, 'ADD')

    #                 for vg in [x for x in cur_obj.vertex_groups if x.name.split(".")[0] == f"{vname}"]:
    #                     cur_obj.vertex_groups.remove(vg)

    #                 for vg in cur_obj.vertex_groups:
    #                     if vg.name[0].lower() == "x":
    #                         vg.name = vg.name[1:]

    #         bpy.context.view_layer.objects.active = cur_obj
    #         bpy.ops.object.vertex_group_sort()

    @staticmethod
    def merge_vertex_groups_with_same_number_v2():
        '''
        Optimized version of Mode 3 of merge_vertex_groups_with_same_number
        Greatly improved execution speed (Differential Update Strategy)

        
        '''
        selected_objs = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
             raise Fatal("No mesh objects selected")

        for obj in selected_objs:
            # 1. Group by prefix
            groups_by_prefix = {}
            for vg in obj.vertex_groups:
                prefix = vg.name.split(".")[0]
                if prefix not in groups_by_prefix:
                    groups_by_prefix[prefix] = []
                groups_by_prefix[prefix].append(vg)
            
            # 2. Identify merge targets and sources
            # merge_actions stores: (target_vg_name, [source_vg_indices])
            # We store indices/names because pointers might be risky if we renamed things, usually ok though.
            merge_actions = [] 
            all_source_vgs = []
            
            for prefix, vgs in groups_by_prefix.items():
                if len(vgs) < 2:
                    # Rename single groups just in case
                    if vgs[0].name != prefix:
                        vgs[0].name = prefix
                    continue
                
                # Pick target: prefer exact match or first
                target = next((g for g in vgs if g.name == prefix), vgs[0])
                if target.name != prefix:
                    target.name = prefix
                
                sources = [g for g in vgs if g != target]
                merge_actions.append( (target.name, sources) )
                all_source_vgs.extend(sources)
            
            if not merge_actions:
                continue

            # 3. Create mapping for fast lookup
            # index -> target_name
            # obj.vertex_groups can be non-contiguous in memory but indices are 0..N-1 usually? 
            # VertexGroup.index is the index in the list.
            max_idx = max(vg.index for vg in obj.vertex_groups)
            idx_to_target = [None] * (max_idx + 1)
            
            for t_name, sources in merge_actions:
                for s in sources:
                    idx_to_target[s.index] = t_name

            # 4. Collect weight updates
            # target_name -> { vertex_idx: accumulated_weight }
            updates = {}

            # Iterate vertices
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group <= max_idx:
                        t_name = idx_to_target[g.group]
                        if t_name:
                            # Accumulate
                            if t_name not in updates:
                                updates[t_name] = {}
                            
                            u_dict = updates[t_name]
                            if v.index in u_dict:
                                u_dict[v.index] += g.weight
                            else:
                                u_dict[v.index] = g.weight

            # 5. Apply updates
            for t_name, w_dict in updates.items():
                vg = obj.vertex_groups.get(t_name)
                if not vg: continue

                for v_idx, w in w_dict.items():
                    if w > 0:
                        vg.add([v_idx], w, 'ADD')
            
            # 6. Remove source groups
            for vg in all_source_vgs:
                try:
                    obj.vertex_groups.remove(vg)
                except Exception:
                    pass # Already removed?
            
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.vertex_group_sort()


    @staticmethod
    def fill_vertex_group_gaps():
        # Author: SilentNightSound#7430
        # Fills in missing vertex groups for a model so there are no gaps, and sorts to make sure everything is in order
        # Works on the currently selected object
        # e.g. if the selected model has groups 0 1 4 5 7 2 it adds an empty group for 3 and 6 and sorts to make it 0 1 2 3 4 5 6 7
        # Very useful to make sure there are no gaps or out-of-order vertex groups

        # Can change this to another number in order to generate missing groups up to that number
        # e.g. setting this to 130 will create 0,1,2...130 even if the active selected object only has 90
        # Otherwise, it will use the largest found group number and generate everything up to that number
        largest = 0

        ob = bpy.context.active_object
        ob.update_from_editmode()

        for vg in ob.vertex_groups:
            try:
                if int(vg.name.split(".")[0]) > largest:
                    largest = int(vg.name.split(".")[0])
            except ValueError:
                print("Vertex group not named as integer, skipping")

        missing = set([f"{i}" for i in range(largest + 1)]) - set([x.name.split(".")[0] for x in ob.vertex_groups])
        for number in missing:
            ob.vertex_groups.new(name=f"{number}")

        bpy.ops.object.vertex_group_sort()


    # Improved version by HongXi: bones are placed at the geometry center
    @staticmethod
    def create_armature_from_vertex_groups(bone_length=0.1):
        # Validate the selected object
        obj = bpy.context.active_object
        if not obj or obj.type != 'MESH':
            raise Exception("Please select a mesh object first")
        
        if not obj.vertex_groups:
            raise Exception("The target object has no vertex groups")

        # Precompute the world transformation matrix
        matrix = obj.matrix_world

        # Create the armature object
        armature = bpy.data.armatures.new("AutoRig_Armature")
        armature_obj = bpy.data.objects.new("AutoRig", armature)
        bpy.context.scene.collection.objects.link(armature_obj)

        # Set the active object
        bpy.context.view_layer.objects.active = armature_obj
        armature_obj.select_set(True)

        # Pre-collect the vertex group data {vertex group index: [vertex list]}
        vg_verts = {vg.index: [] for vg in obj.vertex_groups}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group in vg_verts:
                    vg_verts[g.group].append(v)

        # Enter edit mode to create the bones
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            for vg in obj.vertex_groups:
                verts = vg_verts.get(vg.index)
                if not verts:
                    continue

                # Compute the geometry center (world coordinates)
                coords = [matrix @ v.co for v in verts]
                center = sum(coords, Vector()) / len(coords)

                # Create the bone along the vertical direction
                bone = armature.edit_bones.new(vg.name)
                bone.head = center
                bone.tail = center + Vector((0, 0, 0.1))  # Fixed Z-axis direction

        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

    @staticmethod
    def remove_not_number_vertex_groups(obj):
        for vg in reversed(obj.vertex_groups):
            if vg.name.isdecimal():
                continue
            # print('Removing vertex group', vg.name)
            obj.vertex_groups.remove(vg)

    @staticmethod
    def split_mesh_by_vertex_group(obj):
        '''
        Code copied and modified from @Kail_Nethunter, very useful in some special meets.
        https://blenderartists.org/t/split-a-mesh-by-vertex-groups/438990/11
        '''
        origin_name = obj.name
        keys = obj.vertex_groups.keys()
        real_keys = []
        for gr in keys:
            bpy.ops.object.mode_set(mode="EDIT")
            # Set the vertex group as active
            bpy.ops.object.vertex_group_set_active(group=gr)

            # Deselect all verts and select only current VG
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.vertex_group_select()
            # bpy.ops.mesh.select_all(action='INVERT')
            try:
                bpy.ops.mesh.separate(type="SELECTED")
                real_keys.append(gr)
            except Exception:
                pass
        for i in range(1, len(real_keys) + 1):
            bpy.data.objects['{}.{:03d}'.format(origin_name, i)].name = '{}.{}'.format(
                origin_name, real_keys[i - 1])

    @staticmethod
    def split_mesh_by_each_vertex_group(obj: bpy.types.Object):
        """
        Split the given object into separate meshes by each vertex group.
        All vertices used by each vertex group form a new mesh, preserving all attributes (UV, weight, color, normal, shape keys, etc.).
        Results are placed into a new collection named '{obj.name}_Split'.
        """
        origin_name = obj.name
        collection_name = f"{origin_name}_Split"

        # Create the target collection
        new_collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(new_collection)

        # Count the vertices of each vertex group, skipping empty groups
        vg_vert_count: dict[str, int] = {}
        for vg in obj.vertex_groups:
            count = 0
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0:
                        count += 1
                        break
            if count > 0:
                vg_vert_count[vg.name] = count

        if not vg_vert_count:
            raise Fatal(f"Object '{origin_name}' has no non-empty vertex groups")

        # Save the user's context
        original_active = bpy.context.view_layer.objects.active
        original_selected = [o for o in bpy.context.selected_objects]

        for vg_name in vg_vert_count:
            # Copy the full object (the mesh data is copied independently)
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = f"{origin_name}_{vg_name}"
            new_collection.objects.link(new_obj)

            # Select the copy and make it active
            bpy.ops.object.select_all(action='DESELECT')
            new_obj.select_set(True)
            bpy.context.view_layer.objects.active = new_obj

            # Enter edit mode
            bpy.ops.object.mode_set(mode='EDIT')

            # Select the vertices of the current vertex group
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.vertex_group_set_active(group=vg_name)
            bpy.ops.object.vertex_group_select()

            # Invert the selection -> delete vertices not in the current vertex group
            bpy.ops.mesh.select_all(action='INVERT')
            bpy.ops.mesh.delete(type='VERT')

            # Return to object mode
            bpy.ops.object.mode_set(mode='OBJECT')

            # Remove unused vertex groups (groups whose vertices were all deleted)
            used_groups = set()
            for v in new_obj.data.vertices:
                for g in v.groups:
                    used_groups.add(g.group)
            for vg in reversed(new_obj.vertex_groups):
                if vg.index not in used_groups:
                    new_obj.vertex_groups.remove(vg)

        # Restore the user's context
        bpy.ops.object.select_all(action='DESELECT')
        for o in original_selected:
            try:
                o.select_set(True)
            except ReferenceError:
                pass
        if original_active:
            try:
                bpy.context.view_layer.objects.active = original_active
            except ReferenceError:
                pass

        return new_collection

    @staticmethod
    def split_by_loose_parts_and_cluster(obj: bpy.types.Object, vg_similarity_threshold: float = 0.7, bbox_distance_threshold: float = 0.01):
        """
        1. Split the object by loose parts
        2. Cluster the loose parts: loose parts with similar VG sets (Jaccard similarity >= threshold)
           and spatial adjacency (centroid distance <= bbox_distance_threshold) are merged into one part.
        Results are placed into the '{obj.name}_SplitCluster' collection.
        """
        import math
        from mathutils import Vector

        origin_name = obj.name
        collection_name = f"{origin_name}_SplitCluster"

        # Precompute the set of VG names each vertex of the original object belongs to (avoids repeated traversal later)
        vert_vg_names: list[set[str]] = [set() for _ in range(len(obj.data.vertices))]
        for v in obj.data.vertices:
            names = vert_vg_names[v.index]
            for g in v.groups:
                if g.weight > 0:
                    names.add(obj.vertex_groups[g.group].name)

        # Step 1: Split by loose parts
        ObjUtils.split_obj_by_loose_parts_to_collection(obj=obj, collection_name=collection_name)
        new_collection = bpy.data.collections.get(collection_name)
        if not new_collection:
            return None

        loose_objects = [o for o in new_collection.objects if o.type == 'MESH']
        if len(loose_objects) <= 1:
            return new_collection

        # Step 2: Use the precomputed vert_vg_names to quickly get the VG set of each loose part (without modifying objects)
        obj_vg_sets: dict[str, set[str]] = {}
        for lobj in loose_objects:
            vg_set: set[str] = set()
            for v in lobj.data.vertices:
                if v.index < len(vert_vg_names):
                    vg_set |= vert_vg_names[v.index]
            obj_vg_sets[lobj.name] = vg_set

        # Step 3: Compute the centroid of each loose part (average vertex position); use centroid distance to judge adjacency
        def _centroid(obj: bpy.types.Object) -> Vector:
            c = Vector((0.0, 0.0, 0.0))
            verts = obj.data.vertices
            if not verts:
                return c
            for v in verts:
                c += obj.matrix_world @ v.co
            c /= len(verts)
            return c

        obj_centroids: dict[str, Vector] = {}
        for lobj in loose_objects:
            obj_centroids[lobj.name] = _centroid(lobj)

        def _jaccard(a: set[str], b: set[str]) -> float:
            if not a and not b:
                return 1.0
            union = a | b
            if not union:
                return 0.0
            return len(a & b) / len(union)

        # Spatial hash grid: assign cells by centroid position
        cell_size = 2.0
        grid: dict[tuple[int, int, int], list[bpy.types.Object]] = {}
        for lobj in loose_objects:
            c = obj_centroids[lobj.name]
            cell = (int(c.x / cell_size), int(c.y / cell_size), int(c.z / cell_size))
            grid.setdefault(cell, []).append(lobj)

        epsilon = bbox_distance_threshold
        adj: dict[str, set[str]] = {o.name: set() for o in loose_objects}
        checked_pairs: set[tuple[str, str]] = set()

        for (cx, cy, cz), cell_objs in grid.items():
            neighbors: list[bpy.types.Object] = list(cell_objs)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if dx == 0 and dy == 0 and dz == 0:
                            continue
                        nc = grid.get((cx + dx, cy + dy, cz + dz))
                        if nc:
                            neighbors.extend(nc)

            for i in range(len(cell_objs)):
                for j in range(i + 1, len(neighbors)):
                    a, b = cell_objs[i], neighbors[j]
                    key = (a.name, b.name) if a.name < b.name else (b.name, a.name)
                    if key in checked_pairs:
                        continue
                    checked_pairs.add(key)
                    dist = (obj_centroids[a.name] - obj_centroids[b.name]).length
                    if dist > epsilon:
                        continue
                    sim = _jaccard(obj_vg_sets[a.name], obj_vg_sets[b.name])
                    if sim >= vg_similarity_threshold:
                        adj[a.name].add(b.name)
                        adj[b.name].add(a.name)

        # Step 4: Find connected components -> clusters
        unvisited = set(o.name for o in loose_objects)
        merge_groups: list[list[bpy.types.Object]] = []
        name_to_obj = {o.name: o for o in loose_objects}

        while unvisited:
            cluster_names: list[str] = []
            stack = [next(iter(unvisited))]
            while stack:
                name = stack.pop()
                if name not in unvisited:
                    continue
                unvisited.discard(name)
                cluster_names.append(name)
                for neighbor in adj[name]:
                    if neighbor in unvisited:
                        stack.append(neighbor)
            merge_groups.append([name_to_obj[n] for n in cluster_names])

        # Step 5: Merge the objects in each cluster, skipping empty clusters
        original_active = bpy.context.view_layer.objects.active
        original_selected = list(bpy.context.selected_objects)

        kept_objs: list[bpy.types.Object] = []
        for group in merge_groups:
            if len(group) == 0:
                continue
            if len(group) == 1:
                kept_objs.append(group[0])
                continue

            target = group[0]
            others = group[1:]
            bpy.ops.object.select_all(action='DESELECT')
            for o in group:
                o.select_set(True)
            bpy.context.view_layer.objects.active = target
            bpy.ops.object.join()
            target.name = f"{origin_name}_Cluster{len(kept_objs)}"
            kept_objs.append(target)

        # Clean the empty vertex groups of the final objects (this step was deferred earlier for speed)
        for kept_obj in kept_objs:
            used = set()
            for v in kept_obj.data.vertices:
                for g in v.groups:
                    if g.weight > 0:
                        used.add(g.group)
            for vg in reversed(kept_obj.vertex_groups):
                if vg.index not in used:
                    kept_obj.vertex_groups.remove(vg)

        # Step 6: Second merge pass - merge objects with identical vertex group counts and names (ignoring distance)
        vg_sig_groups: dict[tuple, list[bpy.types.Object]] = {}
        for kept_obj in kept_objs:
            sig = tuple(sorted(vg.name for vg in kept_obj.vertex_groups))
            vg_sig_groups.setdefault(sig, []).append(kept_obj)

        final_objs: list[bpy.types.Object] = []
        for sig, sig_objs in vg_sig_groups.items():
            if len(sig_objs) == 1:
                final_objs.append(sig_objs[0])
                continue
            target = sig_objs[0]
            bpy.ops.object.select_all(action='DESELECT')
            for o in sig_objs:
                o.select_set(True)
            bpy.context.view_layer.objects.active = target
            bpy.ops.object.join()
            target.name = f"{origin_name}_MergeVG_{len(final_objs)}"
            final_objs.append(target)

        kept_objs = final_objs

        # Delete isolated objects that did not take part in merging (objects with no adjacency to any other object were kept as-is)
        merged_names = set(o.name for o in kept_objs)
        for o in list(new_collection.objects):
            if o.name not in merged_names:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except Exception:
                    pass

        # Restore the context
        bpy.ops.object.select_all(action='DESELECT')
        for o in original_selected:
            try:
                o.select_set(True)
            except ReferenceError:
                pass
        if original_active:
            try:
                bpy.context.view_layer.objects.active = original_active
            except ReferenceError:
                pass

        return new_collection

    @staticmethod
    def get_vertex_group_weight(vgroup, vertex):
        '''
        Credit to @Comilarex
        https://gamebanana.com/tools/19057
        '''
        for group in vertex.groups:
            if group.group == vgroup.index:
                return group.weight
        return 0.0

    @staticmethod
    def calculate_vertex_influence_area(obj):
        '''
        Credit to @Comilarex
        https://gamebanana.com/tools/19057
        '''
        vertex_area = [0.0] * len(obj.data.vertices)
        
        for face in obj.data.polygons:
            # Assuming the area is evenly distributed among the vertices
            area_per_vertex = face.area / len(face.vertices)
            for vert_idx in face.vertices:
                vertex_area[vert_idx] += area_per_vertex

        return vertex_area

    @classmethod
    def get_weighted_center(cls, obj, vgroup):
        '''
        Credit to @Comilarex
        https://gamebanana.com/tools/19057
        '''
        total_weight_area = 0.0
        weighted_position_sum = Vector((0.0, 0.0, 0.0))

        # Calculate the area influenced by each vertex
        vertex_influence_area = cls.calculate_vertex_influence_area(obj)

        for vertex in obj.data.vertices:
            weight = cls.get_vertex_group_weight(vgroup, vertex)
            influence_area = vertex_influence_area[vertex.index]
            weight_area = weight * influence_area

            if weight_area > 0:
                weighted_position_sum += obj.matrix_world @ vertex.co * weight_area
                total_weight_area += weight_area

        if total_weight_area > 0:
            return weighted_position_sum / total_weight_area
        else:
            return None

    @classmethod
    def match_vertex_groups(cls, base_obj, target_obj):
        '''
        Credit to @Comilarex
        https://gamebanana.com/tools/19057
        '''
        # Rename all vertex groups in base_obj to "unknown"
        for base_group in base_obj.vertex_groups:
            base_group.name = "unknown"

        # Precompute centers for all target vertex groups
        target_centers = {}
        for target_group in target_obj.vertex_groups:
            target_centers[target_group.name] = cls.get_weighted_center(target_obj, target_group)

        # Perform the matching and renaming process
        for base_group in base_obj.vertex_groups:
            base_center = cls.get_weighted_center(base_obj, base_group)
            if base_center is None:
                continue

            best_match = None
            best_distance = float('inf')

            for target_group_name, target_center in target_centers.items():
                if target_center is None:
                    continue

                distance = (base_center - target_center).length
                if distance < best_distance:
                    best_distance = distance
                    best_match = target_group_name

            if best_match:
                base_group.name = best_match


    @staticmethod
    def get_blendweights_blendindices_v1(mesh,normalize_weights:bool = False):
        mesh_loops = mesh.loops
        mesh_loops_length = len(mesh_loops)
        mesh_vertices = mesh.vertices

        loop_vertex_indices = numpy.empty(mesh_loops_length, dtype=int)
        mesh_loops.foreach_get("vertex_index", loop_vertex_indices)

        max_groups = 4

        # Extract and sort the top 4 groups by weight for each vertex.
        sorted_groups = [
            sorted(v.groups, key=lambda x: x.weight, reverse=True)[:max_groups]
            for v in mesh_vertices
        ]

        # Initialize arrays to hold all groups and weights with zeros.
        all_groups = numpy.zeros((len(mesh_vertices), max_groups), dtype=int)
        all_weights = numpy.zeros((len(mesh_vertices), max_groups), dtype=numpy.float32)


        # Fill the pre-allocated arrays with group indices and weights.
        for v_index, groups in enumerate(sorted_groups):
            num_groups = min(len(groups), max_groups)
            all_groups[v_index, :num_groups] = [g.group for g in groups][:num_groups]
            all_weights[v_index, :num_groups] = [g.weight for g in groups][:num_groups]

        # Initialize the blendindices and blendweights with zeros.
        blendindices = numpy.zeros((mesh_loops_length, max_groups), dtype=numpy.uint32)
        blendweights = numpy.zeros((mesh_loops_length, max_groups), dtype=numpy.float32)

        # Map from loop_vertex_indices to precomputed data using advanced indexing.
        valid_mask = (0 <= numpy.array(loop_vertex_indices)) & (numpy.array(loop_vertex_indices) < len(mesh_vertices))
        valid_indices = loop_vertex_indices[valid_mask]

        blendindices[valid_mask] = all_groups[valid_indices]
        blendweights[valid_mask] = all_weights[valid_indices]

        # XXX The weights of the current obj must be normalized, otherwise the model becomes bumpy after subdivision
        
        blendweights = blendweights / numpy.sum(blendweights, axis=1)[:, None]

        blendweights_dict = {}
        blendindices_dict = {}

        blendweights_dict[0] = blendweights
        blendindices_dict[0] = blendindices
        return blendweights_dict, blendindices_dict
    
    @staticmethod
    def get_blendweights_blendindices_v3(mesh, normalize_weights: bool = False):
        print("get_blendweights_blendindices_v3")
        print(normalize_weights)

        mesh_loops = mesh.loops
        mesh_loops_length = len(mesh_loops)
        mesh_vertices = mesh.vertices
        
        # Get the vertex indices of the loop vertices
        loop_vertex_indices = numpy.empty(mesh_loops_length, dtype=int)
        mesh_loops.foreach_get("vertex_index", loop_vertex_indices)
        
        # Compute the max group count per vertex (rounded up to the nearest multiple of 4)
        max_groups_per_vertex = 0
        for v in mesh_vertices:
            group_count = len(v.groups)
            if group_count > max_groups_per_vertex:
                max_groups_per_vertex = group_count
        
        # Align the max group count to a multiple of 4 (each semantic index holds 4 weights)
        max_groups_per_vertex = ((max_groups_per_vertex + 3) // 4) * 4
        num_sets = max_groups_per_vertex // 4  # Number of semantic indices needed

        # print("num_sets: " + str(num_sets))
        
        # If the max group count is less than 4, at least 1 set is needed
        if num_sets == 0 and max_groups_per_vertex > 0:
            num_sets = 1
        
        groups_per_set = 4
        total_groups = num_sets * groups_per_set

        # Extract and sort the vertex groups (take the top total_groups)
        sorted_groups = [
            sorted(v.groups, key=lambda x: x.weight, reverse=True)[:total_groups]
            for v in mesh_vertices
        ]

        # Initialize the storage arrays
        all_groups = numpy.zeros((len(mesh_vertices), total_groups), dtype=int)
        all_weights = numpy.zeros((len(mesh_vertices), total_groups), dtype=numpy.float32)

        # Fill in the weight and index data
        for v_idx, groups in enumerate(sorted_groups):
            count = min(len(groups), total_groups)
            all_groups[v_idx, :count] = [g.group for g in groups][:count]
            all_weights[v_idx, :count] = [g.weight for g in groups][:count]

        # Key step: normalize all the weights as a whole
        if normalize_weights:
            # Compute the total weight sum of each vertex
            weight_sums = numpy.sum(all_weights, axis=1)
            # Avoid division by zero (vertices with a sum of 0 are set to 1, so their weights stay 0)
            weight_sums[weight_sums == 0] = 1
            # Normalize the weights
            all_weights = all_weights / weight_sums[:, numpy.newaxis]


        # Reshape the data to [vertex count, group count, 4]
        all_weights_reshaped = all_weights.reshape(len(mesh_vertices), num_sets, groups_per_set)
        all_groups_reshaped = all_groups.reshape(len(mesh_vertices), num_sets, groups_per_set)

        # Initialize the output dictionaries
        blendweights_dict = {}
        blendindices_dict = {}


        # Create a separate array for each data set
        for set_idx in range(num_sets):
            # Initialize the storage of the current set
            blendweights = numpy.zeros((mesh_loops_length, groups_per_set), dtype=numpy.float32)
            blendindices = numpy.zeros((mesh_loops_length, groups_per_set), dtype=numpy.uint32)
            
            # Create the valid index mask
            valid_mask = (0 <= loop_vertex_indices) & (loop_vertex_indices < len(mesh_vertices))
            valid_indices = loop_vertex_indices[valid_mask]
            
            # Map the data to the loop vertices
            blendweights[valid_mask] = all_weights_reshaped[valid_indices, set_idx, :]
            blendindices[valid_mask] = all_groups_reshaped[valid_indices, set_idx, :]

            
            # 3. Key: re-normalize each row of 4 weights back to 1 (equivalent to the last line of v1)
            if normalize_weights:
                row_sum = numpy.sum(blendweights, axis=1, keepdims=True)
                # Avoid division by 0
                numpy.putmask(row_sum, row_sum == 0, 1.0)
                blendweights = blendweights / row_sum

            
            # Store into the dictionaries (using SemanticIndex as the key)
            blendweights_dict[set_idx] = blendweights
            blendindices_dict[set_idx] = blendindices

        # blendweights = blendweights / numpy.sum(blendweights, axis=1)[:, None]
        # print("blendweights_dict: " + str(blendweights_dict[2][0]))
        # print("blendindices_dict: " + str(blendindices_dict[2][0]))

        return blendweights_dict, blendindices_dict
    



    @staticmethod
    def get_blendweights_blendindices_v4_fast(mesh, normalize_weights: bool = False, blend_size=4):
        '''
        Collects flat triplets (vertex_idx, group_id, weight) once, then uses numpy to
        compute per-vertex top-K (K = aligned_max_groups) and maps to per-loop arrays.
        Returns same shape: (blendweights_dict, blendindices_dict) with SemanticIndex 0.

        Currently only used by Wuthering Waves; not yet tested on other games
        TODO: test whether other games are compatible.
        '''
        import numpy as np

        mesh_loops = mesh.loops
        mesh_verts = mesh.vertices
        n_loops = len(mesh_loops)
        n_verts = len(mesh_verts)

        # get loop->vertex indices (will be used later)
        loop_vertex_indices = np.empty(n_loops, dtype=int)
        mesh_loops.foreach_get("vertex_index", loop_vertex_indices)

        # 1) collect flat lists of (v_idx, group_id, weight)
        v_idx_list = []
        g_id_list = []
        w_list = []
        for v in mesh_verts:
            # v.groups is typically small; we collect all triplets into flat lists
            for g in v.groups:
                if g.weight > 0:
                    v_idx_list.append(v.index)
                    g_id_list.append(g.group)
                    w_list.append(g.weight)

        if len(v_idx_list) == 0:
            # no weights at all: return zeros compatible with old interface
            aligned_max_groups = max(4, blend_size)
            blendweights = np.zeros((n_loops, aligned_max_groups), dtype=np.float32)
            blendindices = np.zeros((n_loops, aligned_max_groups), dtype=np.uint32)
            return {0: blendweights}, {0: blendindices}

        v_idx_arr = np.asarray(v_idx_list, dtype=np.int32)
        g_arr = np.asarray(g_id_list, dtype=np.int32)
        w_arr = np.asarray(w_list, dtype=np.float32)

        # 2) figure out aligned_max_groups (multiple of 4, at least blend_size)
        # real_max_groups = max groups any vertex has
        # we can compute counts via bincount
        counts = np.bincount(v_idx_arr, minlength=n_verts)
        real_max_groups = int(counts.max()) if counts.size > 0 else 0
        aligned_max_groups = 4 * math.ceil(real_max_groups / 4) if real_max_groups else 4
        M = min(aligned_max_groups, blend_size)

        # 3) we want for each vertex the top-M groups sorted by weight
        # Strategy:
        # - stable sort global entries by (vertex_index asc, weight desc)
        # - compute per-vertex offsets and build index positions for top-M
        order = np.lexsort(( -w_arr, v_idx_arr ))  # sorted by vertex asc, weight desc
        v_sorted = v_idx_arr[order]
        g_sorted = g_arr[order]
        w_sorted = w_arr[order]

        # offsets: start index in sorted arrays for each vertex
        # counts already known; offsets = cumsum(counts) shifted
        offsets = np.zeros(n_verts, dtype=np.int64)
        if n_verts > 0:
            offsets[1:] = np.cumsum(counts)[:-1]

        # build positions matrix: shape (n_verts, M)
        # pos = offsets[:,None] + np.arange(M)
        arange_M = np.arange(M, dtype=np.int64)
        pos = offsets[:, None] + arange_M[None, :]   # may point beyond end
        # mask valid positions
        valid_mask = pos < (offsets[:, None] + counts[:, None])

        # clip positions to last index to avoid OOB (we'll zero invalid later)
        pos_clipped = np.minimum(pos, order.size - 1)
        # pick group ids and weights for these positions
        picked_g = g_sorted[pos_clipped]    # shape (n_verts, M)
        picked_w = w_sorted[pos_clipped]    # shape (n_verts, M)

        # zero out invalid slots
        picked_g[~valid_mask] = 0
        picked_w[~valid_mask] = 0.0

        # 4) optionally ensure per-vertex normalization (per original code behavior)
        if normalize_weights:
            # sum across M and avoid divide by zero
            sums = picked_w.sum(axis=1, keepdims=True)
            sums[sums == 0] = 1.0
            picked_w = picked_w / sums

        # 5) map per-vertex data to per-loop arrays using loop_vertex_indices
        # valid_mask_loop: guard against malformed loops
        valid_loop_mask = (0 <= loop_vertex_indices) & (loop_vertex_indices < n_verts)
        blendindices = np.zeros((n_loops, M), dtype=np.uint32)
        blendweights = np.zeros((n_loops, M), dtype=np.float32)
        if np.any(valid_loop_mask):
            valid_vidx = loop_vertex_indices[valid_loop_mask]
            blendindices[valid_loop_mask] = picked_g[valid_vidx]
            blendweights[valid_loop_mask] = picked_w[valid_vidx]

        # return in old interface: semantic index 0 only (v4 implementation style)
        return {0: blendweights}, {0: blendindices}

    @staticmethod
    def get_blendweights_blendindices_v4(mesh, normalize_weights: bool = False,blend_size = 4):
        """
        Note: do not delete this yet, keep it as a fallback in case the new one breaks. The new fast version is several times faster than this one, so this one is deprecated.
        """
        # -------------------- Basic data --------------------
        mesh_loops = mesh.loops
        mesh_verts = mesh.vertices
        n_loops = len(mesh_loops)

        # Fetch the vertex index corresponding to each loop in advance
        loop_vertex_indices = numpy.empty(n_loops, dtype=int)
        mesh_loops.foreach_get("vertex_index", loop_vertex_indices)

        # -------------------- 1. Collect all non-zero-weight groups of each vertex --------------------
        # Use Python lists to store them first because the group count varies per vertex
        vert_groups_weights = []   # [[(group_id, weight), ...], ...] length = number of vertices
        for v in mesh_verts:
            # Keep only groups with weight > 0 to avoid empty data
            gw = [(g.group, g.weight) for g in v.groups if g.weight > 0]
            # Sort by weight in descending order so the top N can be taken directly later
            gw.sort(key=lambda x: x[1], reverse=True)
            vert_groups_weights.append(gw)

        # -------------------- 2. Compute the "real max group count" and pad it up to a multiple of 4 --------------------
        # First find the real max group count across all vertices
        real_max_groups = max(len(gw) for gw in vert_groups_weights) if vert_groups_weights else 0
        # Pad it up to a multiple of 4
        aligned_max_groups = 4 * math.ceil(real_max_groups / 4) if real_max_groups else 4

        if aligned_max_groups < blend_size:
            aligned_max_groups = blend_size

        # -------------------- 3. Allocate the aligned ndarray in one go --------------------
        # Store all vertices together so advanced indexing can map them to loops at once
        all_groups = numpy.zeros((len(mesh_verts), aligned_max_groups), dtype=int)
        all_weights = numpy.zeros((len(mesh_verts), aligned_max_groups), dtype=numpy.float32)

        # -------------------- 4. Fill the data & optional normalization --------------------
        for v_idx, gw in enumerate(vert_groups_weights):
            # Write the real data in
            for col, (g_id, w) in enumerate(gw):
                all_groups[v_idx, col] = g_id
                all_weights[v_idx, col] = w

            # If normalize_weights=True, normalize this vertex's weights (slots kept as 0 stay 0)
            weight_sum = all_weights[v_idx].sum()
            if weight_sum > 0:
                all_weights[v_idx] /= weight_sum

        # -------------------- 5. Map the "per-vertex" data to "per-loop" --------------------
        # Check index validity first to prevent out-of-bounds access
        valid_mask = (0 <= loop_vertex_indices) & (loop_vertex_indices < len(mesh_verts))
        valid_vidx = loop_vertex_indices[valid_mask]

        blendindices = numpy.zeros((n_loops, aligned_max_groups), dtype=numpy.uint32)
        blendweights = numpy.zeros((n_loops, aligned_max_groups), dtype=numpy.float32)

        # Copy everything at once with advanced indexing
        blendindices[valid_mask] = all_groups[valid_vidx]
        blendweights[valid_mask] = all_weights[valid_vidx]

        # -------------------- 6. Return the dicts compatible with the old interface --------------------
        return {0: blendweights}, {0: blendindices}

    @staticmethod
    def split_merged_object_by_submesh_vg_ranges(
        obj: bpy.types.Object,
        submesh_vg_map: dict[str, set[int]],
        submesh_reverse_vg_map: dict[str, dict[int, int]],
        submesh_unique_vg_map: dict[str, set[int]] | None = None,
    ) -> list[tuple[str, bpy.types.Object]]:
        """
        UniComponent core split: copy + extract.

        submesh_unique_vg_map: the unique VGs of each Submesh.
            Used to determine vertex ownership precisely: a vertex belongs to the Submesh with the highest weight on its "unique VGs".
            Shared VGs (e.g. pelvis) do not count toward ownership determination.
        """
        if obj.type != 'MESH' or len(obj.data.vertices) == 0:
            return []

        import bmesh
        import time
        print(f"\n[UniComponent] Splitting: '{obj.name}' ({len(obj.data.vertices)} verts, {len(obj.vertex_groups)} VG)")

        # --- Precompute each vertex's "primary Submesh" (based on the highest weight among unique VGs) ---
        vert_primary_sm: list[str | None] = [None] * len(obj.data.vertices)
        has_unique = submesh_unique_vg_map is not None

        if has_unique:
            # Build: unique VG index -> the Submesh it belongs to
            unique_vg_sm: dict[int, str] = {}
            for sm_name, uvgs in submesh_unique_vg_map.items():
                for vg in obj.vertex_groups:
                    try:
                        if int(vg.name) in uvgs:
                            unique_vg_sm[vg.index] = sm_name
                    except ValueError:
                        pass

            for v in obj.data.vertices:
                if not v.groups:
                    continue
                best_sm = None
                best_w = 0.0
                for g in v.groups:
                    if g.weight > best_w and g.group in unique_vg_sm:
                        best_sm = unique_vg_sm[g.group]
                        best_w = g.weight
                vert_primary_sm[v.index] = best_sm

            # For vertices without unique VGs (bound only to shared VGs), try any VG as a fallback
            for v in obj.data.vertices:
                if vert_primary_sm[v.index] is not None or not v.groups:
                    continue
                # Find the VG with the highest weight, check which Submeshes it belongs to, and take the first one
                best_g = max(v.groups, key=lambda g: g.weight)
                for sm_name, vg_set in submesh_vg_map.items():
                    if best_g.group in {vg.index for vg in obj.vertex_groups if int(vg.name) in vg_set}:
                        if best_g.group in unique_vg_sm:
                            vert_primary_sm[v.index] = unique_vg_sm[best_g.group]
                        else:
                            # Shared VG fallback: take the first Submesh the VG belongs to
                            vert_primary_sm[v.index] = sm_name
                        break

        # --- Create a split object for each Submesh ---
        results: list[tuple[str, bpy.types.Object]] = []
        src_colls = list(obj.users_collection)
        target_coll = src_colls[0] if src_colls else bpy.context.scene.collection

        for sm_name, vg_set in sorted(submesh_vg_map.items()):
            sm_vg_indices: set[int] = set()
            for vg in obj.vertex_groups:
                try:
                    if int(vg.name) in vg_set:
                        sm_vg_indices.add(vg.index)
                except ValueError:
                    pass
            if not sm_vg_indices:
                continue

            # 1. Copy the object
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = f"Uni_{int(time.time() * 1000) % 100000}_{sm_name.replace('.', '_')}"
            target_coll.objects.link(new_obj)

            # 2. Delete vertices that do not belong to this Submesh with BMesh
            bm = bmesh.new()
            bm.from_mesh(new_obj.data)
            bm.verts.ensure_lookup_table()

            deform = bm.verts.layers.deform.active
            to_delete = []
            if deform is not None:
                for bv in bm.verts:
                    if has_unique:
                        if vert_primary_sm[bv.index] != sm_name:
                            to_delete.append(bv)
                    else:
                        weights = bv[deform]
                        has_match = any(vg_idx in sm_vg_indices and w > 0.0
                                        for vg_idx, w in weights.items())
                        if not has_match:
                            to_delete.append(bv)

            if len(to_delete) == len(bm.verts):
                bm.free()
                bpy.data.objects.remove(new_obj, do_unlink=True)
                continue

            if to_delete:
                bmesh.ops.delete(bm, geom=to_delete, context='VERTS')

            bm.to_mesh(new_obj.data)
            bm.free()
            new_obj.data.update()

            # 3. Clean up and rename the VGs
            reverse_map = submesh_reverse_vg_map.get(sm_name, {})
            vg_to_remove = []
            for vg in new_obj.vertex_groups:
                try:
                    vid = int(vg.name)
                except ValueError:
                    vg_to_remove.append(vg)
                    continue
                if vid in reverse_map:
                    vg.name = str(reverse_map[vid])
                elif vid not in vg_set:
                    vg_to_remove.append(vg)
            for vg in vg_to_remove:
                new_obj.vertex_groups.remove(vg)
            # VertexGroupUtils.remove_unused_vertex_groups(new_obj)

            bpy.ops.object.select_all(action='DESELECT')
            new_obj.select_set(True)
            bpy.context.view_layer.objects.active = new_obj
            bpy.ops.object.vertex_group_sort()
            VertexGroupUtils.merge_vertex_groups_with_same_number_v2()
            VertexGroupUtils.fill_vertex_group_gaps()

            # Strip the zero padding and restore plain numeric names
            for vg in new_obj.vertex_groups:
                try:
                    vg.name = str(int(vg.name))
                except ValueError:
                    pass
            bpy.ops.object.vertex_group_sort()
            bpy.ops.object.select_all(action='DESELECT')

            remaining_verts = len(new_obj.data.vertices)
            remaining_vgs = len(new_obj.vertex_groups)
            vg_names = [vg.name for vg in new_obj.vertex_groups]
            print(f"[UniComponent]   → '{sm_name}': {remaining_verts} verts, {remaining_vgs} VG {vg_names[:5]}{'...' if remaining_vgs > 5 else ''}")

            if remaining_verts > 0:
                results.append((sm_name, new_obj))
            else:
                bpy.data.objects.remove(new_obj, do_unlink=True)

        print(f"[UniComponent] Done: {len(results)} parts {[s for s, _ in results]}")
        return results