import os

from ..common.global_config import GlobalConfig
from ..common.global_properties import GlobalProperties
from ..common.global_config import GlobalConfig
from ..common.m_ini_helper import M_IniHelper
from ..common.m_ini_helper_gui import M_IniHelperGUI
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..blueprint.blueprint_export_helper import BlueprintExportHelper


class ExportYYSLS:
    def __init__(self, blueprint_model):
        self.blueprint_model = blueprint_model
        self.drawib_model_list = blueprint_model.parse_drawib_model_list(combine_ib=False)
        for drawib_model in self.drawib_model_list:
            drawib_model.apply_drawib_alias()

    @staticmethod
    def _get_submesh_ib_resource_name(submesh_model) -> str:
        return "Resource_" + submesh_model.submesh_name.replace("-", "_") + "_Index"

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib
        d3d11_game_type = drawib_model.d3d11_game_type
        for submesh_model in drawib_model.submesh_model_list:
            match_first_index = str(submesh_model.match_first_index)
            texture_override_name_suffix = submesh_model.submesh_name.replace("-", "_")
            ib_resource_name = self._get_submesh_ib_resource_name(submesh_model)

            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + match_first_index)
            texture_override_ib_section.append("match_index_count = " + str(submesh_model.match_index_count))
            texture_override_ib_section.append("handling = skip")
            
            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.append("ib = null")
                texture_override_ib_section.new_line()
                continue

            for original_category_name in d3d11_game_type.CategoryDrawCategoryDict.keys():
                category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                texture_override_ib_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            texture_override_ib_section.append("ib = " + ib_resource_name)

            if not GlobalProperties.forbid_auto_texture_ini():
                texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                if texture_markup_info_list:
                    for texture_markup_info in texture_markup_info_list:
                        if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                            texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            if not d3d11_game_type.GPU_PreSkinning:
                for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
                    if original_category_name == draw_category_name:
                        category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                        texture_override_ib_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            # TODO 杩欓噷娉ㄦ剰锛孻YSLS澶т笘鐣屼腑浣跨敤鐨勬槸DrawindexedInstancedIndirect
            # 绗竴涓弬鏁版槸涓€涓笓闂ㄧ殑鍙傛暟Buffer锛屼絾鏄垜浠洰鍓嶈繕娌″彂鏋勯€犺繖涓弬鏁癇uffer锛屾墍浠ヨ鍔犱笂
            # 绗簩涓弬鏁版槸Buffer鐨勫亸绉婚噺锛屽洜涓轰竴鑸槸涓€涓法澶х殑Buffer鍖呭惈浜嗚繖涓€甯ф墍鏈夎缁樺埗鐨勫唴瀹?
            # 浣嗘槸瑙掕壊澶栬鐣岄潰锛屼娇鐢ㄧ殑鏄疍rawIndexed
            # 鎵€浠ヨ繖涓兘澶熷吋瀹圭殑鏂规硶浠嶇劧闇€瑕佹懜绱紝涔熻鑳藉閫氳繃鏌愮DRAW_TYPE鏉ヨ繘琛岃繃婊わ紵
            # emmmm锛屾€讳箣鍚庨潰娴嬭瘯鐨勬椂鍊欏湪鑰冭檻锛屾殏鏃惰褰曞湪姝?
            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

            if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                if GlobalProperties.generate_branch_mod_gui():
                    texture_override_ib_section.append("$ActiveCharacter = 1")

        ini_builder.append_section(texture_override_ib_section)

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
            ib_resource_name = self._get_submesh_ib_resource_name(submesh_model)
            resource_vb_section.append("[" + ib_resource_name + "]")
            resource_vb_section.append("type = Buffer")
            resource_vb_section.append("format = DXGI_FORMAT_R32_UINT")
            resource_vb_section.append("filename = " + buffer_folder_name + "/" + submesh_model.submesh_name + "-Index.buf")
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

    def export(self):
        for drawib_model in self.drawib_model_list:
            drawib_model.generate_buffer_files(GlobalConfig.path_generatemod_buffer_folder())
        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {drawib_model.draw_ib: drawib_model for drawib_model in self.drawib_model_list}
        M_IniHelper.generate_hash_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelper.generate_shared_slot_style_texture_ini(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        for drawib_model in self.drawib_model_list:
            self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            self.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1
        M_IniHelper.add_branch_key_sections(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        M_IniHelper.add_shapekey_ini_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        M_IniHelperGUI.add_branch_mod_gui_section(ini_builder=ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        ini_builder.save_to_file(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + ".ini"))
