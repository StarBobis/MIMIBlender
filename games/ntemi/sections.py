"""
NTMIv1 INI section builders.

Every builder appends plain text lines to a shared line list; the exporter
assembles them in order and hands the final list to write_ini().  NTEMI
uses its own minimal INI writer (no section reordering), so the append
order here is exactly the output order.
"""

import hashlib

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_helper import M_IniHelper
from ...common.m_ini_builder import get_xxmi_tail_comment_lines
from ...common.global_config import GlobalConfig
from .parts import resource_token, part_name

# NTMIv1 compute shader slot bindings (standard for the NTMIv1 skinning framework)
_NTMI_SKIN_T_GLOBAL_T0 = "cs-t64"
_NTMI_SKIN_T_PALETTE = "cs-t65"
_NTMI_SKIN_T_BLEND = "cs-t66"
_NTMI_SKIN_T_FRAME = "cs-t67"
_NTMI_SKIN_T_POSITION = "cs-t68"
_NTMI_SKIN_T_SHAPEKEY_STATIC = "cs-t69"
_NTMI_SKIN_T_SHAPEKEY_RUNTIME = "cs-t70"
_NTMI_SKIN_U_NORMAL = "cs-u6"
_NTMI_SKIN_U_POSITION = "cs-u7"

# Core NTMIv1 resources and commands
_NTMI_CORE_GLOBAL_T0_RESOURCE = "Resource\\NTMIv1\\RuntimeGlobalT0"
_NTMI_CORE_SKIN_COMMAND = "Resource\\NTMIv1\\SkinFromBoundSlots"
_NTMI_CORE_VERTEX_COUNT = "cs-cb1[0]"

_DEFAULT_DYNAMIC_SLOTS = 16


def source_suffix(drawib_model_list) -> str:
    """Suffix shared by the collector and the skin command list names."""
    if drawib_model_list:
        return drawib_model_list[0].draw_ib
    return "shared"


def append_constants(lines: list[str]):
    lines.extend([
        "[Constants]",
        "global $ntemi_mod_enabled = 0",
    ])
    lines.append("")


def append_present(lines: list[str]):
    lines.extend([
        "[Present]",
        "if $ntemi_mod_enabled",
        "  run = CommandListNTMISetupResources",
        "endif",
        "",
    ])


def append_setup_commandlist(lines: list[str]):
    lines.extend([
        "[CommandListNTMISetupResources]",
        "$ntemi_mod_enabled = 1",
        "",
    ])


def append_resource_sections(lines: list[str], drawib_model_list, source_suffix_str: str):
    """Resource declarations of every part: palette, runtime skinned buffers,
    IB and the pre-CS category buffers."""
    lines.append("; MARK: NTMIv1 Resources")
    lines.append("")

    for drawib_model in drawib_model_list:
        for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
            name = part_name(drawib_model, part_index, submesh_model)
            token = resource_token(name)
            vertex_count = get_vertex_count(submesh_model)
            position_float_count = vertex_count * 3
            normal_row_count = vertex_count * 2

            # Buffer files live in the Buffers subfolder, so every INI filename
            # below carries the subfolder prefix.
            palette_file = GlobalConfig.ini_buffer_filename(palette_filename(submesh_model))
            buffers = {
                "position": GlobalConfig.ini_buffer_filename(f"{name}-position.buf"),
                "blend": GlobalConfig.ini_buffer_filename(f"{name}-blend.buf"),
                "normal": GlobalConfig.ini_buffer_filename(f"{name}-normal.buf"),
                "texcoord": GlobalConfig.ini_buffer_filename(f"{name}-texcoord.buf"),
                "outline": GlobalConfig.ini_buffer_filename(f"{name}-outline.buf"),
                "ib": GlobalConfig.ini_buffer_filename(f"{name}-ib.buf"),
            }
            ib_format = "DXGI_FORMAT_R16_UINT"
            ib = submesh_model.ib
            if ib and max(ib) > 65535:
                ib_format = "DXGI_FORMAT_R32_UINT"

            lines.extend([
                f"; [part:{name}]",
                f"[ResourcePalette_{token}]",
                "type = Buffer",
                "format = R32_UINT",
                f"filename = {palette_file}",
                "",
                f"[ResourcePart_{token}_RuntimeSkinnedPosition_UAV]",
                f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                "type = RWBuffer",
                "format = R32_FLOAT",
                f"array = {position_float_count}",
                "",
                f"[ResourcePart_{token}_RuntimeSkinnedPosition]",
                f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                "type = Buffer",
                "format = R32_FLOAT",
                f"array = {position_float_count}",
                "",
                f"[ResourcePart_{token}_RuntimeSkinnedPositionVB]",
                f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                "type = Buffer",
                "stride = 12",
                "",
                f"[ResourcePart_{token}_RuntimeSkinnedNormal_UAV]",
                f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                "type = RWBuffer",
                "format = R16G16B16A16_SNORM",
                f"array = {normal_row_count}",
                "",
                f"[ResourcePart_{token}_RuntimeSkinnedNormal]",
                f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                "type = Buffer",
                "format = R16G16B16A16_SNORM",
                f"array = {normal_row_count}",
                "",
                f"[ResourcePart_{token}_RuntimePrevSkinnedPosition]",
                f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                f"dynamic_prev_of = ResourcePart_{token}_RuntimeSkinnedPosition",
                "type = Buffer",
                "format = R32_FLOAT",
                f"array = {position_float_count}",
                "",
                f"[ResourcePart_{token}_IB]",
                "type = Buffer",
                f"format = {ib_format}",
                f"filename = {buffers['ib']}",
                "",
                f"[ResourcePart_{token}_Position]",
                "type = Buffer",
                "format = R32_FLOAT",
                f"filename = {buffers['position']}",
                "",
                f"[ResourcePart_{token}_PositionVB]",
                "type = Buffer",
                "stride = 12",
                f"filename = {buffers['position']}",
                "",
                f"[ResourcePart_{token}_Blend]",
                "type = StructuredBuffer",
                "stride = 8",
                f"filename = {buffers['blend']}",
                "",
                f"[ResourcePart_{token}_BlendTyped]",
                "type = Buffer",
                "format = R32_UINT",
                f"filename = {buffers['blend']}",
                "",
                f"[ResourcePart_{token}_Normal]",
                "type = Buffer",
                "format = R8G8B8A8_SNORM",
                f"filename = {buffers['normal']}",
                "",
                f"[ResourcePart_{token}_Texcoord]",
                "type = Buffer",
                "format = R16G16_FLOAT",
                f"filename = {buffers['texcoord']}",
                "",
                f"[ResourcePart_{token}_OutlineParam]",
                "type = Buffer",
                "format = R8G8B8A8_UNORM",
                f"filename = {buffers['outline']}",
                "",
            ])


def append_collector(lines: list[str], source_suffix_str: str, drawib_model_list):
    """Write the Collector section for bone matrix gathering.

    Uses CB4Hash and CategoryHash from the import metadata where available.
    Values that require FrameAnalysis data are marked with comments.
    """
    lines.append("; MARK: Skin dispatch. Collector gathers BoneAtlas pieces, builds RuntimeGlobalT0, then runs skin.")
    lines.append(f"[CollectorSkinPart_{source_suffix_str}]")

    # Derive collector config from available metadata
    collector_config = derive_collector_config(drawib_model_list)
    lines.append(f"group = {collector_config['group']}")
    if collector_config.get("match_cs_t0_hash"):
        lines.append(f"match_cs_t0_hash = {collector_config['match_cs_t0_hash']}")
    lines.append(f"match_cs_u0_hash = {collector_config['match_cs_u0_hash']}")
    lines.append(f"match_cs_u1_hash = {collector_config['match_cs_u1_hash']}")
    lines.append(f"collect = write, cs-t0, {collector_config['collect_key']}")
    lines.append(f"build = {_NTMI_CORE_GLOBAL_T0_RESOURCE}")

    for drawib_model in drawib_model_list:
        for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
            name = part_name(drawib_model, part_index, submesh_model)
            token = resource_token(name)
            lines.append(
                f"map = "
                f"cs-u1:ResourcePart_{token}_RuntimeSkinnedPosition, "
                f"cs-u1:ResourcePart_{token}_RuntimeSkinnedPositionVB, "
                f"cs-u0:ResourcePart_{token}_RuntimeSkinnedNormal"
            )

    lines.append(f"run = CommandList_SkinParts_{source_suffix_str}")
    lines.append("")


def derive_collector_config(drawib_model_list) -> dict:
    """Derive collector configuration from import metadata."""
    config = {
        "group": "u0",
        "match_cs_t0_hash": "",
        "match_cs_u0_hash": "",
        "match_cs_u1_hash": "",
        "collect_key": "",
    }

    for drawib_model in drawib_model_list:
        import_dict = getattr(drawib_model, 'import_json_dict', None) or {}
        if not config["match_cs_t0_hash"]:
            config["match_cs_t0_hash"] = import_dict.get("CB4Hash", "")
        if not config["collect_key"]:
            # Use the first submesh's combined hash as collect key
            cat_hash = import_dict.get("CategoryHash", {})
            if cat_hash:
                config["collect_key"] = list(cat_hash.values())[0] if isinstance(cat_hash, dict) else str(cat_hash)
        # cs-u0/u1 hashes typically come from FrameAnalysis. Without it,
        # use CategoryHash entries as best guess.
        if not config["match_cs_u0_hash"] or not config["match_cs_u1_hash"]:
            cat_hash = import_dict.get("CategoryHash", {})
            if isinstance(cat_hash, dict):
                hashes = list(cat_hash.values())
                if len(hashes) >= 2:
                    if not config["match_cs_u0_hash"]:
                        config["match_cs_u0_hash"] = str(hashes[0])
                    if not config["match_cs_u1_hash"]:
                        config["match_cs_u1_hash"] = str(hashes[1])
                elif len(hashes) == 1:
                    if not config["match_cs_u0_hash"]:
                        config["match_cs_u0_hash"] = str(hashes[0])
                    if not config["match_cs_u1_hash"]:
                        config["match_cs_u1_hash"] = str(hashes[0])

    return config


def append_skin_commandlist(lines: list[str], source_suffix_str: str, drawib_model_list):
    """The command list that skins every part and copies the results out of
    the UAVs into the runtime buffers."""
    lines.append(f"[CommandList_SkinParts_{source_suffix_str}]")
    lines.append(f"{_NTMI_SKIN_T_GLOBAL_T0} = {_NTMI_CORE_GLOBAL_T0_RESOURCE}")
    lines.append("")

    for drawib_model in drawib_model_list:
        for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
            name = part_name(drawib_model, part_index, submesh_model)
            token = resource_token(name)

            lines.extend([
                f"{_NTMI_SKIN_T_PALETTE} = ResourcePalette_{token}",
                f"{_NTMI_CORE_VERTEX_COUNT} = {get_vertex_count(submesh_model)}",
                f"{_NTMI_SKIN_T_BLEND} = ResourcePart_{token}_BlendTyped",
                f"{_NTMI_SKIN_T_FRAME} = ResourcePart_{token}_Normal",
                f"{_NTMI_SKIN_T_POSITION} = ResourcePart_{token}_Position",
                f"{_NTMI_SKIN_U_NORMAL} = ResourcePart_{token}_RuntimeSkinnedNormal_UAV",
                f"{_NTMI_SKIN_U_POSITION} = ResourcePart_{token}_RuntimeSkinnedPosition_UAV",
                f"run = {_NTMI_CORE_SKIN_COMMAND}",
                f"ResourcePart_{token}_RuntimeSkinnedPosition = copy ResourcePart_{token}_RuntimeSkinnedPosition_UAV",
                f"ResourcePart_{token}_RuntimeSkinnedPositionVB = copy ResourcePart_{token}_RuntimeSkinnedPosition_UAV",
                f"ResourcePart_{token}_RuntimeSkinnedNormal = copy ResourcePart_{token}_RuntimeSkinnedNormal_UAV",
                "",
            ])

    # Null all bindings after skinning
    lines.extend([
        f"{_NTMI_SKIN_T_GLOBAL_T0} = null",
        f"{_NTMI_SKIN_T_PALETTE} = null",
        f"{_NTMI_SKIN_T_BLEND} = null",
        f"{_NTMI_SKIN_T_FRAME} = null",
        f"{_NTMI_SKIN_T_POSITION} = null",
        f"{_NTMI_SKIN_T_SHAPEKEY_STATIC} = null",
        f"{_NTMI_SKIN_T_SHAPEKEY_RUNTIME} = null",
        f"{_NTMI_SKIN_U_NORMAL} = null",
        f"{_NTMI_SKIN_U_POSITION} = null",
        "",
    ])


def append_draw_overrides(lines: list[str], drawib_model_list,
                          draw_ib_active_index_dict: dict, source_suffix_str: str,
                          keyname_mkey_dict: dict):
    """Draw replacement: skip the original draw and re-emit every part with
    the runtime skinned buffers bound."""
    lines.append("; MARK: Draw replacement")
    lines.append("")

    for drawib_model in drawib_model_list:
        draw_ib = drawib_model.draw_ib
        active_index = draw_ib_active_index_dict.get(draw_ib, 0)

        # Resolve match hashes from import metadata
        import_dict = getattr(drawib_model, 'import_json_dict', None) or {}
        category_hash = import_dict.get("CategoryHash", {})
        texcoord_hash = str(category_hash.get("Texcoord", "")) if isinstance(category_hash, dict) else ""
        position_hash = str(category_hash.get("Position", "")) if isinstance(category_hash, dict) else ""
        outline_hash = str(category_hash.get("Color", "")) if isinstance(category_hash, dict) else ""

        # Total index count for the region
        total_index_count = sum(
            sm.match_index_count for sm in drawib_model.submesh_model_list
            if sm.match_index_count > 0
        )
        if total_index_count == 0:
            total_index_count = drawib_model.index_count

        first_index = 0
        if drawib_model.submesh_model_list:
            first_indices = [sm.match_first_index for sm in drawib_model.submesh_model_list if sm.match_first_index >= 0]
            if first_indices:
                first_index = min(first_indices)

        lines.extend([
            f"[TextureOverride_IB_{draw_ib}_{total_index_count}_{first_index}]",
            f"hash = {draw_ib}",
        ])
        if first_index > 0:
            lines.append(f"match_first_index = {first_index}")
        lines.extend([
            f"match_index_count = {total_index_count}",
            "handling = skip",
            f"collector = CollectorSkinPart_{source_suffix_str}, vb0",
        ])

        for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
            name = part_name(drawib_model, part_index, submesh_model)
            token = resource_token(name)

            lines.extend([
                f"; [part:{name}] [vertex_count:{get_vertex_count(submesh_model)}]",
                f"ib = ResourcePart_{token}_IB",
                f"match = vb, dynamic, ResourcePart_{token}_RuntimeSkinnedPositionVB",
                f"match = vs, dynamic_prev, ResourcePart_{token}_RuntimePrevSkinnedPosition",
            ])
            if texcoord_hash:
                lines.append(f"match = vs, {texcoord_hash}, ResourcePart_{token}_Texcoord")
            if position_hash:
                lines.append(f"match = vs, {position_hash}, ResourcePart_{token}_Position")
            lines.append(f"match = vs, dynamic, ResourcePart_{token}_RuntimeSkinnedNormal")
            if outline_hash:
                lines.append(f"match = vs, {outline_hash}, ResourcePart_{token}_OutlineParam")

            # Texture bindings
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                for tmi in texture_markup_info_list:
                    if getattr(tmi, "mark_type", "") not in ("Slot", "SharedSlot"):
                        continue
                    lines.append(f"{tmi.mark_slot} = {tmi.get_resource_name()}")

            # Draw commands
            for draw_model in submesh_model.drawcall_model_list:
                index_count = draw_model.index_count
                first_idx = draw_model.index_offset
                lines.append(f"; [mesh:{draw_model.obj_name}] [vertex_count:{draw_model.vertex_count}]")
                # Per-object Texture Bind lines: right before this draw, so
                # the replacement only affects this drawindexed call.
                for slot_line in getattr(draw_model, "resolved_texture_slot_lines", None) or []:
                    lines.append(slot_line)
                lines.append(f"drawindexed = {index_count},{first_idx},0")
                for slot_line in getattr(draw_model, "resolved_texture_slot_restore_lines", None) or []:
                    lines.append(slot_line)

            if len(keyname_mkey_dict.keys()) != 0:
                lines.append(f"$active{active_index} = 1")
                # A visible range marks the whole mod as on screen for the hotkeys.
                lines.append("$mod_visible = 1")

        lines.append("")


def append_texture_resources(lines: list[str], drawib_model_list):
    """Append texture resource sections when auto-texture is enabled."""
    if MIMIGlobalProperties.forbid_auto_texture_ini():
        return

    appended: set[str] = set()
    tex_lines: list[str] = []

    for drawib_model in drawib_model_list:
        for idx, submesh_model in enumerate(drawib_model.submesh_model_list):
            for tmi in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                if getattr(tmi, "mark_type", "") != "Slot":
                    continue
                rn = tmi.get_resource_name()
                if rn in appended:
                    continue
                appended.add(rn)
                slot_filename = M_IniHelper._get_slot_style_texture_filename(drawib_model, idx, tmi)
                tex_lines.extend([
                    f"[{rn}]",
                    f"filename = {GlobalConfig.ini_texture_filename(slot_filename)}",
                    "",
                ])

    if tex_lines:
        lines.append("; MARK: Texture resources")
        lines.append("")
        lines.extend(tex_lines)


def append_object_texture_binding_resources(lines: list[str], drawib_model_list):
    """Resource sections of Texture Bind node FILE textures (explicit user
    intent, so this runs even when the automatic texture pipeline is off)."""
    appended: set[str] = set()
    tex_lines: list[str] = []

    for drawib_model in drawib_model_list:
        for resource_name, target_filename in getattr(drawib_model, "object_texture_binding_resource_list", []) or []:
            if resource_name in appended:
                continue
            appended.add(resource_name)
            tex_lines.extend([
                f"[{resource_name}]",
                f"filename = {GlobalConfig.ini_texture_filename(target_filename)}",
                "",
            ])

    if tex_lines:
        lines.append("; MARK: Texture Bind resources")
        lines.append("")
        lines.extend(tex_lines)


def build_branch_key_lines(keyname_mkey_dict: dict) -> list[str]:
    """Branch key sections (one [Key_<name>] section per blueprint key)."""
    lines: list[str] = []
    for key_name, mkey_list in keyname_mkey_dict.items():
        lines.append(f"[Key_{key_name}]")
        for mkey in mkey_list:
            lines.append(f"key = {mkey}")
        lines.append("")
    return lines


def get_vertex_count(submesh_model) -> int:
    """Get the number of vertex rows in the pre-CS buffers from the Position category stride."""
    pos_bytes = submesh_model.category_buffer_dict.get("Position")
    if pos_bytes is not None and submesh_model.d3d11_game_type:
        stride = submesh_model.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        if stride > 0:
            return len(pos_bytes) // stride
    return submesh_model.vertex_count


def palette_filename(submesh_model) -> str:
    """The palette buffer file name of a part (mirrors the buffer writer)."""
    draw_ib = submesh_model.match_draw_ib
    index_count = submesh_model.match_index_count
    chunk_index = submesh_model.match_first_index
    return f"{draw_ib}-{index_count}-{chunk_index}-Palette.buf"


def write_ini(filepath: str, lines: list[str]):
    """Write the INI only when its content changed (sha256 change detection)."""
    # Optional tail comments, added before hashing so toggling the option
    # rewrites the file. sha256 stays the last line.
    tail_lines = get_xxmi_tail_comment_lines()
    if tail_lines:
        lines = lines + [""] + tail_lines
    content = "\n".join(lines)
    # Add SHA256 for change detection
    sha256 = hashlib.sha256(content.encode('utf-8')).hexdigest()
    content += "\n;sha256=" + sha256 + "\n"

    # Check if existing INI has the same hash
    existing_sha = ""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(";sha256="):
                    existing_sha = stripped[len(";sha256="):].strip()
                    break
    except FileNotFoundError:
        pass

    if existing_sha != sha256:
        print("Write new mod ini because sha256 is not same.")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        print("Skip write mod ini because sha256 is same.")
