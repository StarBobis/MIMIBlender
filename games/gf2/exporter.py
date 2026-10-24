"""
GF2 (Girls' Frontline 2) mod exporter.

This file is a COPY of the GIMI exporter, deliberately not a subclass of it:
GF2 ships the Genshin mod layout (texture-slot API, IB override sections)
only as a starting point and is expected to grow its own logic, so the two
implementations must be free to diverge. A fix that applies to both is meant
to be applied twice; never import or inherit GIMI's exporter from here.

Kept identical to the GIMI exporter for now:
- the IB overrides submit name-driven logical textures to the texture API,
  with physical fallbacks for names the package does not recognize,
- the VertexLimitRaise section never carries uav_byte_stride.

Everything else (pipeline, VB overrides, resource sections, texture
sections) comes from the shared base in games/base/.
"""

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...common.m_ini_helper import M_IniHelper
from ..base.standard_exporter import StandardExporter
from ..base import sections
from ...common.gimi_texture_slots import collect_gimi_texture_bindings, gimi_texture_lines


def _append_slot_texture_lines(section, drawib_model, submesh_model):
    """Submit automatic marks through the package's semantic API."""
    if MIMIGlobalProperties.forbid_auto_texture_ini():
        return
    logical, physical = collect_gimi_texture_bindings(
        drawib_model.get_submesh_texture_markup_info_list(submesh_model)
    )
    for line in gimi_texture_lines(logical, physical):
        section.append(line)


class GF2Exporter(StandardExporter):
    """GF2 exporter: Genshin-style pipeline plus IB override sections."""

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # GIMI's VertexLimitRaise never carries uav_byte_stride.
        sections.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model, include_uav_byte_stride=False)
        sections.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model, blueprint_model=self.blueprint_model)
        self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # IB overrides: skip the whole original IB first, then re-emit every
        # Submesh with its modded IB and the automatic slot textures.
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

            # Objects with semantic MARK overrides need a fresh complete API
            # submission before each draw because SetTextures clears its inputs.
            has_semantic_overrides = any(
                (getattr(draw, "resolved_gimi_texture_bindings", {}) or getattr(draw, "global_gimi_texture_defaults", {}))
                for draw in submesh_model.drawcall_model_list
            )
            if has_semantic_overrides:
                logical, physical = ({}, [])
                if not MIMIGlobalProperties.forbid_auto_texture_ini():
                    logical, physical = collect_gimi_texture_bindings(
                        drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                    )

                def effective_lines(draw):
                    # A draw starts from defaults, never from the previous object.
                    effective = dict(logical)
                    # Merge from scratch because SetTextures consumes its inputs.
                    # Global defaults override automatic captures only for this Submesh.
                    # Connected semantic replacements are applied last and always win.
                    effective.update(getattr(draw, "global_gimi_texture_defaults", {}))
                    effective.update(getattr(draw, "resolved_gimi_texture_bindings", {}))
                    return gimi_texture_lines(effective, physical)

                M_IniHelper.append_drawindexed_with_slot_lines(
                    texture_override_ib_section,
                    submesh_model.drawcall_model_list,
                    effective_lines,
                    obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
                )
                continue

            _append_slot_texture_lines(texture_override_ib_section, drawib_model, submesh_model)
            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

        ini_builder.append_section(texture_override_ib_section)
