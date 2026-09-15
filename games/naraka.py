"""
Naraka (Naraka: Bladepoint) mod INI exporter.

This module was split out from games/unity.py so that Naraka-specific
features can evolve here without risking the other games that still share
the Unity exporter (NarakaM / GF2 / AILIMIT).

Naraka uses the GPU pre-skinning compute-shader path:
- The original Position VB is enlarged by a VertexLimitRaise override.
- A compute shader dispatch copies the modded Position/Blend data from
  resource buffers into the game's own VB at draw time.
- The Texcoord VB is replaced by a resource buffer directly.
- Every submesh IB draw is skipped and re-emitted manually, which is also
  the place where cross-IB rendering blocks will be injected later.
"""
import math
import os

from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.m_ini_helper import M_IniHelper
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType


class ExportNaraka:
    def __init__(self, blueprint_model):
        # Keep the same model preparation as the old Unity CS path:
        # parse every DrawIB model without merging IBs, then resolve aliases.
        self.blueprint_model = blueprint_model
        self.drawib_model_list = blueprint_model.parse_drawib_model_list(combine_ib=False)
        for drawib_model in self.drawib_model_list:
            drawib_model.apply_drawib_alias()

    @staticmethod
    def get_cross_ib_backup_resource_name(drawib_model, submesh_model, vb_slot: int) -> str:
        # The name carries the Submesh identity and the VB slot directly, so
        # any number of backups never collide (no auto-increment numbers),
        # e.g. Resource_LOD0_fd1dede6_0_BK_VB0
        return "Resource_" + drawib_model.get_submesh_unique_key(submesh_model) + "_BK_VB" + str(vb_slot)

    @staticmethod
    def submesh_has_cross_ib_draw_call(submesh_model) -> bool:
        # A Submesh is a cross-IB guest when at least one of its draw calls
        # is marked to be rendered inside another Submesh's section.
        for draw_call_model in submesh_model.drawcall_model_list:
            if draw_call_model.cross_render_at_submesh:
                return True
        return False

    def collect_cross_ib_host_entries(self):
        # Pre-scan every DrawIB and group cross-marked draw calls by their host
        # Submesh, so the IB section generation can inject the cross blocks.
        # Returns: host submesh_name -> list of guest entries.
        submesh_lookup = {}
        for drawib_model in self.drawib_model_list:
            for submesh_model in drawib_model.submesh_model_list:
                submesh_lookup[submesh_model.submesh_name] = submesh_model

        cross_ib_host_entries = {}
        for drawib_model in self.drawib_model_list:
            for submesh_model in drawib_model.submesh_model_list:
                # Group this Submesh's cross-marked draw calls by host,
                # keeping the blueprint parse order inside each group.
                crossed_per_host = {}
                for draw_call_model in submesh_model.drawcall_model_list:
                    host_submesh_name = draw_call_model.cross_render_at_submesh
                    if host_submesh_name:
                        draw_call_list = crossed_per_host.get(host_submesh_name, [])
                        draw_call_list.append(draw_call_model)
                        crossed_per_host[host_submesh_name] = draw_call_list

                for host_submesh_name, draw_call_list in crossed_per_host.items():
                    if host_submesh_name not in submesh_lookup:
                        raise ValueError("Naraka Cross-IB Render: host Submesh '" + host_submesh_name + "' does not exist in this export")
                    entry = {
                        "guest_drawib_model": drawib_model,
                        "guest_submesh_model": submesh_model,
                        "draw_call_list": draw_call_list,
                    }
                    entry_list = cross_ib_host_entries.get(host_submesh_name, [])
                    entry_list.append(entry)
                    cross_ib_host_entries[host_submesh_name] = entry_list

        return cross_ib_host_entries

    def add_naraka_texture_override_vlr_section(self, ini_builder: M_IniBuilder, drawib_model, include_uav_byte_stride: bool = True):
        # VertexLimitRaise: enlarge the game's original Position VB so the
        # compute shader has room to write the modded vertex data into it.
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

    def add_naraka_cs_texture_override_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # VB overrides: the Position category runs a compute shader that fills
        # the game's VB with modded Position/Blend data; every other category
        # (e.g. Texcoord) is replaced by a resource buffer at its bind slot.
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

            # Mark the mod as active while this VB is being drawn so the
            # toggle keys only work when the character is on screen.
            if category_name == d3d11_game_type.CategoryDrawCategoryDict["Position"]:
                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

            texture_override_vb_section.new_line()

        ini_builder.append_section(texture_override_vb_section)

    def add_naraka_cs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model, cross_ib_host_entries):
        # IB overrides: skip every original draw and re-emit it manually with
        # the modded index buffer. Cross-IB rendering is applied here:
        # - guest draw calls are suppressed from their own Submesh section,
        # - guest Submesh sections capture their DrawIB's VB bindings (backup),
        # - host Submesh sections re-emit the guest draws after their own.
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

            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                    if texture_markup_info.mark_type == "Hash":
                        texture_override_ib_section.append("checktextureoverride = " + texture_markup_info.mark_slot)

            texture_override_ib_section.append("handling = skip")

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

            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                    if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                        texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            # Only draw calls without a cross-IB mark stay in this section;
            # marked ones move into their host Submesh section instead.
            normal_draw_call_list = []
            for draw_call_model in submesh_model.drawcall_model_list:
                if not draw_call_model.cross_render_at_submesh:
                    normal_draw_call_list.append(draw_call_model)

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                normal_draw_call_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

            # Guest backup: capture this DrawIB's VB bindings while they are
            # live (vb0 already holds the CS-written modded data and vb1 is
            # the modded Texcoord buffer), so host sections can rebind them.
            if self.submesh_has_cross_ib_draw_call(submesh_model):
                texture_override_ib_section.append(self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 0) + " = ref vb0")
                texture_override_ib_section.append(self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 1) + " = ref vb1")

            # Host cross blocks: always appended after the host's own draws,
            # so the host bindings never need to be restored afterwards.
            for cross_entry in cross_ib_host_entries.get(submesh_model.submesh_name, []):
                guest_drawib_model = cross_entry["guest_drawib_model"]
                guest_submesh_model = cross_entry["guest_submesh_model"]
                texture_override_ib_section.append("; Cross-IB: " + guest_submesh_model.display_str + " rendered at " + submesh_model.display_str)
                texture_override_ib_section.append("ib = " + guest_drawib_model.get_submesh_ib_resource_name(guest_submesh_model))
                texture_override_ib_section.append("vb0 = " + self.get_cross_ib_backup_resource_name(guest_drawib_model, guest_submesh_model, 0))
                texture_override_ib_section.append("vb1 = " + self.get_cross_ib_backup_resource_name(guest_drawib_model, guest_submesh_model, 1))
                for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                    cross_entry["draw_call_list"],
                    obj_name_draw_offset_dict=guest_drawib_model.obj_name_draw_offset,
                ):
                    texture_override_ib_section.append(drawindexed_str)

            if not d3d11_game_type.GPU_PreSkinning:
                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

        ini_builder.append_section(texture_override_ib_section)

    def add_naraka_cs_resource_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # Resource declarations for every category buffer and every submesh IB.
        resource_vb_section = M_IniSection(M_SectionType.ResourceBuffer)
        # Flat layout: buffers and textures sit next to the generated INI
        for category_name in drawib_model.d3d11_game_type.OrderedCategoryNameList:
            resource_vb_section.append("[Resource" + drawib_model.draw_ib + category_name + "]")
            if drawib_model.d3d11_game_type.GPU_PreSkinning and (category_name == "Position" or category_name == "Blend"):
                resource_vb_section.append("type = ByteAddressBuffer")
            else:
                resource_vb_section.append("type = Buffer")

            resource_vb_section.append("stride = " + str(drawib_model.d3d11_game_type.CategoryStrideDict[category_name]))
            resource_vb_section.append("filename = " + drawib_model.get_category_buffer_filename(category_name))
            resource_vb_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
            resource_vb_section.append("[" + ib_resource_name + "]")
            resource_vb_section.append("type = Buffer")
            resource_vb_section.append("format = DXGI_FORMAT_R32_UINT")
            resource_vb_section.append("filename = " + submesh_model.display_str + "-Index.buf")
            resource_vb_section.new_line()

        # Unified declaration area for cross-IB backup resources: one empty
        # section per guest Submesh and VB slot (filled by "ref" at runtime).
        for submesh_model in drawib_model.submesh_model_list:
            if not self.submesh_has_cross_ib_draw_call(submesh_model):
                continue
            resource_vb_section.append("[" + self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 0) + "]")
            resource_vb_section.new_line()
            resource_vb_section.append("[" + self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 1) + "]")
            resource_vb_section.new_line()

        ini_builder.append_section(resource_vb_section)

    def add_naraka_cs_resource_vertexlimit(self, ini_builder: M_IniBuilder, drawib_model):
        # Constant buffer feeding the compute shader with the vertex limit.
        resource_vertex_limit_section = M_IniSection(M_SectionType.ResourceBuffer)
        resource_vertex_limit_section.append("[Resource_" + drawib_model.draw_ib + "_VertexLimit]")
        resource_vertex_limit_section.append("type = Buffer")
        resource_vertex_limit_section.append("format = R32G32B32A32_UINT")
        resource_vertex_limit_section.append("data = " + str(drawib_model.draw_number) + " 0 " + str(drawib_model.draw_number) + " 0")
        resource_vertex_limit_section.new_line()
        ini_builder.append_section(resource_vertex_limit_section)

    def add_naraka_resource_texture_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # Resource declarations for slot-style marked textures of this DrawIB.
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
                    resource_texture_section.append("filename = " + slot_filename)
                    resource_texture_section.new_line()

        ini_builder.append_section(resource_texture_section)

    def generate_naraka_cs_config_ini(self):
        # Build the whole mod INI with the compute-shader (GPU pre-skinning) path.
        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {drawib_model.draw_ib: drawib_model for drawib_model in self.drawib_model_list}

        # Cross-IB pre-scan: host submesh_name -> guest entries, shared by all DrawIBs.
        cross_ib_host_entries = self.collect_cross_ib_host_entries()

        M_IniHelper.generate_hash_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelper.generate_shared_slot_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)

        for drawib_model in self.drawib_model_list:
            self.add_naraka_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_naraka_cs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_naraka_cs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model, cross_ib_host_entries=cross_ib_host_entries)
            self.add_naraka_cs_resource_vertexlimit(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_naraka_cs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_naraka_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1

        M_IniHelper.add_branch_key_sections(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        M_IniHelper.add_shapekey_ini_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        ini_builder.save_to_file(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini"))

    def export(self):
        # Naraka always uses the compute-shader path; write buffers first.
        for drawib_model in self.drawib_model_list:
            drawib_model.generate_buffer_files(GlobalConfig.path_generatemod_buffer_folder())
        self.generate_naraka_cs_config_ini()
