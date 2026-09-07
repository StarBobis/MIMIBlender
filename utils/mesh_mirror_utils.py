# Utilities for cleanly mirroring mesh objects.
#
# A negative object scale (for example scale.x = -1) only *looks* like a
# mirror. In fact it flips the face winding, so normals point inward, the
# shading breaks, and modifiers / exporters behave badly afterwards.
#
# These helpers instead bake the mirror into the real mesh data:
#   - the vertex coordinates are flipped for real,
#   - face winding is reversed when needed so normals stay correct,
#   - shape keys follow the mirror,
#   - L/R vertex group names can be swapped for symmetric rigs,
#   - the object scale ends up clean at (1, 1, 1) again.
#
# The result is a "perfect mirror": editing, modifiers and exports all work
# exactly like they do on a normally modeled mesh, with no hidden negative
# scale left behind.
import bpy
import bmesh


class MeshMirrorUtils:
    """Mirror helpers for mesh objects, shared by the add-on operator."""

    # Suffix pairs that mark the left / right side of a symmetric rig.
    # They are recognized at the END of vertex group names, for example
    # "arm.L" / "arm.R" or "arm_L" / "arm_R".
    SIDE_TOKEN_PAIRS = (
        ("_L", "_R"),
        (".L", ".R"),
        ("_left", "_right"),
        (".left", ".right"),
        ("_l", "_r"),
        (".l", ".r"),
    )

    @staticmethod
    def _find_side_pair(name):
        """Return (base_name, other_side_suffix) when the name ends with a
        side token, otherwise return None.

        Example: "hand.L" -> ("hand", ".R"), which means after a mirror the
        group can be renamed to "hand.R". Both sides of every pair are
        checked, so "hand.R" returns ("hand", ".L") instead.
        """
        for left_suffix, right_suffix in MeshMirrorUtils.SIDE_TOKEN_PAIRS:
            if name.endswith(left_suffix):
                # Cut the left suffix away and return the right one.
                return (name[: -len(left_suffix)], right_suffix)
            if name.endswith(right_suffix):
                # Cut the right suffix away and return the left one.
                return (name[: -len(right_suffix)], left_suffix)
        return None

    @staticmethod
    def _swap_side_vertex_groups(obj):
        """Rename the L/R vertex groups of one object after a mirror.

        Mirroring moves every weighted vertex to the other side of the
        model, so every left group must become the matching right group and
        the other way round (for example "arm.L" -> "arm.R"). The weights
        themselves stay on their vertices, only the names change. This is
        exactly what a symmetric rig needs; when the mesh has no L/R group
        names nothing happens at all.
        """
        groups = obj.vertex_groups
        if len(groups) == 0:
            return

        # First collect every (group, final_name) pair. Names must be read
        # before anything is renamed, because renaming changes the source.
        rename_items = []
        for group in groups:
            pair = MeshMirrorUtils._find_side_pair(group.name)
            if pair is not None:
                base_name, other_suffix = pair
                rename_items.append((group, base_name + other_suffix))
        if len(rename_items) == 0:
            return

        # Pass 1: free the final names by moving every group to a temporary
        # name. Blender auto-uniquifies duplicates, which is harmless here.
        for group, final_name in rename_items:
            group.name = "__MIMI_MIRROR_SWAP_TMP__"

        # Pass 2: assign the final names. No name can collide any more,
        # because every renamed group currently holds a temporary name.
        for group, final_name in rename_items:
            group.name = final_name

    @staticmethod
    def _mirror_shape_keys(mesh, factor_x, factor_y, factor_z):
        """Mirror relative shape keys after the base mesh was mirrored.

        Blender keeps the first key block (the "Basis") in sync with the
        base mesh geometry: when the base mesh is edited, the basis follows
        automatically, so after the base mirror the basis is already right.

        Every other block stores its offset from the basis, and a mirror
        must flip those offsets too. Writing each point as
        "basis + mirrored offset" instead of a plain "factor * point" is
        safe on every Blender version, because the offset is anchored to
        the (already mirrored) basis.
        """
        shape_keys = mesh.shape_keys
        if shape_keys is None:
            return
        key_blocks = shape_keys.key_blocks
        if len(key_blocks) <= 1:
            return

        if not shape_keys.use_relative:
            # Absolute shape keys do not reference a base anchor. Mirror
            # every block (including the first one) as plain coordinates.
            for key_block in key_blocks:
                for point in key_block.data:
                    point.co.x *= factor_x
                    point.co.y *= factor_y
                    point.co.z *= factor_z
            return

        # Relative shape keys: mirror the offset of every later block from
        # the basis block, keeping the mirrored basis as the new anchor.
        basis_data = key_blocks[0].data
        for key_block in key_blocks[1:]:
            point_data = key_block.data
            count = min(len(point_data), len(basis_data))
            for index in range(count):
                base = basis_data[index].co
                point = point_data[index].co
                point.x = base.x + factor_x * (point.x - base.x)
                point.y = base.y + factor_y * (point.y - base.y)
                point.z = base.z + factor_z * (point.z - base.z)

    @staticmethod
    def _mirror_uv(mesh, flip_u):
        """Mirror every UV map of a mesh around the middle of the UV tile.

        flip_u = True  mirrors the U axis (u becomes 1 - u).
        flip_u = False mirrors the V axis (v becomes 1 - v).

        Leave this off for the usual "mirror image" look. Turn it on when
        the mirrored copy should keep the texture reading direction of the
        original object (for example when both sides share one texture and
        the decal must stay readable).
        """
        for uv_layer in mesh.uv_layers:
            for loop_data in uv_layer.data:
                uv = loop_data.uv
                if flip_u:
                    uv.x = 1.0 - uv.x
                else:
                    uv.y = 1.0 - uv.y

    @staticmethod
    def _find_unique_name(names, base_name):
        """Return base_name when free, otherwise base_name.001, .002, ..."""
        candidate = base_name
        counter = 1
        while candidate in names:
            counter += 1
            candidate = f"{base_name}.{counter:03d}"
        return candidate

    @staticmethod
    def mirror_mesh_object(obj, mode="COPY", axis="X", recalc_normals=True,
                           mirror_uv="NONE", swap_side_groups=True,
                           copy_suffix="_mirror"):
        """Mirror one mesh object and return the object that holds the
        mirrored mesh.

        mode:
            "COPY" - keep obj untouched and return a clean mirrored copy.
            "FLIP" - mirror obj in place; every call swaps the side again.
            "BAKE" - fix obj without changing its look: an already applied
                     negative scale (made earlier, for example scale.x = -1)
                     is baked into the real mesh data, normals are repaired
                     and the scale becomes (1, 1, 1).

        axis:            "X", "Y" or "Z". The mirror plane is the axis
                         plane through the object origin, the same plane a
                         negative scale on that axis would use.
        recalc_normals:  Also run Blender's "recalculate outside" to repair
                         any normals that were already wrong before.
        mirror_uv:       "NONE", "U" or "V", see _mirror_uv().
        swap_side_groups: Rename L/R vertex groups for symmetric rigs.
        copy_suffix:     Name suffix used by the "COPY" mode.
        """
        if obj.type != "MESH":
            raise ValueError(f"Object '{obj.name}' is not a mesh.")
        mode = str(mode).upper()
        axis = str(axis).upper()
        if mode not in ("COPY", "FLIP", "BAKE"):
            raise ValueError(f"Unknown mirror mode '{mode}'.")
        if axis not in "XYZ":
            raise ValueError(f"Unknown mirror axis '{axis}'.")
        axis_index = "XYZ".index(axis)

        # ------------------------------------------------------------------
        # Step 1: decide which object gets the mirrored mesh.
        # ------------------------------------------------------------------
        if mode == "COPY":
            # Build the copy on a fresh mesh data block. This is important:
            # an object copy alone still shares vertex groups with the
            # original, but swapping the mesh data makes them independent.
            mirrored_obj = obj.copy()
            mirrored_obj.data = obj.data.copy()

            # Give the copy a unique name (and its mesh the same name).
            # Object names and mesh names live in separate namespaces, so
            # both must be checked to keep the pair synchronized.
            new_name = MeshMirrorUtils._find_unique_name(
                bpy.data.objects, obj.name + copy_suffix)
            while new_name in bpy.data.meshes:
                new_name = MeshMirrorUtils._find_unique_name(
                    bpy.data.meshes, new_name)
            mirrored_obj.name = new_name
            mirrored_obj.data.name = new_name

            # Link the copy into the same collections as the original.
            collections = list(obj.users_collection)
            if len(collections) == 0:
                # The original is not linked anywhere yet; fall back to the
                # scene collection so the copy stays reachable.
                scene = bpy.context.scene
                if scene is not None:
                    collections = [scene.collection]
            for collection in collections:
                collection.objects.link(mirrored_obj)
        else:
            # In-place modes work on the object itself. When its mesh data
            # is shared with other objects, give it a private copy first so
            # the other users of the data are not modified.
            mirrored_obj = obj
            if obj.data.users > 1:
                mirrored_obj.data = obj.data.copy()

        mesh = mirrored_obj.data

        # ------------------------------------------------------------------
        # Step 2: compute the baking factors for the mesh coordinates.
        # ------------------------------------------------------------------
        # The current scale is baked into the mesh, so the object scale can
        # go back to (1, 1, 1) with the look unchanged. "BAKE" keeps every
        # sign, while "COPY" / "FLIP" also flips the mirror axis sign so the
        # result is mirrored relative to the current look.
        scale = mirrored_obj.scale
        factor_x = scale.x
        factor_y = scale.y
        factor_z = scale.z
        if mode != "BAKE":
            if axis_index == 0:
                factor_x = -factor_x
            elif axis_index == 1:
                factor_y = -factor_y
            else:
                factor_z = -factor_z

        # Mirroring by an odd number of axes flips the handedness of the
        # mesh, which turns every face winding around. Those faces need to
        # be reversed so their normals still point the right way.
        negative_count = 0
        for factor in (factor_x, factor_y, factor_z):
            if factor < 0:
                negative_count += 1
        flip_winding = (negative_count % 2) == 1

        # ------------------------------------------------------------------
        # Step 3: mirror the base mesh geometry with BMesh.
        # ------------------------------------------------------------------
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        for vertex in bm.verts:
            vertex.co.x *= factor_x
            vertex.co.y *= factor_y
            vertex.co.z *= factor_z

        if flip_winding:
            # Reverse the winding order of every face (all of them together,
            # so closed meshes stay consistently oriented).
            faces = list(bm.faces)
            if len(faces) > 0:
                bmesh.ops.reverse_faces(bm, faces=faces)

        if recalc_normals:
            # Repair faces that were already inside-out before the mirror.
            # This matches Blender's "Mesh > Normals > Recalculate Outside".
            faces = list(bm.faces)
            if len(faces) > 0:
                bmesh.ops.recalc_face_normals(bm, faces=faces)

        bm.normal_update()
        bm.to_mesh(mesh)
        bm.free()

        # ------------------------------------------------------------------
        # Step 4: mirror shape keys, UV maps and vertex group names.
        # ------------------------------------------------------------------
        MeshMirrorUtils._mirror_shape_keys(
            mesh, factor_x, factor_y, factor_z)
        if mirror_uv in ("U", "V"):
            MeshMirrorUtils._mirror_uv(mesh, flip_u=(mirror_uv == "U"))
        if swap_side_groups:
            MeshMirrorUtils._swap_side_vertex_groups(mirrored_obj)

        # ------------------------------------------------------------------
        # Step 5: clean up the mesh and the object transform.
        # ------------------------------------------------------------------
        mesh.validate()
        mesh.update()
        mirrored_obj.scale = (1.0, 1.0, 1.0)
        return mirrored_obj
