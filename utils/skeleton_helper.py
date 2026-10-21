"""Apply a reversed-mod skeleton sidecar (skeleton.json).

SSMT5/MMT writes a sidecar next to every reverse output that carries the chosen
character's bones plus the numeric-vertex-group -> bone-name map. This helper
builds the armature from those rest matrices and binds the imported meshes.

Two naming modes exist because the two namespaces have different owners:

* BONE_TO_GROUP (default): keep the numeric vertex groups (they are the game's
  bone palette indices used by the mod's Blend buffer, so the model stays
  exportable) and rename the armature bones to the same numbers.
* GROUP_TO_BONE: keep readable bone names and rename the vertex groups instead.

One armature can carry only one numbering, but one character can have several
palettes (the body and the hair of a pack may index different bones under the
same numbers). Numeric naming therefore builds one armature per palette, so every
mesh can keep its own numbers; readable bone names stay on one shared armature.
"""

import json
import math
import os
import re

import bpy
from mathutils import Matrix, Vector


NAMING_BONE_TO_GROUP = "BONE_TO_GROUP"
NAMING_GROUP_TO_BONE = "GROUP_TO_BONE"
# Requested naming mode: take whatever the desktop app stored in the sidecar.
# The two concrete modes above stay available as explicit overrides.
NAMING_SIDECAR = "SIDECAR"
MIRROR_MARKER = "MIMI:MirrorWorkflowApplied"

# Bone cleanup modes offered by the Mod Reverse panel. A bone counts as invalid
# when no imported mesh stores a non-zero weight in a vertex group of the same
# name: reverse outputs carry the whole character skeleton, while one mod
# usually deforms only a small part of it.
BONE_CLEANUP_NONE = "NONE"
BONE_CLEANUP_DELETE = "DELETE"
BONE_CLEANUP_HIDE = "HIDE"

# Object property that records which Component an imported mesh belongs to.
# Both import paths know that number while they create the object, so the
# binder reads it directly instead of guessing from the object name. The name
# keeps the "MIMI:" prefix used by the other import contracts, so it is easy to
# find in the Object Properties panel.
COMPONENT_INDEX_PROPERTY = "MIMI:ComponentIndex"

# The desktop app stores the naming choice in camelCase ("boneToGroup") while
# this helper compares upper-case constants. Every incoming value therefore
# passes through normalize_naming_mode() before it is compared, which is what
# makes "Follow MMT" work for the embedded skeleton blocks as well.
_NAMING_ALIASES = {
    "bonetogroup": NAMING_BONE_TO_GROUP,
    "grouptobone": NAMING_GROUP_TO_BONE,
    "sidecar": NAMING_SIDECAR,
    "followmmt": NAMING_SIDECAR,
}

# Bones closer than this to their parent head only decorate the skeleton (twist
# or fix-up bones sit exactly on their parent). They must never define the
# parent's display length, otherwise that length collapses to zero.
COINCIDENT_DISTANCE = 1e-4

# An explicit Length from the sidecar is trusted only when it stays within this
# factor of the geometric child distance. Packs write placeholder lengths such
# as 4 mm for a 44 cm calf, which used to turn every main bone into a dot.
LENGTH_TOLERANCE = 4.0

# Confidence below this value is worth a warning: the desktop app itself is not
# sure that the skeleton it picked matches the model.
LOW_CONFIDENCE = 0.5


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
    def normalize_naming_mode(value):
        """Turn any spelling of a naming choice into one of the constants.

        The desktop app writes "boneToGroup" / "groupToBone", the operators
        write "BONE_TO_GROUP" / "GROUP_TO_BONE", and older files may carry an
        empty value. Comparing the raw strings was the reason a sidecar that
        asked for numeric bones silently renamed the vertex groups instead, so
        every value is normalized once, here.
        An unknown value returns an empty string; the caller decides the
        fallback, which keeps "Follow MMT" working.
        """
        # Case and separators differ between writers, so both are removed
        # before the lookup: "BONE_TO_GROUP" and "boneToGroup" become equal.
        key = str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")
        return _NAMING_ALIASES.get(key, "")

    @staticmethod
    def naming_from_sidecar(sidecar):
        """Concrete naming mode requested by a loaded sidecar.

        Missing or unknown values fall back to keeping the numeric vertex
        groups, which is the mode that keeps a reversed model exportable.
        """
        mode = SkeletonHelper.normalize_naming_mode((sidecar or {}).get("NamingMode", ""))
        return mode if mode in (NAMING_BONE_TO_GROUP, NAMING_GROUP_TO_BONE) else NAMING_BONE_TO_GROUP

    @staticmethod
    def sidecar_naming_mode(path):
        """Naming mode requested by the desktop app, if the sidecar declares one."""
        try:
            sidecar = SkeletonHelper.load_sidecar(path)
        except Exception:  # noqa: BLE001 - a broken sidecar falls back to the operator default
            return ""
        mode = SkeletonHelper.normalize_naming_mode(sidecar.get("NamingMode", ""))
        if mode in (NAMING_BONE_TO_GROUP, NAMING_GROUP_TO_BONE):
            return mode
        return ""

    @staticmethod
    def _draw_ib_keys(value):
        """Return the DrawIB keys one sidecar value can be addressed by.

        A value is a plain reverse folder (``195857d8``), an extraction folder
        with the draw call counts (``195857d8-1234-0``) or a nested path that
        also names its data-type folder. The full path segment and, for a
        hexadecimal DrawIB, its leading hash are both valid keys. Imported
        workspace objects are keyed by that leading hash only, which is why
        comparing the whole string was not enough.
        """
        keys = set()
        text = str(value or "").replace("\\", "/").strip("/")
        for segment in (part.strip().lower() for part in text.split("/")):
            if not segment:
                continue
            keys.add(segment)
            leading = re.split(r"[-_]", segment, maxsplit=1)[0]
            if re.fullmatch(r"[0-9a-f]{6,}", leading):
                keys.add(leading)
        return keys

    @staticmethod
    def pick_drawib(sidecar, object_names, draw_ib_name=""):
        entries = sidecar.get("DrawIBs") or []
        if not entries:
            return None

        names = [str(name or "").strip().lower() for name in object_names or []]
        name_tokens = set()
        for name in names:
            # Object names look like "LOD0.e590b8d4-0", so split them into
            # comparable words instead of searching the whole string.
            name_tokens.update(part for part in re.split(r"[^0-9a-z]+", name) if part)
        wanted = str(draw_ib_name or "").strip().lower()

        if wanted:
            # Exact folder names first: the reverse pass writes plain DrawIBs.
            for entry in entries:
                if str(entry.get("DrawIB", "")).strip().lower() == wanted:
                    return entry
            # Extraction folders append the draw call counts and may nest a
            # data-type folder, so compare the derived keys as well.
            for entry in entries:
                if wanted in SkeletonHelper._draw_ib_keys(entry.get("DrawIB")):
                    return entry
        # Fall back to the imported object names, which embed the same folder.
        for entry in entries:
            keys = SkeletonHelper._draw_ib_keys(entry.get("DrawIB"))
            if not keys:
                continue
            if keys & name_tokens:
                return entry
            if any(key in name for key in keys for name in names):
                return entry
        if len(entries) == 1:
            return entries[0]
        for entry in entries:
            folder = os.path.basename(str(entry.get("Folder", ""))).strip().lower()
            if folder and any(folder in name for name in names):
                return entry
        # Several entries and no evidence which one belongs to these objects.
        # Binding the first one would attach a wrong rig, and the group rename
        # of GROUP_TO_BONE is not reversible, so the caller is told instead.
        return None

    @staticmethod
    def character_by_id(sidecar, character_id):
        """Character entry this DrawIB names, or None when it cannot be told.

        Falling back to the first character of a multi-character pack attached
        the wrong skeleton to every DrawIB whose id did not match, which is far
        worse than leaving the mesh unbound and saying so.
        """
        characters = sidecar.get("Characters") or []
        if not characters:
            return None
        wanted = str(character_id or "")
        for character in characters:
            if str(character.get("Id", "")) == wanted:
                return character
        if len(characters) == 1:
            # One character cannot be the wrong one.
            return characters[0]
        return None

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
        """Display length per bone, in the same source units as the rest pose.

        The length only drives what the user sees in the viewport; it never
        changes heads, weights or the exported model. Three rules keep the
        skeleton readable:

        * an explicit ``Length`` wins when it agrees with the geometry (see
          ``LENGTH_TOLERANCE``), so a pack that writes real lengths stays exact;
        * otherwise the distance to the nearest child head that is actually
          apart from this bone is used, which ignores zero-length helper bones;
        * leaves and bones without usable geometry inherit a fraction of the
          parent.

        Prior behaviour trusted ``Length`` blindly and took ``min()`` over every
        child, including coincident ones. Reverse packs write 4 mm placeholders
        for bones that are half a metre long, so the spine, thighs, calves and
        forearms collapsed into invisible dots.
        """
        heads = SkeletonHelper._rest_heads(bones)
        lengths = [0.0] * len(bones)

        for index, bone in enumerate(bones):
            # Nearest child head that is really away from this bone. A helper
            # bone that sits exactly on its parent describes no length at all.
            distances = []
            for child_index, child in enumerate(bones):
                if child_index == index or int(child.get("Parent", -1)) != index:
                    continue
                distance = (heads[child_index] - heads[index]).length
                if distance > COINCIDENT_DISTANCE:
                    distances.append(distance)
            geometric = min(distances) if distances else 0.0
            explicit = float(bone.get("Length", 0) or 0)

            if geometric > COINCIDENT_DISTANCE and explicit > COINCIDENT_DISTANCE:
                # Accept the pack's value only when it describes the same
                # physical scale as the actual child distance.
                smallest = geometric / LENGTH_TOLERANCE
                largest = geometric * LENGTH_TOLERANCE
                lengths[index] = explicit if smallest <= explicit <= largest else geometric
            elif geometric > COINCIDENT_DISTANCE:
                lengths[index] = geometric
            elif explicit > COINCIDENT_DISTANCE:
                # A leaf has no geometry to compare against, so its explicit
                # length is the only information available.
                lengths[index] = explicit

        # Bones without any usable value inherit from the nearest parent that
        # has one. A pack may list a child before its parent (some game packs
        # do), so this repeats until nothing changes instead of relying on the
        # order of the array. Every pass can only add lengths, so it stops.
        for _ in range(len(bones)):
            changed = False
            for index, bone in enumerate(bones):
                if lengths[index] > COINCIDENT_DISTANCE:
                    continue
                parent = int(bone.get("Parent", -1))
                if 0 <= parent < len(bones) and lengths[parent] > COINCIDENT_DISTANCE:
                    lengths[index] = lengths[parent] * 0.6
                    changed = True
            if not changed:
                break
        for index in range(len(bones)):
            if lengths[index] <= COINCIDENT_DISTANCE:
                lengths[index] = 0.05

        # Length and Rest use the same source units (WWMI packs are centimetres).
        # Do not cap source lengths at one: the importer applies the unit scale
        # afterwards, so that cap reduced every WWMI bone to at most one cm.
        # Explicit and inferred lengths must preserve their physical proportions.
        return [max(1e-5, value) for value in lengths]

    @staticmethod
    def _mirrored_matrix(matrix):
        """Reflect a bone transform across X (`S M S` with `S = diag(-1,1,1,1)`)."""
        reflection = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
        return reflection @ matrix @ reflection

    @staticmethod
    def _space_matrix(scale, rotation_z, alignment=None):
        """Transform the game importer baked into the mesh (WWMI: 0.01, 180 deg).

        ``Alignment`` is a translation written in the pack's own frame, so it is
        applied before the rotation and the scale: the vertex data flows through
        the importer in the same order. A pack that leaves it at zero (the usual
        case) gets exactly the previous matrix.
        """
        matrix = Matrix.Identity(4)
        changed = False
        if alignment:
            values = list(alignment) + [0.0, 0.0, 0.0]
            offset = Vector((float(values[0]), float(values[1]), float(values[2])))
            if offset.length > 1e-9:
                matrix = Matrix.Translation(offset) @ matrix
                changed = True
        if abs(rotation_z) > 1e-9:
            matrix = Matrix.Rotation(math.radians(rotation_z), 4, "Z") @ matrix
            changed = True
        if abs(scale - 1.0) > 1e-9:
            matrix = Matrix.Scale(scale, 4) @ matrix
            changed = True
        return matrix if changed else None

    @staticmethod
    def _enter_edit_mode(armature_obj):
        """Make the armature active and switch to Edit Mode.

        Edit Bones only exist in Edit Mode, so the operator context has to be
        prepared explicitly. A different object may still be in Edit Mode from a
        manual edit, which makes the switch fail, so that mode is left first.
        """
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = armature_obj
        armature_obj.select_set(True)
        if armature_obj.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")

    @staticmethod
    def _leave_edit_mode(armature_obj):
        """Return to Object Mode without raising when the object is gone."""
        try:
            if armature_obj.mode != "OBJECT" and armature_obj.name in bpy.data.objects:
                bpy.ops.object.mode_set(mode="OBJECT")
        except (RuntimeError, ReferenceError):
            # A broken armature must not hide the original import error.
            pass

    @staticmethod
    def _assign_bone_collections(armature_obj):
        """Group bones by their name prefix so a 300-bone rig stays usable.

        Reverse packs name every bone with a system prefix ("Bip001", "Skn_",
        "Ctr_"). One Bone Collection per prefix lets the user hide the skin
        helpers or the control bones while the deform bones stay visible, which
        is far easier than scrolling a flat list of hundreds of bones.
        Blender versions without Bone Collections simply skip this step.
        """
        collections = getattr(armature_obj.data, "collections", None)
        if collections is None:
            return
        groups = {}
        for bone in armature_obj.data.bones:
            # The system prefix is the first word, and for names such as
            # "Skn_R_Tie_04" the part before the first underscore.
            prefix = bone.name.split(" ")[0].split("_")[0].strip()
            if not prefix:
                prefix = "Other"
            groups.setdefault(prefix, []).append(bone)
        for prefix, bones in groups.items():
            try:
                bone_collection = collections.new(prefix)
            except (RuntimeError, TypeError):
                continue
            for bone in bones:
                bone_collection.assign(bone)

    @staticmethod
    def build_armature(character, space_scale=1.0, space_rotation_z=0.0,
                       mirror_x=False, collection=None, alignment=None, suffix=""):
        """Create the armature of one character in the mesh's own space.

        ``collection`` receives the armature object. Passing it explicitly keeps
        the rig inside the collection tree the import created instead of
        ``bpy.context.collection``, which is often the scene root during a
        one-click import.
        ``suffix`` names the rig after the DrawIB it serves when one character
        needs more than one armature (one per bone palette).
        """
        bones = character.get("Bones") or []
        if not bones:
            return None, [], []

        armature_name = str(character.get("Id", "Skeleton")) + "_Armature"
        if suffix:
            armature_name += "_" + str(suffix)
        armature = bpy.data.armatures.new(armature_name)
        armature_obj = bpy.data.objects.new(armature.name, armature)
        target_collection = collection or bpy.context.collection or bpy.context.scene.collection
        target_collection.objects.link(armature_obj)

        view_layer = bpy.context.view_layer
        previous_active = view_layer.objects.active
        lengths = SkeletonHelper._bone_lengths(bones)
        space_matrix = SkeletonHelper._space_matrix(space_scale, space_rotation_z, alignment)
        used_names = set()
        created = []
        originals = []
        edit_bones = []
        try:
            SkeletonHelper._enter_edit_mode(armature_obj)
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
                # The matrix setter also rewrites the tail from the current
                # length, so the display length must be applied after it.
                edit_bone.length = lengths[index] * (space_scale if space_matrix is not None else 1.0)
                edit_bones.append(edit_bone)
                created.append(edit_bone.name)
                originals.append(original_name)

            for index, bone in enumerate(bones):
                parent = int(bone.get("Parent", -1))
                if 0 <= parent < len(edit_bones) and parent != index:
                    edit_bones[index].parent = edit_bones[parent]
                    edit_bones[index].use_connect = False
        finally:
            # A failure used to leave Blender in Edit Mode with a half built
            # armature, which blocked every later operator of the import.
            SkeletonHelper._leave_edit_mode(armature_obj)
            if previous_active is not None:
                try:
                    armature_obj.select_set(False)
                except RuntimeError:
                    pass
                view_layer.objects.active = previous_active

        armature_obj.show_in_front = True
        armature.display_type = 'OCTAHEDRAL'
        # The Deform flag from the pack decides which bones the armature
        # modifier and every exporter may consider; helper bones stay visual.
        for index, bone_data in enumerate(bones):
            deform = bone_data.get("Deform", True)
            if str(deform).lower() in ("false", "0"):
                bone = armature.bones.get(created[index])
                if bone is not None:
                    bone.use_deform = False
        SkeletonHelper._assign_bone_collections(armature_obj)
        return armature_obj, created, originals

    @staticmethod
    def _bone_map(character):
        return {int(index): str(name) for index, name in (character.get("BoneMap") or {}).items()}

    @classmethod
    def drawib_map(cls, draw_ib, character):
        """Numeric group -> bone name for one DrawIB.

        A mod that rebuilt some of its meshes indexes each DrawIB's palette
        separately, so the DrawIB map wins and the character map is only the
        fallback for sidecars written before that table existed.
        """
        own = (draw_ib or {}).get("BoneMap") or {}
        if own:
            return {str(index): str(name) for index, name in own.items()}
        return {str(index): str(name) for index, name in (character.get("BoneMap") or {}).items()}

    @staticmethod
    def palettes_conflict(mappings):
        """True when two numeric palettes of one character disagree."""
        seen = {}
        for mapping in mappings:
            for index, name in mapping.items():
                previous = seen.get(index)
                if previous is not None and previous != name:
                    return True
                seen[index] = name
        return False

    @staticmethod
    def palette_signature(mapping):
        """Stable text identity of one bone palette.

        DrawIBs that write the same index -> bone pairs can share one armature,
        so the identity is the sorted content of the map, not its length or the
        order the desktop app happened to use.
        """
        pairs = sorted(str(index) + ":" + str(name) for index, name in (mapping or {}).items())
        return "|".join(pairs)

    @classmethod
    def rename_bones_to_groups(cls, character, armature_obj, original_names, final_names, bone_map=None):
        """BONE_TO_GROUP: bones take the game palette numbers stored in the groups.

        The sidecar ``BoneMap`` is game index -> source bone name, and armature
        order is unrelated to the game palette order, so the rename must go
        through the name map.
        ``bone_map`` lets the caller pass the union of every palette that shares
        this armature, which is what a multi-DrawIB character needs: renaming
        with only the first DrawIB's map leaves the extra slots of the second
        one without a bone.
        """
        source_map = bone_map if bone_map is not None else cls._bone_map(character)
        # First index wins when a palette names the same bone twice: a bone can
        # carry only one name, and the second slot is reported as unmapped.
        name_to_index = {}
        for index, name in source_map.items():
            name_to_index.setdefault(str(name), int(index))
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
    def read_component_index(obj):
        """Component number recorded on an imported object, or -1 when absent.

        A workspace import renames its objects to ``LOD0.<DrawIB>-<N>``, which
        no longer contains the word "Component", so the number cannot be parsed
        from the name. The importer therefore stores it as a property while it
        still knows it.
        """
        try:
            value = obj.get(COMPONENT_INDEX_PROPERTY)
        except AttributeError:
            return -1
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def pick_component(components, object_name, component_index=-1):
        """Pick the component entry of one imported mesh.

        ``component_index`` wins when the importer recorded it, because it is
        the only source that survives an object rename. The object name is the
        fallback for the reverse import, whose meshes are named
        ``{DrawIB}-Component {N}.{Alias}``.
        """
        entries = components or []
        if component_index >= 0:
            for entry in entries:
                if int(entry.get("ComponentIndex", -1)) == component_index:
                    return entry
            return None
        match = re.search(r"component[\s_-]*(\d+)", str(object_name or ""), re.IGNORECASE)
        if match:
            index = int(match.group(1))
            for entry in entries:
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
    def count_unbound_groups(armature_obj, mesh_objects):
        """Weighted vertex groups whose name matches no bone.

        Those vertices keep their rest position whatever the armature does, so a
        non-zero count is the shortest honest signal that a binding is incomplete.
        """
        bone_names = {bone.name for bone in armature_obj.data.bones}
        meshes = 0
        groups = 0
        for obj in mesh_objects:
            if obj is None or getattr(obj, "type", "") != "MESH":
                continue
            missing = [name for name in SkeletonHelper.collect_weighted_group_names([obj]) if name not in bone_names]
            if missing:
                meshes += 1
                groups += len(missing)
        return meshes, groups

    @staticmethod
    def scan_weights(objects, bone_names=None):
        """Read every mesh once and describe how well its weights are bound.

        Returns a dict with these entries:

        * ``weighted``: group names that at least one vertex really uses;
        * ``orphans``: ``{name: [vertex count, weight sum]}`` for weighted
          groups whose name matches no bone in ``bone_names``;
        * ``unweighted``: vertices without a single positive weight, which stay
          in their rest position whatever the armature does;
        * ``unnormalized``: vertices whose weights do not add up to about one,
          which silently scales the deformation.

        A vertex group alone does not prove a bone is bound: the importer
        creates groups for every numeric slot up to the highest used one, so
        palette gaps contain empty groups. Only a stored weight above zero binds
        a vertex, therefore only those names may keep a bone alive.

        One scan serves the cleanup and the import report, because a full pass
        costs O(vertices x influences) Python steps and used to run twice.
        """
        weighted = set()
        orphans = {}
        unweighted = 0
        unnormalized = 0
        bone_set = set(bone_names or ())
        for obj in objects:
            if obj is None or getattr(obj, "type", "") != "MESH":
                continue
            mesh = getattr(obj, "data", None)
            if mesh is None or len(obj.vertex_groups) == 0:
                continue

            # Group indices are stable inside one object; resolve the names only
            # once, then collect the indices that receive a real weight.
            group_names = {group.index: group.name for group in obj.vertex_groups}
            for vertex in mesh.vertices:
                weight_sum = 0.0
                for assignment in vertex.groups:
                    # Zero weights are padding slots written by the importer.
                    # Counting them would keep bones that deform nothing.
                    if assignment.weight <= 0.0:
                        continue
                    weight_sum += assignment.weight
                    name = group_names.get(assignment.group)
                    if not name:
                        continue
                    weighted.add(name)
                    if bone_set and name not in bone_set:
                        row = orphans.setdefault(name, [0, 0.0])
                        row[0] += 1
                        row[1] += assignment.weight
                if weight_sum <= 1e-6:
                    unweighted += 1
                elif abs(weight_sum - 1.0) > 0.01:
                    unnormalized += 1
        return {
            "weighted": weighted,
            "orphans": orphans,
            "unweighted": unweighted,
            "unnormalized": unnormalized,
        }

    @staticmethod
    def collect_weighted_group_names(objects):
        """Return every vertex group name that at least one vertex actually uses."""
        return SkeletonHelper.scan_weights(objects)["weighted"]

    @classmethod
    def cleanup_bones(cls, armature_obj, mesh_objects, cleanup_mode, scan=None):
        """Delete or hide bones that no bound mesh actually deforms.

        Returns ``(removed_count, hidden_count)`` so the caller can add the
        result to its report. The mesh_objects list must contain every mesh
        bound to this armature, because a bone may be used by only one part.
        ``scan`` is the result of ``scan_weights`` for exactly those meshes; the
        import passes it in so the weights are read only once.
        """
        mode = str(cleanup_mode or BONE_CLEANUP_NONE).upper()
        if mode not in (BONE_CLEANUP_DELETE, BONE_CLEANUP_HIDE):
            return 0, 0
        if armature_obj is None or getattr(armature_obj, "type", "") != "ARMATURE":
            return 0, 0

        bone_names = {bone.name for bone in armature_obj.data.bones}
        if not bone_names:
            return 0, 0

        weighted_names = (scan or {}).get("weighted")
        if weighted_names is None:
            weighted_names = cls.scan_weights(mesh_objects)["weighted"]
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

    @staticmethod
    def forced_naming_warning(character_name):
        """Explain the one naming mode the component palettes still overrule.

        A forced mode looks exactly like an ignored dropdown, so the import has
        to say what happened. Per-component palettes are the reason left: the
        export addresses them through one merged table, so the rig keeps bone
        names although numeric bones were requested.
        """
        return (
            "Skeleton " + str(character_name) + ": its components each carry their own "
            "bone numbering, so one armature cannot carry a single numbering; "
            "the vertex groups keep the bone names."
        )

    @classmethod
    def _plan_from_block(cls, block, meshes):
        """Build a binding plan from the skeleton embedded in a SubmeshJson."""
        bones = block.get("Bones") or []
        if not bones:
            return None
        bone_map = block.get("BoneMap") or {}
        character = {
            "Id": str(block.get("CharacterId") or block.get("Hash") or "skeleton"),
            "Name": str(block.get("CharacterName") or ""),
            "Bones": bones,
            # The block's map is the DrawIB palette, which is also what a
            # bone-to-group rename must use.
            "BoneMap": bone_map,
        }
        components = block.get("Components") or []
        draw_ib = {"BoneMap": bone_map, "Components": components}
        fallback = cls.drawib_map(draw_ib, character)
        component_maps = [entry.get("BoneMap") or {} for entry in components if entry.get("BoneMap")]
        maps = [mapping for mapping in component_maps if mapping] or [fallback]
        return {
            "key": str(block.get("Hash") or character["Id"]),
            "draw_ib": draw_ib,
            "character": character,
            "meshes": meshes,
            "components": components,
            "fallback": fallback,
            "maps": maps,
            "space": block.get("Space") or {},
            # The app writes camelCase ("boneToGroup"); normalize it here so the
            # rest of the helper only ever compares the constants.
            "naming": cls.normalize_naming_mode(block.get("NamingMode")),
            # Filled in from the sidecar entry of the same DrawIB when one
            # exists: the embedded block carries no confidence values.
            "confidence": None,
            "used_bones": None,
            "mapped_bones": None,
            "mean_error": None,
        }

    @staticmethod
    def attach_sidecar_metadata(plan, entry):
        """Copy the desktop app's binding quality values onto one plan.

        The sidecar records how sure MMT is about the skeleton it picked
        (``Confidence``, ``MeanError``) and how many bones it could map
        (``MappedBones`` of ``UsedBones``). Those numbers explain a broken bind
        far better than any guess, so they are reported instead of ignored.
        """
        if not entry:
            return
        for source, target in (
            ("Confidence", "confidence"),
            ("UsedBones", "used_bones"),
            ("MappedBones", "mapped_bones"),
            ("MeanError", "mean_error"),
        ):
            if plan.get(target) is None and entry.get(source) is not None:
                plan[target] = entry[source]

    @classmethod
    def _plan_from_sidecar(cls, sidecar, draw_ib_name, meshes):
        """Build a binding plan from a legacy skeleton.json entry."""
        draw_ib = cls.pick_drawib(sidecar, [obj.name for obj in meshes], draw_ib_name)
        if draw_ib is None:
            # Several DrawIBs and none of them can be identified: binding any of
            # them would rename the vertex groups of a model that belongs to a
            # different character. The caller reports this instead.
            print("Skeleton binding skipped: cannot identify DrawIB '" + str(draw_ib_name) + "'")
            return None
        character = cls.character_by_id(sidecar, draw_ib.get("CharacterId"))
        if character is None:
            print("Skeleton binding skipped: unknown character for DrawIB " + str(draw_ib_name))
            return None
        components = draw_ib.get("Components") or []
        fallback = cls.drawib_map(draw_ib, character)
        # A DrawIB with declared components may still carry meshes without a
        # component identity (whole-buffer recovery parts); those keep the
        # DrawIB palette instead of being dropped from the binding.
        component_maps = [entry.get("BoneMap") or {} for entry in components if entry.get("BoneMap")]
        maps = [mapping for mapping in component_maps if mapping] or [fallback]
        plan = {
            "key": str(character.get("Id", "")),
            "draw_ib": draw_ib,
            "character": character,
            "meshes": meshes,
            "components": components,
            "fallback": fallback,
            "maps": maps,
            "space": sidecar.get("Space") or {},
            "naming": cls.normalize_naming_mode(sidecar.get("NamingMode")),
            "confidence": None,
            "used_bones": None,
            "mapped_bones": None,
            "mean_error": None,
        }
        cls.attach_sidecar_metadata(plan, draw_ib)
        return plan

    @classmethod
    def apply_groups(
        cls,
        naming_mode,
        groups,
        sidecar_path="",
        cleanup_mode=BONE_CLEANUP_NONE,
        import_mirror=None,
        skeletons=None,
        collection=None,
        warnings=None,
    ):
        """Bind several DrawIB groups at once, one armature per numbering.

        groups: {drawib_folder_name: [mesh objects]}
        naming_mode may also be NAMING_SIDECAR: the embedded block (or the
        legacy sidecar) then decides, which is what the shared import settings
        default to. An explicit mode always wins over the block. One armature
        carries one numbering, so a character whose DrawIBs disagree gets one
        armature per palette when numeric bones are requested; per-component
        palettes still fall back to bone names because the export addresses them
        through one merged table.
        import_mirror: whether this import baked the non-mirrored workflow's X
        reflection into the meshes. The one-click imports pass the scene mode;
        None falls back to the per-object marker (manual binding of objects an
        earlier session imported).
        skeletons: {drawib_folder_name: "Skeleton" block}. The desktop app writes
        one into every SubmeshJson, so a workspace that mixes LODs or characters
        binds each DrawIB to its own rig; identical blocks share one armature via
        their hash. Missing entries fall back to the legacy skeleton.json.
        collection: collection that receives the armature objects. Without it
        the rig lands in the active Outliner collection, which is often the
        scene root instead of the tree this import created.
        warnings: optional list that collects human readable warnings, so the
        calling operator can raise them as WARNING instead of burying every
        problem in one INFO line.
        """
        if str(naming_mode or "").upper() == "NONE":
            return ""

        # The desktop app writes camelCase while the operators write the
        # constants, so every caller value is normalized before it is compared.
        requested_mode = cls.normalize_naming_mode(naming_mode) or NAMING_SIDECAR
        warning_list = warnings if warnings is not None else []

        embedded = {
            str(name): block
            for name, block in (skeletons or {}).items()
            if isinstance(block, dict) and block.get("Bones")
        }

        # The sidecar is read even when every DrawIB ships an embedded block:
        # it holds the binding confidence and the used/mapped bone counts that
        # make a bad bind explainable. A missing sidecar is a normal state.
        sidecar = None
        path = sidecar_path or cls.find_sidecar()
        if path and os.path.isfile(path):
            try:
                sidecar = cls.load_sidecar(path)
            except Exception as error:  # noqa: BLE001 - a broken sidecar must not break the import
                print("Skeleton sidecar cannot be read:", error)
        if sidecar is None and not embedded:
            return ""

        # Resolve every group before touching the scene. The naming mode and the
        # number of armatures are decided from the complete list of palettes:
        # renaming bones to numbers for one DrawIB and groups to bone names for
        # the next left one of them pointing at no bone at all.
        plans = []
        palettes = {}
        for draw_ib_name, objects in groups.items():
            meshes = [obj for obj in objects if obj is not None and getattr(obj, "type", "") == "MESH"]
            if not meshes:
                continue
            plan = None
            block = embedded.get(str(draw_ib_name))
            if block:
                plan = cls._plan_from_block(block, meshes)
            # The sidecar entry of the same DrawIB carries the confidence that
            # the embedded block does not contain. Without a block it is the
            # only source of the binding.
            entry = None
            if sidecar is not None:
                entry = cls.pick_drawib(sidecar, [obj.name for obj in meshes], draw_ib_name)
            if plan is not None:
                cls.attach_sidecar_metadata(plan, entry)
            elif entry is not None:
                plan = cls._plan_from_sidecar(sidecar, draw_ib_name, meshes)
            if plan is None:
                continue
            # The DrawIB name is kept on the plan: a character with several bone
            # palettes needs one armature per palette, and each rig has to say
            # which DrawIBs it serves.
            plan["group"] = str(draw_ib_name or "")
            key = plan["key"]
            palettes.setdefault(key, []).extend(plan["maps"])
            plans.append(plan)

        if not plans:
            return ""

        # "Follow MMT" is decided once per character: the embedded blocks each
        # carry the app's choice, the legacy sidecar carries it globally. An
        # explicit choice from the panel is respected for every character.
        if requested_mode == NAMING_SIDECAR:
            default_naming = cls.naming_from_sidecar(sidecar) if sidecar else NAMING_BONE_TO_GROUP
        else:
            default_naming = requested_mode
        naming_by_key = {}
        for plan in plans:
            key = plan["key"]
            if requested_mode == NAMING_SIDECAR:
                naming_by_key.setdefault(key, plan.get("naming") or default_naming)
            else:
                naming_by_key.setdefault(key, requested_mode)

        # Per-component palettes are internal to one DrawIB and the export
        # addresses them through one merged table, so such a character keeps one
        # armature with bone names. Splitting it per component would change the
        # export architecture, not fix a naming problem.
        component_mode = {}
        for key in palettes:
            component_mode[key] = any(plan["key"] == key and plan["components"] for plan in plans)

        group_mode = {}
        override_reason = {}
        for key in palettes:
            group_mode[key] = bool(component_mode.get(key))
            if group_mode[key] and naming_by_key.get(key) != NAMING_GROUP_TO_BONE:
                override_reason[key] = "component palettes"

        # One armature can only carry one numbering, and every part should be
        # manageable on its own, so each palette gets its own armature in both
        # naming modes. Numeric naming needs the split to give every mesh the
        # bones its own numbers name; with readable bone names the split keeps
        # the parts independent (each rig can be posed and cleaned alone).
        # Equal palettes still share one rig, so a normal character keeps one.
        palettes_per_character = {}
        armature_labels = {}
        armature_character = {}
        for plan in plans:
            key = plan["key"]
            armature_key = key + "|" + cls.palette_signature(plan["fallback"])
            plan["armature_key"] = armature_key
            palettes_per_character.setdefault(key, set()).add(armature_key)
            armature_character.setdefault(armature_key, key)
            label = armature_labels.setdefault(armature_key, [])
            if plan["group"] and plan["group"] not in label:
                label.append(plan["group"])

        # Only a character that really received several rigs needs the DrawIB
        # label; a normal import keeps clean names.
        split_characters = set()
        for key, armature_keys in palettes_per_character.items():
            if len(armature_keys) > 1:
                split_characters.add(key)

        # BONE_TO_GROUP can name a bone only once per armature, so every rig is
        # renamed with the palette of the DrawIBs it serves.
        merged_palettes = {}
        for plan in plans:
            merged = merged_palettes.setdefault(plan["armature_key"], {})
            for index, name in (plan["fallback"] or {}).items():
                merged.setdefault(str(index), str(name))

        armatures = {}
        bound_counts = {}
        modes = {}
        skipped_meshes = 0
        # Every mesh bound to an armature must be known when its bones are
        # cleaned: a bone may be used by only one of the character's parts.
        armature_meshes = {}
        for plan in plans:
            key = plan["key"]
            armature_key = plan["armature_key"]
            character = plan["character"]
            meshes = plan["meshes"]
            effective_naming = (
                NAMING_GROUP_TO_BONE if group_mode.get(key) else naming_by_key.get(key, default_naming)
            )
            if armature_key not in armatures:
                # The mesh and the skeleton share one orientation; the armature
                # follows the X reflection this import baked into the mesh. A
                # block from an older, mirror-matched build still reports it, so
                # its bones stay on the side that build intended.
                space = plan.get("space") or {}
                space_scale = float(space.get("Scale", 1.0) or 1.0)
                space_rotation_z = float(space.get("RotationZ", 0.0) or 0.0)
                match_mirror_x = bool(space.get("MatchMirrorX", False))
                if import_mirror is None:
                    mesh_flipped = any(bool(obj.get(MIRROR_MARKER, False)) for obj in meshes)
                else:
                    mesh_flipped = bool(import_mirror)
                mirror_x = mesh_flipped != match_mirror_x
                # A split character names every rig after the DrawIB it serves,
                # so the Outliner never shows two indistinguishable armatures.
                suffix = ""
                if key in split_characters:
                    suffix = (armature_labels.get(armature_key) or [""])[0]
                armature_obj, final_names, original_names = cls.build_armature(
                    character,
                    space_scale=space_scale,
                    space_rotation_z=space_rotation_z,
                    mirror_x=mirror_x,
                    collection=collection,
                    alignment=space.get("Alignment"),
                    suffix=suffix,
                )
                if armature_obj is None:
                    continue
                if effective_naming == NAMING_BONE_TO_GROUP:
                    # Every rig carries exactly one numbering, so its bones are
                    # renamed once, when it is created.
                    cls.rename_bones_to_groups(
                        character,
                        armature_obj,
                        original_names,
                        final_names,
                        bone_map=merged_palettes.get(armature_key),
                    )
                armatures[armature_key] = (armature_obj, final_names, original_names, character)
                modes[armature_key] = effective_naming
                bound_counts[armature_key] = 0
                armature_meshes[armature_key] = []
            armature_obj, final_names, original_names, character = armatures[armature_key]
            if effective_naming == NAMING_BONE_TO_GROUP:
                bindable = meshes
            else:
                by_original = {}
                for original, final in zip(original_names, final_names):
                    by_original.setdefault(original, final)
                bindable = []
                for mesh in meshes:
                    entry = cls.pick_component(
                        plan["components"], mesh.name, cls.read_component_index(mesh)
                    )
                    if plan["components"] and entry is None:
                        # A declared component table means each component owns an
                        # independent palette; a whole-buffer recovery mesh
                        # cannot be resolved and must keep its raw geometry.
                        skipped_meshes += 1
                        continue
                    mapping = (entry or {}).get("BoneMap") or plan["fallback"]
                    if mapping:
                        cls.rename_groups_with_map([mesh], mapping, by_original)
                    bindable.append(mesh)
            cls.bind(bindable, armature_obj)
            bound_counts[armature_key] = bound_counts.get(armature_key, 0) + len(bindable)
            armature_meshes.setdefault(armature_key, []).extend(bindable)

        if skipped_meshes:
            message = (
                "Skeleton binding skipped "
                + str(skipped_meshes)
                + " mesh(es) without component identity"
            )
            print(message)
            warning_list.append(message)

        # Binding quality is aggregated per armature: the worst confidence of a
        # rig's DrawIBs and the palette coverage the desktop app reported.
        quality = {}
        for plan in plans:
            row = quality.setdefault(plan["armature_key"], {"confidence": None, "used": None, "mapped": None})
            if plan.get("confidence") is not None:
                value = float(plan["confidence"])
                row["confidence"] = value if row["confidence"] is None else min(row["confidence"], value)
            if plan.get("used_bones") is not None:
                row["used"] = max(row["used"] or 0, int(plan["used_bones"]))
            if plan.get("mapped_bones") is not None:
                row["mapped"] = max(row["mapped"] or 0, int(plan["mapped_bones"]))

        summaries = []
        cleanup_notes = []
        # A split character reports one rig per palette; the confidence warning
        # is about the character, so it must not be repeated for every rig.
        warned_confidence = set()
        # Several rigs are a workflow change, not a cosmetic detail: they have to
        # be posed together, so the user is told once per character.
        split_groups = {}
        character_names = {}
        for plan in plans:
            key = plan["key"]
            character_names.setdefault(key, str(plan["character"].get("Name") or key))
            if key in split_characters and plan["group"]:
                split_groups.setdefault(key, [])
                if plan["group"] not in split_groups[key]:
                    split_groups[key].append(plan["group"])
        for key, names in split_groups.items():
            warning_list.append(
                "Skeleton " + character_names[key] + ": its DrawIBs " + ", ".join(names)
                + " number different bones, so every palette got its own armature; "
                + "pose them together."
            )
        for armature_key, (armature_obj, final_names, _, character) in armatures.items():
            meshes = armature_meshes.get(armature_key, [])
            bone_names = {bone.name for bone in armature_obj.data.bones}
            # One weight pass per armature serves the cleanup and the report.
            # It runs before the cleanup so the report describes the geometry
            # the user actually has, not the bones that survived it.
            scan = cls.scan_weights(meshes, bone_names)
            # Cleanup runs after every DrawIB that uses this armature is bound,
            # so a bone used by a later mesh is never deleted too early.
            removed_count, hidden_count = cls.cleanup_bones(
                armature_obj, meshes, cleanup_mode, scan=scan
            )
            # Several characters can be imported at once (body, weapon, ...), so
            # every note names the skeleton it belongs to. One line per armature
            # keeps the panel hint readable instead of repeating the name five
            # times, which also survived the 512 character panel limit.
            character_key = armature_character.get(armature_key, armature_key)
            character_name = str(character.get("Name", "") or character_key)
            split = character_key in split_characters
            if split:
                # Two rigs of one character must be distinguishable in the
                # Outliner and in the report.
                character_name += " [" + ", ".join(armature_labels.get(armature_key) or []) + "]"
            details = []

            # The effective mode is part of the result: it explains why a
            # character unexpectedly carries bone names instead of numbers.
            mode_text = (
                "Rename Vertex Groups"
                if modes.get(armature_key) == NAMING_GROUP_TO_BONE
                else "Rename Bones"
            )
            mode_detail = "naming " + mode_text
            reason = override_reason.get(character_key)
            if reason:
                mode_detail += " [forced: " + reason + "]"
                # The summary alone is not enough: it is one INFO line that the
                # next report overwrites, and the panel shortens it in the
                # middle. The user must be told that the dropdown was overruled.
                warning_list.append(cls.forced_naming_warning(character_name))
            details.append(mode_detail)
            if split:
                # The rig name is the only way to tell the two armatures apart
                # in the Outliner after the import.
                details.append("armature " + armature_obj.name)

            row = quality.get(armature_key) or {}
            if row.get("confidence") is not None:
                details.append("confidence " + format(float(row["confidence"]), ".2f"))
            if row.get("mapped") is not None and row.get("used") is not None:
                details.append("palette " + str(row["mapped"]) + "/" + str(row["used"]))

            # A palette slot without a bone means real weights that can never
            # deform. Naming the slots is what turns a silent defect into a
            # fixable one: the user can look the bone up and map it by hand.
            orphans = scan.get("orphans") or {}
            if orphans:
                ordered = sorted(orphans.items(), key=lambda item: -item[1][0])
                slots = [name for name, _ in ordered[:3]]
                vertices = sum(int(value[0]) for _, value in ordered)
                details.append(
                    str(len(orphans))
                    + " slot(s) without a bone ("
                    + ", ".join(slots)
                    + ") -> "
                    + str(vertices)
                    + " weights in bind pose"
                )
                warning_list.append(
                    "Skeleton "
                    + character_name
                    + ": "
                    + str(len(orphans))
                    + " palette slot(s) without a bone ("
                    + ", ".join(slots)
                    + "); "
                    + str(vertices)
                    + " weights stay in bind pose"
                )

            if scan.get("unweighted"):
                details.append(str(scan["unweighted"]) + " vertex(es) carry no weight")
            if scan.get("unnormalized"):
                details.append(str(scan["unnormalized"]) + " vertex(es) with weights not summing to 1")

            if row.get("confidence") is not None and float(row["confidence"]) < LOW_CONFIDENCE:
                if character_key not in warned_confidence:
                    warned_confidence.add(character_key)
                    warning_list.append(
                        "Skeleton "
                        + character_name
                        + " was matched with low confidence "
                        + format(float(row["confidence"]), ".2f")
                        + "; check the rig before editing"
                    )

            # The effective mode comes first: the panel shortens a long line in
            # the middle, so a mode hidden behind the bone and mesh counts was
            # invisible exactly when it mattered (a forced fallback).
            summaries.append(
                "Skeleton: "
                + character_name
                + ", "
                + ", ".join(details)
                + " ("
                + str(len(armature_obj.data.bones))
                + " bones, "
                + str(bound_counts.get(armature_key, 0))
                + " meshes)"
            )

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
        summaries.extend(cleanup_notes)
        return " | ".join(summaries)
