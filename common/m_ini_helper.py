import os
import re
import shutil

from .m_ini_builder import *
from .m_control_flow import M_ControlFlow
from .m_key import M_Key
from .texture_naming import default_texture_resource_name, normalize_texture_role
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

        # Strategy 2: scan the TYPE_<gametype> folders of all submeshes
        for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
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
                    for row in getattr(draw_model, "resolved_hash_texture_binding_list", None) or []:
                        managed_hash_set.add(str(row.get("texture_hash", "") or "").strip().lower())

        # Global rows are not attached to a DrawIB, so they need an explicit
        # second collection pass before the automatic hash pipeline runs.
        for row in global_hash_texture_binding_list or []:
            if not row.get("enabled", True) or row.get("restore_original", False):
                continue
            managed_hash_set.add(str(row.get("texture_hash", "") or "").strip().lower())

        managed_hash_set.discard("")
        return managed_hash_set

    @classmethod
    def generate_hash_style_global_texture_ini(
        cls,
        ini_builder: M_IniBuilder,
        global_hash_texture_binding_list: list | None,
    ):
        '''Emit unconditional replacements from unconnected global hash nodes.'''
        # Resolve and validate every row before copying anything. This keeps a
        # broken row from leaving a half-written global texture set behind.
        resolved_rows = []
        seen_hashes = set()
        # A replacement in another global node takes precedence over restoring
        # a cleared row. Restoration must not claim a managed hash or emit INI.
        active_hashes = {
            str(row.get("texture_hash", "")).strip().lower()
            for row in global_hash_texture_binding_list or []
            if row.get("enabled", True) and not row.get("restore_original", False)
        }
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

                # Stable hash-based names make the generated texture easy to
                # find and prevent two source basenames from colliding.
                resource_name = "ResourceHashGlobal_" + texture_hash
                target_filename = texture_hash + "_global" + file_suffix
                if binding.get("preserve_mark_filename", False):
                    # Scanned replacements keep the familiar hash/mark name.
                    # Keep the real extension for PNG/JPEG too; never disguise
                    # encoded image bytes as DDS by changing only the suffix.
                    role = normalize_texture_role(binding.get("mark_name", ""))
                    target_filename = texture_hash + "_" + role + file_suffix
                resolved_rows.append({
                    "texture_hash": texture_hash,
                    "resource_name": resource_name,
                    "target_filename": target_filename,
                    "source_path": source_path,
                    "restore_original": restore_original,
                })
            elif source_type == "RESOURCE":
                resource_name = str(binding.get("resource_name", "") or "").strip()
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

        # Copy explicit global files on every export. A changed source must
        # replace the previous generated copy instead of leaving stale bytes.
        output_folder = GlobalConfig.path_generatemod_texture_folder(draw_ib="global")
        os.makedirs(output_folder, exist_ok=True)
        for row in resolved_rows:
            source_path = row["source_path"]
            if not source_path:
                continue
            target_path = os.path.join(output_folder, row["target_filename"])
            source_key = os.path.normcase(os.path.abspath(source_path))
            target_key = os.path.normcase(os.path.abspath(target_path))
            if source_key == target_key:
                continue
            shutil.copy2(source_path, target_path)

        # Keep resource declarations before all hash overrides. The separate
        # section types also preserve the intended order when a global default
        # and a conditional object row target the same hash.
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
            override_section.append("[TextureOverride_Texture_" + row["texture_hash"] + "_Global]")
            override_section.append("hash = " + row["texture_hash"])
            override_section.append("match_priority = 0")
            override_section.append("this = " + resource_name)
            override_section.new_line()

        ini_builder.append_section(resource_section)
        ini_builder.append_section(override_section)

    @classmethod
    def generate_hash_style_object_texture_ini(cls, ini_builder: M_IniBuilder, drawib_drawibmodel_dict: dict):
        '''Conditional hash-style overrides driven by Hash Texture Bind nodes.

        One [TextureOverride_Texture_<hash>_Switch] section per managed hash,
        shared by the whole blueprint: every resolved binding row becomes an
        if/endif block around "this = ResourceXXX", so the switch conditions
        collected upstream decide which texture is bound. Rows without a
        condition become a plain unconditional this= line.

        Emitted even when forbid_auto_texture_ini is on, for the same reason
        as the slot bindings: a Hash Texture Bind node is explicit user
        intent, not part of the automatic texture pipeline.
        '''
        # hash -> ordered list of (condition_str, resource_name)
        binding_entry_dict: dict[str, list] = {}
        for draw_ib_model in drawib_drawibmodel_dict.values():
            for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
                for draw_model in getattr(submesh_model, "drawcall_model_list", []):
                    for row in getattr(draw_model, "resolved_hash_texture_binding_list", None) or []:
                        texture_hash = str(row.get("texture_hash", "") or "").strip().lower()
                        if not texture_hash:
                            continue
                        condition_str = str(row.get("condition_str", "") or "").strip()
                        resource_name = str(row.get("resource_name", "") or "").strip()
                        binding_entry_dict.setdefault(texture_hash, []).append((condition_str, resource_name))

        if not binding_entry_dict:
            return

        for texture_hash, entry_list in binding_entry_dict.items():
            # Normalize: identical (condition, resource) pairs dedupe, the
            # same condition with two different resources is a contradiction
            # and mixing an unconditional row with conditional ones makes the
            # result depend on line order, so both fail loudly.
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

            if has_unconditional and len(condition_order) > 1:
                raise ValueError(
                    "Hash Texture Bind: texture hash " + texture_hash + " mixes an unconditional binding with "
                    + str(len(condition_order) - 1) + " conditional one(s); connect every branch through an explicit switch so the replacement states stay unambiguous."
                )

            switch_section = M_IniSection(M_SectionType.TextureOverrideTexture)
            switch_section.append("[TextureOverride_Texture_" + texture_hash + "_Switch]")
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
    ):
        """
        Hash style textures: generate texture config sections (Resource_Texture + TextureOverride) and copy the texture files.
        Overall flow: iterate over DrawIB -> iterate over SubMesh -> process each texture.
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
                        "[TextureOverride_" + texture_markup_info.mark_hash + "]",
                    )
                    resource_texture_section.append(
                        "; " + texture_markup_info.mark_filename,
                    )
                    resource_texture_section.append(
                        "hash = " + texture_markup_info.mark_hash,
                    )
                    resource_texture_section.append("match_priority = 0")
                    resource_texture_section.append(
                        "this = " + hash_style_resource_name,
                    )
                    resource_texture_section.new_line()
                    ini_builder.append_section(resource_texture_section)

                    # Copy the texture file (do not overwrite existing ones, keeping manual replacements)
                    if not os.path.exists(target_texture_file_path):
                        shutil.copy2(original_texture_file_path, target_texture_file_path)

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

                        # Copy the file (dedupe)
                        target_texture_file_path = (
                            GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib)
                            + hash_style_texture_filename
                        )
                        if not os.path.exists(target_texture_file_path):
                            shutil.copy2(original_texture_file_path, target_texture_file_path)

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

                if os.path.exists(target_path):
                    print("[TRACE] Slot texture target already exists, skip copy: " + target_path)
                    slot_skipped_exists += 1
                else:
                    if source_path == "":
                        print("[TRACE] Slot texture source_path is empty, skip! mark_filename=" + texture_markup_info.mark_filename)
                        slot_skipped_no_source += 1
                        continue
                    if not os.path.exists(source_path):
                        print("[TRACE] Slot texture source_path file does not exist, skip! source_path=" + source_path)
                        slot_skipped_no_source += 1
                        continue
                    print("[TRACE] >>> Executing shutil.copy2: " + source_path + " -> " + target_path)
                    try:
                        shutil.copy2(source_path,target_path)
                        print("[TRACE] <<< shutil.copy2 succeeded: " + target_path)
                        slot_copied += 1
                    except Exception as e:
                        print("[TRACE] <<< shutil.copy2 failed! Exception: " + str(e))

        print("[TRACE] move_slot_style_textures() summary - DrawIB: " + draw_ib_model.draw_ib)
        print("[TRACE]   Slot copied: " + str(slot_copied))
        print("[TRACE]   Slot skipped (target exists): " + str(slot_skipped_exists))
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

        resource_texture_section = M_IniSection(M_SectionType.ResourceTexture)
        appended_resource_names = set()
        for resource_name, target_filename in resource_entries:
            if resource_name in appended_resource_names:
                continue
            appended_resource_names.add(resource_name)
            resource_texture_section.append("[" + resource_name + "]")
            resource_texture_section.append("filename = " + GlobalConfig.ini_texture_filename(target_filename))
            resource_texture_section.new_line()

        ini_builder.append_section(resource_texture_section)

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

        texture_output_folder = GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib_model.draw_ib)
        os.makedirs(texture_output_folder, exist_ok=True)

        copied_count = 0
        skipped_count = 0
        for resource_name, source_path, target_filename in file_list:
            target_path = os.path.join(texture_output_folder, target_filename)
            if not os.path.exists(source_path):
                print("M_IniHelper: Texture Bind source file missing, skip copy: " + source_path)
                continue

            # Avoid a SameFileError when a source already lives in the output
            # folder, but overwrite an existing target when it came from a
            # different source selected in the node.
            source_key = os.path.normcase(os.path.abspath(source_path))
            target_key = os.path.normcase(os.path.abspath(target_path))
            if source_key == target_key:
                skipped_count += 1
                continue
            shutil.copy2(source_path, target_path)
            copied_count += 1

        print(
            "M_IniHelper: Texture Bind texture copy done, DrawIB: " + draw_ib_model.draw_ib
            + ", copied: " + str(copied_count) + ", skipped (source already is target): " + str(skipped_count)
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
                # The shared result is a raw vertex buffer, not a skinning hook.
                # Raw GPU skinning needs a game-specific conversion/hook (as
                # Naraka provides), not a silent reference to this accumulator.
                if getattr(model.d3d11_game_type, "GPU_PreSkinning", False):
                    raise ValueError("Shared shape keys do not support this GPU pre-skinning path; use DrawIndexed animation")
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
                    key_section.append("; " + comment)
                
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
                    key_section.append("; " + comment)
                
                # key_section.append("condition = $active" + str(key_number) + " == 1")

                # XXX: due to a BUG here, we always use $active0 to detect activation; not making it more complex.
                key_section.append("condition = $active0 == 1")

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
