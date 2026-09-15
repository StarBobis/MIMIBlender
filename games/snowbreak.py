"""
SnowBreak mod exporter.

Only the IB override sections are SnowBreak-specific (they back up the
original IB before replacing it and restore it after the draw); the buffer
resource sections and the whole export pipeline come from the shared base.
"""

from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from .base.standard_exporter import StandardExporter
from .base import sections


class ExportSnowBreak(StandardExporter):
    """SnowBreak exporter: shared pipeline, custom IB override sections."""

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # SnowBreak emits no VB overrides, only per-Submesh IB overrides.
        self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model, use_display_str=False)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # IB overrides: back up the live IB, bind the modded one, draw, then
        # restore the backup so later draws see the original buffer again.
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib
        d3d11_game_type = drawib_model.d3d11_game_type

        for submesh_model in drawib_model.submesh_model_list:
            texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
            backup_resource_name = "Resource_IB_" + drawib_model.get_submesh_texture_override_suffix(submesh_model) + "_Bak"

            texture_override_ib_section.append("[" + backup_resource_name + "]")
            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
            texture_override_ib_section.append("handling = skip")
            texture_override_ib_section.append(backup_resource_name + " = ref ib")
            texture_override_ib_section.append("checktextureoverride = vb0")

            # Hash-marked textures join the override check so the mod only
            # applies when the original textures are bound.
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                if texture_markup_info_list:
                    for texture_markup_info in texture_markup_info_list:
                        if texture_markup_info.mark_type == "Hash":
                            texture_override_ib_section.append("checktextureoverride = " + texture_markup_info.mark_slot)

            texture_override_ib_section.append("ib = " + ib_resource_name)

            for original_category_name in d3d11_game_type.CategoryDrawCategoryDict.keys():
                category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                texture_override_ib_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            # Automatic Slot / SharedSlot texture bindings from the Submesh marks.
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
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

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

            texture_override_ib_section.append("ib = " + backup_resource_name)

        ini_builder.append_section(texture_override_ib_section)
