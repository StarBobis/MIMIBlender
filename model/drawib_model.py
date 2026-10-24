
from dataclasses import field, dataclass
import os
import re

from ..common.d3d11_gametype import D3D11GameType
from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.texture_naming import normalize_texture_role
from ..common.texture_output_naming import (
    alias_output_filename_with_suffix,
    ensure_ini_encodable,
    file_resource_stem,
    hash_output_stem,
    normalize_alias_stem,
    object_resource_slug,
)
from ..common.gimi_texture_slots import get_gimi_texture_slot

from ..utils.json_utils import JsonUtils
from ..workspace.texture_metadata_helper import TextureMetadataResolver
from ..workspace.submesh_json import SubmeshJson
from ..workspace.mmt_workspace import MMTWorkSpace
from ..common.buffer_export_helper import BufferExportHelper

import numpy

from .submesh_model import SubMeshModel

# 3Dmigoto texture slot syntax, e.g. ps-t0 / vs-s1 / cs-u2.
OBJECT_TEXTURE_SLOT_PATTERN = re.compile(r"^(ps|vs|gs|hs|ds|cs)-(t|s|b|u)\d+$")
# 3Dmigoto resource section names are plain identifiers.
OBJECT_TEXTURE_RESOURCE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A 3Dmigoto texture hash is 8 hexadecimal characters (a 32-bit hash).
OBJECT_TEXTURE_HASH_PATTERN = re.compile(r"^[0-9a-f]{8}$")
# File formats 3Dmigoto can load directly from a [ResourceXXX] filename.
# They are also the replacement formats the file browser accepts.
OBJECT_TEXTURE_FILE_SUFFIXES = (".dds", ".png", ".jpg", ".jpeg", ".bmp", ".tga")


def exact_texture_format_enabled():
    """Return the global exact-format switch without breaking test stubs.

    The model layer is unit tested with a minimal MIMIGlobalProperties stub,
    so a missing method means "enabled" instead of an AttributeError.
    """
    getter = getattr(MIMIGlobalProperties, "exact_texture_format_enabled", None)
    try:
        return bool(getter()) if callable(getter) else True
    except Exception:
        return True


def exact_texture_resize_filter():
    """Return the configured resize filter, falling back to the default."""
    getter = getattr(MIMIGlobalProperties, "exact_texture_resize_filter_name", None)
    try:
        value = str(getter() or "") if callable(getter) else ""
    except Exception:
        value = ""
    # Imported lazily so the model layer only pulls the core module on demand.
    from ..texcomb.core.dds_match import DEFAULT_RESIZE_FILTER
    return value or DEFAULT_RESIZE_FILTER

@dataclass
class DrawIBModel:
    '''
    - DrawIBModel is a higher-level model that contains one or more SubMeshModel
    - For games like miHoYo and Unity that must combine multiple SubMeshes into a single DrawIB for export
    - To use DrawIBModel, every SubMesh must share the same Data Type so they can be combined
    '''
    submesh_model_list:list[SubMeshModel]
    combine_ib:bool = True

    draw_ib:str = field(init=False, default="")
    draw_ib_alias:str = field(init=False, default="")

    vertex_count:int = field(init=False, default=0)
    index_count:int = field(init=False, default=0)

    # There is an implicit constraint on d3d11_game_type here
    # Once a DrawIBModel is created, every SubmeshModel inside it is assumed to have the same d3d11_game_type
    # Otherwise it is impossible to combine buffer data for a correct export
    # So d3d11_game_type can be taken directly from the first SubMeshModel in submesh_model_list
    d3d11_game_type:D3D11GameType = field(init=False,repr=False,default=None)

    import_json_path:str = field(init=False,repr=False,default="")
    import_json_dict:dict = field(init=False,repr=False,default_factory=dict)
    category_hash_dict:dict = field(init=False,repr=False,default_factory=dict)
    submesh_texturemarkinfolist_dict:dict = field(init=False,repr=False,default_factory=dict)
    vertex_limit_hash:str = field(init=False,repr=False,default="")
    cs_output_vertex_limit_hash:str = field(init=False,repr=False,default="")
    original_vertex_count:int = field(init=False,repr=False,default=0)

    ib:list = field(init=False,repr=False,default_factory=list)
    submesh_ib_dict:dict = field(init=False,repr=False,default_factory=dict)
    category_buffer_dict:dict = field(init=False,repr=False,default_factory=dict)
    index_vertex_id_dict:dict = field(init=False,repr=False,default_factory=dict)
    obj_name_draw_offset:dict = field(init=False,repr=False,default_factory=dict)
    shapekey_name_bytelist_dict:dict = field(init=False,repr=False,default_factory=dict)

    # Byte offset of every Submesh inside the concatenated category buffers
    # (exported-vertex base).  Filled by _assemble_category_buffers; the
    # Time Position Switch writer needs it to locate the animated slice.
    submesh_vertex_base_dict:dict = field(init=False,repr=False,default_factory=dict)

    # Time Position Switch frames of this DrawIB, attached by
    # BluePrintModel.parse_drawib_model_list():
    # {timeline variable name: {frame value: [DrawCallModel, ...]}}.
    # Frame DrawCallModels never joined the submesh buffers; they only
    # provide per-frame Position bytes.
    time_pos_frame_groups:dict = field(default_factory=dict, repr=False)

    # Per-object texture slot bindings (Texture Bind blueprint nodes):
    # resource sections that still need to be emitted, as
    # (resource_name, target_filename) pairs, and file copy jobs as
    # (resource_name, source_path, target_filename) triples. Both are
    # filled by resolve_texture_slot_bindings() during __post_init__.
    object_texture_binding_resource_list:list = field(init=False,repr=False,default_factory=list)
    object_texture_binding_file_list:list = field(init=False,repr=False,default_factory=list)

    # Exact-format conversion jobs keyed by generated resource name:
    # {resource_name: {"original_path": ..., "manual_format": ...,
    #                  "force_original_size": bool, "resize_filter": str}}
    # Filled by both binding resolvers and by the global slot pass; consumed
    # by the export copy stage, which converts before writing the Mod folder.
    exact_texture_jobs:dict = field(init=False,repr=False,default_factory=dict)



    def __post_init__(self):
        # Every SubMeshModel in the list passed at init shares the same match_draw_ib, so take the first one
        self.draw_ib = self.submesh_model_list[0].match_draw_ib if len(self.submesh_model_list) > 0 else ""
        self.draw_ib_alias = self.draw_ib
        self.d3d11_game_type = self.submesh_model_list[0].d3d11_game_type if len(self.submesh_model_list) > 0 else None
        self._load_import_metadata_from_first_submesh()

        category_buffer_dict, submesh_vertex_base_dict, index_vertex_id_dict, vertex_count = self._assemble_category_buffers()

        self.vertex_count = vertex_count
        self.category_buffer_dict = category_buffer_dict
        self.index_vertex_id_dict = index_vertex_id_dict
        self.submesh_vertex_base_dict = submesh_vertex_base_dict
        self.shapekey_name_bytelist_dict = self._assemble_shape_key_buffers()

        if self.combine_ib:
            total_ib, obj_name_draw_offset = self._assemble_combined_ib_and_draw_offset(submesh_vertex_base_dict)
            self.ib = total_ib
            self.submesh_ib_dict = {}
            self.obj_name_draw_offset = obj_name_draw_offset
            self.index_count = len(total_ib)
        else:
            submesh_ib_dict, obj_name_draw_offset, total_index_count = self._assemble_split_ib_and_draw_offset(submesh_vertex_base_dict)
            self.ib = []
            self.submesh_ib_dict = submesh_ib_dict
            self.obj_name_draw_offset = obj_name_draw_offset
            self.index_count = total_index_count

        # Resolve per-object texture slot bindings (Slot Texture Bind nodes)
        # now that the texture markup dict is loaded, so every game exporter
        # sees ready-made INI lines on the DrawCallModels.
        self.resolve_texture_slot_bindings()

        # Resolve per-object hash texture bindings (Hash Texture Bind nodes)
        # the same way; the resolved rows are consumed by the blueprint-wide
        # conditional this= section generator in M_IniHelper.
        self.resolve_hash_texture_bindings()

    def _load_import_metadata_from_first_submesh(self):
        if not self.submesh_model_list:
            print("DrawIBModel: submesh_model_list is empty, cannot read import metadata")
            return

        first_submesh = self.submesh_model_list[0]
        folder_name = first_submesh.submesh_name
        print("DrawIBModel: Start reading export metadata, DrawIB: " + self.draw_ib + ", submesh_name: " + folder_name)

        submesh_json = SubmeshJson(MMTWorkSpace.check_and_get_submesh_json_path(folder_name))
        self.import_json_path = submesh_json.JsonFilePath
        self.import_json_dict = dict(submesh_json.JsonDict)
        print("DrawIBModel: SubmeshJson read: " + self.import_json_path)

        if self.import_json_dict:
            self.category_hash_dict = dict(self.import_json_dict.get("CategoryHash", {}))
            self.submesh_texturemarkinfolist_dict = TextureMetadataResolver.load_submesh_texture_markup_info_from_all_submeshes(
                draw_ib_model=self,
            )
            self.vertex_limit_hash = self.import_json_dict.get("VertexLimitVB", "")
            self.cs_output_vertex_limit_hash = self.load_cs_output_vertex_limit_hash()
            self.original_vertex_count = self.import_json_dict.get("OriginalVertexCount", 0)
            print(
                "DrawIBModel: Used new-format metadata, Texture markup SubMesh count: "
                + str(len(self.submesh_texturemarkinfolist_dict))
            )
            return

        print("DrawIBModel: No SubmeshJson metadata found, Texture markup info is empty, DrawIB: " + self.draw_ib)

    def load_cs_output_vertex_limit_hash(self) -> str:
        for submesh_model in self.submesh_model_list:
            try:
                submesh_json = SubmeshJson(MMTWorkSpace.check_and_get_submesh_json_path(submesh_model.submesh_name))
            except Exception as ex:
                print(
                    "DrawIBModel: failed to read CSOutputVertexLimitVB, Submesh: "
                    + submesh_model.submesh_name
                    + ", error: "
                    + str(ex)
                )
                continue

            cs_output_vertex_limit_hash = str(submesh_json.CSOutputVertexLimitVB or "").strip()
            if cs_output_vertex_limit_hash:
                return cs_output_vertex_limit_hash

        return ""

    def _assemble_category_buffers(self) -> tuple[dict, dict, dict, int]:
        total_category_buffer_chunks = {}
        total_index_vertex_id_dict = {}
        submesh_vertex_base_dict = {}
        vertex_offset = 0

        for submesh_model in self.submesh_model_list:
            submesh_vertex_base_dict[submesh_model.submesh_name] = vertex_offset

            for category, category_buf in submesh_model.category_buffer_dict.items():
                if category not in total_category_buffer_chunks:
                    total_category_buffer_chunks[category] = []
                total_category_buffer_chunks[category].append(category_buf)

            if submesh_model.index_vertex_id_dict:
                for local_index, vertex_id in submesh_model.index_vertex_id_dict.items():
                    total_index_vertex_id_dict[local_index + vertex_offset] = vertex_id

            vertex_offset += self._get_exported_vertex_count(submesh_model)

        total_category_buffer_dict = {
            category: numpy.concatenate(category_chunks)
            for category, category_chunks in total_category_buffer_chunks.items()
            if category_chunks
        }
        return total_category_buffer_dict, submesh_vertex_base_dict, total_index_vertex_id_dict, vertex_offset

    def _assemble_combined_ib_and_draw_offset(self, submesh_vertex_base_dict: dict) -> tuple[list, dict]:
        total_ib = []
        obj_name_draw_offset = {}
        submesh_index_offset = 0

        for submesh_model in self.submesh_model_list:
            vertex_base = submesh_vertex_base_dict.get(submesh_model.submesh_name, 0)
            total_ib.extend(index + vertex_base for index in submesh_model.ib)

            for draw_call_model in submesh_model.drawcall_model_list:
                # Scope offsets to the draw, not just the reused Blender name.
                # Retain name keys for callers that still use the legacy lookup.
                offset = submesh_index_offset + draw_call_model.index_offset
                obj_name_draw_offset[id(draw_call_model)] = offset
                obj_name_draw_offset[draw_call_model.obj_name] = offset

            submesh_index_offset += len(submesh_model.ib)

        return total_ib, obj_name_draw_offset

    def _assemble_split_ib_and_draw_offset(self, submesh_vertex_base_dict: dict) -> tuple[dict, dict, int]:
        submesh_ib_dict = {}
        obj_name_draw_offset = {}
        total_index_count = 0

        for submesh_model in self.submesh_model_list:
            vertex_base = submesh_vertex_base_dict.get(submesh_model.submesh_name, 0)
            remapped_ib = [index + vertex_base for index in submesh_model.ib]
            submesh_ib_dict[submesh_model.submesh_name] = remapped_ib
            total_index_count += len(remapped_ib)

            for draw_call_model in submesh_model.drawcall_model_list:
                # Local offsets also differ when object order varies by Submesh.
                # Exact draw identities prevent one body's range replacing another.
                obj_name_draw_offset[id(draw_call_model)] = draw_call_model.index_offset
                obj_name_draw_offset[draw_call_model.obj_name] = draw_call_model.index_offset

        return submesh_ib_dict, obj_name_draw_offset, total_index_count

    def _assemble_shape_key_buffers(self) -> dict:
        if self.d3d11_game_type is None:
            return {}

        position_stride = self.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        if position_stride <= 0:
            return {}

        position_offset = self._get_category_byte_offset("Position")
        ordered_shapekey_names = []
        seen_shapekey_names = set()

        for submesh_model in self.submesh_model_list:
            for shapekey_name in submesh_model.shape_key_buffer_dict.keys():
                if shapekey_name in seen_shapekey_names:
                    continue
                seen_shapekey_names.add(shapekey_name)
                ordered_shapekey_names.append(shapekey_name)

        if not ordered_shapekey_names:
            return {}

        shapekey_chunks = {shapekey_name: [] for shapekey_name in ordered_shapekey_names}

        for submesh_model in self.submesh_model_list:
            base_position_buffer = submesh_model.category_buffer_dict.get("Position")

            for shapekey_name in ordered_shapekey_names:
                shape_key_buffer_result = submesh_model.shape_key_buffer_dict.get(shapekey_name)

                if shape_key_buffer_result is None:
                    if base_position_buffer is not None:
                        shapekey_chunks[shapekey_name].append(base_position_buffer)
                    continue

                position_bytes = self._extract_position_bytes_from_shape_key(
                    shape_key_buffer_result.element_vertex_ndarray,
                    position_offset,
                    position_stride,
                )
                shapekey_chunks[shapekey_name].append(position_bytes)

        return {
            shapekey_name: numpy.concatenate(chunks)
            for shapekey_name, chunks in shapekey_chunks.items()
            if chunks
        }

    def _get_category_byte_offset(self, target_category: str) -> int:
        byte_offset = 0

        for category_name in self.d3d11_game_type.OrderedCategoryNameList:
            if category_name == target_category:
                return byte_offset
            byte_offset += self.d3d11_game_type.CategoryStrideDict.get(category_name, 0)

        return byte_offset

    def _extract_position_bytes_from_shape_key(
        self,
        element_vertex_ndarray: numpy.ndarray,
        position_offset: int,
        position_stride: int,
    ) -> numpy.ndarray:
        if len(element_vertex_ndarray) == 0:
            return numpy.array([], dtype=numpy.uint8)

        full_byte_view = element_vertex_ndarray.view(numpy.uint8).reshape(len(element_vertex_ndarray), -1)
        return full_byte_view[:, position_offset:position_offset + position_stride].reshape(-1)

    def _get_exported_vertex_count(self, submesh_model: SubMeshModel) -> int:
        if submesh_model.index_vertex_id_dict:
            return len(submesh_model.index_vertex_id_dict)

        position_buffer = submesh_model.category_buffer_dict.get("Position")
        if position_buffer is None or self.d3d11_game_type is None:
            return 0

        position_stride = self.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        if position_stride <= 0:
            return 0

        return int(len(position_buffer) / position_stride)

    @property
    def draw_number(self) -> int:
        return self.vertex_count

    @property
    def d3d11GameType(self) -> D3D11GameType:
        return self.d3d11_game_type

    def get_submesh_part_name(self, submesh_model: SubMeshModel) -> str:
        return submesh_model.submesh_name

    def apply_drawib_alias(self):
        '''Read the current DrawIB alias from the workspace and apply it.'''
        alias_name = MMTWorkSpace.get_drawib_aliasname_dict().get(self.draw_ib, "").strip()
        if alias_name:
            self.draw_ib_alias = alias_name

    def get_submesh_unique_key(self, submesh_model: SubMeshModel) -> str:
        return submesh_model.display_str.replace("-", "_")

    def get_submesh_ib_resource_name(self, submesh_model: SubMeshModel) -> str:
        unique_key = self.get_submesh_unique_key(submesh_model)
        if unique_key:
            return "Resource_" + unique_key + "_Index"

        part_name = self.get_submesh_part_name(submesh_model)
        if part_name is not None:
            return "Resource_" + self.draw_ib + "_Component" + part_name

        return ""

    def get_submesh_texture_override_suffix(self, submesh_model: SubMeshModel) -> str:
        unique_key = self.get_submesh_unique_key(submesh_model)
        if unique_key:
            return unique_key

        part_name = self.get_submesh_part_name(submesh_model)
        if part_name is not None:
            return "IB_" + self.draw_ib + "_" + self.draw_ib_alias + "_Component" + part_name

        return ""

    def get_submesh_texture_markup_info_list(self, submesh_model: SubMeshModel) -> list:
        return self.submesh_texturemarkinfolist_dict.get(submesh_model.submesh_name, [])

    @staticmethod
    def _object_texture_resource_slug(text: str, limit: int = 24) -> str:
        '''Turn an arbitrary name into a safe ASCII resource name fragment.

        Kept as a thin wrapper because the exporters and the global slot
        binding call it through the model; the rule itself lives in
        ``common.texture_output_naming`` so the node UI can show the very same
        generated name.
        '''
        return object_resource_slug(text, limit)

    @classmethod
    def resolve_texture_bindings_for_model(cls, model):
        '''Resolve bindings for a game-specific model without assembling buffers.

        WWMI builds geometry independently and never runs our constructor.
        Use a metadata-only adapter so it shares the same binding validation,
        resource naming and copy jobs rather than duplicating those rules.
        The Submesh views must contain the original DrawCallModel instances:
        resolved rows are then visible to the game's INI writer as well.
        '''
        resolver = cls.__new__(cls)
        resolver.draw_ib = model.draw_ib
        resolver.d3d11_game_type = model.d3d11_game_type
        resolver.submesh_model_list = model.submesh_model_list
        resolver.submesh_texturemarkinfolist_dict = model.submesh_texturemarkinfolist_dict
        # Slot resolution initializes both job lists; Hash resolution appends
        # to them. Keep this order even for a model with no Slot bindings.
        resolver.resolve_texture_slot_bindings()
        resolver.resolve_hash_texture_bindings()
        model.object_texture_binding_resource_list = resolver.object_texture_binding_resource_list
        model.object_texture_binding_file_list = resolver.object_texture_binding_file_list
        # The exact-format jobs are owned by the resolver; without copying them
        # the later copy stage would silently skip every conversion for games
        # that build their model through this adapter (WWMI, for example).
        model.exact_texture_jobs = getattr(resolver, "exact_texture_jobs", {})

    def resolve_texture_slot_bindings(self):
        '''Resolve Texture Bind node rows into ready-made INI lines.

        For every DrawCallModel carrying texture_slot_binding_list (collected
        by BluePrintModel when an object passes through a Texture Bind node)
        this builds:
        - resolved_texture_slot_lines: written right before the object's
          drawindexed line, so the replacement only affects that draw;
        - resolved_texture_slot_restore_lines: written right after the draw
          when "Restore After Draw" is on (ref capture + rebind);

        MARK sources reuse the Submesh's existing Slot / SharedSlot resource
        (no new section or file copy). FILE sources get a dedicated resource
        name; the actual copy and the [ResourceXXX] section happen later in
        the export pipeline (M_IniHelper), driven by the two job lists this
        method fills on self.

        Raises ValueError on any invalid row so a typo fails the export
        loudly instead of silently reaching the generated INI.
        '''
        self.object_texture_binding_resource_list = []
        self.object_texture_binding_file_list = []

        # Only GIMI interprets known MARK names as logical API resources.
        is_gimi = getattr(GlobalConfig, "logic_name", "") == "GIMI"
        for submesh in self.submesh_model_list:
            for draw in submesh.drawcall_model_list:
                draw.resolved_gimi_texture_bindings = {}

        binding_owner_list = [
            (submesh_model, draw_model)
            for submesh_model in self.submesh_model_list
            for draw_model in submesh_model.drawcall_model_list
            if getattr(draw_model, "texture_slot_binding_list", None)
        ]
        if not binding_owner_list:
            # This pass owns both per-object line fields, so they are cleared
            # even without bindings. Resolving twice (a repeated export in one
            # session) must not keep appending to the previous result.
            for submesh_model in self.submesh_model_list:
                for draw_model in submesh_model.drawcall_model_list:
                    draw_model.resolved_texture_slot_lines = []
                    draw_model.resolved_texture_slot_restore_lines = []
            return

        print("DrawIBModel: resolving per-object texture slot bindings, DrawIB: " + self.draw_ib)
        if MIMIGlobalProperties.forbid_auto_texture_ini():
            # The global switch only disables the automatic texture pipeline;
            # a Texture Bind node is explicit user intent and still applies.
            print("DrawIBModel: forbid_auto_texture_ini is on, but Slot Texture Bind nodes are explicit user intent; bindings still apply.")

        used_resource_names = set()
        # One FILE resource per unique source path, shared by all objects
        # that picked the same file (same dedupe idea as the hash style).
        file_resource_by_source = {}

        for submesh_model, draw_model in binding_owner_list:
            markup_list = self.get_submesh_texture_markup_info_list(submesh_model)
            before_lines = []
            after_lines = []
            seen_slots = set()

            for binding in draw_model.texture_slot_binding_list:
                if not binding.get("enabled", True):
                    continue
                node_label = str(binding.get("node_label", "") or "Texture Bind")
                owner_name = str(getattr(draw_model, "obj_name", "") or draw_model)
                slot = str(binding.get("slot", "") or "").strip().lower()
                logical_slot = None
                if is_gimi and binding.get("source_type") == "MARK":
                    logical_slot = get_gimi_texture_slot(binding.get("mark_name"))
                if logical_slot:
                    # A GIMI semantic slot is submitted to the game API by name,
                    # so there is no generated file the alias could rename.
                    if normalize_alias_stem(binding.get("output_name", "")):
                        raise ValueError(
                            "Slot Texture Bind node '" + node_label + "': the GIMI texture slot '" + logical_slot
                            + "' of object '" + owner_name + "' is submitted by name and generates no texture file, "
                            + "so it cannot be renamed; clear the texture alias."
                        )
                    # Captured slots and restore flags do not describe the API's
                    # runtime slots. Re-submitting defaults restores next draws.
                    resource = self._resolve_mark_texture_resource(
                        binding, markup_list, node_label, owner_name, submesh_model
                    )
                    previous = draw_model.resolved_gimi_texture_bindings.get(logical_slot)
                    if previous is not None and previous != resource:
                        raise ValueError("GIMI texture slot has conflicting resources: " + logical_slot)
                    draw_model.resolved_gimi_texture_bindings[logical_slot] = resource
                    continue
                if OBJECT_TEXTURE_SLOT_PATTERN.match(slot) is None:
                    raise ValueError(
                        "Slot Texture Bind node '" + node_label + "': invalid texture slot '" + str(binding.get("slot", ""))
                        + "' for object '" + owner_name + "'; expected the form ps-t0."
                    )
                if slot in seen_slots:
                    raise ValueError(
                        "Slot Texture Bind node '" + node_label + "': slot '" + slot + "' is bound twice for object '"
                        + owner_name + "'."
                    )
                seen_slots.add(slot)

                source_type = str(binding.get("source_type", "") or "")
                if source_type == "MARK":
                    if normalize_alias_stem(binding.get("output_name", "")):
                        # A renamed mark binding must own a file, so the mark's
                        # captured image is copied under the alias instead of
                        # sharing the Submesh-wide mark resource.
                        resource_name = self._resolve_mark_alias_resource(
                            binding, markup_list, submesh_model, node_label, owner_name,
                            slot, used_resource_names, file_resource_by_source,
                        )
                    else:
                        resource_name = self._resolve_mark_texture_resource(binding, markup_list, node_label, owner_name, submesh_model)
                elif source_type == "FILE":
                    # A slot row has no mark name, so the slot identifies the
                    # captured original; a missing one keeps the raw copy.
                    source_path = str(binding.get("file_path", "") or "").strip()
                    if source_path:
                        source_path = os.path.normpath(source_path)
                    replacement_plan = self._plan_replacement(
                        source_path, binding, markup_list, submesh_model,
                        slot=slot, node_label=node_label, owner_name=owner_name,
                    )
                    resource_name = self._resolve_file_texture_resource(
                        binding, node_label, owner_name, slot.replace("-", "_"),
                        used_resource_names, file_resource_by_source,
                        replacement_plan=replacement_plan,
                    )
                elif source_type == "RESOURCE":
                    resource_name = str(binding.get("resource_name", "") or "").strip()
                    # An existing resource points at a file this node does not
                    # create, so it has no name of its own that could be changed.
                    self._reject_alias_for_existing_resource(binding, "Slot Texture Bind", node_label, owner_name)
                    if OBJECT_TEXTURE_RESOURCE_PATTERN.match(resource_name) is None:
                        raise ValueError(
                            "Slot Texture Bind node '" + node_label + "': invalid resource name '" + resource_name
                            + "' for object '" + owner_name + "'."
                        )
                    used_resource_names.add(resource_name)
                else:
                    raise ValueError(
                        "Slot Texture Bind node '" + node_label + "': unknown source type '" + source_type
                        + "' for object '" + owner_name + "'."
                    )

                # Connected slots are draw-local regardless of old UI settings.
                # Capture incoming state, then restore after the draw. Reference
                # holders are declared alongside the file-backed resources.
                backup_name = resource_name + "_Bak_" + str(len(before_lines))
                self.object_texture_binding_resource_list.append((backup_name, ''))
                before_lines.append(backup_name + " = ref " + slot)
                before_lines.append(slot + " = " + resource_name)
                after_lines.insert(0, slot + " = " + backup_name)

            draw_model.resolved_texture_slot_lines = before_lines
            draw_model.resolved_texture_slot_restore_lines = after_lines

    def _find_mark_markup(self, binding, markup_list, node_label, owner_name, submesh_model):
        '''Return the Slot / SharedSlot mark a MARK row points at.

        Shared by the plain (shared resource) path and the renamed path, so a
        mark is validated in exactly one place.
        '''
        mark_name = str(binding.get("mark_name", "") or "").strip()
        if not mark_name:
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': mark name is empty for object '" + owner_name + "'."
            )
        matched_markup = None
        for markup_info in markup_list:
            if str(getattr(markup_info, "mark_name", "") or "").strip().lower() == mark_name.lower():
                # GIMI must not silently choose between images for one semantic.
                if getattr(GlobalConfig, "logic_name", "") == "GIMI":
                    if matched_markup is not None and matched_markup.get_resource_name() != markup_info.get_resource_name():
                        raise ValueError("Slot Texture Bind: ambiguous marked texture: " + mark_name)
                matched_markup = markup_info
                if getattr(GlobalConfig, "logic_name", "") != "GIMI":
                    break
        if matched_markup is None:
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': mark '" + mark_name + "' was not found in the texture marks of Submesh '"
                + str(getattr(submesh_model, "submesh_name", "") or "") + "' (object '" + owner_name + "'). Run the SSMT5 texture mark apply first."
            )
        if str(getattr(matched_markup, "mark_type", "") or "") not in ("Slot", "SharedSlot"):
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': mark '" + mark_name + "' uses the Hash style, which is a global texture replacement and needs no per-object binding; mark it as Slot / SharedSlot in SSMT5 instead."
            )
        return matched_markup

    def _resolve_mark_texture_resource(self, binding, markup_list, node_label, owner_name, submesh_model) -> str:
        '''MARK source: reuse the Submesh mark's existing resource name.'''
        return self._find_mark_markup(binding, markup_list, node_label, owner_name, submesh_model).get_resource_name()

    def _resolve_mark_alias_resource(self, binding, markup_list, submesh_model, node_label, owner_name, slot, used_resource_names, file_resource_by_source) -> str:
        '''MARK source with a texture alias: copy the mark under the alias.

        A marked texture is normally a resource shared by every object of the
        Submesh, so it cannot carry a name that belongs to one node row. An
        alias therefore copies the mark's captured image once and binds that
        copy, exactly like an external FILE row would.
        '''
        matched_markup = self._find_mark_markup(binding, markup_list, node_label, owner_name, submesh_model)
        # Imported here on purpose: m_ini_helper imports DrawIBModel for its
        # type hints, so a module-level import would create a cycle.
        from ..common.m_ini_helper import M_IniHelper
        source_path = M_IniHelper._get_slot_texture_source_path(
            draw_ib_model=self,
            part_name=self.get_submesh_part_name(submesh_model),
            texture_markup_info=matched_markup,
        )
        if not source_path or not os.path.exists(source_path):
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': mark '" + str(binding.get("mark_name", "") or "")
                + "' cannot be renamed to '" + str(binding.get("output_name", "") or "")
                + "' because its original texture file was not found in the workspace extract (object '"
                + owner_name + "'); clear the texture alias to keep using the shared mark resource."
            )
        # The format decision runs on the mark's own capture, so a renamed mark
        # keeps exactly the bytes and format the shared mark pipeline produces.
        replacement_plan = self._plan_replacement(
            source_path, binding, markup_list, submesh_model,
            slot=slot,
            mark_name=str(binding.get("mark_name", "") or ""),
            node_label=node_label,
            owner_name=owner_name,
        )
        return self._resolve_file_texture_resource(
            binding, node_label, owner_name, slot.replace("-", "_"),
            used_resource_names, file_resource_by_source,
            source_path_override=source_path,
            replacement_plan=replacement_plan,
        )

    @staticmethod
    def _reject_alias_for_existing_resource(binding, node_title, node_label, owner_name):
        '''An existing [ResourceXXX] row generates no file, so it cannot be renamed.'''
        if not normalize_alias_stem(binding.get("output_name", "")):
            return
        raise ValueError(
            node_title + " node '" + node_label + "': object '" + owner_name + "' reuses an existing resource, "
            + "which generates no texture file to rename; clear the texture alias or select a texture file / mark instead."
        )

    def _exact_job_dict(self):
        """Return the per-DrawIB conversion jobs, creating the dict on demand."""
        # Several tools tests build DrawIBModel with __new__ and never run
        # __post_init__, so the field may be missing on those stand-ins.
        jobs = getattr(self, "exact_texture_jobs", None)
        if not isinstance(jobs, dict):
            jobs = {}
            self.exact_texture_jobs = jobs
        return jobs

    def _resolve_original_candidates(self, markup_list, submesh_model, slot="",
                                     mark_name="", texture_hash=""):
        """Return every original DDS path that can describe one replacement.

        The selectors mirror the export rules:
        - a mark name identifies exactly one mark;
        - a slot can be shared by several marks of the same Submesh;
        - a texture hash is global, so a workspace scan is the fallback.
        """
        # Imported here to avoid the model -> ini helper import cycle.
        from ..common.m_ini_helper import M_IniHelper
        part_name = self.get_submesh_part_name(submesh_model)
        wanted_name = str(mark_name or "").strip().lower()
        wanted_slot = str(slot or "").strip().lower()
        wanted_hash = str(texture_hash or "").strip().lower()
        candidates = []
        for markup in markup_list or []:
            mark = str(getattr(markup, "mark_name", "") or "").strip().lower()
            mark_slot = str(getattr(markup, "mark_slot", "") or "").strip().lower()
            mark_hash = str(getattr(markup, "mark_hash", "") or "").strip().lower()
            # A name is the most specific selector; slot and hash are fallbacks.
            if wanted_name:
                if mark != wanted_name:
                    continue
            elif wanted_slot:
                if mark_slot != wanted_slot:
                    continue
            elif wanted_hash:
                if mark_hash != wanted_hash:
                    continue
            else:
                continue
            path = M_IniHelper._get_slot_texture_source_path(
                draw_ib_model=self,
                part_name=part_name,
                texture_markup_info=markup,
            )
            if path:
                candidates.append(path)
        if not candidates and wanted_hash:
            # A hash row without a local mark still has captures elsewhere in
            # the workspace; the same scan the global node refresh uses.
            try:
                from ..blueprint.blueprint_node_hash_texture import _load_global_hash_mark_entries
                for entry in _load_global_hash_mark_entries():
                    if entry["hash"] == wanted_hash and entry["source_path"]:
                        candidates.append(entry["source_path"])
            except Exception as error:
                print("DrawIBModel: workspace hash scan unavailable: " + str(error))
        return candidates

    def _plan_replacement(self, source_path, binding, markup_list, submesh_model,
                          slot="", mark_name="", texture_hash="",
                          node_label="", owner_name=""):
        """Decide whether one replacement must be converted to the capture format.

        The returned dict is the single contract shared by the slot resolver,
        the hash resolver and the copy stage:

        - convert: True when a texconv job must run before the file is copied;
        - suffix: generated filename extension (".dds" whenever converting);
        - signature: identity of the target shape, used to dedupe resources;
        - job: dict consumed by ``prepare_replacement_job``;
        - reason/detail: why no conversion happened, for logs and the node UI.
        """
        # Imported lazily so the model layer stays importable without texcomb.
        from ..texcomb.core.dds_match import (
            agree_on_metadata,
            build_conversion_plan,
            describe_format,
            image_dimensions,
            metadata_for_format,
            read_dds_metadata,
        )
        source_suffix = os.path.splitext(source_path)[1].lower()
        plan = {
            "convert": False,
            "suffix": source_suffix,
            "signature": "raw",
            "job": None,
            "reason": "",
            "detail": "",
        }
        if not exact_texture_format_enabled():
            # The global switch restores the historical copy-as-is behaviour.
            plan["reason"] = "disabled"
            return plan

        mode = str(binding.get("format_mode", "auto") or "auto").strip().lower()
        manual_format = str(binding.get("manual_format", "") or "").strip()
        force_original_size = bool(binding.get("force_original_size", False))
        resize_filter = exact_texture_resize_filter()

        candidates = self._resolve_original_candidates(
            markup_list, submesh_model,
            slot=slot, mark_name=mark_name, texture_hash=texture_hash,
        )
        metadata, conflict, agreed_path = agree_on_metadata(candidates)
        if conflict:
            # Two captures disagree about the format. Guessing would produce a
            # plausible but wrong file, so the row keeps its raw copy instead.
            formats = set()
            for path in candidates:
                try:
                    formats.add(describe_format(read_dds_metadata(path)))
                except Exception:
                    continue
            plan["reason"] = "conflict"
            plan["detail"] = ", ".join(sorted(formats))
            print(
                "DrawIBModel: " + node_label + ": original formats disagree for '"
                + owner_name + "' (" + plan["detail"] + "); copying the replacement as-is."
            )
            return plan
        if metadata is None and not (mode == "manual" and manual_format):
            # No usable capture and no manual override: nothing to match.
            plan["reason"] = "missing" if candidates else "unresolved"
            return plan

        try:
            if metadata is not None:
                # Validate now so an unsupported capture fails before the
                # exporter writes buffers instead of halfway through copying.
                build_conversion_plan(source_path, metadata, force_original_size, resize_filter)
                job = {
                    "original_path": agreed_path,
                    "manual_format": "",
                    "force_original_size": force_original_size,
                    "resize_filter": resize_filter,
                }
                # Header style, topology, alpha mode and size policy all decide
                # whether two rows may share one generated resource.
                signature = "exact:" + "|".join(str(value) for value in metadata.storage_key)
                signature += "|" + str(int(force_original_size))
            else:
                width, height = image_dimensions(source_path)
                synthetic = metadata_for_format(manual_format, width, height)
                build_conversion_plan(source_path, synthetic, force_original_size, resize_filter)
                job = {
                    "original_path": "",
                    "manual_format": manual_format,
                    "force_original_size": force_original_size,
                    "resize_filter": resize_filter,
                }
                signature = "manual:" + manual_format + "|" + str(int(force_original_size))
        except ValueError as error:
            plan["reason"] = "unsupported"
            plan["detail"] = str(error)
            print(
                "DrawIBModel: " + node_label + ": cannot convert '" + source_path
                + "' for '" + owner_name + "': " + str(error)
            )
            return plan

        plan["convert"] = True
        plan["suffix"] = ".dds"
        plan["signature"] = signature
        plan["job"] = job
        return plan

    def _resolve_file_texture_resource(self, binding, node_label, owner_name, slug_token, used_resource_names, file_resource_by_source, source_path_override="", target_filename_override="", replacement_plan=None) -> str:
        '''FILE source: build a resource and record its copy job.

        ``source_path_override`` lets the Hash Texture Bind MARK source feed
        a workspace-resolved mark file through the same validation, dedupe
        and copy-job registration as a plain FILE row. ``target_filename_override``
        keeps a marked Hash texture's generated filename stable when an
        external replacement is selected. ``replacement_plan`` carries the
        exact-format decision so this method never re-resolves the original.
        '''
        source_path = str(source_path_override or "").strip() or str(binding.get("file_path", "") or "").strip()
        if not source_path:
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': texture file path is empty for object '" + owner_name + "'."
            )
        file_suffix = os.path.splitext(source_path)[1].lower()
        if file_suffix not in OBJECT_TEXTURE_FILE_SUFFIXES:
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': unsupported texture file '" + source_path
                + "' for object '" + owner_name + "'; use one of " + ", ".join(OBJECT_TEXTURE_FILE_SUFFIXES) + "."
            )
        # A converted replacement is always a DDS resource, whatever the
        # user's source extension was; otherwise the old suffix is kept.
        target_suffix = str((replacement_plan or {}).get("suffix", "") or file_suffix)
        if target_filename_override and os.path.splitext(target_filename_override)[1].lower() != target_suffix:
            raise ValueError(
                "Hash Texture Bind node '" + node_label + "': external file '" + source_path
                + "' cannot replace marked filename '" + target_filename_override
                + "'; the generated resource must end with '" + target_suffix + "'."
            )
        if not os.path.exists(source_path):
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': texture file does not exist: " + source_path
                + " (object '" + owner_name + "')."
            )

        # A texture alias replaces the whole generated stem. The suffix always
        # follows the copied bytes, so a typed extension can never announce the
        # wrong format; the INI is checked for characters it cannot store.
        alias_filename = alias_output_filename_with_suffix(binding.get("output_name", ""), target_suffix)
        if alias_filename:
            ensure_ini_encodable(
                alias_filename,
                "Texture alias '" + str(binding.get("output_name", "") or "") + "' of node '" + node_label + "'",
            )

        source_key = source_path.casefold()
        # Two rows may legitimately reuse one image for two different target
        # formats, so the conversion signature belongs in the dedupe key.
        source_key += "|exact=" + str((replacement_plan or {}).get("signature", "raw"))
        if target_filename_override:
            source_key += "|target=" + str(target_filename_override).casefold()
        if alias_filename:
            # Two rows keep one resource per alias, so an alias shared by two
            # rows of the same image still shares one file.
            source_key += "|alias=" + alias_filename.casefold()
        existing = file_resource_by_source.get(source_key)
        if existing is not None:
            # Same file and same target shape: reuse the same resource.
            return existing

        base_name = file_resource_stem(self.draw_ib, owner_name, slug_token)
        resource_name = base_name
        counter = 2
        while resource_name in used_resource_names:
            resource_name = base_name + "_" + str(counter)
            counter += 1
        used_resource_names.add(resource_name)

        target_filename = alias_filename or str(target_filename_override or "").strip() or (resource_name + target_suffix)
        file_resource_by_source[source_key] = resource_name
        self.object_texture_binding_file_list.append((resource_name, source_path, target_filename))
        self.object_texture_binding_resource_list.append((resource_name, target_filename))
        if (replacement_plan or {}).get("convert"):
            # The copy stage converts before the file lands in the Mod folder.
            self._exact_job_dict()[resource_name] = dict(replacement_plan["job"])
        return resource_name


    @staticmethod
    def _allocate_object_target_filename(base_name, suffix, source_key, target_owner_by_name):
        '''Return a generated texture filename that no other source claimed.

        Two different images must never be copied onto the same file in the
        generated Textures folder: the last copy would silently win and both
        resource sections would reference the wrong picture.
        '''
        candidate = base_name + suffix
        counter = 2
        while candidate in target_owner_by_name and target_owner_by_name[candidate] != source_key:
            candidate = base_name + "_" + str(counter) + suffix
            counter += 1
        target_owner_by_name[candidate] = source_key
        return candidate

    def resolve_hash_texture_bindings(self):
        '''Resolve Hash Texture Bind node rows onto the objects that own them.

        A row that knows the mark's texture slot binds its replacement inside
        the owning object's draw section (the same list the Slot Texture Bind
        node fills), so the replacement applies to that draw call only. The
        object's own switch condition already wraps that line, and an object
        whose state does not match keeps whatever the shared hash section
        binds - the global replacement therefore stays the default.

        A row without a slot (legacy MARK / FILE / RESOURCE rows saved before
        slots were recorded) falls back to the shared
        [TextureOverride_Texture_<hash>_Switch] section that M_IniHelper emits.
        Emitting one section per hash is what keeps 3Dmigoto from reporting a
        duplicate hash override for the same texture.

        FILE sources (and MARK sources, resolved through the workspace extract
        folders) reuse the same copy jobs and resource sections as the slot
        bindings, but keep their own generated filename per object.
        '''
        binding_owner_list = [
            (submesh_model, draw_model)
            for submesh_model in self.submesh_model_list
            for draw_model in submesh_model.drawcall_model_list
            if getattr(draw_model, "hash_texture_binding_list", None)
        ]
        if not binding_owner_list:
            return

        print("DrawIBModel: resolving per-object hash texture bindings, DrawIB: " + self.draw_ib)
        if MIMIGlobalProperties.forbid_auto_texture_ini():
            # Same rule as the slot bindings: explicit node intent wins over
            # the global "no automatic texture" switch.
            print("DrawIBModel: forbid_auto_texture_ini is on, but Hash Texture Bind nodes are explicit user intent; bindings still apply.")

        used_resource_names = set()
        file_resource_by_source = {}
        # Generated filename -> source key, shared by every object of this
        # DrawIB so equal images reuse one file and different images do not.
        target_owner_by_name = {}

        for submesh_model, draw_model in binding_owner_list:
            markup_list = self.get_submesh_texture_markup_info_list(submesh_model)
            condition_str = str(draw_model.get_condition_str() or "").strip()
            owner_name = str(getattr(draw_model, "obj_name", "") or draw_model)
            resolved_rows = []
            slot_rows = []
            seen_hashes = set()
            bound_slots = set()
            slot_lines = list(getattr(draw_model, "resolved_texture_slot_lines", None) or [])

            for binding in draw_model.hash_texture_binding_list:
                if not binding.get("enabled", True):
                    continue
                node_label = str(binding.get("node_label", "") or "Hash Texture Bind")
                texture_hash = str(binding.get("texture_hash", "") or "").strip().lower()
                if OBJECT_TEXTURE_HASH_PATTERN.match(texture_hash) is None:
                    raise ValueError(
                        "Hash Texture Bind node '" + node_label + "': invalid texture hash '" + str(binding.get("texture_hash", ""))
                        + "' for object '" + owner_name + "'; expected 8 hexadecimal characters (a 32-bit texture hash)."
                    )
                if texture_hash in seen_hashes:
                    raise ValueError(
                        "Hash Texture Bind node '" + node_label + "': texture hash '" + texture_hash + "' is bound twice for object '"
                        + owner_name + "'."
                    )
                seen_hashes.add(texture_hash)

                # A cleared or disabled row means "no local replacement": the
                # object keeps the global replacement, so nothing is bound and
                # the object specific file is simply left unused.
                if binding.get("restore_original", False) and str(binding.get("mark_slot", "") or "").strip():
                    continue

                source_type = str(binding.get("source_type", "") or "")
                source_path = ""
                if source_type == "MARK":
                    # Resolve the Hash-style mark's source file, then manage the
                    # copy and resource ourselves so the binding stays self
                    # contained even when the automatic hash pipeline is skipped
                    # for this managed hash.
                    source_path = self._resolve_hash_mark_source_path(
                        binding, markup_list, node_label, owner_name, submesh_model,
                    )
                elif source_type == "FILE":
                    source_path = str(binding.get("file_path", "") or "").strip()
                elif source_type != "RESOURCE":
                    raise ValueError(
                        "Hash Texture Bind node '" + node_label + "': unknown source type '" + source_type
                        + "' for object '" + owner_name + "'."
                    )

                mark_slot = str(binding.get("mark_slot", "") or "").strip().lower()
                if mark_slot and OBJECT_TEXTURE_SLOT_PATTERN.match(mark_slot) is None:
                    raise ValueError(
                        "Hash Texture Bind node '" + node_label + "': invalid mark slot '" + mark_slot
                        + "' for object '" + owner_name + "'; expected the form ps-t0."
                    )
                if not mark_slot and not binding.get('legacy_slotless', False):
                    # Hash conditions cannot isolate two draws in the same state.
                    # Strict connected nodes therefore require a captured slot.
                    raise ValueError("Hash Texture Bind: no resolvable slot for " + texture_hash
                                     + "; refresh a slotted mark or explicitly enable Legacy slotless Hash.")
                if mark_slot:
                    # The dedicated Slot Texture Bind node is more specific
                    # than a hash replacement, so the conflict is reported
                    # instead of silently picking one of the two.
                    slot_owner_slots = {
                        str(row.get("slot", "") or "").strip().lower()
                        for row in (getattr(draw_model, "texture_slot_binding_list", None) or [])
                        if row.get("enabled", True)
                    }
                    if mark_slot in slot_owner_slots:
                        raise ValueError(
                            "Hash Texture Bind node '" + node_label + "': slot '" + mark_slot + "' of object '" + owner_name
                            + "' is already bound by a Slot Texture Bind node; remove one of the two bindings."
                        )
                    if mark_slot in bound_slots:
                        raise ValueError(
                            "Hash Texture Bind node '" + node_label + "': slot '" + mark_slot + "' is bound twice for object '"
                            + owner_name + "'; keep one hash replacement per slot."
                        )
                    bound_slots.add(mark_slot)

                # The exact-format decision must happen before the target name
                # is allocated: a converted replacement is always a .dds file.
                replacement_plan = None
                if source_type in ("MARK", "FILE"):
                    replacement_plan = self._plan_replacement(
                        source_path, binding, markup_list, submesh_model,
                        slot=mark_slot,
                        mark_name=str(binding.get("mark_name", "") or ""),
                        texture_hash=texture_hash,
                        node_label=node_label,
                        owner_name=owner_name,
                    )

                target_filename_override = ""
                if mark_slot:
                    # Object scoped copies need their own filename: the global
                    # row owns "<hash>_<role>.dds" and both used to share it,
                    # so one replacement silently overwrote the other. The
                    # allocator keeps one file per distinct image, so every
                    # object that picked the same image reuses one resource.
                    role = normalize_texture_role(binding.get("mark_name", "") or mark_slot)
                    suffix = (replacement_plan or {}).get("suffix", "") or os.path.splitext(source_path)[1].lower()
                    # Shared with the node UI, so the displayed name is the
                    # name this branch really writes.
                    base_name = hash_output_stem(
                        texture_hash, role, self.draw_ib, object_scoped=True,
                    )
                    source_key = source_path.casefold() if source_path else ""
                    target_filename_override = self._allocate_object_target_filename(
                        base_name=base_name,
                        suffix=suffix,
                        source_key=source_key,
                        target_owner_by_name=target_owner_by_name,
                    )
                elif binding.get("preserve_mark_filename", False):
                    # Legacy scanned section row keeps the familiar name.
                    if not condition_str:
                        suffix = (replacement_plan or {}).get("suffix", "") or os.path.splitext(binding.get("file_path", ""))[1].lower()
                        role = normalize_texture_role(binding.get("mark_name", ""))
                        # Same stem helper as the node UI preview.
                        target_filename_override = hash_output_stem(texture_hash, role) + suffix
                    # Conditional states need distinct resources/files. Sharing
                    # the marked basename would make the last copied image win
                    # regardless of the active switch state.
                elif source_type in ("MARK", "FILE") and str(binding.get("mark_name", "") or "").strip():
                    # A selected Hash Source Mark identifies the generated
                    # filename that the user expects to see in Textures. Keep
                    # that name even when the replacement bytes come from an
                    # external file.
                    matched_markup = self._find_hash_mark_markup(
                        binding, markup_list, node_label, owner_name, submesh_model,
                    )
                    target_filename_override = self._get_hash_mark_filename(matched_markup)

                if source_type == "RESOURCE":
                    resource_name = str(binding.get("resource_name", "") or "").strip()
                    # Same rule as the slot bindings: an existing resource owns
                    # no generated file, so an alias has nothing to rename.
                    self._reject_alias_for_existing_resource(binding, "Hash Texture Bind", node_label, owner_name)
                    if OBJECT_TEXTURE_RESOURCE_PATTERN.match(resource_name) is None:
                        raise ValueError(
                            "Hash Texture Bind node '" + node_label + "': invalid resource name '" + resource_name
                            + "' for object '" + owner_name + "'."
                        )
                    used_resource_names.add(resource_name)
                else:
                    resource_name = self._resolve_file_texture_resource(
                        binding, node_label, owner_name, "hash" + texture_hash[:8],
                        used_resource_names, file_resource_by_source,
                        source_path_override=source_path,
                        target_filename_override=target_filename_override,
                        replacement_plan=replacement_plan,
                    )

                if mark_slot:
                    # Bind inside this object's draw section instead of
                    # replacing the texture hash for every object in the game.
                    # Capture the incoming binding before the connected override.
                    # Always restore it so unrelated subsequent draws cannot leak.
                    backup = resource_name + '_LocalBackup'
                    self.object_texture_binding_resource_list.append((backup, ''))
                    slot_lines.append(backup + ' = ref ' + mark_slot)
                    slot_lines.append(mark_slot + " = " + resource_name)
                    restores = getattr(draw_model, 'resolved_texture_slot_restore_lines', [])
                    restores.insert(0, mark_slot + ' = ' + backup)
                    draw_model.resolved_texture_slot_restore_lines = restores
                    slot_rows.append({
                        "texture_hash": texture_hash,
                        "slot": mark_slot,
                        "resource_name": resource_name,
                    })
                    continue

                # An unconditional cleared row only restores the output file.
                # A switch branch instead binds its original image in that
                # state, so other branches can still use replacement images.
                if binding.get("restore_original", False) and not condition_str:
                    continue
                resolved_rows.append({
                    "texture_hash": texture_hash,
                    "condition_str": condition_str,
                    "resource_name": resource_name,
                })

            draw_model.resolved_texture_slot_lines = slot_lines
            draw_model.resolved_hash_texture_binding_list = resolved_rows
            draw_model.resolved_hash_slot_binding_list = slot_rows

    def _find_hash_mark_markup(self, binding, markup_list, node_label, owner_name, submesh_model):
        '''Find the selected Hash mark and validate its style.'''
        mark_name = str(binding.get("mark_name", "") or "").strip()
        if not mark_name:
            raise ValueError(
                "Hash Texture Bind node '" + node_label + "': mark name is empty for object '" + owner_name + "'."
            )
        for markup_info in markup_list:
            if str(getattr(markup_info, "mark_name", "") or "").strip().lower() != mark_name.lower():
                continue
            if str(getattr(markup_info, "mark_type", "") or "") != "Hash":
                raise ValueError(
                    "Hash Texture Bind node '" + node_label + "': mark '" + mark_name + "' uses the " + str(getattr(markup_info, "mark_type", "") or "")
                    + " style; the Hash Texture Bind node only accepts Hash-style marks (Slot / SharedSlot marks belong to the Slot Texture Bind node)."
                )
            return markup_info
        raise ValueError(
            "Hash Texture Bind node '" + node_label + "': mark '" + mark_name + "' was not found in the texture marks of Submesh '"
            + str(getattr(submesh_model, "submesh_name", "") or "") + "' (object '" + owner_name + "'). Run the SSMT5 texture mark apply first."
        )

    @staticmethod
    def _get_hash_mark_filename(markup_info) -> str:
        '''Return the automatic Hash-style filename for one marked texture.'''
        get_filename = getattr(markup_info, "get_hash_style_filename", None)
        if callable(get_filename):
            return str(get_filename() or "").strip()
        mark_hash = str(getattr(markup_info, "mark_hash", "") or "").strip()
        mark_name = str(getattr(markup_info, "mark_name", "") or "").strip()
        return mark_hash + "_" + mark_name + ".dds" if mark_hash and mark_name else ""

    def _resolve_hash_mark_source_path(self, binding, markup_list, node_label, owner_name, submesh_model) -> str:
        '''MARK source of a hash binding: locate the mark's texture file.'''
        matched_markup = self._find_hash_mark_markup(
            binding, markup_list, node_label, owner_name, submesh_model,
        )
        mark_name = str(binding.get("mark_name", "") or "").strip()
        # Imported here on purpose: m_ini_helper imports DrawIBModel for its
        # type hints, so a module-level import would create a cycle. At call
        # time every module is fully loaded, making this safe.
        from ..common.m_ini_helper import M_IniHelper
        source_path = M_IniHelper._get_slot_texture_source_path(
            draw_ib_model=self,
            part_name=self.get_submesh_part_name(submesh_model),
            texture_markup_info=matched_markup,
        )
        if not source_path or not os.path.exists(source_path):
            raise ValueError(
                "Hash Texture Bind node '" + node_label + "': source file of mark '" + mark_name + "' was not found in the workspace (object '"
                + owner_name + "')."
            )
        return source_path

    def get_lod_name(self) -> str:
        """Return the LOD name shared by the Submeshes of this DrawIB ('' when none).

        Submesh names carry the LOD prefix (e.g. 'LOD0.94517393-0'), so the
        prefix is read from the first Submesh. Category buffers are exported
        once per DrawIB and get the same prefix so files of different LODs
        never collide.
        """
        for submesh_model in self.submesh_model_list:
            submesh_name = str(getattr(submesh_model, "submesh_name", "") or "").strip()
            if submesh_name.upper().startswith("LOD") and "." in submesh_name:
                lod_name = submesh_name.split(".", 1)[0]
                if lod_name[3:].isdigit():
                    return lod_name
        return ""

    def get_category_buffer_filename(self, category: str) -> str:
        """Return the exported CategoryBuffer file name for this DrawIB.

        Mirrors the IB naming ('<display_str>-Index.buf'): when the DrawIB
        belongs to an LOD, the LOD prefix is added in front of the DrawIB,
        e.g. 'LOD0.94517393-Position.buf'.
        """
        lod_name = self.get_lod_name()
        prefix = lod_name + "." if lod_name else ""
        return f"{prefix}{self.draw_ib}-{category}.buf"

    def generate_buffer_files(self, output_folder: str):
        for submesh_model in self.submesh_model_list:
            ib = self.submesh_ib_dict.get(submesh_model.submesh_name, [])
            if ib:
                ib_filename = submesh_model.display_str + "-Index.buf"
                BufferExportHelper.write_buf_ib_r32_uint(ib, os.path.join(output_folder, ib_filename))

        for category, category_buf in self.category_buffer_dict.items():
            category_buf_filename = self.get_category_buffer_filename(category)
            filepath = os.path.join(output_folder, category_buf_filename)
            with open(filepath, 'wb') as f:
                category_buf.tofile(f)

        for shapekey_name, shapekey_buf in self.shapekey_name_bytelist_dict.items():
            shapekey_buf_filename = self.draw_ib + "-Position." + shapekey_name + ".buf"
            filepath = os.path.join(output_folder, shapekey_buf_filename)
            with open(filepath, 'wb') as f:
                shapekey_buf.tofile(f)

        # Time Position Switch: one full-size Position buffer per frame.
        self.write_time_position_files(output_folder)

    def get_time_position_buffer_filename(self, var_name: str, frame_value: int) -> str:
        """Return the side-buffer file name of one Time Position Switch frame.

        Uses the same LOD prefix rule as the category buffers, so frames of
        different LODs of the same DrawIB never overwrite each other.
        """
        lod_name = self.get_lod_name()
        prefix = lod_name + "." if lod_name else ""
        # Keep animation files outside the Position.<shape-name> namespace.
        # A user shape named dyntime0_0 must not overwrite an animation frame.
        return f"{prefix}{self.draw_ib}-position_timeframe.{var_name}_{frame_value}.buf"

    @staticmethod
    def get_time_position_resource_name(draw_ib: str, var_name: str, frame_value: int) -> str:
        """Return the 3Dmigoto resource name holding one frame's positions.

        Resource names carry no LOD prefix, mirroring the existing
        [Resource<draw_ib><Category>] declarations of the slot-style games.
        """
        # Resources also have a distinct prefix to avoid shape-name collisions.
        return "Resource" + draw_ib + "PositionTimeFrame." + var_name + "_" + str(frame_value)

    def _compute_time_pos_frame_position_bytes(self, frame_model, base_submesh) -> numpy.ndarray:
        """Run the standard single-object export pipeline for one frame
        object and return its Position category bytes.

        A throwaway SubMeshModel reuses the exact same conversion, weight
        normalization, rotation and vertex ordering code as the base object,
        so frame bytes land in the identical export order.  A fresh
        DrawCallModel is used so the frame model itself is never mutated.
        """
        from .draw_call_model import DrawCallModel

        temp_draw_call = DrawCallModel(
            obj_name=frame_model.obj_name,
            submesh_name=frame_model.submesh_name,
        )
        temp_submesh_model = SubMeshModel(drawcall_model_list=[temp_draw_call])
        position_buffer = temp_submesh_model.category_buffer_dict.get("Position")
        if position_buffer is None or len(position_buffer) == 0:
            raise ValueError(
                "Position.buf Based Dynamic Mod: frame object '" + str(frame_model.obj_name)
                + "' produced no Position data; is it a valid mesh?"
            )
        # Equal byte counts do not prove compatible vertex ordering. Welding,
        # triangulation and UV seams can reorder or split the exported vertices
        # without changing the final count. Compare the actual exported mapping.
        if (not numpy.array_equal(temp_submesh_model.ib, base_submesh.ib)
                or temp_submesh_model.index_vertex_id_dict != base_submesh.index_vertex_id_dict):
            raise ValueError("Position.buf Based Dynamic Mod: exported topology/order differs for " + frame_model.obj_name)
        # Only Position is replaced at runtime. Any other animated category
        # would silently retain base values (normals, UVs, weights, etc.).
        # Require DrawIndexed switching for those animations rather than export
        # a visually incorrect or incorrectly skinned position-only sequence.
        for category, base_bytes in base_submesh.category_buffer_dict.items():
            if category == "Position":
                continue
            if not numpy.array_equal(temp_submesh_model.category_buffer_dict.get(category), base_bytes):
                raise ValueError(
                    "Position.buf Based Dynamic Mod: frame '" + frame_model.obj_name + "' changes " + category
                    + "; use the DrawIndex Based Dynamic Mod node for non-Position animation"
                )
        return position_buffer

    def write_time_position_files(self, output_folder: str):
        """Write one full-DrawIB-size Position buffer per (timeline, frame).

        Public because not every exporter routes buffer writing through
        generate_buffer_files() (SRMI writes its buffers itself); those
        exporters call this method directly after their own buffer writes.

        D3D11's BaseVertexLocation applies to every bound vertex buffer, so a
        frame cannot be a submesh-only buffer: the frame buffer is a copy of
        the base Position buffer with the animated submesh slice replaced by
        the frame object's positions.  Submeshes without a frame keep their
        base positions byte for byte.
        """
        if not self.time_pos_frame_groups:
            return
        if self.d3d11_game_type is None:
            raise ValueError(
                "Position.buf Based Dynamic Mod: DrawIB " + str(self.draw_ib)
                + " has no game type; cannot export position frames"
            )
        # GPU pre-skinning support depends on WHERE the skinning compute
        # reads its positions from:
        # - Unity CS path (Naraka, NarakaM, AILIMIT, PGR) and ZZMIDX12 re-read
        #   "cs-t0 = Resource<drawib>Position" at every dispatch, so a
        #   per-frame copy into that resource flows through skinning fine.
        # - SRMI/ZZMI route skinned draws through an extra PositionCS
        #   indirection that this feature does not feed yet, so block them
        #   loudly instead of silently exporting a static mod.
        if getattr(self.d3d11_game_type, "GPU_PreSkinning", False):
            from ..common.global_config import LogicName
            supported_preskinning_logics = (
                LogicName.Naraka, LogicName.NarakaM, LogicName.AILIMIT, LogicName.ZZMIDX12,
                # PGR copies the Naraka compute pipeline, so the same
                # per-frame resource copy reaches its skinning dispatch.
                LogicName.PGR,
            )
            if GlobalConfig.logic_name not in supported_preskinning_logics:
                raise ValueError(
                    "Position.buf Based Dynamic Mod is not supported for the GPU pre-skinning data type of DrawIB "
                    + str(self.draw_ib) + " under the current game preset"
                    + "; use the DrawIndex Based Dynamic Mod node (whole-mesh switching) instead"
                )

        position_stride = self.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        if position_stride <= 0:
            raise ValueError(
                "Position.buf Based Dynamic Mod: DrawIB " + str(self.draw_ib)
                + " has no Position category; cannot export position frames"
            )
        base_position_buffer = self.category_buffer_dict.get("Position")
        if base_position_buffer is None:
            raise ValueError(
                "Position.buf Based Dynamic Mod: DrawIB " + str(self.draw_ib)
                + " has no base Position buffer; connect the base object normally"
            )

        submesh_by_name = {
            submesh_model.submesh_name: submesh_model
            for submesh_model in self.submesh_model_list
        }

        for key_name, value_frame_dict in self.time_pos_frame_groups.items():
            safe_var_name = key_name.lstrip("$")
            for frame_value, frame_model_list in sorted(value_frame_dict.items()):
                frame_buffer = base_position_buffer.copy()
                for frame_model in frame_model_list:
                    submesh_model = submesh_by_name.get(frame_model.match_submesh_name)
                    if submesh_model is None:
                        raise ValueError(
                            "Position.buf Based Dynamic Mod: no base draw call found for submesh '"
                            + str(frame_model.match_submesh_name)
                            + "' of frame object '" + str(frame_model.obj_name)
                            + "'; connect the base object of this submesh to the output node normally"
                        )
                    if len(submesh_model.drawcall_model_list) != 1:
                        raise ValueError(
                            "Position.buf Based Dynamic Mod: submesh '" + str(submesh_model.submesh_name)
                            + "' has " + str(len(submesh_model.drawcall_model_list))
                            + " base objects; a position frame replaces the whole submesh, "
                            + "so exactly one base object per animated submesh is required"
                        )
                    frame_position_bytes = self._compute_time_pos_frame_position_bytes(frame_model, submesh_model)
                    vertex_base = self.submesh_vertex_base_dict.get(submesh_model.submesh_name, 0)
                    byte_start = vertex_base * position_stride
                    expected_len = self._get_exported_vertex_count(submesh_model) * position_stride
                    if len(frame_position_bytes) != expected_len:
                        raise ValueError(
                            "Position.buf Based Dynamic Mod: frame object '" + str(frame_model.obj_name)
                            + "' exported " + str(len(frame_position_bytes))
                            + " Position bytes but the base submesh '" + str(submesh_model.submesh_name)
                            + "' expects " + str(expected_len)
                            + "; every frame must keep the exact same topology as the base object"
                        )
                    frame_buffer[byte_start:byte_start + expected_len] = frame_position_bytes

                buffer_filename = self.get_time_position_buffer_filename(safe_var_name, frame_value)
                filepath = os.path.join(output_folder, buffer_filename)
                with open(filepath, 'wb') as f:
                    frame_buffer.tofile(f)

    @property
    def part_name_submesh_dict(self) -> dict:
        mapping = {}
        for submesh_model in self.submesh_model_list:
            mapping[submesh_model.submesh_name] = submesh_model
        return mapping

