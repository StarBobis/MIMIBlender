from ..model.blueprint_model import BluePrintModel
from ..model.draw_call_model import DrawCallModel
from ..model.submesh_model import SubMeshModel
from ..model.drawib_model import DrawIBModel
from dataclasses import dataclass,field
from ..common.global_config import GlobalConfig
from ..common.global_properties import GlobalProperties

from ..common.buffer_export_helper import BufferExportHelper
from ..common.global_config import GlobalConfig
from ..common.m_ini_helper import M_IniHelper
from ..common.m_ini_helper_gui import M_IniHelperGUI
from ..common.m_ini_builder import M_IniBuilder,M_IniSection, M_SectionType
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..workspace.ssmt_workspace import SSMTWorkSpace

import os

@dataclass
class ExportEFMI:

    blueprint_model:BluePrintModel

    submesh_model_list:list[SubMeshModel] = field(default_factory=list,init=False)
    drawib_model_list:list[DrawIBModel] = field(default_factory=list,init=False)

    def __post_init__(self):
        self.submesh_model_list = self.blueprint_model.parse_submesh_model_list()
        self.drawib_model_list = self.blueprint_model.parse_drawib_model_list(combine_ib=False)
        print("SubMeshModel鍒楄〃鍒濆鍖栧畬鎴愶紝鍏辨湁 " + str(len(self.submesh_model_list)) + " 涓猄ubMeshModel")

        for drawib_model in self.drawib_model_list:
            drawib_model.apply_drawib_alias()


    def generate_buffer_files(self):
        buf_output_folder = GlobalConfig.path_generatemod_buffer_folder()

        # 鏂扮増EFMI鍙渶瑕佷緷娆″鍑烘瘡涓猄ubMeshModel鐨勫唴瀹癸紝鐢氳嚦鏃犻渶鍚堝苟锛岄潪甯哥畝鍗?
        for submesh_model in self.submesh_model_list:
            print("ExportEFMI: 瀵煎嚭SubMeshModel锛孶nique鏍囪瘑: " + submesh_model.submesh_name)

            # 鐢熸垚IndexBuffer
            ib_filename = submesh_model.display_str + "-Index.buf"
            ib_filepath = os.path.join(buf_output_folder, ib_filename)
            BufferExportHelper.write_buf_ib_r32_uint(submesh_model.ib, ib_filepath)

            # 鐢熸垚CategoryBuffer
            for category, category_buf in submesh_model.category_buffer_dict.items():
                category_buf_filename = submesh_model.display_str + "-" + category + ".buf"
                category_buf_filepath = os.path.join(buf_output_folder, category_buf_filename)
                with open(category_buf_filepath, 'wb') as f:
                    category_buf.tofile(f)

    def generate_ini_file(self):
        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {
            drawib_model.draw_ib: drawib_model
            for drawib_model in self.drawib_model_list
        }
        draw_ib_active_index_dict = {
            drawib_model.draw_ib: index
            for index, drawib_model in enumerate(self.drawib_model_list)
        }

        M_IniHelper.generate_hash_style_texture_ini(
            ini_builder=ini_builder,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
        )
        M_IniHelper.generate_shared_slot_style_texture_ini(
            ini_builder=ini_builder,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
        )

        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)

        for submesh_model in self.submesh_model_list:
            drawib_model = drawib_drawibmodel_dict.get(submesh_model.match_draw_ib)
            active_index = draw_ib_active_index_dict.get(submesh_model.match_draw_ib, 0)
            part_name = drawib_model.get_submesh_part_name(submesh_model) if drawib_model is not None else None
            
            texture_override_ib_section.append("[TextureOverride_" + drawib_model.get_submesh_texture_override_suffix(submesh_model) + "]")
            texture_override_ib_section.append("hash = " + submesh_model.match_draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
            texture_override_ib_section.append("match_index_count = " + str(submesh_model.match_index_count))
            texture_override_ib_section.append("handling = skip")

            texture_override_ib_section.append("run = CommandList\\EFMIv1\\OverrideTextures")

            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
            texture_override_ib_section.append("ib = " + ib_resource_name)

            for category in submesh_model.category_buffer_dict.keys():
                category_slot = submesh_model.d3d11_game_type.CategoryExtractSlotDict.get(category,"unknown_slot")
                category_resource_name = "Resource_" + drawib_model.get_submesh_unique_key(submesh_model) + "_" + category
                texture_override_ib_section.append(category_slot + " = " + category_resource_name)

            if not GlobalProperties.forbid_auto_texture_ini() and drawib_model is not None:
                texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                for texture_markup_info in texture_markup_info_list:
                    if getattr(texture_markup_info, "mark_type", "") not in ("Slot", "SharedSlot"):
                        continue
                    texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            for draw_line in M_IniHelper.get_drawindexed_instanced_str_list(submesh_model.drawcall_model_list):
                texture_override_ib_section.append(draw_line)

            if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_ib_section.append("$active" + str(active_index) + " = 1")
                if GlobalProperties.generate_branch_mod_gui():
                    texture_override_ib_section.append("$ActiveCharacter = 1")
            
            texture_override_ib_section.new_line()

        ini_builder.append_section(texture_override_ib_section)

        # ResourceBuffer閮ㄥ垎
        resource_buffer_section = M_IniSection(M_SectionType.ResourceBuffer)
        for submesh_model in self.submesh_model_list:
            drawib_model = drawib_drawibmodel_dict.get(submesh_model.match_draw_ib)
            submesh_unique_key = drawib_model.get_submesh_unique_key(submesh_model) if drawib_model else submesh_model.display_str.replace("-", "_")

            ib_resource_name = "Resource_" + submesh_unique_key + "_Index"
            resource_buffer_section.append("[" + ib_resource_name + "]")
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R32_UINT")
            resource_buffer_section.append("filename = Meshes\\" + submesh_model.display_str + "-Index.buf")
            resource_buffer_section.new_line()

            for category in submesh_model.category_buffer_dict.keys():
                category_resource_name = "Resource_" + submesh_unique_key + "_" + category
                stride = submesh_model.d3d11_game_type.CategoryStrideDict.get(category,0)
                resource_buffer_section.append("[" + category_resource_name + "]")
                resource_buffer_section.append("type = Buffer")
                resource_buffer_section.append("stride = " + str(stride))
                resource_buffer_section.append("filename = Meshes\\" + submesh_model.display_str + "-" + category + ".buf")
                resource_buffer_section.new_line()

        if not GlobalProperties.forbid_auto_texture_ini():
            resource_texture_section = M_IniSection(M_SectionType.ResourceTexture)
            appended_resource_names = set()
            for drawib_model in self.drawib_model_list:
                for idx, submesh_model in enumerate(drawib_model.submesh_model_list):
                    for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                        if getattr(texture_markup_info, "mark_type", "") != "Slot":
                            continue
                        resource_name = texture_markup_info.get_resource_name()
                        if resource_name in appended_resource_names:
                            continue
                        appended_resource_names.add(resource_name)
                        slot_filename = M_IniHelper._get_slot_style_texture_filename(drawib_model, idx, texture_markup_info)
                        resource_texture_section.append("[" + texture_markup_info.get_resource_name() + "]")
                        resource_texture_section.append("filename = Textures/" + slot_filename)
                        resource_texture_section.new_line()
            ini_builder.append_section(resource_texture_section)

        ini_builder.append_section(resource_buffer_section)

        for drawib_model in self.drawib_model_list:
            M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)

        GlobalConfig.generated_mod_number = len(self.drawib_model_list)
        M_IniHelper.add_branch_key_sections(
            ini_builder=ini_builder,
            key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict,
        )
        M_IniHelperGUI.add_branch_mod_gui_section(
            ini_builder=ini_builder,
            key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict,
        )

        
        ini_filepath = os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini")
        ini_builder.save_to_file(ini_filepath)
                


        

    def export(self):
        self.generate_buffer_files()
        self.generate_ini_file()

        
            
        
