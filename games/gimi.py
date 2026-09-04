import math
import os

from ..common.global_config import GlobalConfig, LogicName
from ..common.global_properties import GlobalProperties
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from ..common.m_ini_helper_gui import M_IniHelperGUI

from ..common.m_texture_helper import M_TextureHelper


class GIMITextureMarkName:
    DiffuseMap = "DiffuseMap"
    NormalMap = "NormalMap"
    LightMap = "LightMap"


class ExportGIMI:
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

        texture_override_ib_section.append("[TextureOverride_IB_" + draw_ib + "]")
        texture_override_ib_section.append("hash = " + draw_ib)
        texture_override_ib_section.append("handling = skip")
        texture_override_ib_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)

            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))

            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.append("ib = null")
                texture_override_ib_section.new_line()
                continue

            texture_override_ib_section.append("ib = " + ib_resource_name)

            # 节点驱动的 slot 贴图：每个 drawindexed 前单独设置槽位
            def _slot_provider(obj_model):
                return M_TextureHelper.get_slot_texture_lines_for_drawcall(obj_model)

            def _slot_provider_with_orfix(obj_model):
                lines = _slot_provider(obj_model)
                if GlobalProperties.gimi_use_orfix() and lines:
                    if M_TextureHelper.drawcall_has_normal_map(obj_model):
                        lines.append(r"run = CommandList\global\ORFix\ORFix")
                    else:
                        lines.append(r"run = CommandList\global\ORFix\NNFix")
                return lines

            M_IniHelper.append_drawindexed_with_slot_lines(
                texture_override_ib_section,
                submesh_model.drawcall_model_list,
                _slot_provider_with_orfix,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            )

        ini_builder.append_section(texture_override_ib_section)

    def add_unity_vs_texture_override_vlr_section(self, ini_builder: M_IniBuilder, drawib_model, include_uav_byte_stride: bool = False):
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
        # 从蓝图 Texture 节点生成 [Resource_...] 段
        M_TextureHelper.generate_slot_texture_resource_sections(
            drawib_model=drawib_model,
            blueprint_model=self.blueprint_model,
            ini_builder=ini_builder,
        )

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

            # 节点驱动的 slot 贴图：每个 drawindexed 前单独设置槽位
            M_IniHelper.append_drawindexed_with_slot_lines(
                texture_override_ib_section,
                submesh_model.drawcall_model_list,
                lambda obj_model: M_TextureHelper.get_slot_texture_lines_for_drawcall(obj_model),
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            )

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

        all_texture_nodes = M_TextureHelper.collect_all_texture_nodes(self.blueprint_model, self.drawib_model_list)
        M_TextureHelper.copy_texture_files(
            all_texture_nodes,
            os.path.join(GlobalConfig.path_generate_mod_folder(), "Textures"),
        )

        for drawib_model in self.drawib_model_list:
            if GlobalConfig.logic_name != LogicName.SRMI:
                self.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_resource_vertexlimit(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_cs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1

        M_TextureHelper.generate_hash_texture_sections(
            getattr(self.blueprint_model, "hash_texture_node_list", []),
            ini_builder=ini_builder,
        )

        M_IniHelper.add_branch_key_sections(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        M_IniHelper.add_shapekey_ini_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelperGUI.add_branch_mod_gui_section(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        self.add_unity_cs_vertex_shader_check(ini_builder=ini_builder)
        ini_builder.save_to_file(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini"))

    def generate_unity_vs_config_ini(self):
        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {drawib_model.draw_ib: drawib_model for drawib_model in self.drawib_model_list}

        all_texture_nodes = M_TextureHelper.collect_all_texture_nodes(self.blueprint_model, self.drawib_model_list)
        M_TextureHelper.copy_texture_files(
            all_texture_nodes,
            os.path.join(GlobalConfig.path_generate_mod_folder(), "Textures"),
        )

        for drawib_model in self.drawib_model_list:
            self.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1

        M_TextureHelper.generate_hash_texture_sections(
            getattr(self.blueprint_model, "hash_texture_node_list", []),
            ini_builder=ini_builder,
        )

        M_IniHelper.add_branch_key_sections(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        M_IniHelper.add_shapekey_ini_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelperGUI.add_branch_mod_gui_section(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        ini_builder.save_to_file(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini"))

    def export(self):
        for drawib_model in self.drawib_model_list:
            drawib_model.generate_buffer_files(GlobalConfig.path_generatemod_buffer_folder())
        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {drawib_model.draw_ib: drawib_model for drawib_model in self.drawib_model_list}

        all_texture_nodes = M_TextureHelper.collect_all_texture_nodes(self.blueprint_model, self.drawib_model_list)
        M_TextureHelper.copy_texture_files(
            all_texture_nodes,
            os.path.join(GlobalConfig.path_generate_mod_folder(), "Textures"),
        )
        for drawib_model in self.drawib_model_list:
            self.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1

        M_TextureHelper.generate_hash_texture_sections(
            getattr(self.blueprint_model, "hash_texture_node_list", []),
            ini_builder=ini_builder,
        )

        M_IniHelper.add_branch_key_sections(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        M_IniHelper.add_shapekey_ini_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelperGUI.add_branch_mod_gui_section(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        ini_builder.save_to_file(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini"))
