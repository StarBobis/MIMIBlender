"""
YYSLS (Where Winds Meet) mod exporter.

IB overrides, resource naming and draw-scoped cloth bypass are YYSLS-specific.
The custom VS is used only for mod draws matching its verified original hash.
Other shader passes keep their original VS; the shared export pipeline remains
responsible for buffers, texture automation, branch keys and shape keys.
"""

from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from .base.standard_exporter import StandardExporter
from .base import sections
from . import yysls_cloth


class ExportYYSLS(StandardExporter):
    """YYSLS exporter with a hash-checked, draw-local no-cloth VS."""

    def generate_buffer_files(self):
        # Package the shader with each mod instead of installing a global fix.
        # This also keeps exported mods portable to another game installation.
        super().generate_buffer_files()
        yysls_cloth.copy_shader_asset()

    def add_final_sections(self, ini_builder, drawib_drawibmodel_dict):
        # Keep shared branch/shape-key behavior, then identify the target VS.
        # This hook runs once, even when the mod contains several DrawIBs.
        # The marker carries no render commands and cannot affect other meshes.
        # Actual shader selection is deferred until each enabled object draw.
        super().add_final_sections(ini_builder, drawib_drawibmodel_dict)
        yysls_cloth.add_shader_check(ini_builder)

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
        # Each submesh has a shared binding/draw list and a scoped CustomShader.
        # Select the shader before entering that list, never after binding slots.
        # The same index buffer can appear in multiple passes with different VSs.
        # An unknown VS must keep the old draw path instead of guessing its ABI.
        custom_section = M_IniSection(M_SectionType.CommandList)
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
            # The game package declares this switch in d3dx.ini (F6 in Core).
            # A disabled mod must not skip the game draw or bind mod resources.
            # Object branch conditions below still control their actual draws.
            texture_override_ib_section.append("; Disabled mods leave the game draw untouched.")
            texture_override_ib_section.append("if $costume_mods")
            texture_override_ib_section.append("handling = skip")

            # An empty index buffer means the submesh is hidden: null the IB out.
            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.append("ib = null")
                # Hidden meshes issue no draw and therefore need no custom VS.
                texture_override_ib_section.append("endif")
                texture_override_ib_section.new_line()
                continue

            # Collect resource bindings instead of executing them in the parent.
            # The matching CustomShader must install VS before these commands.
            # The fallback invokes the same list with the original shader intact.
            mod_lines = []
            for original_category_name in d3d11_game_type.CategoryDrawCategoryDict.keys():
                category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                mod_lines.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            mod_lines.append("ib = " + ib_resource_name)

            # Automatic Slot / SharedSlot bindings belong inside the scope too.
            # Preserve their ordering relative to per-object texture overrides.
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                if texture_markup_info_list:
                    for texture_markup_info in texture_markup_info_list:
                        if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                            mod_lines.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            if not d3d11_game_type.GPU_PreSkinning:
                for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
                    if original_category_name == draw_category_name:
                        category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                        mod_lines.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            # Retain the existing explicit DrawIndexed export behavior.
            # Appearance UI draws use this path; indirect open-world draws are
            # a separate compatibility issue and are not changed by VS scoping.
            # Shared helper output includes object conditions and texture cleanup.
            mod_lines.extend(M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ))
            # Wrap the whole bind/draw sequence, not only its drawindexed lines.
            # The helper checks the original VS before either command-list path.
            yysls_cloth.append_scoped_submesh(
                texture_override_ib_section, custom_section, mod_lines,
                texture_override_name_suffix,
            )

            if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

            texture_override_ib_section.append("endif")
            texture_override_ib_section.new_line()

        ini_builder.append_section(texture_override_ib_section)
        ini_builder.append_section(custom_section)

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
