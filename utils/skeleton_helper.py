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
import os

import bpy
from mathutils import Matrix, Vector


NAMING_BONE_TO_GROUP = "BONE_TO_GROUP"
NAMING_GROUP_TO_BONE = "GROUP_TO_BONE"


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
        wanted = str(draw_ib_name or "").strip().lower()
        if wanted:
            for entry in entries:
                if str(entry.get("DrawIB", "")).strip().lower() == wanted:
                    return entry
            for entry in entries:
                folder = os.path.basename(str(entry.get("Folder", ""))).strip().lower()
                if folder and folder == wanted:
                    return entry
        for entry in entries:
            draw_ib = str(entry.get("DrawIB", ""))
            if draw_ib and any(draw_ib.lower() in name.lower() for name in object_names):
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
    def build_armature(character, naming_mode):
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
        used_names = set()
        created = []
        originals = []
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = []
        for index, bone in enumerate(bones):
            original_name = bone.get("Name", "")
            edit_bone = armature.edit_bones.new(SkeletonHelper._unique_name(original_name, used_names))
            rest = bone.get("Rest") or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
            edit_bone.matrix = Matrix([rest[0:4], rest[4:8], rest[8:12], rest[12:16]])
            # The matrix setter also rewrites the tail from the current length,
            # so the display length must be applied after it.
            edit_bone.length = lengths[index]
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

    @classmethod
    def rename_groups_to_bones(cls, character, objects, original_names, final_names):
        """GROUP_TO_BONE: groups take the source bone names of the character."""
        bone_map = cls._bone_map(character)
        by_original = {}
        for original, final in zip(original_names, final_names):
            by_original.setdefault(original, final)
        renamed = 0
        for obj in objects:
            for group in obj.vertex_groups:
                if not group.name.isdigit():
                    continue
                index = int(group.name)
                original = bone_map.get(index)
                if original is None:
                    continue
                target = by_original.get(original, original)
                if target:
                    group.name = target
                    renamed += 1
        return renamed

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

    @classmethod
    def apply(cls, naming_mode, objects, sidecar_path="", draw_ib_name=""):
        """Apply the sidecar to one group of meshes (manual operator entry point)."""
        return cls.apply_groups(naming_mode, {str(draw_ib_name or ""): list(objects)}, sidecar_path)

    @classmethod
    def apply_groups(cls, naming_mode, groups, sidecar_path=""):
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

        armatures = {}
        bound_counts = {}
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
            key = str(character.get("Id", ""))
            if key not in armatures:
                armature_obj, final_names, original_names = cls.build_armature(character, naming_mode)
                if armature_obj is None:
                    continue
                armatures[key] = (armature_obj, final_names, original_names, character)
            armature_obj, final_names, original_names, character = armatures[key]
            if naming_mode == NAMING_BONE_TO_GROUP:
                cls.rename_bones_to_groups(character, armature_obj, original_names, final_names)
            elif naming_mode == NAMING_GROUP_TO_BONE:
                cls.rename_groups_to_bones(character, meshes, original_names, final_names)
            cls.bind(meshes, armature_obj)
            bound_counts[key] = bound_counts.get(key, 0) + len(meshes)

        summaries = []
        for key, (_, final_names, _, character) in armatures.items():
            summaries.append(
                "Skeleton: "
                + str(character.get("Name", ""))
                + " ("
                + str(len(final_names))
                + " bones, "
                + str(bound_counts.get(key, 0))
                + " meshes)"
            )
        return " | ".join(summaries)
