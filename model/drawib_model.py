
from dataclasses import field, dataclass
import os
import re

from ..common.d3d11_gametype import D3D11GameType
from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.texture_naming import normalize_texture_role

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
OBJECT_TEXTURE_FILE_SUFFIXES = (".dds", ".png", ".jpg", ".jpeg", ".bmp", ".tga")

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
                obj_name_draw_offset[draw_call_model.obj_name] = submesh_index_offset + draw_call_model.index_offset

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
        '''Turn an arbitrary name into a safe ASCII resource name fragment.'''
        slug = re.sub(r"[^A-Za-z0-9_]", "_", str(text or ""))
        slug = re.sub(r"_+", "_", slug).strip("_")
        return (slug or "obj")[:limit]

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

        binding_owner_list = [
            (submesh_model, draw_model)
            for submesh_model in self.submesh_model_list
            for draw_model in submesh_model.drawcall_model_list
            if getattr(draw_model, "texture_slot_binding_list", None)
        ]
        if not binding_owner_list:
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
                    resource_name = self._resolve_mark_texture_resource(binding, markup_list, node_label, owner_name, submesh_model)
                elif source_type == "FILE":
                    resource_name = self._resolve_file_texture_resource(
                        binding, node_label, owner_name, slot.replace("-", "_"),
                        used_resource_names, file_resource_by_source,
                    )
                elif source_type == "RESOURCE":
                    resource_name = str(binding.get("resource_name", "") or "").strip()
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

                if binding.get("restore_after_draw", False):
                    # Capture the currently bound texture before replacing
                    # it, then rebind the original after the draw. The ref
                    # keyword is the same backup trick used for the SnowBreak
                    # index buffer; verify on the target game before shipping.
                    backup_name = resource_name + "_Bak_" + str(len(before_lines))
                    before_lines.append(backup_name + " = ref " + slot)
                    before_lines.append(slot + " = " + resource_name)
                    after_lines.append(slot + " = " + backup_name)
                else:
                    before_lines.append(slot + " = " + resource_name)

            draw_model.resolved_texture_slot_lines = before_lines
            draw_model.resolved_texture_slot_restore_lines = after_lines

    def _resolve_mark_texture_resource(self, binding, markup_list, node_label, owner_name, submesh_model) -> str:
        '''MARK source: reuse the Submesh mark's existing resource name.'''
        mark_name = str(binding.get("mark_name", "") or "").strip()
        if not mark_name:
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': mark name is empty for object '" + owner_name + "'."
            )
        matched_markup = None
        for markup_info in markup_list:
            if str(getattr(markup_info, "mark_name", "") or "").strip().lower() == mark_name.lower():
                matched_markup = markup_info
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
        return matched_markup.get_resource_name()

    def _resolve_file_texture_resource(self, binding, node_label, owner_name, slug_token, used_resource_names, file_resource_by_source, source_path_override="", target_filename_override="") -> str:
        '''FILE source: build a resource and record its copy job.

        ``source_path_override`` lets the Hash Texture Bind MARK source feed
        a workspace-resolved mark file through the same validation, dedupe
        and copy-job registration as a plain FILE row. ``target_filename_override``
        keeps a marked Hash texture's generated filename stable when an
        external replacement is selected.
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
        if target_filename_override and file_suffix != os.path.splitext(target_filename_override)[1].lower():
            raise ValueError(
                "Hash Texture Bind node '" + node_label + "': external file '" + source_path
                + "' cannot replace marked filename '" + target_filename_override
                + "' because the file formats differ. Use a DDS source for a marked Hash texture."
            )
        if not os.path.exists(source_path):
            raise ValueError(
                "Slot Texture Bind node '" + node_label + "': texture file does not exist: " + source_path
                + " (object '" + owner_name + "')."
            )

        source_key = source_path.casefold()
        if target_filename_override:
            source_key += "|target=" + str(target_filename_override).casefold()
        existing = file_resource_by_source.get(source_key)
        if existing is not None:
            # Same file picked by another object: reuse the same resource.
            return existing

        base_name = (
            "ResourceTex_"
            + self._object_texture_resource_slug(self.draw_ib, 16)
            + "_"
            + self._object_texture_resource_slug(owner_name, 24)
            + "_"
            + slug_token
        )
        resource_name = base_name
        counter = 2
        while resource_name in used_resource_names:
            resource_name = base_name + "_" + str(counter)
            counter += 1
        used_resource_names.add(resource_name)

        target_filename = str(target_filename_override or "").strip() or (resource_name + file_suffix)
        file_resource_by_source[source_key] = resource_name
        self.object_texture_binding_file_list.append((resource_name, source_path, target_filename))
        self.object_texture_binding_resource_list.append((resource_name, target_filename))
        return resource_name

    def resolve_hash_texture_bindings(self):
        '''Resolve Hash Texture Bind node rows for the conditional this= sections.

        Each resolved row carries the object's switch condition (captured via
        get_condition_str, so Switch Key and Time Switch states both work)
        plus the resource name to bind. The actual
        [TextureOverride_Texture_<hash>_Switch] sections are emitted once per
        hash for the whole blueprint by M_IniHelper, because hash overrides
        are global: they apply wherever the game binds the hash.

        FILE sources (and MARK sources, resolved through the workspace
        extract folders) reuse the same copy jobs and resource sections as
        the slot bindings. When a Hash Source Mark is selected, the copy job
        retains that mark's automatic ``<mark_hash>_<mark_name>.dds`` name.
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

        for submesh_model, draw_model in binding_owner_list:
            markup_list = self.get_submesh_texture_markup_info_list(submesh_model)
            condition_str = str(draw_model.get_condition_str() or "").strip()
            owner_name = str(getattr(draw_model, "obj_name", "") or draw_model)
            resolved_rows = []
            seen_hashes = set()

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

                source_type = str(binding.get("source_type", "") or "")
                target_filename_override = ""
                if binding.get("preserve_mark_filename", False):
                    # Scanned rows already identify a mark from the connected
                    # scope. Do not resolve the name again on every passing
                    # object: another Submesh may use the same name/hash.
                    if not condition_str:
                        suffix = os.path.splitext(binding.get("file_path", ""))[1].lower()
                        role = normalize_texture_role(binding.get("mark_name", ""))
                        target_filename_override = texture_hash + "_" + role + suffix
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

                if source_type == "MARK":
                    # Resolve the Hash-style mark's source file, then manage
                    # the copy and resource ourselves so the binding stays
                    # self-contained even when the automatic hash pipeline
                    # is skipped for this managed hash.
                    source_path = self._resolve_hash_mark_source_path(binding, markup_list, node_label, owner_name, submesh_model)
                    resource_name = self._resolve_file_texture_resource(
                        binding, node_label, owner_name, "hash" + texture_hash[:8],
                        used_resource_names, file_resource_by_source,
                        source_path_override=source_path,
                        target_filename_override=target_filename_override,
                    )
                elif source_type == "FILE":
                    resource_name = self._resolve_file_texture_resource(
                        binding, node_label, owner_name, "hash" + texture_hash[:8],
                        used_resource_names, file_resource_by_source,
                        target_filename_override=target_filename_override,
                    )
                elif source_type == "RESOURCE":
                    resource_name = str(binding.get("resource_name", "") or "").strip()
                    if OBJECT_TEXTURE_RESOURCE_PATTERN.match(resource_name) is None:
                        raise ValueError(
                            "Hash Texture Bind node '" + node_label + "': invalid resource name '" + resource_name
                            + "' for object '" + owner_name + "'."
                        )
                    used_resource_names.add(resource_name)
                else:
                    raise ValueError(
                        "Hash Texture Bind node '" + node_label + "': unknown source type '" + source_type
                        + "' for object '" + owner_name + "'."
                    )

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

            draw_model.resolved_hash_texture_binding_list = resolved_rows

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
        # - Unity CS path (Naraka, NarakaM, AILIMIT) and ZZMIDX12 re-read
        #   "cs-t0 = Resource<drawib>Position" at every dispatch, so a
        #   per-frame copy into that resource flows through skinning fine.
        # - SRMI/ZZMI route skinned draws through an extra PositionCS
        #   indirection that this feature does not feed yet, so block them
        #   loudly instead of silently exporting a static mod.
        if getattr(self.d3d11_game_type, "GPU_PreSkinning", False):
            from ..common.global_config import LogicName
            supported_preskinning_logics = (
                LogicName.Naraka, LogicName.NarakaM, LogicName.AILIMIT, LogicName.ZZMIDX12,
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

