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
from mathutils import Matrix


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
    def pick_drawib(sidecar, object_names):
        entries = sidecar.get("DrawIBs") or []
        if not entries:
            return None
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
    def build_armature(character, naming_mode):
        bones = character.get("Bones") or []
        if not bones:
            return None, []

        armature = bpy.data.armatures.new(str(character.get("Id", "Skeleton")) + "_Armature")
        armature_obj = bpy.data.objects.new(armature.name, armature)
        collection = bpy.context.collection or bpy.context.scene.collection
        collection.objects.link(armature_obj)

        view_layer = bpy.context.view_layer
        previous_active = view_layer.objects.active
        view_layer.objects.active = armature_obj
        armature_obj.select_set(True)

        used_names = set()
        created = []
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = []
        for bone in bones:
            edit_bone = armature.edit_bones.new(SkeletonHelper._unique_name(bone.get("Name", ""), used_names))
            rest = bone.get("Rest") or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
            matrix = Matrix([rest[0:4], rest[4:8], rest[8:12], rest[12:16]])
            edit_bone.matrix = matrix
            edit_bones.append(edit_bone)
            created.append(edit_bone.name)

        for index, bone in enumerate(bones):
            parent = int(bone.get("Parent", -1))
            if 0 <= parent < len(edit_bones) and parent != index:
                edit_bones[index].parent = edit_bones[parent]
                edit_bones[index].use_connect = False

        bpy.ops.object.mode_set(mode="OBJECT")
        armature_obj.show_in_front = True

        if naming_mode == NAMING_BONE_TO_GROUP:
            for index, name in enumerate(created):
                group_name = str(index)
                if group_name in armature.bones:
                    continue
                bone = armature.bones.get(name)
                if bone is not None:
                    bone.name = group_name

        if previous_active is not None:
            view_layer.objects.active = previous_active
        return armature_obj, created

    @staticmethod
    def rename_groups_to_bones(objects, character, bone_names):
        bone_map = {int(index): name for index, name in (character.get("BoneMap") or {}).items()}
        renamed = 0
        for obj in objects:
            for group in obj.vertex_groups:
                if not group.name.isdigit():
                    continue
                index = int(group.name)
                if index not in bone_map:
                    continue
                target = bone_names[index] if index < len(bone_names) else bone_map[index]
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
    def apply(cls, naming_mode, objects, sidecar_path=""):
        path = sidecar_path or cls.find_sidecar()
        if not path or not os.path.isfile(path):
            return ""
        sidecar = cls.load_sidecar(path)
        object_names = [obj.name for obj in objects]
        draw_ib = cls.pick_drawib(sidecar, object_names)
        if draw_ib is None:
            return ""
        character = cls.character_by_id(sidecar, draw_ib.get("CharacterId"))
        if character is None:
            return ""

        armature_obj, bone_names = cls.build_armature(character, naming_mode)
        if armature_obj is None:
            return ""

        if naming_mode == NAMING_GROUP_TO_BONE:
            cls.rename_groups_to_bones(objects, character, bone_names)

        cls.bind(objects, armature_obj)

        mapped = int(draw_ib.get("MappedBones", 0))
        used = int(draw_ib.get("UsedBones", 0))
        return (
            "Skeleton applied: "
            + str(character.get("Name", ""))
            + " ("
            + str(mapped)
            + "/"
            + str(used)
            + " bones, "
            + str(len(bone_names))
            + " total)"
        )
