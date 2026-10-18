"""Apply a reversed-mod skeleton sidecar (skeleton.json).

SSMT5/MMT writes a sidecar next to every reverse output that carries the chosen
character's bones plus the numeric-vertex-group -> bone-name map. This helper
builds the armature from those rest matrices and binds the imported meshes.

Two naming modes exist because the two namespaces have different owners:

* BONE_TO_GROUP (default): keep the numeric vertex groups (they are the game's
  bone palette indices used by the mod's Blend buffer, so the model stays
  exportable) and rename the armature bones to the same numbers.
* GROUP_TO_BONE: keep readable bone names and rename the vertex groups instead.
"""

import json
import math
import os
import re

import bpy
from mathutils import Matrix, Vector


NAMING_BONE_TO_GROUP = "BONE_TO_GROUP"
NAMING_GROUP_TO_BONE = "GROUP_TO_BONE"
MIRROR_MARKER = "MIMI:MirrorWorkflowApplied"

# Bone cleanup modes offered by the Mod Reverse panel. A bone counts as invalid
# when no imported mesh stores a non-zero weight in a vertex group of the same
# name: reverse outputs carry the whole character skeleton, while one mod
# usually deforms only a small part of it.
BONE_CLEANUP_NONE = "NONE"
BONE_CLEANUP_DELETE = "DELETE"
BONE_CLEANUP_HIDE = "HIDE"


class SkeletonHelper:
    @staticmethod
    def candidate_sidecar_paths():
        """Likely sidecar locations written by the desktop app."""
        paths = []
        try:
            from ..common.global_config import GlobalConfig

            for folder in (
                GlobalConfig.path_workspace_folder(),
                GlobalConfig.path_reverse_output_folder(),
            ):
                if folder:
                    paths.append(os.path.join(folder, "skeleton.json"))
        except Exception as error:  # noqa: BLE001 - optional helpers must not break the operator
            print("Skeleton sidecar candidates unavailable:", error)
        return paths

    @staticmethod
    def find_sidecar():
        for path in SkeletonHelper.candidate_sidecar_paths():
            if os.path.isfile(path):
                return path
        return ""

    @staticmethod
    def load_sidecar(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def sidecar_naming_mode(path):
        """Naming mode requested by the desktop app, if the sidecar declares one."""
        try:
            sidecar = SkeletonHelper.load_sidecar(path)
        except Exception:  # noqa: BLE001 - a broken sidecar falls back to the operator default
            return ""
        mode = str(sidecar.get("NamingMode", "") or "")
        if mode == "groupToBone":
            return NAMING_GROUP_TO_BONE
        if mode == "boneToGroup":
            return NAMING_BONE_TO_GROUP
        return ""

    @staticmethod
    def pick_drawib(sidecar, object_names, draw_ib_name=""):
        entries = sidecar.get("DrawIBs") or []
        if not entries:
            return None

        def first_segment(value):
            # Extraction sidecars key entries by nested folders
            # (drawib-indexcount-firstindex/TYPE_...), while imported objects are
            # named after the top DrawIB folder only.
            text = str(value or "").replace("\\", "/").strip("/")
            return text.split("/")[0].strip().lower() if text else ""

        wanted = str(draw_ib_name or "").strip().lower()
        if wanted:
            for entry in entries:
                if str(entry.get("DrawIB", "")).strip().lower() == wanted:
                    return entry
            for entry in entries:
                if first_segment(entry.get("DrawIB")) == wanted:
                    return entry
            for entry in entries:
                folder = os.path.basename(str(entry.get("Folder", ""))).strip().lower()
                if folder and folder == wanted:
                    return entry
        for entry in entries:
            draw_ib = str(entry.get("DrawIB", ""))
            short = first_segment(draw_ib)
            if draw_ib and any(draw_ib.lower() in name.lower() for name in object_names):
                return entry
            if short and any(short in name.lower() for name in object_names):
                return entry
        if len(entries) == 1:
            return entries[0]
        for entry in entries:
            folder = os.path.basename(str(entry.get("Folder", "")))
            if folder and any(folder.lower() in name.lower() for name in object_names):
                return entry
        return entries[0]

    @staticmethod
    def character_by_id(sidecar, character_id):
        characters = sidecar.get("Characters") or []
        for character in characters:
            if character.get("Id") == character_id:
                return character
        return characters[0] if characters else None

    @staticmethod
    def _unique_name(name, used):
        base = (name or "Bone")[:60]
        candidate = base
        index = 1
        while candidate.lower() in used:
            suffix = "_" + str(index)
            candidate = base[: 60 - len(suffix)] + suffix
            index += 1
        used.add(candidate.lower())
        return candidate

    @staticmethod
    def _rest_heads(bones):
        heads = []
        for bone in bones:
            rest = bone.get("Rest") or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
            heads.append(Vector((rest[3], rest[7], rest[11])))
        return heads

    @staticmethod
    def _bone_lengths(bones):
        """Display length per bone.

        An explicit ``Length`` (newer sidecars) wins; otherwise the distance to
        the first child's head is used, leaves inherit a fraction of their
        parent. Without this every bone kept Blender's default length and the
        skeleton showed up as a trail of dots inside the mesh.
        """
        heads = SkeletonHelper._rest_heads(bones)
        lengths = [0.0] * len(bones)
        for index, bone in enumerate(bones):
            explicit = float(bone.get("Length", 0) or 0)
            if explicit > 1e-5:
                lengths[index] = explicit
                continue
            children = [
                child_index
                for child_index, child in enumerate(bones)
                if int(child.get("Parent", -1)) == index and child_index != index
            ]
            if children:
                lengths[index] = min((heads[child] - heads[index]).length for child in children)
        for index, bone in enumerate(bones):
            if lengths[index] > 1e-5:
                continue
            parent = int(bone.get("Parent", -1))
            if 0 <= parent < len(bones) and lengths[parent] > 1e-5:
                lengths[index] = lengths[parent] * 0.6
            else:
                lengths[index] = 0.05
        return [max(0.01, min(1.0, value)) for value in lengths]

    @staticmethod
    def _mirrored_matrix(matrix):
        """Reflect a bone transform across X (`S M S` with `S = diag(-1,1,1,1)`)."""
        reflection = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
        return reflection @ matrix @ reflection

    @staticmethod
    def _space_matrix(scale, rotation_z):
        """Transform the game importer baked into the mesh (WWMI: 0.01, 180 deg)."""
        if abs(scale - 1.0) < 1e-9 and abs(rotation_z) < 1e-9:
            return None
        matrix = Matrix.Rotation(math.radians(rotation_z), 4, "Z") @ Matrix.Scale(scale, 4)
        return matrix

    @staticmethod
    def build_armature(character, naming_mode, mirror_x=False, space_scale=1.0, space_rotation_z=0.0):
        bones = character.get("Bones") or []
        if not bones:
            return None, [], []

        armature = bpy.data.armatures.new(str(character.get("Id", "Skeleton")) + "_Armature")
        armature_obj = bpy.data.objects.new(armature.name, armature)
        collection = bpy.context.collection or bpy.context.scene.collection
        collection.objects.link(armature_obj)

        view_layer = bpy.context.view_layer
        previous_active = view_layer.objects.active
        view_layer.objects.active = armature_obj
        armature_obj.select_set(True)

        lengths = SkeletonHelper._bone_lengths(bones)
        space_matrix = SkeletonHelper._space_matrix(space_scale, space_rotation_z)
        used_names = set()
        created = []
        originals = []
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = []
        for index, bone in enumerate(bones):
            original_name = bone.get("Name", "")
            edit_bone = armature.edit_bones.new(SkeletonHelper._unique_name(original_name, used_names))
            rest = bone.get("Rest") or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
            matrix = Matrix([rest[0:4], rest[4:8], rest[8:12], rest[12:16]])
            if mirror_x:
                matrix = SkeletonHelper._mirrored_matrix(matrix)
            if space_matrix is not None:
                matrix = space_matrix @ matrix
            edit_bone.matrix = matrix
            # The matrix setter also rewrites the tail from the current length,
            # so the display length must be applied after it.
            edit_bone.length = lengths[index] * (space_scale if space_matrix is not None else 1.0)
            edit_bones.append(edit_bone)
            created.append(edit_bone.name)
            originals.append(original_name)

        for index, bone in enumerate(bones):
            parent = int(bone.get("Parent", -1))
            if 0 <= parent < len(edit_bones) and parent != index:
                edit_bones[index].parent = edit_bones[parent]
                edit_bones[index].use_connect = False

        bpy.ops.object.mode_set(mode="OBJECT")
        armature_obj.show_in_front = True
        armature.display_type = 'OCTAHEDRAL'

        if previous_active is not None:
            view_layer.objects.active = previous_active
        return armature_obj, created, originals

    @staticmethod
    def _bone_map(character):
        return {int(index): str(name) for index, name in (character.get("BoneMap") or {}).items()}

    @classmethod
    def rename_bones_to_groups(cls, character, armature_obj, original_names, final_names):
        """BONE_TO_GROUP: bones take the game palette numbers stored in the groups.

        The sidecar ``BoneMap`` is game index -> source bone name, and armature
        order is unrelated to the game palette order, so the rename must go
        through the name map. Renaming bone N to the string "N" (armature order)
        produces a skeleton that looks right but deforms nothing.
        """
        name_to_index = {name: index for index, name in cls._bone_map(character).items()}
        by_original = {}
        for original, final in zip(original_names, final_names):
            by_original.setdefault(original, final)
        renamed = 0
        for original, game_index in name_to_index.items():
            final = by_original.get(original)
            if not final:
                continue
            bone = armature_obj.data.bones.get(final)
            if bone is not None:
                bone.name = str(game_index)
                renamed += 1
        return renamed

    @staticmethod
    def rename_groups_with_map(objects, mapping, by_original=None):
        """Rename numeric vertex groups through an explicit index -> bone map."""
        by_original = by_original or {}
        renamed = 0
        for obj in objects:
            for group in obj.vertex_groups:
                if not group.name.isdigit():
                    continue
                original = mapping.get(str(int(group.name)))
                if original is None:
                    continue
                target = by_original.get(original, original)
                if target:
                    group.name = target
                    renamed += 1
        return renamed

    @staticmethod
    def pick_component(components, object_name):
        """Pick the component entry for an imported mesh (`...-Component 3`)."""
        match = re.search(r"component[\s_-]*(\d+)", str(object_name or ""), re.IGNORECASE)
        if match:
            index = int(match.group(1))
            for entry in components:
                if int(entry.get("ComponentIndex", -1)) == index:
                    return entry
        return None

    @classmethod
    def rename_groups_to_bones(cls, character, objects, original_names, final_names):
        """GROUP_TO_BONE: groups take the source bone names of the character."""
        bone_map = cls._bone_map(character)
        by_original = {}
        for original, final in zip(original_names, final_names):
            by_original.setdefault(original, final)
        mapping = {str(index): name for index, name in bone_map.items()}
        return cls.rename_groups_with_map(objects, mapping, by_original)

    @staticmethod
    def bind(objects, armature_obj):
        bound = 0
        for obj in objects:
            modifier = None
            for candidate in obj.modifiers:
                if candidate.type == "ARMATURE":
                    modifier = candidate
                    break
            if modifier is None:
                modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
            modifier.object = armature_obj
            if obj.parent != armature_obj:
                world = obj.matrix_world.copy()
                obj.parent = armature_obj
                obj.matrix_parent_inverse = armature_obj.matrix_world.inverted()
                obj.matrix_world = world
            bound += 1
        return bound

    @staticmethod
    def collect_weighted_group_names(objects):
        """Return every vertex group name that at least one vertex actually uses.

        A vertex group alone does not prove a bone is bound: the importer creates
        groups for every numeric slot up to the highest used one, so the palette
        gaps contain empty groups. Only a stored weight above zero binds a
        vertex, therefore only those group names may keep a bone alive.
        """
        weighted_names = set()
        for obj in objects:
            if obj is None or getattr(obj, "type", "") != "MESH":
                continue
            mesh = getattr(obj, "data", None)
            if mesh is None or len(obj.vertex_groups) == 0:
                continue

            # Group indices are stable inside one object; resolve the names only
            # once, then collect the indices that receive a real weight.
            group_names = {group.index: group.name for group in obj.vertex_groups}
            used_group_indices = set()
            for vertex in mesh.vertices:
                for assignment in vertex.groups:
                    # Zero weights are padding slots written by the importer.
                    # Counting them would keep bones that deform nothing.
                    if assignment.weight > 0.0:
                        used_group_indices.add(assignment.group)

            for group_index in used_group_indices:
                group_name = group_names.get(group_index)
                if group_name:
                    weighted_names.add(group_name)
        return weighted_names

    @classmethod
    def cleanup_bones(cls, armature_obj, mesh_objects, cleanup_mode):
        """Delete or hide bones that no bound mesh actually deforms.

        Returns ``(removed_count, hidden_count)`` so the caller can add the
        result to its report. The mesh_objects list must contain every mesh
        bound to this armature, because a bone may be used by only one part.
        """
        mode = str(cleanup_mode or BONE_CLEANUP_NONE).upper()
        if mode not in (BONE_CLEANUP_DELETE, BONE_CLEANUP_HIDE):
            return 0, 0
        if armature_obj is None or getattr(armature_obj, "type", "") != "ARMATURE":
            return 0, 0

        bone_names = {bone.name for bone in armature_obj.data.bones}
        if not bone_names:
            return 0, 0

        weighted_names = cls.collect_weighted_group_names(mesh_objects)
        if not weighted_names:
            # No mesh carries any weight at all. Deleting every bone would
            # destroy a skeleton the user may still need, so leave it intact;
            # hiding everything would be equally surprising.
            print("Bone cleanup skipped: no weighted vertex group was found")
            return 0, 0

        invalid_names = bone_names - weighted_names
        if not invalid_names:
            return 0, 0
        if mode == BONE_CLEANUP_HIDE:
            return 0, cls._hide_invalid_bones(armature_obj, invalid_names)
        return cls._delete_invalid_bones(armature_obj, invalid_names), 0

    @staticmethod
    def _hide_invalid_bones(armature_obj, invalid_names):
        """Hide invalid bones in Edit and Pose Mode without changing anything else."""
        hidden_count = 0
        for bone in armature_obj.data.bones:
            if bone.name not in invalid_names:
                continue
            # Bone.hide controls Edit Mode, while PoseBone.hide controls Pose
            # Mode; set both so the unused part really disappears from view.
            bone.hide = True
            pose_bone = armature_obj.pose.bones.get(bone.name)
            if pose_bone is not None:
                pose_bone.hide = True
            hidden_count += 1
        return hidden_count

    @staticmethod
    def _delete_invalid_bones(armature_obj, invalid_names):
        """Remove invalid bones and keep every usable child in the hierarchy.

        A usable child of a removed bone is reattached to the nearest usable
        ancestor. The child keeps its rest position because Edit Bone heads and
        tails live in armature space; clearing use_connect before changing the
        parent prevents Blender from snapping the head onto the new parent's
        tail. Without this step the surviving skeleton would break apart.
        """
        view_layer = bpy.context.view_layer
        previous_active = view_layer.objects.active
        was_selected = armature_obj.select_get()

        # Edit Bone operations need the armature active, selected and visible.
        view_layer.objects.active = armature_obj
        armature_obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            edit_bones = armature_obj.data.edit_bones

            # A hidden Edit Bone cannot be relied on to be removed, so reveal
            # only the doomed bones; usable bones keep their own visibility.
            for bone in edit_bones:
                if bone.name in invalid_names:
                    bone.hide = False

            # Reattach usable children before any bone disappears. Walking up
            # over the invalid chain finds the closest ancestor worth keeping.
            for bone in list(edit_bones):
                if bone.name not in invalid_names:
                    continue
                for child in list(bone.children):
                    if child.name in invalid_names:
                        # This child is deleted too; its own usable children are
                        # handled when its turn comes in this same loop.
                        continue
                    ancestor = bone.parent
                    while ancestor is not None and ancestor.name in invalid_names:
                        ancestor = ancestor.parent
                    child.use_connect = False
                    child.parent = ancestor

            # Remove one bone at a time and re-fetch it by name: removing an
            # Edit Bone invalidates other Edit Bone references in Blender.
            removed_count = 0
            for bone_name in sorted(invalid_names):
                edit_bone = edit_bones.get(bone_name)
                if edit_bone is None:
                    continue
                edit_bones.remove(edit_bone)
                removed_count += 1
            return removed_count
        finally:
            # Always leave Edit Mode, even when a removal raised an exception.
            if armature_obj.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            armature_obj.select_set(was_selected)
            view_layer.objects.active = previous_active

    @classmethod
    def apply(cls, naming_mode, objects, sidecar_path="", draw_ib_name=""):
        """Apply the sidecar to one group of meshes (manual operator entry point)."""
        return cls.apply_groups(naming_mode, {str(draw_ib_name or ""): list(objects)}, sidecar_path)

    @classmethod
    def apply_groups(cls, naming_mode, groups, sidecar_path="", cleanup_mode=BONE_CLEANUP_NONE):
        """Bind several DrawIB groups at once, one armature per character.

        groups: {drawib_folder_name: [mesh objects]}
        """
        if str(naming_mode or "").upper() == "NONE":
            return ""
        path = sidecar_path or cls.find_sidecar()
        if not path or not os.path.isfile(path):
            return ""
        try:
            sidecar = cls.load_sidecar(path)
        except Exception as error:  # noqa: BLE001 - a broken sidecar must not break the import
            print("Skeleton sidecar cannot be read:", error)
            return ""

        space = sidecar.get("Space") or {}
        space_scale = float(space.get("Scale", 1.0) or 1.0)
        space_rotation_z = float(space.get("RotationZ", 0.0) or 0.0)

        armatures = {}
        bound_counts = {}
        # Every mesh bound to an armature must be known when its bones are
        # cleaned: a bone may be used by only one of the character's parts.
        armature_meshes = {}
        for draw_ib_name, objects in groups.items():
            meshes = [obj for obj in objects if obj is not None and getattr(obj, "type", "") == "MESH"]
            if not meshes:
                continue
            draw_ib = cls.pick_drawib(sidecar, [obj.name for obj in meshes], draw_ib_name)
            if draw_ib is None:
                continue
            character = cls.character_by_id(sidecar, draw_ib.get("CharacterId"))
            if character is None:
                continue
            # WWMI components each carry their own numeric palette, so a single
            # armature cannot be renamed to every component's numbers. Keep the
            # bone names and rename each component's groups instead.
            components = draw_ib.get("Components") or []
            component_mode = bool(components)
            effective_naming = NAMING_GROUP_TO_BONE if component_mode else naming_mode
            key = str(character.get("Id", ""))
            if key not in armatures:
                # A non-mirrored workflow bakes an X reflection into the imported
                # mesh; the armature must receive the same reflection or bones
                # land on the wrong side of the model.
                mirror_x = any(bool(obj.get(MIRROR_MARKER, False)) for obj in meshes)
                armature_obj, final_names, original_names = cls.build_armature(
                    character, effective_naming, mirror_x, space_scale, space_rotation_z
                )
                if armature_obj is None:
                    continue
                armatures[key] = (armature_obj, final_names, original_names, character)
            armature_obj, final_names, original_names, character = armatures[key]
            if component_mode:
                by_original = {}
                for original, final in zip(original_names, final_names):
                    by_original.setdefault(original, final)
                for mesh in meshes:
                    entry = cls.pick_component(components, mesh.name)
                    mapping = (entry or {}).get("BoneMap") or draw_ib.get("BoneMap") or {}
                    cls.rename_groups_with_map([mesh], mapping, by_original)
            elif naming_mode == NAMING_BONE_TO_GROUP:
                cls.rename_bones_to_groups(character, armature_obj, original_names, final_names)
            elif naming_mode == NAMING_GROUP_TO_BONE:
                cls.rename_groups_to_bones(character, meshes, original_names, final_names)
            cls.bind(meshes, armature_obj)
            bound_counts[key] = bound_counts.get(key, 0) + len(meshes)
            armature_meshes.setdefault(key, []).extend(meshes)

        summaries = []
        cleanup_notes = []
        for key, (armature_obj, final_names, _, character) in armatures.items():
            # Cleanup runs after every DrawIB of this character is bound, so a
            # bone used by a later mesh is never deleted too early.
            removed_count, hidden_count = cls.cleanup_bones(
                armature_obj,
                armature_meshes.get(key, []),
                cleanup_mode,
            )
            # Several characters can be imported at once (body, weapon, ...),
            # so every cleanup note names the skeleton it belongs to.
            character_name = str(character.get("Name", "") or key)
            if removed_count:
                cleanup_notes.append(
                    "Bone cleanup "
                    + character_name
                    + ": "
                    + str(removed_count)
                    + " invalid bone(s) removed, "
                    + str(len(armature_obj.data.bones))
                    + " kept"
                )
            elif hidden_count:
                cleanup_notes.append(
                    "Bone cleanup "
                    + character_name
                    + ": "
                    + str(hidden_count)
                    + " invalid bone(s) hidden, "
                    + str(len(armature_obj.data.bones) - hidden_count)
                    + " used"
                )
            summaries.append(
                "Skeleton: "
                + str(character.get("Name", ""))
                + " ("
                + str(len(final_names))
                + " bones, "
                + str(bound_counts.get(key, 0))
                + " meshes)"
            )
        summaries.extend(cleanup_notes)
        return " | ".join(summaries)
