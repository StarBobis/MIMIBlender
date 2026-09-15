"""
YYSLS (Where Winds Meet) mod exporter.

Only the IB override sections and the IB resource naming are
YYSLS-specific (resource names use the raw submesh name with dashes
replaced); everything else comes from the shared base.
"""

from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from .base.standard_exporter import StandardExporter
from .base import sections


class ExportYYSLS(StandardExporter):
    """YYSLS exporter: shared pipeline, custom IB override + IB resources."""

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # YYSLS emits no VB overrides, only per-Submesh IB overrides.
        self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        self.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    @staticmethod
    def _get_submesh_ib_resource_name(submesh_model) -> str:
        # YYSLS names IB resources from the raw submesh name (dashes become
        # underscores) instead of the alias-aware unique key.
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

            # An empty index buffer means the submesh is hidden: null the IB out.
            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.append("ib = null")
                texture_override_ib_section.new_line()
                continue

            for original_category_name in d3d11_game_type.CategoryDrawCategoryDict.keys():
                category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                texture_override_ib_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            texture_override_ib_section.append("ib = " + ib_resource_name)

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

            # TODO note: YYSLS uses DrawindexedInstancedIndirect in its open world.
            # The first argument is a dedicated parameter buffer, but we cannot build that parameter buffer yet, so it has to be added.
            # The second argument is the offset into the buffer, because usually one huge buffer holds everything that will be drawn in this frame.
            # However, the character appearance UI uses DrawIndexed.
            # So a compatible approach still needs to be explored; maybe it can be filtered by some DRAW_TYPE?
            # emmmm, will think about it during later testing; recorded here for now.
            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

            if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

        ini_builder.append_section(texture_override_ib_section)

    def add_unity_vs_resource_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # Resource declarations; the IB resources use the YYSLS raw-name style
        # (see _get_submesh_ib_resource_name) and raw submesh file stems.
        resource_vb_section = M_IniSection(M_SectionType.ResourceBuffer)
        # Buffer files live in the Buffers subfolder; INI lines carry the prefix.
        for category_name in drawib_model.d3d11_game_type.OrderedCategoryNameList:
            resource_vb_section.append("[Resource" + drawib_model.draw_ib + category_name + "]")
            resource_vb_section.append("type = Buffer")
            resource_vb_section.append("stride = " + str(drawib_model.d3d11_game_type.CategoryStrideDict[category_name]))
            resource_vb_section.append("filename = " + GlobalConfig.ini_buffer_filename(drawib_model.get_category_buffer_filename(category_name)))
            resource_vb_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            ib_resource_name = self._get_submesh_ib_resource_name(submesh_model)
            resource_vb_section.append("[" + ib_resource_name + "]")
            resource_vb_section.append("type = Buffer")
            resource_vb_section.append("format = DXGI_FORMAT_R32_UINT")
            resource_vb_section.append("filename = " + GlobalConfig.ini_buffer_filename(submesh_model.submesh_name + "-Index.buf"))
            resource_vb_section.new_line()
        ini_builder.append_section(resource_vb_section)
