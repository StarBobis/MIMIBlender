import filecmp
import os
import re
import shutil

from .m_ini_builder import *
from .m_control_flow import M_ControlFlow
from .m_key import M_Key
from .texture_naming import default_texture_resource_name, normalize_texture_role
from .texture_output_naming import (
    TextureOutputNameClaims,
    alias_output_filename_with_suffix,
    ensure_ini_encodable,
    normalize_alias_stem,
)
from ..model.draw_call_model import DrawCallModel
from ..model.drawib_model import DrawIBModel
from ..utils.json_utils import JsonUtils
from ..utils.format_utils import Fatal
from .global_config import GlobalConfig
from .mimi_global_properties import MIMIGlobalProperties
from ..workspace.mmt_workspace import MMTWorkSpace
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..workspace.texture_metadata_helper import TextureMetadataResolver, TextureMarkUpInfo

# These are the only direct image formats accepted by the resource writers.
_GLOBAL_HASH_FILE_SUFFIXES = (".dds", ".png", ".jpg", ".jpeg", ".bmp", ".tga")
_GLOBAL_HASH_PATTERN = re.compile(r"^[0-9a-f]{8}$")
_GLOBAL_RESOURCE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _exact_format_enabled():
    """Return the global exact-format switch, tolerating lightweight stubs.

    Several INI tests replace MIMIGlobalProperties with a minimal stand-in,
    so a missing method must mean "enabled" rather than an AttributeError.
    """
    getter = getattr(MIMIGlobalProperties, "exact_texture_format_enabled", None)
    try:
        return bool(getter()) if callable(getter) else True
    except Exception:
        return True


class M_IniHelper:
    @staticmethod
    def _count_marked_textures(draw_ib_model: DrawIBModel, mark_type: str | None = None) -> int:
        count = 0
        for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
            texture_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
            for texture_info in texture_info_list:
                if mark_type is not None and getattr(texture_info, "mark_type", "") != mark_type:
                    continue
                count += 1
        return count

    @staticmethod
    def _get_extract_gametype_folder_path(draw_ib_model: DrawIBModel) -> str:
        primary_submesh_metadata = getattr(draw_ib_model, "primary_submesh_metadata", None)
        if primary_submesh_metadata is not None:
            extract_gametype_folder_path = getattr(primary_submesh_metadata, "extract_gametype_folder_path", "")
            if extract_gametype_folder_path:
                return extract_gametype_folder_path

        submesh_model_list = getattr(draw_ib_model, "submesh_model_list", [])
        if submesh_model_list:
            first_submesh_model = submesh_model_list[0]
            submesh_name = getattr(first_submesh_model, "submesh_name", "")
            d3d11_game_type = getattr(first_submesh_model, "d3d11_game_type", None)
            if submesh_name and d3d11_game_type is not None:
                return os.path.join(
                    MMTWorkSpace.get_submesh_folder_path(submesh_name),
                    "TYPE_" + d3d11_game_type.GameTypeName,
                    "",
                )

        d3d11_game_type = getattr(draw_ib_model, "d3d11_game_type", None)
        if d3d11_game_type is None:
            return ""

        return GlobalConfig.path_extract_gametype_folder(
            draw_ib=draw_ib_model.draw_ib,
            gametype_name=d3d11_game_type.GameTypeName,
        )

    @staticmethod
    def _get_part_extract_gametype_folder_path(draw_ib_model: DrawIBModel, part_name: str) -> str:
        part_name_submesh_dict = getattr(draw_ib_model, "part_name_submesh_dict", {})
        submesh_model = part_name_submesh_dict.get(part_name)
        if submesh_model is None:
            return ""

        d3d11_game_type = getattr(submesh_model, "d3d11_game_type", None)
        if d3d11_game_type is None:
            d3d11_game_type = getattr(draw_ib_model, "d3d11_game_type", None)
        submesh_name = getattr(submesh_model, "submesh_name", "")
        if d3d11_game_type is None or submesh_name == "":
            return ""

        submesh_folder = MMTWorkSpace.get_submesh_folder_path(submesh_name)
        return os.path.join(submesh_folder, "TYPE_" + d3d11_game_type.GameTypeName, "")

    @classmethod
    def _get_slot_texture_source_path(cls, draw_ib_model: DrawIBModel, part_name: str, texture_markup_info) -> str:
        # Strategy 1: locate precisely via part_name
        extract_gametype_folder_path = cls._get_part_extract_gametype_folder_path(draw_ib_model, part_name)
        if extract_gametype_folder_path:
            source_path = extract_gametype_folder_path + texture_markup_info.mark_filename
            if os.path.exists(source_path):
                return source_path

        # Never resolve another Submesh's similarly named capture as this mark.
        # A precise folder with a missing original is an export error upstream.
        if extract_gametype_folder_path:
            return ''
        for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
            if getattr(submesh_model, 'submesh_name', '') != part_name:
                continue
            d3d11_game_type = getattr(submesh_model, "d3d11_game_type", None)
            if d3d11_game_type is None:
                d3d11_game_type = getattr(draw_ib_model, "d3d11_game_type", None)
            submesh_name = getattr(submesh_model, "submesh_name", "")
            if d3d11_game_type is None or submesh_name == "":
                continue

            candidate_source_path = os.path.join(
                MMTWorkSpace.get_submesh_folder_path(submesh_name),
                "TYPE_" + d3d11_game_type.GameTypeName,
                texture_markup_info.mark_filename,
            )
            if os.path.exists(candidate_source_path):
                return candidate_source_path

        return ""

    @staticmethod
    def _get_part_submesh_folder_name(draw_ib_model: DrawIBModel, part_name: str) -> str:
        part_name_submesh_dict = getattr(draw_ib_model, "part_name_submesh_dict", {})
        submesh_model = part_name_submesh_dict.get(part_name)
        if submesh_model is None:
            print("M_IniHelper: part_name did not match a submesh, DrawIB: " + draw_ib_model.draw_ib + ", Part: " + str(part_name))
            return ""

        submesh_folder_name = getattr(submesh_model, "submesh_name", "")
        print("M_IniHelper: Part " + str(part_name) + " maps to submesh_name: " + submesh_folder_name)
        return submesh_folder_name

    @staticmethod
    def _get_hash_deduped_texture_info(draw_ib_model: DrawIBModel, mark_hash: str):
        for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
            submesh_folder_name = getattr(submesh_model, "submesh_name", "")
            if not submesh_folder_name:
                continue

            hash_deduped_texture_info_dict = MMTWorkSpace.get_hash_deduped_texture_info_dict(submesh_folder_name=submesh_folder_name)
            deduped_texture_info = hash_deduped_texture_info_dict.get(mark_hash, None)
            if deduped_texture_info is not None:
                print(
                    "M_IniHelper: Found hash dedupe info in submesh_name "
                    + submesh_folder_name
                    + ", Hash: "
                    + mark_hash
                )
                return deduped_texture_info

        print("M_IniHelper: No hash dedupe info found in any submesh_name of the current DrawIB, Hash: " + mark_hash)
        return None

    @staticmethod
    def get_drawindexed_str_list(
        ordered_draw_obj_model_list: list[DrawCallModel],
        obj_name_draw_offset_dict: dict[str, int] | None = None,
    ) -> list[str]:
        # Traditional way: called using DrawIndexed
        # Before outputting, group obj_models by condition
        condition_str_obj_model_list_dict:dict[str,list[DrawCallModel]] = {}
        for obj_model in ordered_draw_obj_model_list:
            condition_str = obj_model.get_condition_str()

            obj_model_list = condition_str_obj_model_list_dict.get(condition_str,[])
            
            obj_model_list.append(obj_model)
            condition_str_obj_model_list_dict[condition_str] = obj_model_list
        
        drawindexed_str_list:list[str] = []
        for condition_str, obj_model_list in condition_str_obj_model_list_dict.items():
            if condition_str != "":
                drawindexed_str_list.append("if " + condition_str)
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("  ; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    # Per-object Texture Bind lines go right before this
                    # object's drawindexed (after the submesh level ones).
                    for slot_line in M_ControlFlow.get_object_texture_slot_lines(obj_model):
                        drawindexed_str_list.append("  " + slot_line)
                    draw_line = obj_model.get_drawindexed_str(obj_name_draw_offset_dict)
                    drawindexed_str_list.append("  " + draw_line)
                    for slot_line in M_ControlFlow.get_object_texture_slot_restore_lines(obj_model):
                        drawindexed_str_list.append("  " + slot_line)
                drawindexed_str_list.append("endif")
            else:
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    for slot_line in M_ControlFlow.get_object_texture_slot_lines(obj_model):
                        drawindexed_str_list.append(slot_line)
                    draw_line = obj_model.get_drawindexed_str(obj_name_draw_offset_dict)
                    drawindexed_str_list.append(draw_line)
                    for slot_line in M_ControlFlow.get_object_texture_slot_restore_lines(obj_model):
                        drawindexed_str_list.append(slot_line)
            drawindexed_str_list.append("")

        return drawindexed_str_list

    @staticmethod
    def append_drawindexed_with_slot_lines(
        section,
        ordered_draw_obj_model_list: list[DrawCallModel],
        slot_line_provider,
        obj_name_draw_offset_dict: dict[str, int] | None = None,
    ):
        """Output drawindexed by condition, inserting Slot lines before each drawindexed."""
        M_ControlFlow.append_drawindexed_with_slot_lines(
            section=section,
            ordered_draw_obj_model_list=ordered_draw_obj_model_list,
            slot_line_provider=slot_line_provider,
            obj_name_draw_offset_dict=obj_name_draw_offset_dict,
        )
    
    @staticmethod
    def get_drawindexed_instanced_str_list(
        ordered_draw_obj_model_list: list[DrawCallModel],
        obj_name_draw_offset_dict: dict[str, int] | None = None,
    ) -> list[str]:
        # Called using the DrawIndexedInstanced method
        # Before outputting, group obj_models by condition
        condition_str_obj_model_list_dict:dict[str,list[DrawCallModel]] = {}
        for obj_model in ordered_draw_obj_model_list:
            condition_str = obj_model.get_condition_str()

            obj_model_list = condition_str_obj_model_list_dict.get(condition_str,[])
            
            obj_model_list.append(obj_model)
            condition_str_obj_model_list_dict[condition_str] = obj_model_list
        
        drawindexed_str_list:list[str] = []
        for condition_str, obj_model_list in condition_str_obj_model_list_dict.items():
            if condition_str != "":
                drawindexed_str_list.append("if " + condition_str)
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("  ; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    for slot_line in M_ControlFlow.get_object_texture_slot_lines(obj_model):
                        drawindexed_str_list.append("  " + slot_line)
                    draw_line = obj_model.get_drawindexed_instanced_str(obj_name_draw_offset_dict)
                    drawindexed_str_list.append("  " + draw_line)
                    for slot_line in M_ControlFlow.get_object_texture_slot_restore_lines(obj_model):
                        drawindexed_str_list.append("  " + slot_line)
                drawindexed_str_list.append("endif")
            else:
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    for slot_line in M_ControlFlow.get_object_texture_slot_lines(obj_model):
                        drawindexed_str_list.append(slot_line)
                    draw_line = obj_model.get_drawindexed_instanced_str(obj_name_draw_offset_dict)
                    drawindexed_str_list.append(draw_line)
                    for slot_line in M_ControlFlow.get_object_texture_slot_restore_lines(obj_model):
                        drawindexed_str_list.append(slot_line)
            drawindexed_str_list.append("")

        return drawindexed_str_list

    @staticmethod
    def _collect_hash_binding_managed_hashes(
        drawib_drawibmodel_dict: dict,
        global_hash_texture_binding_list: list | None = None,
    ) -> set:
        '''Every active hash explicitly bound by either hash node variant.'''
        managed_hash_set = set()
        for draw_ib_model in drawib_drawibmodel_dict.values():
            for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
                for draw_model in getattr(submesh_model, "drawcall_model_list", []):
                    for attribute in ("resolved_hash_texture_binding_list", "resolved_hash_slot_binding_list"):
                        for row in getattr(draw_model, attribute, None) or []:
                            managed_hash_set.add(str(row.get("texture_hash", "") or "").strip().lower())

        # Global rows are not attached to a DrawIB, so they need an explicit
        # second collection pass before the automatic hash pipeline runs.
        for row in global_hash_texture_binding_list or []:
            if not row.get("enabled", True) or row.get("restore_original", False):
                continue
            managed_hash_set.add(str(row.get("texture_hash", "") or "").strip().lower())

        managed_hash_set.discard("")
        return managed_hash_set

    @staticmethod
    def _collect_hash_switch_entry_dict(drawib_drawibmodel_dict: dict | None) -> dict:
        '''Object scoped hash rows that could not bind per draw, keyed by hash.

        Rows carrying a texture slot bind inside their object's draw section,
        so they never reach this collection.
        '''
        binding_entry_dict: dict[str, list] = {}
        for draw_ib_model in (drawib_drawibmodel_dict or {}).values():
            for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
                for draw_model in getattr(submesh_model, "drawcall_model_list", []):
                    for row in getattr(draw_model, "resolved_hash_texture_binding_list", None) or []:
                        texture_hash = str(row.get("texture_hash", "") or "").strip().lower()
                        if not texture_hash:
                            continue
                        condition_str = str(row.get("condition_str", "") or "").strip()
                        resource_name = str(row.get("resource_name", "") or "").strip()
                        binding_entry_dict.setdefault(texture_hash, []).append((condition_str, resource_name))
        return binding_entry_dict

    @staticmethod
    def _normalize_hash_switch_entries(texture_hash: str, entry_list: list) -> tuple:
        '''Dedupe switch entries and reject contradictory assignments.'''
        resource_by_condition: dict[str, str] = {}
        condition_order: list[str] = []
        has_unconditional = False
        for condition_str, resource_name in entry_list:
            if not condition_str:
                has_unconditional = True
            if condition_str in resource_by_condition:
                if resource_by_condition[condition_str] != resource_name:
                    raise ValueError(
                        "Hash Texture Bind: texture hash " + texture_hash + " is bound with condition '"
                        + (condition_str or "<always>") + "' to both " + resource_by_condition[condition_str]
                        + " and " + resource_name + "; give each switch state one texture."
                    )
                continue
            resource_by_condition[condition_str] = resource_name
            condition_order.append(condition_str)
        return resource_by_condition, condition_order, has_unconditional

    @staticmethod
    def _collect_global_active_hashes(global_hash_texture_binding_list: list | None) -> set:
        '''Hashes that carry a real global replacement (not a restore row).'''
        return {
            str(row.get("texture_hash", "")).strip().lower()
            for row in global_hash_texture_binding_list or []
            if row.get("enabled", True) and not row.get("restore_original", False)
        }

    @classmethod
    def generate_hash_style_global_texture_ini(
        cls,
        ini_builder: M_IniBuilder,
        global_hash_texture_binding_list: list | None,
        drawib_drawibmodel_dict: dict | None = None,
        preflight_only: bool = False,
    ):
        '''Emit one hash override section per hash, global replacement first.

        The global replacement is the default of its hash. Object scoped rows
        that could not bind inside their own draw section are merged into the
        same section as conditional overrides, because 3Dmigoto reports a
        duplicate hash override when two sections claim the same texture hash:
        a second section could never act as a fallback for the first one.

        The default assignment comes first and every matching condition
        overrides it, which is what makes the global image the fallback for
        every object and switch state that is not listed explicitly.
        '''
        # Resolve and validate every row before copying anything. This keeps a
        # broken row from leaving a half-written global texture set behind.
        resolved_rows = []
        seen_hashes = set()
        # A replacement in another global node takes precedence over restoring
        # a cleared row. Restoration must not claim a managed hash or emit INI.
        active_hashes = cls._collect_global_active_hashes(global_hash_texture_binding_list)
        for binding in global_hash_texture_binding_list or []:
            if not binding.get("enabled", True):
                continue

            node_label = str(binding.get("node_label", "") or "Global Hash Texture Bind")
            texture_hash = str(binding.get("texture_hash", "") or "").strip().lower()
            restore_original = bool(binding.get("restore_original", False))
            if restore_original and (texture_hash in active_hashes or texture_hash in seen_hashes):
                continue
            if _GLOBAL_HASH_PATTERN.fullmatch(texture_hash) is None:
                raise ValueError(
                    "Global Hash Texture Bind node '" + node_label
                    + "': invalid texture hash '" + str(binding.get("texture_hash", ""))
                    + "'; expected 8 hexadecimal characters."
                )
            if texture_hash in seen_hashes:
                raise ValueError(
                    "Global Hash Texture Bind node '" + node_label
                    + "': texture hash '" + texture_hash
                    + "' is specified more than once; keep one global replacement per hash."
                )
            seen_hashes.add(texture_hash)

            source_type = str(binding.get("source_type", "") or "")
            if source_type in ("FILE", "MARK"):
                if source_type == "MARK":
                    source_path = str(binding.get("mark_source_file_path", "") or "").strip()
                else:
                    source_path = str(binding.get("file_path", "") or "").strip()
                if not source_path:
                    raise ValueError(
                        "Global Hash Texture Bind node '" + node_label
                        + "': texture file path is empty for hash '" + texture_hash + "'."
                    )
                file_suffix = os.path.splitext(source_path)[1].lower()
                if file_suffix not in _GLOBAL_HASH_FILE_SUFFIXES:
                    raise ValueError(
                        "Global Hash Texture Bind node '" + node_label
                        + "': unsupported texture file '" + source_path
                        + "'; use one of " + ", ".join(_GLOBAL_HASH_FILE_SUFFIXES) + "."
                    )
                if not os.path.isfile(source_path):
                    raise ValueError(
                        "Global Hash Texture Bind node '" + node_label
                        + "': texture file does not exist: " + source_path + "."
                    )

                # Exact conversion requires an authoritative original DDS.
                # Include every same-hash mark so conflicting captures cannot
                # silently select an arbitrary format from another Submesh.
                # Source image suffix does not determine the required DDS format.
                # Every capture of a managed hash contributes to authority checks.
                # Missing authority must fail instead of selecting a generic format.
                # Dimensions and mip metadata disagreements are ambiguous as well.
                original_path = ""
                file_suffix = os.path.splitext(source_path)[1].lower()
                if _exact_format_enabled():
                    originals = []
                    marked_source = binding.get("mark_source_file_path", "")
                    if marked_source:
                        originals.append(marked_source)
                    for model in (drawib_drawibmodel_dict or {}).values():
                        for part, marks in getattr(model, "submesh_texturemarkinfolist_dict", {}).items():
                            for mark in marks:
                                if str(mark.mark_hash).lower() == texture_hash:
                                    path = cls._get_slot_texture_source_path(model, part, mark)
                                    if path:
                                        originals.append(path)
                    # Global scope includes captures outside the selected export.
                    # Conflicting formats there are just as ambiguous as local ones.
                    from ..blueprint.blueprint_node_hash_texture import _load_global_hash_mark_entries
                    originals.extend(entry['source_path'] for entry in _load_global_hash_mark_entries()
                                     if entry['hash'] == texture_hash and entry['source_path'])
                    if not originals:
                        raise ValueError("Global Hash Texture Bind: original DDS is unavailable for hash " + texture_hash)
                    from ..texcomb.core.dds_match import read_dds_metadata
                    # Parse originals before creating the global texture output folder.
                    # Comparing immutable metadata makes conflict detection deterministic.
                    # The first path is safe to use only after all paths agree.
                    # Replacement size policy is independent of original-format selection.
                    metadata = [read_dds_metadata(path) for path in originals]
                    if any(value != metadata[0] for value in metadata[1:]):
                        raise ValueError("Global Hash Texture Bind: conflicting original DDS metadata for hash " + texture_hash)
                    # A converted replacement is always written as a DDS file.
                    original_path = originals[0]
                    file_suffix = ".dds"

                # Stable hash-based names make the generated texture easy to
                # find and prevent two source basenames from colliding.
                resource_name = "ResourceHashGlobal_" + texture_hash
                target_filename = texture_hash + "_global" + file_suffix
                if binding.get("preserve_mark_filename", False):
                    # Scanned replacements keep the familiar hash/mark name.
                    # Sources are converted before copying; all output names
                    # describe genuine DDS bytes rather than renamed PNG files.
                    role = normalize_texture_role(binding.get("mark_name", ""))
                    target_filename = texture_hash + "_" + role + file_suffix
                # A user alias replaces the generated stem; the suffix still
                # follows the bytes this row really writes.
                alias_filename = alias_output_filename_with_suffix(
                    binding.get("output_name", ""), file_suffix,
                )
                if alias_filename:
                    ensure_ini_encodable(
                        alias_filename,
                        "Texture alias '" + str(binding.get("output_name", "") or "")
                        + "' of node '" + node_label + "'",
                    )
                    target_filename = alias_filename
                resolved_rows.append({
                    "texture_hash": texture_hash,
                    "resource_name": resource_name,
                    "target_filename": target_filename,
                    "source_path": source_path,
                    "original_path": original_path,
                    "force_original_size": binding.get("force_original_size", False),
                    "restore_original": restore_original,
                })
            elif source_type == "RESOURCE":
                resource_name = str(binding.get("resource_name", "") or "").strip()
                # An existing resource owns no generated file to rename.
                if normalize_alias_stem(binding.get("output_name", "")):
                    raise ValueError(
                        "Global Hash Texture Bind node '" + node_label + "': hash '" + texture_hash
                        + "' reuses an existing resource, which generates no texture file to rename; "
                        + "clear the texture alias or pick a texture file / mark instead."
                    )
                if _GLOBAL_RESOURCE_PATTERN.fullmatch(resource_name) is None:
                    raise ValueError(
                        "Global Hash Texture Bind node '" + node_label
                        + "': invalid resource name '" + resource_name + "'."
                    )
                resolved_rows.append({
                    "texture_hash": texture_hash,
                    "resource_name": resource_name,
                    "target_filename": "",
                    "source_path": "",
                })
            else:
                raise ValueError(
                    "Global Hash Texture Bind node '" + node_label
                    + "': source type '" + source_type
                    + "' is not supported; use Marked Texture, External File or Existing Resource."
                )

        if not resolved_rows:
            return

        # Global replacements share the Textures folder with every DrawIB
        # binding, so their generated names join the same duplicate check.
        claims = cls._texture_output_name_claims(ini_builder)
        for row in resolved_rows:
            if row["target_filename"] and row["source_path"]:
                claims.claim(
                    row["target_filename"],
                    os.path.normcase(os.path.abspath(row["source_path"])),
                    "global hash group " + str(row["texture_hash"]),
                )

        # Copy explicit global files on every export. A changed source must
        # replace the previous generated copy instead of leaving stale bytes.
        from ..texcomb.core.dds_match import DDSReplacementStage
        # Keep all converted rows alive until the whole batch has validated.
        # No final file is opened when any row has invalid pixels or metadata.
        # Restoring a cleared hash copies the authoritative original bytes.
        # RESOURCE rows carry no file and therefore need no image conversion.
        with DDSReplacementStage() as stage:
            # Validate every conversion before opening the generated folder.
            # Restoration copies original bytes without any recompression.
            # A disabled exact-format switch leaves rows with no original path,
            # which are copied unchanged exactly like the historical behaviour.
            for row in resolved_rows:
                if row["source_path"] and row.get("original_path") and not row.get("restore_original", False):
                    # Keep the user's own file as the timestamp reference; the
                    # converted product is only the bytes that must be copied.
                    row["stamp_path"] = row["source_path"]
                    row["source_path"] = stage.prepare(
                        row["source_path"], row["original_path"], row["force_original_size"]
                    )
            # Blueprint construction validates the whole export before writers
            # create any output. The normal pass repeats this against live files.
            if preflight_only:
                return
            output_folder = GlobalConfig.path_generatemod_texture_folder(draw_ib="global")
            os.makedirs(output_folder, exist_ok=True)
            for row in resolved_rows:
                source_path = row["source_path"]
                if not source_path:
                    continue
                target_path = os.path.join(output_folder, row["target_filename"])
                if os.path.normcase(os.path.abspath(source_path)) != os.path.normcase(os.path.abspath(target_path)):
                    # Same "newer wins" rule as the automatic texture copies: a
                    # file the user re-saved in the Mod folder is kept.
                    cls._refresh_generated_texture(
                        source_path, target_path, str(row.get("stamp_path", "") or ""),
                    )

        # Keep resource declarations before all hash overrides. One section per
        # hash carries the global default plus every object scoped override.
        switch_entry_dict = cls._collect_hash_switch_entry_dict(drawib_drawibmodel_dict)
        resource_section = M_IniSection(M_SectionType.ResourceTexture)
        override_section = M_IniSection(M_SectionType.TextureOverrideTexture)
        for row in resolved_rows:
            if row.get("restore_original", False):
                continue
            resource_name = row["resource_name"]
            target_filename = row["target_filename"]
            if target_filename:
                resource_section.append("[" + resource_name + "]")
                resource_section.append("filename = " + GlobalConfig.ini_texture_filename(target_filename))
                resource_section.new_line()
            texture_hash = str(row["texture_hash"] or "").strip().lower()
            resource_by_condition, condition_order, has_unconditional = cls._normalize_hash_switch_entries(
                texture_hash, switch_entry_dict.get(texture_hash, []),
            )
            if has_unconditional:
                raise ValueError(
                    "Hash Texture Bind: texture hash " + texture_hash
                    + " uses a global replacement and an object binding without a switch state;"
                    + " connect the object through a Switch Key node, or remove the global replacement for that hash."
                )
            override_section.append("[TextureOverride_Texture_" + texture_hash + "]")
            override_section.append("hash = " + texture_hash)
            override_section.append("match_priority = 0")
            # Default first, then the listed states override it. Every object
            # and state that is not listed therefore keeps the global image.
            override_section.append("this = " + resource_name)
            for condition_str in condition_order:
                override_section.append("if " + condition_str)
                override_section.append("  this = " + resource_by_condition[condition_str])
                override_section.append("endif")
            override_section.new_line()

        ini_builder.append_section(resource_section)
        ini_builder.append_section(override_section)

    @classmethod
    def generate_hash_style_object_texture_ini(
        cls,
        ini_builder: M_IniBuilder,
        drawib_drawibmodel_dict: dict,
        global_hash_texture_binding_list: list | None = None,
    ):
        '''Conditional hash sections for rows that cannot bind per object.

        Only rows without a texture slot reach this generator: a row that
        knows its slot binds inside the owning object's draw section instead.
        A hash that also carries a global replacement is owned by
        generate_hash_style_global_texture_ini, which merges these same
        conditions into its single section, so this method skips it to avoid
        two overrides claiming one texture hash.

        Emitted even when forbid_auto_texture_ini is on, for the same reason
        as the slot bindings: a Hash Texture Bind node is explicit user
        intent, not part of the automatic texture pipeline.
        '''
        binding_entry_dict = cls._collect_hash_switch_entry_dict(drawib_drawibmodel_dict)
        if not binding_entry_dict:
            return
        global_active_hashes = cls._collect_global_active_hashes(global_hash_texture_binding_list)

        for texture_hash, entry_list in binding_entry_dict.items():
            if texture_hash in global_active_hashes:
                # Owned by the merged global section for this hash.
                continue
            resource_by_condition, condition_order, has_unconditional = cls._normalize_hash_switch_entries(
                texture_hash, entry_list,
            )
            if has_unconditional and len(condition_order) > 1:
                raise ValueError(
                    "Hash Texture Bind: texture hash " + texture_hash + " mixes an unconditional binding with "
                    + str(len(condition_order) - 1) + " conditional one(s); connect every branch through an explicit switch so the replacement states stay unambiguous."
                )

            switch_section = M_IniSection(M_SectionType.TextureOverrideTexture)
            switch_section.append("[TextureOverride_Texture_" + texture_hash + "]")
            switch_section.append("hash = " + texture_hash)
            # Same priority as the automatic hash overrides, so the managed
            # section behaves like a drop-in replacement for them.
            switch_section.append("match_priority = 0")
            for condition_str in condition_order:
                if condition_str:
                    switch_section.append("if " + condition_str)
                    switch_section.append("  this = " + resource_by_condition[condition_str])
                    switch_section.append("endif")
                else:
                    switch_section.append("this = " + resource_by_condition[condition_str])
            switch_section.new_line()

            ini_builder.append_section(switch_section)

    @classmethod
    def generate_hash_style_texture_ini(
        cls,
        ini_builder: M_IniBuilder,
        drawib_drawibmodel_dict: dict[str, DrawIBModel],
        global_hash_texture_binding_list: list | None = None,
        resource_prefix: str = "",
        guard_with_object_detected: bool = False,
    ):
        """
        Hash style textures: generate texture config sections (Resource_Texture + TextureOverride) and copy the texture files.
        Overall flow: iterate over DrawIB -> iterate over SubMesh -> process each texture.

        ``resource_prefix`` disambiguates the generated resource and override
        section names for presets that write one INI per object (WWMI): every
        INI of such a mod shares one 3Dmigoto namespace, so two objects using
        the same texture hash would otherwise collide. Other presets write a
        single INI and keep the default empty prefix.

        ``guard_with_object_detected`` wraps the replacement into
        ``if $object_detected``. That is what keeps the override from changing
        the texture for every other object in the scene that happens to use the
        same texture; it requires the preset to maintain that variable.
        """

        # ═══════════════════════════════════════════════════
        # Step 1: check the global switch; skip all processing when forbidden
        # ═══════════════════════════════════════════════════
        if MIMIGlobalProperties.forbid_auto_texture_ini():
            print("[TRACE] generate_hash_style_texture_ini: forbid_auto_texture_ini=True, skipped!")
            return

        # ═══════════════════════════════════════════════════
        # Step 2: initialize the dedupe list, then process Hash textures for each DrawIB
        # ═══════════════════════════════════════════════════
        repeat_hash_list: list[str] = []

        # Hashes managed by either explicit hash node variant are user intent:
        # the automatic unconditional override hands over to the node sections.
        managed_hash_set = cls._collect_hash_binding_managed_hashes(
            drawib_drawibmodel_dict,
            global_hash_texture_binding_list=global_hash_texture_binding_list,
        )

        for draw_ib, draw_ib_model in drawib_drawibmodel_dict.items():
            submesh_list = getattr(draw_ib_model, "submesh_model_list", [])
            print("M_IniHelper: DrawIB " + draw_ib + " Hash mark count: "
                  + str(cls._count_marked_textures(draw_ib_model, mark_type="Hash"))
                  + ", SubMesh count: " + str(len(submesh_list)))

            for submesh_model in submesh_list:
                texture_markup_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
                if not texture_markup_info_list:
                    continue

                part_name = draw_ib_model.get_submesh_part_name(submesh_model)
                submesh_folder_name = getattr(submesh_model, "submesh_name", "")
                if not submesh_folder_name:
                    print("M_IniHelper: Skipping Hash texture processing, submesh_name not found, Part: " + str(part_name))
                    continue

                # Read this SubMesh's hash dedupe info dict
                hash_deduped_texture_info_dict = MMTWorkSpace.get_hash_deduped_texture_info_dict(
                    submesh_folder_name=submesh_folder_name,
                )

                for texture_markup_info in texture_markup_info_list:
                    # Type filter: only process Hash marks
                    if texture_markup_info.mark_type != "Hash":
                        continue

                    # Dedupe and managed-hash comparisons use one case so a
                    # metadata file with uppercase hex still matches a global
                    # or conditional node row.
                    mark_hash = str(texture_markup_info.mark_hash or "").strip().lower()
                    if mark_hash in repeat_hash_list:
                        continue
                    repeat_hash_list.append(mark_hash)

                    # Hashes bound by Hash Texture Bind nodes keep their
                    # resource management but skip the automatic override;
                    # the explicit node sections take over.
                    if mark_hash in managed_hash_set:
                        print("M_IniHelper: hash " + mark_hash + " is managed by Hash Texture Bind nodes; skipping the automatic Hash override.")
                        continue

                    # Find the source texture file path
                    original_texture_file_path = cls._get_slot_texture_source_path(
                        draw_ib_model=draw_ib_model,
                        part_name=part_name,
                        texture_markup_info=texture_markup_info,
                    )
                    if not original_texture_file_path or not os.path.exists(original_texture_file_path):
                        continue

                    # Build the output filename
                    #  New format: "{mark_hash}_{mark_name}_{format}.dds"
                    hash_style_texture_filename = ""

                    # Look up hash dedupe info; prefer the current SubMesh's, fall back to all SubMeshes
                    deduped_texture_info = hash_deduped_texture_info_dict.get(
                        texture_markup_info.mark_hash, None,
                    )
                    if deduped_texture_info is None:
                        for sm in getattr(draw_ib_model, "submesh_model_list", []):
                            sm_folder = getattr(sm, "submesh_name", "")
                            if not sm_folder:
                                continue
                            sm_deduped_dict = MMTWorkSpace.get_hash_deduped_texture_info_dict(
                                submesh_folder_name=sm_folder,
                            )
                            deduped_texture_info = sm_deduped_dict.get(
                                texture_markup_info.mark_hash, None,
                            )
                            if deduped_texture_info is not None:
                                break

                    hash_style_texture_filename = (
                        texture_markup_info.mark_hash + "_"
                        + texture_markup_info.mark_name
                        + ".dds"
                    )
                    hash_style_resource_name = default_texture_resource_name(
                        texture_markup_info.mark_hash,
                        texture_markup_info.mark_name,
                    )
                    if resource_prefix:
                        # Keep the "Resource" head intact: 3Dmigoto only treats a
                        # section as a resource when its name starts with it.
                        hash_style_resource_name = hash_style_resource_name + "_" + resource_prefix
                    # The override section name follows the resource so two
                    # prefixed resources never claim the same override name.
                    hash_style_override_section_name = "TextureOverride_" + texture_markup_info.mark_hash
                    if resource_prefix:
                        hash_style_override_section_name = hash_style_override_section_name + "_" + resource_prefix

                    # Assemble the target path
                    target_texture_file_path = (
                        GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib)
                        + hash_style_texture_filename
                    )

                    # Generate the INI config sections (Resource_Texture + TextureOverride)
                    resource_texture_section = M_IniSection(
                        M_SectionType.ResourceAndTextureOverride_Texture,
                    )
                    resource_texture_section.append(
                        "[" + hash_style_resource_name + "]",
                    )
                    resource_texture_section.append(
                        "filename = " + GlobalConfig.ini_texture_filename(hash_style_texture_filename),
                    )
                    resource_texture_section.new_line()
                    resource_texture_section.append(
                        "[" + hash_style_override_section_name + "]",
                    )
                    resource_texture_section.append(
                        "; " + texture_markup_info.mark_filename,
                    )
                    resource_texture_section.append(
                        "hash = " + texture_markup_info.mark_hash,
                    )
                    resource_texture_section.append("match_priority = 0")
                    if guard_with_object_detected:
                        resource_texture_section.append("if $object_detected")
                        resource_texture_section.append(
                            "  this = " + hash_style_resource_name,
                        )
                        resource_texture_section.append("endif")
                    else:
                        resource_texture_section.append(
                            "this = " + hash_style_resource_name,
                        )
                    resource_texture_section.new_line()
                    ini_builder.append_section(resource_texture_section)

                    # Refresh the copy when the capture changed. The old rule
                    # ("skip when the target exists") kept a texture from a
                    # previous export forever, so editing or re-extracting a
                    # capture produced a Mod that mixed old and new pictures.
                    cls._refresh_generated_texture(original_texture_file_path, target_texture_file_path)

    @classmethod
    def generate_shared_slot_style_texture_ini(cls, ini_builder: M_IniBuilder, drawib_drawibmodel_dict: dict[str, DrawIBModel]):
        """
        Generate Shared Slot style texture INI config.
        The logic mixes Hash and Slot styles:
          - Dedupe and file naming = Hash style (dedupe by mark_hash, structured filenames)
          - INI output = Slot style (write [Resource-XXX] sections, no TextureOverride sections)
        File copying dedupes the Hash-style way (each hash is copied only once).
        """
        if MIMIGlobalProperties.forbid_auto_texture_ini():
            print("[TRACE] generate_shared_slot_style_texture_ini: forbid_auto_texture_ini=True, skipped!")
            return

        repeat_hash_list: list[str] = []
        appended_resource_names: set[str] = set()
        # Cache: mark_hash -> hash_style_filename, shared across all DrawIBs so each hash is copied only once
        hash_filename_cache: dict[str, str] = {}

        for draw_ib, draw_ib_model in drawib_drawibmodel_dict.items():
            submesh_list = getattr(draw_ib_model, "submesh_model_list", [])
            print("M_IniHelper: DrawIB " + draw_ib + " SharedSlot mark count: "
                  + str(cls._count_marked_textures(draw_ib_model, mark_type="SharedSlot"))
                  + ", SubMesh count: " + str(len(submesh_list)))

            has_shared_slot = False
            shared_slot_resource_section = M_IniSection(M_SectionType.ResourceTexture)

            for submesh_model in submesh_list:
                texture_markup_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
                if not texture_markup_info_list:
                    continue

                part_name = draw_ib_model.get_submesh_part_name(submesh_model)
                submesh_folder_name = getattr(submesh_model, "submesh_name", "")
                if not submesh_folder_name:
                    print("M_IniHelper: Skipping SharedSlot texture processing, submesh_name not found, Part: " + str(part_name))
                    continue

                hash_deduped_texture_info_dict = MMTWorkSpace.get_hash_deduped_texture_info_dict(
                    submesh_folder_name=submesh_folder_name,
                )

                for texture_markup_info in texture_markup_info_list:
                    # Type filter: only process SharedSlot marks
                    if texture_markup_info.mark_type != "SharedSlot":
                        continue

                    # File copy + filename construction (deduped by hash)
                    hash_style_texture_filename: str | None = hash_filename_cache.get(texture_markup_info.mark_hash)
                    if hash_style_texture_filename is None:
                        # First time this hash is seen: find the source file, build the filename, copy
                        original_texture_file_path = cls._get_slot_texture_source_path(
                            draw_ib_model=draw_ib_model,
                            part_name=part_name,
                            texture_markup_info=texture_markup_info,
                        )
                        if not original_texture_file_path or not os.path.exists(original_texture_file_path):
                            continue

                        hash_style_texture_filename = ""

                        deduped_texture_info = hash_deduped_texture_info_dict.get(
                            texture_markup_info.mark_hash, None,
                        )
                        if deduped_texture_info is None:
                            for sm in getattr(draw_ib_model, "submesh_model_list", []):
                                sm_folder = getattr(sm, "submesh_name", "")
                                if not sm_folder:
                                    continue
                                sm_deduped_dict = MMTWorkSpace.get_hash_deduped_texture_info_dict(
                                    submesh_folder_name=sm_folder,
                                )
                                deduped_texture_info = sm_deduped_dict.get(
                                    texture_markup_info.mark_hash, None,
                                )
                                if deduped_texture_info is not None:
                                    break

                        hash_style_texture_filename = (
                            texture_markup_info.mark_hash + "_"
                            + texture_markup_info.mark_name
                            + ".dds"
                        )

                        # Copy the file (dedupe); identical bytes stay untouched.
                        target_texture_file_path = (
                            GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib)
                            + hash_style_texture_filename
                        )
                        cls._refresh_generated_texture(original_texture_file_path, target_texture_file_path)

                        hash_filename_cache[texture_markup_info.mark_hash] = hash_style_texture_filename
                        repeat_hash_list.append(texture_markup_info.mark_hash)
                    else:
                        # Hash already handled: skip the file copy but still write the Resource section
                        pass

                    # Generate the Slot-style Resource section (deduped by resource name)
                    has_shared_slot = True
                    resource_name = texture_markup_info.get_resource_name()
                    if resource_name not in appended_resource_names:
                        appended_resource_names.add(resource_name)
                        shared_slot_resource_section.append("[" + resource_name + "]")
                        shared_slot_resource_section.append("filename = " + GlobalConfig.ini_texture_filename(hash_style_texture_filename))
                        shared_slot_resource_section.new_line()

            if has_shared_slot:
                ini_builder.append_section(shared_slot_resource_section)

    @staticmethod
    def _get_slot_style_texture_filename(draw_ib_model: DrawIBModel, submesh_index: int, texture_markup_info) -> str:
        """
        Build the Slot-style texture filename.
        Format: {alias-or-DrawIB}-{Submesh-index}-{mark-name}.dds
        """
        prefix = draw_ib_model.draw_ib_alias or draw_ib_model.draw_ib
        return f"{prefix}-{submesh_index}-{texture_markup_info.mark_name}.dds"

    @staticmethod
    def _texture_stamp_ns(path: str) -> int:
        """Return the modification time of one file in nanoseconds, or 0.

        Only used to decide which of two files is newer, so a vanished file
        simply loses that comparison instead of raising.
        """
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return 0

    @staticmethod
    def _copy_generated_texture(source_path: str, target_path: str, stamp_ns: int) -> None:
        """Copy one texture and stamp the copy with its source time.

        The stamp is what the next export compares, so the generated file always
        says how new the picture inside it really is. ``copy2`` already carries
        the time of the file it copies; a converted replacement keeps the time
        of the user's own image instead, which is why the stamp is explicit.
        """
        shutil.copy2(source_path, target_path)
        if stamp_ns:
            os.utime(target_path, ns=(stamp_ns, stamp_ns))

    @classmethod
    def _refresh_generated_texture(cls, source_path: str, target_path: str,
                                   source_stamp_path: str = "") -> str:
        """Copy one texture into the generated Mod, or keep a hand-edited one.

        Two earlier rules were both wrong for somebody:

        - "skip when the target exists" (before 1.0.66) kept a picture from a
          previous export forever, so re-extracting a workspace or editing a
          capture produced a Mod that mixed old and new textures;
        - "copy whenever the bytes differ" (1.0.66) always won against a texture
          the user had re-saved inside the generated folder by hand.

        The rule is therefore "the newer file wins": a capture re-extracted or
        edited after the export refreshes the Mod, while a generated texture the
        user saved later is kept and reported. Identical bytes never touch the
        file, so a repeated export stays free.

        ``source_stamp_path`` lets a converted replacement carry the timestamp
        of the user's own image instead of the temporary conversion product.

        Returns ``copied``, ``unchanged``, ``kept`` or ``missing``.
        """
        # ``exists`` (not ``isfile``) is deliberate: the copy tests patch the
        # exists probe only, and a directory source fails loudly in copy2.
        if not source_path or not os.path.exists(source_path):
            return "missing"
        # The stamp belongs to the picture, which is the real source when the
        # bytes handed in are a converted copy of it.
        source_stamp = cls._texture_stamp_ns(source_stamp_path or source_path)
        if not os.path.isfile(target_path):
            cls._copy_generated_texture(source_path, target_path, source_stamp)
            return "copied"
        if filecmp.cmp(source_path, target_path, shallow=False):
            return "unchanged"
        if cls._texture_stamp_ns(target_path) > source_stamp:
            print(
                "M_IniHelper: kept the generated texture you edited by hand "
                + "(newer than its source): " + target_path
            )
            return "kept"
        cls._copy_generated_texture(source_path, target_path, source_stamp)
        return "copied"

    @classmethod
    def move_slot_style_textures(cls,draw_ib_model:DrawIBModel):
        '''
        Move all textures from extracted game type folder to generate mod Texture folder.
        Only works in default slot style texture.
        '''
        print("=" * 60)
        print("[TRACE] move_slot_style_textures() entry - DrawIB: " + draw_ib_model.draw_ib)
        print("=" * 60)

        if MIMIGlobalProperties.forbid_auto_texture_ini():
            print("[TRACE] move_slot_style_textures: forbid_auto_texture_ini=True, skipping all texture copies!")
            return

        marked_slot_count = cls._count_marked_textures(draw_ib_model, mark_type="Slot")
        print("M_IniHelper: Starting to copy Slot textures, DrawIB: " + draw_ib_model.draw_ib + ", Slot mark count: " + str(marked_slot_count))

        submesh_model_list = getattr(draw_ib_model, "submesh_model_list", [])
        print("[TRACE] move_slot_style_textures: submesh_model_list size = " + str(len(submesh_model_list)))

        slot_copied = 0
        slot_skipped_exists = 0
        slot_kept_manual = 0
        slot_skipped_no_source = 0
        slot_skipped_non_slot = 0

        for idx, submesh_model in enumerate(submesh_model_list):
            texture_markup_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
            submesh_name = getattr(submesh_model, "submesh_name", "<none>")
            print("[TRACE] submesh[" + str(idx) + "] submesh_name=" + submesh_name + ", texture mark count=" + str(len(texture_markup_info_list)))

            if not texture_markup_info_list:
                print("[TRACE] submesh[" + str(idx) + "] no texture marks, skip")
                continue

            part_name = draw_ib_model.get_submesh_part_name(submesh_model) or submesh_model.submesh_name
            for ti, texture_markup_info in enumerate(texture_markup_info_list):
                print("[TRACE]   texture[" + str(ti) + "]: mark_type=" + texture_markup_info.mark_type
                      + ", mark_filename=" + texture_markup_info.mark_filename
                      + ", mark_hash=" + str(getattr(texture_markup_info, "mark_hash", "<none>")))

                if texture_markup_info.mark_type != "Slot":
                    print("[TRACE]   texture[" + str(ti) + "]: mark_type is not Slot (actual=" + texture_markup_info.mark_type + "), skip")
                    slot_skipped_non_slot += 1
                    continue

                texture_output_folder = GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib_model.draw_ib)
                print("M_IniHelper: Slot texture output folder: " + texture_output_folder)
                print("[TRACE] Slot texture output folder exists: " + str(os.path.exists(texture_output_folder)))

                slot_texture_filename = cls._get_slot_style_texture_filename(draw_ib_model, idx, texture_markup_info)
                print("[TRACE] Slot texture new filename: " + slot_texture_filename)

                target_path = GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib_model.draw_ib) + slot_texture_filename
                source_path = cls._get_slot_texture_source_path(draw_ib_model, part_name, texture_markup_info)
                print("[TRACE] Slot texture source_path resolve result: '" + source_path + "'")
                print("[TRACE] Slot texture target_path: '" + target_path + "'")
                print("[TRACE] source_path exists: " + str(os.path.exists(source_path) if source_path else "N/A (empty string)"))
                print("[TRACE] target_path exists: " + str(os.path.exists(target_path)))

                if source_path == "":
                    print("[TRACE] Slot texture source_path is empty, skip! mark_filename=" + texture_markup_info.mark_filename)
                    slot_skipped_no_source += 1
                    continue
                if not os.path.exists(source_path):
                    print("[TRACE] Slot texture source_path file does not exist, skip! source_path=" + source_path)
                    slot_skipped_no_source += 1
                    continue
                # The capture is newer than the Mod file it should refresh, so
                # a re-extracted or edited texture is copied; a generated file
                # the user saved later is kept instead of being restored.
                print("[TRACE] >>> Refreshing generated texture: " + source_path + " -> " + target_path)
                try:
                    result = cls._refresh_generated_texture(source_path, target_path)
                    print("[TRACE] <<< Generated texture result: " + result + " for " + target_path)
                    if result == "copied":
                        slot_copied += 1
                    elif result == "kept":
                        slot_kept_manual += 1
                    else:
                        slot_skipped_exists += 1
                except Exception as e:
                    print("[TRACE] <<< Refresh failed! Exception: " + str(e))

        print("[TRACE] move_slot_style_textures() summary - DrawIB: " + draw_ib_model.draw_ib)
        print("[TRACE]   Slot copied: " + str(slot_copied))
        print("[TRACE]   Slot kept (edited in the Mod folder): " + str(slot_kept_manual))
        print("[TRACE]   Slot unchanged: " + str(slot_skipped_exists))
        print("[TRACE]   Slot skipped (source missing): " + str(slot_skipped_no_source))
        print("[TRACE]   Slot skipped (non-Slot type): " + str(slot_skipped_non_slot))
        print("=" * 60)
    
    @classmethod
    def add_object_texture_binding_resource_sections(cls, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModel):
        '''Resource declarations for the Texture Bind node FILE textures.

        Unlike the automatic Slot pipeline this runs even when
        forbid_auto_texture_ini is on: a Texture Bind node is explicit user
        intent, not an automatic texture replacement.
        '''
        resource_entries = list(getattr(draw_ib_model, "object_texture_binding_resource_list", None) or [])
        if not resource_entries:
            return

        # Every DrawIB of one Mod writes into the same Textures folder, so a
        # duplicate file name has to be reported once all of them are known.
        # This method is the one place every exporter calls per DrawIB with the
        # shared INI builder, which makes it the natural place to check.
        cls._claim_texture_output_names(ini_builder, draw_ib_model)

        resource_texture_section = M_IniSection(M_SectionType.ResourceTexture)
        appended_resource_names = set()
        for resource_name, target_filename in resource_entries:
            if resource_name in appended_resource_names:
                continue
            appended_resource_names.add(resource_name)
            resource_texture_section.append("[" + resource_name + "]")
            # Empty resources hold per-draw references, not texture filenames.
            if target_filename:
                resource_texture_section.append("filename = " + GlobalConfig.ini_texture_filename(target_filename))
            resource_texture_section.new_line()

        ini_builder.append_section(resource_texture_section)

    @staticmethod
    def _texture_output_name_claims(ini_builder):
        '''Return the claim table shared by every DrawIB of one export.

        The table lives on the INI builder, so it covers all DrawIBs written
        into the same Textures folder and disappears together with that
        builder.  The same image may still be shared by several rows, which is
        why the source path is part of every claim.

        The preflight call passes ``None`` because it writes no INI and no
        texture; name conflicts there are irrelevant, so it gets an empty,
        throw-away table instead of an AttributeError.
        '''
        if ini_builder is None:
            return TextureOutputNameClaims()
        claims = getattr(ini_builder, "_mimi_texture_output_claims", None)
        if claims is None:
            claims = TextureOutputNameClaims()
            ini_builder._mimi_texture_output_claims = claims
        return claims

    @classmethod
    def _claim_texture_output_names(cls, ini_builder, draw_ib_model: DrawIBModel):
        '''Report two different images that would be written under one name.'''
        claims = cls._texture_output_name_claims(ini_builder)
        for resource_name, source_path, target_filename in (
            getattr(draw_ib_model, "object_texture_binding_file_list", None) or []
        ):
            description = (
                "DrawIB " + str(getattr(draw_ib_model, "draw_ib", "") or "?")
                + " resource " + str(resource_name)
            )
            # The normalized absolute path identifies the image, so a repeated
            # job for the same picture never looks like a conflict.
            source_key = os.path.normcase(os.path.abspath(str(source_path or "")))
            claims.claim(target_filename, source_key, description)

    @classmethod
    def move_object_texture_binding_files(cls, draw_ib_model: DrawIBModel):
        '''Copy explicit Texture Bind files into the generated Texture folder.

        A changed source must refresh the generated copy. The old skip-only
        behavior made a newly selected external file look as if it vanished
        because the previous export's bytes were kept under the same name.
        Repeated calls remain safe because an identical source/target path is
        skipped before copying.
        '''
        file_list = list(getattr(draw_ib_model, "object_texture_binding_file_list", None) or [])
        if not file_list:
            return

        from ..texcomb.core.dds_match import DDSReplacementStage, prepare_replacement_job
        # Exact jobs are preflighted again here to catch edits since model build.
        # Temporary staged files remain alive until every copy completes.
        with DDSReplacementStage() as stage:
            prepared = []
            jobs = getattr(draw_ib_model, "exact_texture_jobs", {})
            for resource, source, filename in file_list:
                row = jobs.get(resource)
                # The user's own image stays the timestamp reference, so a
                # generated file they edited later is still recognised as newer.
                stamp_path = source
                if row:
                    # The conversion result is always a .dds file; the model
                    # resolver already named the target accordingly.
                    source = prepare_replacement_job(stage, source, row)
                prepared.append((resource, source, filename, stamp_path))
            cls._copy_object_texture_binding_files(draw_ib_model, prepared)

    @classmethod
    def prepare_exact_texture_jobs(cls, drawib_model_list):
        """Convert every registered replacement before the exporter writes files.

        The copy stage repeats this work later, but the conversion cache makes
        that second pass a pure lookup. Doing it up front means a broken
        capture or an unsupported format stops the export before buffers and
        INIs are written, instead of leaving a half-generated Mod behind.
        """
        from ..texcomb.core.dds_match import DDSReplacementStage, prepare_replacement_job
        pairs = []
        for model in drawib_model_list or []:
            jobs = getattr(model, "exact_texture_jobs", None) or {}
            if not jobs:
                continue
            # The job dict deliberately carries no source path: the file list
            # is the single place that knows which image a resource reads from.
            source_by_resource = {
                resource: source
                for resource, source, _target in (getattr(model, "object_texture_binding_file_list", None) or [])
            }
            for resource, job in jobs.items():
                source = source_by_resource.get(resource)
                if source:
                    pairs.append((source, job))
        if not pairs:
            return 0
        # Staged products stay alive for the whole batch, so no final file is
        # opened when one of the conversions turns out to be invalid.
        with DDSReplacementStage() as stage:
            for source, job in pairs:
                prepare_replacement_job(stage, source, job)
        print("M_IniHelper: exact texture format preflight done, jobs: " + str(len(pairs)))
        return len(pairs)

    @classmethod
    def _copy_object_texture_binding_files(cls, draw_ib_model, file_list):
        # The caller owns staged storage; this helper performs only final copies.
        # File resources and names stay local to the existing exporter namespace.
        # Entries are (resource, bytes_to_copy, target_name, timestamp_source):
        # the timestamp source is the picture the user picked, never the
        # temporary conversion product, so "newer wins" keeps working.
        texture_output_folder = GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib_model.draw_ib)
        os.makedirs(texture_output_folder, exist_ok=True)

        copied_count = 0
        kept_count = 0
        skipped_count = 0
        for entry in file_list:
            resource_name, source_path, target_filename = entry[0], entry[1], entry[2]
            stamp_path = entry[3] if len(entry) > 3 else source_path
            target_path = os.path.join(texture_output_folder, target_filename)
            if not os.path.exists(source_path):
                print("M_IniHelper: Texture Bind source file missing, skip copy: " + source_path)
                continue

            # Avoid a SameFileError when a source already lives in the output
            # folder; that row already points at the generated file.
            source_key = os.path.normcase(os.path.abspath(source_path))
            target_key = os.path.normcase(os.path.abspath(target_path))
            if source_key == target_key:
                skipped_count += 1
                continue
            # Same rule as the automatic copies: a generated texture the user
            # re-saved by hand is newer than its source and must survive.
            result = cls._refresh_generated_texture(source_path, target_path, stamp_path)
            if result == "kept":
                kept_count += 1
                continue
            if result == "unchanged":
                skipped_count += 1
                continue
            copied_count += 1
            # An older export may have written the same resource with the
            # source extension (for example .png). Only one file may exist for
            # one generated name, so stale siblings are removed.
            target_stem = os.path.splitext(target_path)[0]
            for stale_suffix in _GLOBAL_HASH_FILE_SUFFIXES:
                stale_path = target_stem + stale_suffix
                if os.path.normcase(os.path.abspath(stale_path)) == target_key:
                    continue
                if os.path.isfile(stale_path):
                    try:
                        os.remove(stale_path)
                    except OSError as error:
                        print("M_IniHelper: could not remove stale texture " + stale_path + ": " + str(error))

        print(
            "M_IniHelper: Texture Bind texture copy done, DrawIB: " + draw_ib_model.draw_ib
            + ", copied: " + str(copied_count)
            + ", kept (edited in the Mod folder): " + str(kept_count)
            + ", unchanged: " + str(skipped_count)
        )

    @staticmethod
    def add_time_animation_sections(ini_builder, present_section, m_key):
        """Emit one timeline, optionally controlled by a keyboard switch.

        Untoggled nodes retain their exact legacy Present expression. Toggled
        nodes update after input events, before Position copies/shape compute.
        A rising enable edge captures a new epoch, so each activation starts
        at frame zero rather than resuming an invisible wall-clock phase.
        """
        expression = m_key.timeline_expression()
        is_shape = m_key.key_type == "time_shapekey"
        if m_key.playback_mode == "trigger":
            M_IniHelper.add_trigger_animation_sections(ini_builder, present_section, m_key)
            return
        if not m_key.toggle_key:
            if is_shape:
                M_IniHelper.append_time_shapekey_weight_lines(present_section, m_key)
            else:
                present_section.append(m_key.key_name + " = " + expression)
            return

        control = m_key.animation_control_name()
        enabled = control + "_enabled"
        previous = control + "_previous"
        epoch = control + "_start"
        suffix = m_key.key_name.lstrip("$")
        command_name = "CommandListMimiAnimation_" + suffix
        constants = M_IniSection(M_SectionType.Constants)
        # Do not persist the switch or clock: reload honors the node default
        # and must never restore an epoch from a previous injection session.
        constants.append("global " + enabled + " = " + str(int(m_key.start_enabled)))
        constants.append("global " + previous + " = 0")
        constants.append("global " + epoch + " = 0")
        ini_builder.append_section(constants)

        key_section = M_IniSection(M_SectionType.Key)
        key_section.append("[KeyMimiAnimation_" + suffix + "]")
        key_section.append("key = " + m_key.toggle_key)
        key_section.append("type = cycle")
        # Smart cycling matches the current value before advancing. The first
        # press must toggle correctly for BOTH enabled and disabled defaults.
        # No visibility gate: users can always turn an animation back on.
        key_section.append("smart = true")
        key_section.append(enabled + " = 0,1")
        ini_builder.append_section(key_section)

        commands = M_IniSection(M_SectionType.CommandList)
        commands.append("[" + command_name + "]")
        commands.append("if " + enabled)
        commands.append("  if !" + previous)
        commands.append("    " + epoch + " = time")
        commands.append("  endif")
        clock = "(time - " + epoch + ")"
        if is_shape:
            M_IniHelper.append_time_shapekey_weight_lines(commands, m_key, "  ", clock)
        else:
            commands.append("  " + m_key.key_name + " = " + m_key.timeline_expression(clock))
        commands.append("else")
        # Draw switching selects branch zero. Shape switching removes only
        # this shape's influence. Position uses an additional enable condition
        # when choosing a resource, so it restores the separate base buffer.
        commands.append("  " + m_key.key_name + " = 0")
        commands.append("endif")
        commands.append(previous + " = " + enabled)
        ini_builder.append_section(commands)
        present_section.append("post run = " + command_name)

    @staticmethod
    def add_trigger_animation_sections(ini_builder, present_section, m_key):
        """Emit a one-shot timeline replayed from frame zero by a trigger key.

        3Dmigoto source facts backing this design (bo3b/3Dmigoto, DirectX11):
        - [Key] sections accept "run = CommandListX" (Override.cpp
          Override::ParseIniSection, ParseRunExplicitCommandList).
        - With "type = activate" (the default, IniHandler.cpp
          KeyOverrideType::ACTIVATE), KeyOverride::DownEvent calls
          Override::Activate every key-down, which runs that command list
          (Override.cpp RunCommandList) -- no toggle state, so every press
          captures a fresh epoch and restarts playback at frame zero.
        - The post-Present command list then maps elapsed time since the
          epoch to the frame expression while the play-through is inside
          the timeline period; past the period it resets the variable to
          zero and disarms the playing flag, so the timeline never wraps
          into a second loop and the next press starts clean.
        """
        control = m_key.animation_control_name()
        playing = control + "_playing"
        epoch = control + "_start"
        elapsed = control + "_elapsed"
        suffix = m_key.key_name.lstrip("$")
        trigger_command_name = "CommandListMimiAnimationTrigger_" + suffix
        command_name = "CommandListMimiAnimation_" + suffix
        is_shape = m_key.key_type == "time_shapekey"
        # Precompute the period literal: frame_count / fps seconds.
        period = repr(len(m_key.value_list) / m_key.fps)

        constants = M_IniSection(M_SectionType.Constants)
        # Runtime-only state (plain "global", never persisted): a reload
        # starts disarmed at frame zero, matching the toggle clock rules.
        constants.append("global " + playing + " = 0")
        constants.append("global " + epoch + " = 0")
        ini_builder.append_section(constants)

        key_section = M_IniSection(M_SectionType.Key)
        key_section.append("[KeyMimiAnimation_" + suffix + "]")
        key_section.append("key = " + m_key.toggle_key)
        # type=activate runs the command list on EVERY key-down, which is
        # exactly the "press to replay once" trigger semantic.
        key_section.append("type = activate")
        key_section.append("run = " + trigger_command_name)
        ini_builder.append_section(key_section)

        trigger_commands = M_IniSection(M_SectionType.CommandList)
        trigger_commands.append("[" + trigger_command_name + "]")
        trigger_commands.append(epoch + " = time")
        trigger_commands.append(playing + " = 1")
        ini_builder.append_section(trigger_commands)

        commands = M_IniSection(M_SectionType.CommandList)
        commands.append("[" + command_name + "]")
        commands.append("if " + playing + " == 1")
        commands.append("  local " + elapsed)
        commands.append("  " + elapsed + " = time - " + epoch)
        commands.append("  if " + elapsed + " < " + period)
        if is_shape:
            M_IniHelper.append_time_shapekey_weight_lines(commands, m_key, "    ", elapsed)
        else:
            commands.append("    " + m_key.key_name + " = " + m_key.timeline_expression(elapsed))
        commands.append("  else")
        # The play-through ended: return to frame zero and disarm, so the
        # timeline never wraps and the next press starts a fresh one.
        commands.append("    " + m_key.key_name + " = 0")
        commands.append("    " + playing + " = 0")
        commands.append("  endif")
        commands.append("else")
        # Disarmed (never triggered, finished or reloaded): hold frame zero.
        commands.append("  " + m_key.key_name + " = 0")
        commands.append("endif")
        ini_builder.append_section(commands)
        present_section.append("post run = " + command_name)

    @staticmethod
    def append_time_shapekey_weight_lines(section: M_IniSection, m_key: M_Key, indent: str = "", clock: str = "time"):
        '''Append the wall-clock weight timeline of a Time Shape Key variable.

        Emits a local frame counter recomputed from 3Dmigoto's built-in
        "time" operand and an if/elif chain mapping the frame index to the
        per-frame weight:

            local $shapekey1_frame
            $shapekey1_frame = ((time % (step * count)) // step) % count
            if $shapekey1_frame == 0
                $shapekey1 = 0.0
            elif $shapekey1_frame == 1
                $shapekey1 = 0.5
            endif

        The "//" floor division yields exact integer-valued floats
        (CommandList.cpp operator definitions), so the "== N" conditions are
        exact; the local variable name extends the weight variable name and
        stays inside 3Dmigoto's ^[$][a-z_][a-z0-9_]*$ rule.
        '''
        frame_var_name = m_key.key_name + "_frame"
        # Validate before emitting any lines: malformed weights must not
        # silently fall back to zero or leave a stale weight active.
        expression = m_key.timeline_expression(clock)
        section.append(indent + "local " + frame_var_name)
        section.append(indent + frame_var_name + " = " + expression)
        for index, frame_value in enumerate(m_key.value_list):
            keyword = "if" if index == 0 else "elif"
            weight = m_key.weight_list[index] if index < len(m_key.weight_list) else 0.0
            section.append(indent + keyword + " " + frame_var_name + " == " + str(frame_value))
            section.append(indent + "  " + m_key.key_name + " = " + repr(float(weight)))
        section.append(indent + "endif")

    @staticmethod
    def add_shapekey_ini_sections(ini_builder:M_IniBuilder,drawib_drawibmodel_dict:dict[str,DrawIBModel]):
        shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
        if len(shapekeyname_mkey_dict.keys()) == 0:
            return

        from .m_shape_layout import shape_shader_for_layout
        # Validate all layouts before writing resources or copying shaders.
        # A 12-byte Position buffer must never be interpreted as a 40-byte
        # position/normal/tangent struct merely because both have a stride.
        shader_by_drawib = {}
        for drawib, model in drawib_drawibmodel_dict.items():
            if getattr(model, "shapekey_name_bytelist_dict", None):
                # Time weights reuse the ordinary shape resources and compute.
                # GPU_PreSkinning describes the model, not a different shape
                # format; keep the existing preset consumer unchanged here.
                # Validate the actual Position layout instead of that flag.
                shader_by_drawib[drawib] = shape_shader_for_layout(model.d3d11_game_type)
                count = getattr(model, "draw_number", getattr(model, "vertex_count", 0))
                if count < 1 or count > 65535 * 64:
                    raise ValueError("Shape key vertex count exceeds the supported Dispatch range")
        import shutil
        addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dst_dir = GlobalConfig.path_generate_mod_folder()
        os.makedirs(dst_dir, exist_ok=True)
        for shader in set(shader_by_drawib.values()):
            shutil.copy2(os.path.join(addon_root, "resources", shader), os.path.join(dst_dir, shader))

        # [Constants]
        constants_section = M_IniSection(M_SectionType.Constants)
        constants_section.append("[Constants]")
        # No persistent first-run flag: the accumulator is initialized from
        # the seed on every compute run, including immediately after reload.

        for shapekey_name, m_key in shapekeyname_mkey_dict.items():
            constants_section.append("; ShapeKey: " + shapekey_name)
            if getattr(m_key, 'key_type', 'key') == "time_shapekey":
                # Runtime animation state must not be restored on reload.
                # Persist assignments mark user_config_dirty; they do not
                # themselves write d3dx_user.ini on every rendered frame.
                constants_section.append("global " + m_key.key_name + " = " + str(m_key.initialize_value))
            else:
                constants_section.append("global persist " + m_key.key_name + " = " + str(m_key.initialize_value))
            constants_section.new_line()

        ini_builder.append_section(constants_section)

        # [Present]
        present_section = M_IniSection(M_SectionType.Present)
        present_section.append("[Present]")
        # The shader copies its seed once per run. A second first-run dispatch
        # only duplicated work and a persisted initialization flag was unsafe
        # after reload; neither is needed for a freshly allocated accumulator.

        # Time Shape Key timelines: update the weight variables from
        # wall-clock time BEFORE the compute dispatches below read them, so
        # subsequent draws use these weights and the matching position seed.
        for shapekey_name, m_key in shapekeyname_mkey_dict.items():
            if getattr(m_key, 'key_type', 'key') == "time_shapekey":
                present_section.append("; ShapeKey time timeline: " + shapekey_name)
                M_IniHelper.add_time_animation_sections(ini_builder, present_section, m_key)

        ib_number = 1
        for drawib, drawib_model in drawib_drawibmodel_dict.items():
            shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})

            # If the current DrawIB has no shape key data, skip it
            if not shapekey_buffer_dict:
                continue

            # Run after input events and the position-frame post hook. This
            # keeps hotkey gates, animated seeds and shape weights coherent.
            present_section.append("post run = CustomShaderComputeShapes" + str(ib_number))
            ib_number += 1

        ini_builder.append_section(present_section)
        
        # [CustomShaderComputeShapes]
        customshader_section = M_IniSection(M_SectionType.CommandList)

        ib_number = 1
        for drawib, drawib_model in drawib_drawibmodel_dict.items():
            shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
            d3d11_game_type = getattr(drawib_model, "d3d11_game_type", None)
            draw_number = getattr(drawib_model, "draw_number", getattr(drawib_model, "vertex_count", 0))

            # If the current DrawIB has no shape key data, skip it
            if not shapekey_buffer_dict or d3d11_game_type is None:
                continue

            customshader_section.append("[CustomShaderComputeShapes" + str(ib_number) + "]")
            customshader_section.append("cs = " + shader_by_drawib[drawib])
            # CustomShader does not automatically restore borrowed CS slots.
            # Save references before binding our resources, then restore below.
            for slot in ("cs-u5", "cs-t50", "cs-t51"):
                customshader_section.append("Resource" + drawib + "ShapeBackup_" + slot + " = ref " + slot)
            seed = "Resource" + drawib + "Position.1"
            if getattr(drawib_model, "time_pos_frame_groups", None):
                seed = "Resource" + drawib + "PositionTimeBase"
            customshader_section.append("cs-u5 = copy " + seed)
            customshader_section.new_line()

            # Compute for each shape key buffer
            for shapekey_name, m_key in shapekeyname_mkey_dict.items():
                # This is obviously problematic: what if one DrawIB has this shape key but another DrawIB does not?
                # Then in-game models without this shape key would malfunction
                # So if this DrawIB does not have this shape key, skip generating its compute code
                if shapekey_buffer_dict.get(shapekey_name, None) is None:
                    continue

                customshader_section.append("x88 = " + m_key.key_name)
                # Immutable structured SRVs can be referenced without a GPU copy.
                # Keep the original reference even when the accumulation seed
                # came from PositionTimeBase, so shape deltas remain invariant.
                customshader_section.append("cs-t50 = ref Resource" + drawib + "Position.1")
                customshader_section.append("cs-t51 = ref Resource" + drawib + "Position." + shapekey_name)
                customshader_section.append("Dispatch = " + str((draw_number + 63) // 64) + ",1,1")
                customshader_section.new_line()

            ib_number += 1

            # D3D11 rejects STRUCTURED combined with VERTEX_BUFFER bindings.
            # Copy bytes into an explicitly raw vertex buffer before exposing
            # the result to normal draws; type alone does not clear old flags.
            customshader_section.append("Resource" + drawib + "PositionComputed = copy cs-u5")
            customshader_section.append("Resource" + drawib + "Position = ref Resource" + drawib + "PositionComputed")
            for slot in ("cs-u5", "cs-t50", "cs-t51"):
                customshader_section.append(slot + " = ref Resource" + drawib + "ShapeBackup_" + slot)

        ini_builder.append_section(customshader_section)

        # [Resources]
        resource_section = M_IniSection(M_SectionType.ResourceBuffer)


        ib_number = 1
        for drawib, drawib_model in drawib_drawibmodel_dict.items():
            shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
            d3d11_game_type = getattr(drawib_model, "d3d11_game_type", None)

            # If the current DrawIB has no shape key data, skip it
            if not shapekey_buffer_dict or d3d11_game_type is None:
                continue

            # Explicit flags replace the structured descriptor inherited by
            # CopyResource. RAW permits vertex binding; STRUCTURED does not.
            resource_section.append("[Resource" + drawib + "PositionComputed]")
            resource_section.append("type = ByteAddressBuffer")
            resource_section.append("misc_flags = buffer_allow_raw_views")
            resource_section.append("bind_flags = vertex_buffer")
            resource_section.append("stride = " + str(d3d11_game_type.CategoryStrideDict["Position"]))
            resource_section.new_line()
            # Scratch resources hold the game's borrowed CS bindings.
            for slot in ("cs-u5", "cs-t50", "cs-t51"):
                resource_section.append("[Resource" + drawib + "ShapeBackup_" + slot + "]")
                resource_section.new_line()
            resource_section.append("[Resource" + drawib + "Position.1]")
            resource_section.append("type = StructuredBuffer")
            resource_section.append("stride = " + str(d3d11_game_type.CategoryStrideDict["Position"]))
            resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(drawib_model.get_category_buffer_filename("Position")))
            resource_section.new_line()

            # Buffers for each shape key
            for shapekey_name, m_key in shapekeyname_mkey_dict.items():
                # This is obviously problematic: what if one DrawIB has this shape key but another DrawIB does not?
                # Then in-game models without this shape key would malfunction
                # So if this DrawIB does not have this shape key, skip generating its compute code
                if shapekey_buffer_dict.get(shapekey_name, None) is None:
                    continue
                
                resource_section.append("[Resource" + drawib + "Position." + shapekey_name + "]")
                resource_section.append("type = StructuredBuffer")
                resource_section.append("stride = " + str(d3d11_game_type.CategoryStrideDict["Position"]))
                resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(drawib + "-" + "Position." + shapekey_name + ".buf"))
                resource_section.new_line()

            ib_number += 1
        
        ini_builder.append_section(resource_section)

        # [Key]
        # Keys for press testing; can also serve as hotkeys to toggle shape keys when no panel exists
        key_section = M_IniSection(M_SectionType.Key)
        for shapekey_name, m_key in shapekeyname_mkey_dict.items():
            # Time weights do not get a classic weight-cycle key. Optional
            # playback toggles were already emitted by the timeline writer.
            if getattr(m_key, 'key_type', 'key') == "time_shapekey":
                continue
            if m_key.initialize_vk_str != "":
                key_section.append("[Key_ShapeKey_" +shapekey_name + "]")
                
                # Append the remark line
                comment = getattr(m_key, 'comment', '')
                if comment:
                    # Prefix every line so pasted remarks cannot become INI commands.
                    # Keep the leading block readable by external UI builders.
                    for comment_line in comment.splitlines():
                        key_section.append("; " + comment_line)
                
                key_section.append("key = " + m_key.initialize_vk_str)
                key_section.append("type = cycle")
                key_section.append(m_key.key_name + " = 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1")
                key_section.new_line()

        ini_builder.append_section(key_section)



    @staticmethod
    def add_branch_key_sections(ini_builder:M_IniBuilder, key_name_mkey_dict:dict[str,M_Key], blueprint_model=None, drawib_models=None):
        # Split the variables by their driver kind:
        # - "key"  : cycled by a hotkey [Key] section (classic Switch Key node).
        # - "time" : recomputed every frame from 3Dmigoto's built-in wall-clock
        #            "time" operand in the [Present] command list (Time Switch
        #            and Time Position Switch nodes).
        time_mkey_list = [mkey for mkey in key_name_mkey_dict.values() if getattr(mkey, 'key_type', 'key') == "time"]

        if len(key_name_mkey_dict.keys()) != 0:
            constants_section = M_IniSection(M_SectionType.Constants)
            constants_section.SectionName = "Constants"

            for i in range(GlobalConfig.generated_mod_number):
                constants_section.append("global $active" + str(i))

            # One flag for "any part of this mod is on screen". Hotkeys use it
            # instead of a single $activeN, because a mod may consist of several
            # draw ranges and only one of them is usually visible: binding the
            # keys to $active0 made them dead whenever that first range was off
            # screen.
            constants_section.append("global $mod_visible = 0")

            for mkey in key_name_mkey_dict.values():
                if getattr(mkey, 'key_type', 'key') == "time":
                    # Timeline indices are runtime-only, not user settings.
                    # Persist would mark settings dirty and restore an obsolete
                    # phase on reload, even though assignments do not write disk.
                    constants_section.append("global " + mkey.key_name + " = " + str(mkey.initialize_value))
                else:
                    key_str = "global persist " + mkey.key_name + " = " + str(mkey.initialize_value)
                    constants_section.append(key_str) 

            ini_builder.append_section(constants_section)


        if len(key_name_mkey_dict.keys()) != 0:
            present_section = M_IniSection(M_SectionType.Present)
            present_section.SectionName = "Present"

            for i in range(GlobalConfig.generated_mod_number):
                present_section.append("post $active" + str(i) + " = 0")
            # Cleared together with the per range flags, set again by whichever
            # draw range is drawn in the frame that follows.
            present_section.append("post $mod_visible = 0")

            # Recompute every time-driven variable once per frame.  [Present]
            # is a command list run at every DXGI::Present call (3Dmigoto
            # HackerDXGI.cpp, RunFrameActions), and "time" evaluates to
            # wall-clock seconds since injection (CommandList.cpp,
            # ParamOverrideType::TIME), so the animation speed never depends
            # on the game's frame rate.
            #
            # Float32 rounding near the period boundary can yield count.
            # M_Key adds a final modulo after floor division to keep the
            # selected index in range. Modulo cannot restore uptime precision
            # already lost by the engine's float32 wall-clock operand.
            for mkey in time_mkey_list:
                # The shared writer keeps autoplay compatible and schedules
                # optional switch updates after input, before Position copies.
                if mkey.comment:
                    present_section.append("; " + mkey.comment)
                M_IniHelper.add_time_animation_sections(ini_builder, present_section, mkey)
            ini_builder.append_section(present_section)
        
        key_number = 0
        if len(key_name_mkey_dict.keys()) != 0:

            for mkey in key_name_mkey_dict.values():
                # Only classic branch-cycle keys belong here. Optional time
                # playback toggles were already emitted by the common driver.
                if getattr(mkey, 'key_type', 'key') == "time":
                    continue

                key_section = M_IniSection(M_SectionType.Key)
                key_section.append("[KeySwap_" + str(key_number) + "]")
                
                # Append the remark line
                comment = getattr(mkey, 'comment', '')
                if comment:
                    # Prefix every line so pasted remarks cannot become INI commands.
                    # Keep the leading block readable by external UI builders.
                    for comment_line in comment.splitlines():
                        key_section.append("; " + comment_line)
                
                # key_section.append("condition = $active" + str(key_number) + " == 1")

                # Any visible draw range of this mod activates the hotkeys. A
                # mod can consist of several draw ranges and the keys must work
                # whichever of them is currently on screen.
                key_section.append("condition = $mod_visible == 1")

                if mkey.initialize_vk_str != "":
                    key_section.append("key = " + mkey.initialize_vk_str)
                else:
                    key_section.append("key = " + mkey.key_value)
                key_section.append("type = cycle")

                key_cycle_str = ",".join(str(i) for i in range(len(mkey.value_list)))
                key_section.append(mkey.key_name + " = " + key_cycle_str)
                key_section.new_line()
                ini_builder.append_section(key_section)

                key_number = key_number + 1

        # Time Position Switch: per-frame Position resources + the [Present]
        # copy lines that swap the real Position buffer content.  Appended
        # after the Present section above, so the timeline variables are
        # updated before the copies read them within the same frame.
        if blueprint_model is not None:
            from .m_time_position import append_time_position_sections
            append_time_position_sections(
                ini_builder=ini_builder,
                blueprint_model=blueprint_model,
                drawib_models=drawib_models,
            )
