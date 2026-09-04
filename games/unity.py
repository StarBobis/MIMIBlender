import math
import os

from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from ..common.global_properties import GlobalProperties
from ..common.global_config import GlobalConfig
from ..common.m_ini_helper import M_IniHelper
from ..common.m_ini_helper_gui import M_IniHelperGUI
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..blueprint.blueprint_export_helper import BlueprintExportHelper


class ExportUnity:
    def __init__(self, blueprint_model):
        self.blueprint_model = blueprint_model
        self.drawib_model_list = blueprint_model.parse_drawib_model_list(combine_ib=False)
        for drawib_model in self.drawib_model_list:
            drawib_model.apply_drawib_alias()

    def add_unity_vs_texture_override_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
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

            draw_category_name = d3d11_game_type.CategoryDrawCategoryDict.get("Blend", None)
            if draw_category_name is not None and category_name == draw_category_name:
                texture_override_vb_section.append("handling = skip")
                texture_override_vb_section.append("draw = " + str(drawib_model.draw_number) + ", 0")

            if category_name == d3d11_game_type.CategoryDrawCategoryDict["Position"]:
                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                    if GlobalProperties.generate_branch_mod_gui():
                        texture_override_vb_section.append("$ActiveCharacter = 1")

            texture_override_vb_section.new_line()

        ini_builder.append_section(texture_override_vb_section)

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib

        for submesh_model in drawib_model.submesh_model_list:
            texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)

            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
            texture_override_ib_section.append("handling = skip")

            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.append("ib = null")
                texture_override_ib_section.new_line()
                continue

            texture_override_ib_section.append("ib = " + ib_resource_name)

            if not GlobalProperties.forbid_auto_texture_ini():
                for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                    if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                        texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

        ini_builder.append_section(texture_override_ib_section)

    def add_unity_vs_texture_override_vlr_section(self, ini_builder: M_IniBuilder, drawib_model, include_uav_byte_stride: bool = True):
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

    def add_unity_vs_resource_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        resource_vb_section = M_IniSection(M_SectionType.ResourceBuffer)
        buffer_folder_name = "Meshes"

        for category_name in drawib_model.d3d11_game_type.OrderedCategoryNameList:
            resource_vb_section.append("[Resource" + drawib_model.draw_ib + category_name + "]")
            resource_vb_section.append("type = Buffer")
            resource_vb_section.append("stride = " + str(drawib_model.d3d11_game_type.CategoryStrideDict[category_name]))
            resource_vb_section.append("filename = " + buffer_folder_name + "/" + drawib_model.draw_ib + "-" + category_name + ".buf")
            resource_vb_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
            resource_vb_section.append("[" + ib_resource_name + "]")
            resource_vb_section.append("type = Buffer")
            resource_vb_section.append("format = DXGI_FORMAT_R32_UINT")
            resource_vb_section.append("filename = " + buffer_folder_name + "/" + submesh_model.display_str + "-Index.buf")
            resource_vb_section.new_line()

        ini_builder.append_section(resource_vb_section)

    def add_resource_texture_sections(self, ini_builder: M_IniBuilder, drawib_model):
        if GlobalProperties.forbid_auto_texture_ini():
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
                    resource_texture_section.append("filename = Textures/" + slot_filename)
                    resource_texture_section.new_line()

        ini_builder.append_section(resource_texture_section)

    def add_unity_cs_texture_override_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
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
                    texture_override_vb_section.append("cs-cb0 = Resource_" + draw_ib + "_VertexLimit")
                    texture_override_vb_section.append(d3d11_game_type.CategoryExtractSlotDict["Position"] + " = Resource" + draw_ib + "Position")
                    texture_override_vb_section.append(d3d11_game_type.CategoryExtractSlotDict["Blend"] + " = Resource" + draw_ib + "Blend")
                    texture_override_vb_section.append("handling = skip")
                    dispatch_number = int(math.ceil(drawib_model.draw_number / 64)) + 1
                    texture_override_vb_section.append("dispatch = " + str(dispatch_number) + ",1,1")
                elif original_category_name != "Blend":
                    category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                    texture_override_vb_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            if category_name == d3d11_game_type.CategoryDrawCategoryDict["Position"]:
                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                    if GlobalProperties.generate_branch_mod_gui():
                        texture_override_vb_section.append("$ActiveCharacter = 1")

            texture_override_vb_section.new_line()

        ini_builder.append_section(texture_override_vb_section)

    def add_unity_cs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
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

            if not GlobalProperties.forbid_auto_texture_ini():
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

            if not GlobalProperties.forbid_auto_texture_ini():
                for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                    if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                        texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

            if not d3d11_game_type.GPU_PreSkinning:
                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                    if GlobalProperties.generate_branch_mod_gui():
                        texture_override_ib_section.append("$ActiveCharacter = 1")

        ini_builder.append_section(texture_override_ib_section)

    def add_unity_cs_resource_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        resource_vb_section = M_IniSection(M_SectionType.ResourceBuffer)
        buffer_folder_name = "Meshes"

        for category_name in drawib_model.d3d11_game_type.OrderedCategoryNameList:
            resource_vb_section.append("[Resource" + drawib_model.draw_ib + category_name + "]")
            if drawib_model.d3d11_game_type.GPU_PreSkinning and (category_name == "Position" or category_name == "Blend"):
                resource_vb_section.append("type = ByteAddressBuffer")
            else:
                resource_vb_section.append("type = Buffer")

            resource_vb_section.append("stride = " + str(drawib_model.d3d11_game_type.CategoryStrideDict[category_name]))
            resource_vb_section.append("filename = " + buffer_folder_name + "/" + drawib_model.draw_ib + "-" + category_name + ".buf")
            resource_vb_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
            resource_vb_section.append("[" + ib_resource_name + "]")
            resource_vb_section.append("type = Buffer")
            resource_vb_section.append("format = DXGI_FORMAT_R32_UINT")
            resource_vb_section.append("filename = " + buffer_folder_name + "/" + submesh_model.display_str + "-Index.buf")
            resource_vb_section.new_line()

        ini_builder.append_section(resource_vb_section)

    def add_unity_cs_resource_vertexlimit(self, ini_builder: M_IniBuilder, drawib_model):
        resource_vertex_limit_section = M_IniSection(M_SectionType.ResourceBuffer)
        resource_vertex_limit_section.append("[Resource_" + drawib_model.draw_ib + "_VertexLimit]")
        resource_vertex_limit_section.append("type = Buffer")
        resource_vertex_limit_section.append("format = R32G32B32A32_UINT")
        resource_vertex_limit_section.append("data = " + str(drawib_model.draw_number) + " 0 " + str(drawib_model.draw_number) + " 0")
        resource_vertex_limit_section.new_line()
        ini_builder.append_section(resource_vertex_limit_section)

    def add_unity_cs_vertex_shader_check(self, ini_builder: M_IniBuilder):
        vscheck_section = M_IniSection(M_SectionType.VertexShaderCheck)
        ini_builder.append_section(vscheck_section)

    def generate_unity_cs_config_ini(self):
        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {drawib_model.draw_ib: drawib_model for drawib_model in self.drawib_model_list}

        M_IniHelper.generate_hash_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelper.generate_shared_slot_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)

        for drawib_model in self.drawib_model_list:
            if GlobalConfig.logic_name != LogicName.SRMI:
                self.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_resource_vertexlimit(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1

        M_IniHelper.add_branch_key_sections(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        M_IniHelper.add_shapekey_ini_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelperGUI.add_branch_mod_gui_section(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        self.add_unity_cs_vertex_shader_check(ini_builder=ini_builder)
        ini_builder.save_to_file(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini"))

    def generate_unity_vs_config_ini(self):
        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {drawib_model.draw_ib: drawib_model for drawib_model in self.drawib_model_list}

        M_IniHelper.generate_hash_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelper.generate_shared_slot_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)

        for drawib_model in self.drawib_model_list:
            self.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1

        M_IniHelper.add_branch_key_sections(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        M_IniHelper.add_shapekey_ini_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelperGUI.add_branch_mod_gui_section(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        ini_builder.save_to_file(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini"))

    def export(self):
        for drawib_model in self.drawib_model_list:
            drawib_model.generate_buffer_files(GlobalConfig.path_generatemod_buffer_folder())
        if GlobalConfig.logic_name in {LogicName.Naraka, LogicName.NarakaM, LogicName.AILIMIT}:
            self.generate_unity_cs_config_ini()
        else:
            self.generate_unity_vs_config_ini()
