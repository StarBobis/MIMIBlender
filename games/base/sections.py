"""
Shared INI section builders for the "unity-style" game exporters.

These functions hold the canonical version of every section builder that
used to be copy-pasted across games/unity.py, games/himi.py, games/gimi.py,
games/zzmi.py and games/naraka.py.  Each function appends its sections to
the given M_IniBuilder; games that need a slightly different variant keep
their own builder inside their game package and simply do not call the
shared one.

Conventions:
- ini_builder:    the M_IniBuilder collecting every section of the mod INI.
- drawib_model:   the DrawIBModel whose sections are being generated.
- blueprint_model: the parsed BluePrintModel (used for the $active / $mod_visible key check).
"""

import math

from ...common.global_config import GlobalConfig
from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...common.m_ini_helper import M_IniHelper


# ----------------------------------------------------------------------
# Vertex shader (CPU pre-skinning) section builders
# ----------------------------------------------------------------------

def add_unity_vs_texture_override_vb_sections(ini_builder: M_IniBuilder, drawib_model, blueprint_model):
    """VB overrides: replace every category bind with its resource buffer."""
    d3d11_game_type = drawib_model.d3d11_game_type
    draw_ib = drawib_model.draw_ib

    texture_override_vb_section = M_IniSection(M_SectionType.TextureOverrideVB)
    texture_override_vb_section.append("; " + draw_ib)
    for category_name in d3d11_game_type.OrderedCategoryNameList:
        category_hash = drawib_model.category_hash_dict.get(category_name, "")
        texture_override_vb_name_suffix = "VB_" + draw_ib + "_" + drawib_model.draw_ib_alias + "_" + category_name
        texture_override_vb_section.append("[TextureOverride_" + texture_override_vb_name_suffix + "]")
        texture_override_vb_section.append("hash = " + category_hash)

        for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
            if category_name != draw_category_name:
                continue
            category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
            texture_override_vb_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

        # The Blend draw category carries the skinned draw call.
        draw_category_name = d3d11_game_type.CategoryDrawCategoryDict.get("Blend", None)
        if draw_category_name is not None and category_name == draw_category_name:
            texture_override_vb_section.append("handling = skip")
            texture_override_vb_section.append("draw = " + str(drawib_model.draw_number) + ", 0")

        # Mark the mod as active while this VB is being drawn so the toggle
        # keys only work when the character is on screen.
        if category_name == d3d11_game_type.CategoryDrawCategoryDict["Position"]:
            if len(blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                # A visible range marks the whole mod as on screen for the hotkeys.
                texture_override_vb_section.append("$mod_visible = 1")

        texture_override_vb_section.new_line()

    ini_builder.append_section(texture_override_vb_section)


def add_unity_vs_texture_override_ib_sections(ini_builder: M_IniBuilder, drawib_model, blueprint_model):
    """IB overrides: skip every original draw and re-emit it with the mod IB."""
    texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
    draw_ib = drawib_model.draw_ib

    for submesh_model in drawib_model.submesh_model_list:
        texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
        ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)

        texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
        texture_override_ib_section.append("hash = " + draw_ib)
        texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
        texture_override_ib_section.append("handling = skip")

        # An empty index buffer means the submesh is hidden: null the IB out.
        ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
        if ib_buf is None or len(ib_buf) == 0:
            texture_override_ib_section.append("ib = null")
            texture_override_ib_section.new_line()
            continue

        texture_override_ib_section.append("ib = " + ib_resource_name)

        # Automatic Slot / SharedSlot texture bindings from the Submesh marks.
        if not MIMIGlobalProperties.forbid_auto_texture_ini():
            for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                    texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

        for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
            submesh_model.drawcall_model_list,
            obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
        ):
            texture_override_ib_section.append(drawindexed_str)

    ini_builder.append_section(texture_override_ib_section)


def add_unity_vs_texture_override_vlr_section(ini_builder: M_IniBuilder, drawib_model, include_uav_byte_stride: bool = True):
    """VertexLimitRaise: enlarge the game's original Position VB."""
    d3d11_game_type = drawib_model.d3d11_game_type
    if not d3d11_game_type.GPU_PreSkinning:
        return

    vertexlimit_section = M_IniSection(M_SectionType.TextureOverrideVertexLimitRaise)
    vertexlimit_section_name_suffix = drawib_model.draw_ib + "_" + drawib_model.draw_ib_alias + "_VertexLimitRaise"
    vertexlimit_section.append("[TextureOverride_" + vertexlimit_section_name_suffix + "]")
    vertexlimit_section.append("hash = " + drawib_model.vertex_limit_hash)
    vertexlimit_section.append("override_byte_stride = " + str(d3d11_game_type.CategoryStrideDict["Position"]))
    vertexlimit_section.append("override_vertex_count = " + str(drawib_model.draw_number))
    if include_uav_byte_stride:
        vertexlimit_section.append("uav_byte_stride = 4")
    vertexlimit_section.new_line()
    ini_builder.append_section(vertexlimit_section)


def add_unity_vs_resource_vb_sections(ini_builder: M_IniBuilder, drawib_model, use_display_str: bool = True):
    """Resource declarations for every category buffer and every submesh IB.

    use_display_str picks the IB file name style: aliased exports use
    display_str so the file name matches the alias; SnowBreak / IdentityV
    pass False to keep the raw submesh name (their historical behavior).
    """
    resource_vb_section = M_IniSection(M_SectionType.ResourceBuffer)
    # Buffer files live in the Buffers subfolder; INI lines carry the prefix.
    for category_name in drawib_model.d3d11_game_type.OrderedCategoryNameList:
        resource_vb_section.append("[Resource" + drawib_model.draw_ib + category_name + "]")
        resource_vb_section.append("type = Buffer")
        resource_vb_section.append("stride = " + str(drawib_model.d3d11_game_type.CategoryStrideDict[category_name]))
        resource_vb_section.append("filename = " + GlobalConfig.ini_buffer_filename(drawib_model.get_category_buffer_filename(category_name)))
        resource_vb_section.new_line()

    for submesh_model in drawib_model.submesh_model_list:
        ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
        file_stem = submesh_model.display_str if use_display_str else submesh_model.submesh_name
        resource_vb_section.append("[" + ib_resource_name + "]")
        resource_vb_section.append("type = Buffer")
        resource_vb_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_vb_section.append("filename = " + GlobalConfig.ini_buffer_filename(file_stem + "-Index.buf"))
        resource_vb_section.new_line()

    ini_builder.append_section(resource_vb_section)


def add_resource_texture_sections(ini_builder: M_IniBuilder, drawib_model):
    """Resource declarations for the Slot-style marked textures of this DrawIB."""
    # Texture Bind node FILE resources come first: they are explicit user
    # intent and must exist even when the automatic texture pipeline is off.
    M_IniHelper.add_object_texture_binding_resource_sections(ini_builder=ini_builder, draw_ib_model=drawib_model)

    if MIMIGlobalProperties.forbid_auto_texture_ini():
        return

    resource_texture_section = M_IniSection(M_SectionType.ResourceTexture)
    appended_resource_names = set()
    for idx, submesh_model in enumerate(drawib_model.submesh_model_list):
        for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
            if texture_markup_info.mark_type == "Slot":
                resource_name = texture_markup_info.get_resource_name()
                if resource_name in appended_resource_names:
                    continue
                appended_resource_names.add(resource_name)
                slot_filename = M_IniHelper._get_slot_style_texture_filename(drawib_model, idx, texture_markup_info)
                resource_texture_section.append("[" + texture_markup_info.get_resource_name() + "]")
                resource_texture_section.append("filename = " + GlobalConfig.ini_texture_filename(slot_filename))
                resource_texture_section.new_line()

    ini_builder.append_section(resource_texture_section)


# ----------------------------------------------------------------------
# Compute shader (GPU pre-skinning) section builders
# ----------------------------------------------------------------------

def add_unity_cs_texture_override_vb_sections(ini_builder: M_IniBuilder, drawib_model, blueprint_model, position_pre_dispatch_run: str = ""):
    """VB overrides: Position runs a compute shader that fills the game's VB
    with the modded Position/Blend data; every other category bind (e.g.
    Texcoord) is replaced by a resource buffer directly.

    position_pre_dispatch_run optionally names a command list that is run at
    the top of the Position VB override, before the skinning re-dispatch.
    Naraka uses it to apply shape keys onto the position buffer right before
    the game's skinning compute shader reads it.
    """
    d3d11_game_type = drawib_model.d3d11_game_type
    draw_ib = drawib_model.draw_ib

    if not d3d11_game_type.GPU_PreSkinning:
        return

    texture_override_vb_section = M_IniSection(M_SectionType.TextureOverrideVB)
    texture_override_vb_section.append("; " + draw_ib)
    for category_name in d3d11_game_type.OrderedCategoryNameList:
        category_hash = drawib_model.category_hash_dict.get(category_name, "")
        texture_override_vb_namesuffix = "VB_" + draw_ib + "_" + drawib_model.draw_ib_alias + "_" + category_name

        texture_override_vb_section.append("[TextureOverride_" + texture_override_vb_namesuffix + "]")
        texture_override_vb_section.append("hash = " + category_hash)

        # The command list runs before any binding/dispatch below, so the
        # game's skinning compute shader later reads the already-updated
        # position buffer.
        if (position_pre_dispatch_run
                and category_name == d3d11_game_type.CategoryDrawCategoryDict.get("Position")):
            texture_override_vb_section.append("run = " + position_pre_dispatch_run)

        for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
            if category_name != draw_category_name:
                continue
            if original_category_name == "Position":
                # Position bind: run the copy compute shader instead of the game.
                texture_override_vb_section.append("cs-cb0 = Resource_" + draw_ib + "_VertexLimit")
                texture_override_vb_section.append(d3d11_game_type.CategoryExtractSlotDict["Position"] + " = Resource" + draw_ib + "Position")
                texture_override_vb_section.append(d3d11_game_type.CategoryExtractSlotDict["Blend"] + " = Resource" + draw_ib + "Blend")
                texture_override_vb_section.append("handling = skip")
                dispatch_number = int(math.ceil(drawib_model.draw_number / 64)) + 1
                texture_override_vb_section.append("dispatch = " + str(dispatch_number) + ",1,1")
            elif original_category_name != "Blend":
                # Other binds (Texcoord etc.): simple resource replacement.
                category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                texture_override_vb_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

        # Mark the mod as active while this VB is being drawn so the toggle
        # keys only work when the character is on screen.
        if category_name == d3d11_game_type.CategoryDrawCategoryDict["Position"]:
            if len(blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                # A visible range marks the whole mod as on screen for the hotkeys.
                texture_override_vb_section.append("$mod_visible = 1")

        texture_override_vb_section.new_line()

    ini_builder.append_section(texture_override_vb_section)


def add_unity_cs_texture_override_ib_sections(ini_builder: M_IniBuilder, drawib_model, blueprint_model):
    """IB overrides (compute path): skip every original draw and re-emit it
    manually with the modded index buffer."""
    texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
    draw_ib = drawib_model.draw_ib
    d3d11_game_type = drawib_model.d3d11_game_type

    for submesh_model in drawib_model.submesh_model_list:
        ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
        texture_override_ib_namesuffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)

        texture_override_ib_section.append("[TextureOverride_" + texture_override_ib_namesuffix + "]")
        texture_override_ib_section.append("hash = " + draw_ib)
        texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
        texture_override_ib_section.append("checktextureoverride = vb1")

        # Hash-marked textures join the override check so the mod only
        # applies when the original textures are bound.
        if not MIMIGlobalProperties.forbid_auto_texture_ini():
            for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                if texture_markup_info.mark_type == "Hash":
                    texture_override_ib_section.append("checktextureoverride = " + texture_markup_info.mark_slot)

        texture_override_ib_section.append("handling = skip")

        # An empty index buffer means the submesh is hidden: leave it skipped.
        ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
        if ib_buf is None or len(ib_buf) == 0:
            texture_override_ib_section.new_line()
            continue

        if not d3d11_game_type.GPU_PreSkinning:
            for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
                if original_category_name == draw_category_name:
                    category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                    texture_override_ib_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

        texture_override_ib_section.append("ib = " + ib_resource_name)

        # Automatic Slot / SharedSlot texture bindings from the Submesh marks.
        if not MIMIGlobalProperties.forbid_auto_texture_ini():
            for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                    texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

        for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
            submesh_model.drawcall_model_list,
            obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
        ):
            texture_override_ib_section.append(drawindexed_str)

        if not d3d11_game_type.GPU_PreSkinning:
            if len(blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                # A visible range marks the whole mod as on screen for the hotkeys.
                texture_override_ib_section.append("$mod_visible = 1")

    ini_builder.append_section(texture_override_ib_section)


def build_unity_cs_resource_vb_section(drawib_model) -> M_IniSection:
    """Build the compute-path resource declarations of one DrawIB.

    Returned as a section (instead of appending it directly) so games like
    Naraka can add their own lines before handing it to the builder.
    """
    resource_vb_section = M_IniSection(M_SectionType.ResourceBuffer)
    # Buffer files live in the Buffers subfolder; INI lines carry the prefix.
    for category_name in drawib_model.d3d11_game_type.OrderedCategoryNameList:
        resource_vb_section.append("[Resource" + drawib_model.draw_ib + category_name + "]")
        # Position/Blend are read by the compute shader as raw bytes.
        if drawib_model.d3d11_game_type.GPU_PreSkinning and (category_name == "Position" or category_name == "Blend"):
            resource_vb_section.append("type = ByteAddressBuffer")
        else:
            resource_vb_section.append("type = Buffer")

        resource_vb_section.append("stride = " + str(drawib_model.d3d11_game_type.CategoryStrideDict[category_name]))
        resource_vb_section.append("filename = " + GlobalConfig.ini_buffer_filename(drawib_model.get_category_buffer_filename(category_name)))
        resource_vb_section.new_line()

    for submesh_model in drawib_model.submesh_model_list:
        ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
        resource_vb_section.append("[" + ib_resource_name + "]")
        resource_vb_section.append("type = Buffer")
        resource_vb_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_vb_section.append("filename = " + GlobalConfig.ini_buffer_filename(submesh_model.display_str + "-Index.buf"))
        resource_vb_section.new_line()

    return resource_vb_section


def add_unity_cs_resource_vb_sections(ini_builder: M_IniBuilder, drawib_model):
    """Append the compute-path resource declarations of one DrawIB."""
    ini_builder.append_section(build_unity_cs_resource_vb_section(drawib_model))


def add_unity_cs_resource_vertexlimit(ini_builder: M_IniBuilder, drawib_model):
    """Constant buffer feeding the compute shader with the vertex limit."""
    resource_vertex_limit_section = M_IniSection(M_SectionType.ResourceBuffer)
    resource_vertex_limit_section.append("[Resource_" + drawib_model.draw_ib + "_VertexLimit]")
    resource_vertex_limit_section.append("type = Buffer")
    resource_vertex_limit_section.append("format = R32G32B32A32_UINT")
    resource_vertex_limit_section.append("data = " + str(drawib_model.draw_number) + " 0 " + str(drawib_model.draw_number) + " 0")
    resource_vertex_limit_section.new_line()
    ini_builder.append_section(resource_vertex_limit_section)


def add_unity_cs_vertex_shader_check(ini_builder: M_IniBuilder):
    """Append an empty VertexShaderCheck marker section (kept for tooling)."""
    vscheck_section = M_IniSection(M_SectionType.VertexShaderCheck)
    ini_builder.append_section(vscheck_section)
