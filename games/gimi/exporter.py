"""
GIMI (Genshin Impact) mod exporter.

GIMI-specific pieces kept here:
- the IB overrides emit the automatic ps-t slot texture assignments and
  the optional ORFix/NNFix command when a normal map is present,
- the VertexLimitRaise section never carries uav_byte_stride.

Everything else (pipeline, VB overrides, resource sections, texture
sections) comes from the shared base.  The unused compute-shader variants
that were copy-pasted from unity.py were dropped; the canonical versions
live in games/base/sections.py should they ever be needed.
"""

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...common.m_ini_helper import M_IniHelper
from ..base.standard_exporter import StandardExporter
from ..base import sections


def _slot_texture_lines(drawib_model, submesh_model) -> list[str]:
    """Return the automatic ps-t slot assignment lines for one SubMesh.

    Slot style textures are generated from the Submesh texture marks, so the
    blueprint does not need Texture nodes anymore.
    """
    lines = []
    seen_keys = set()
    for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
        mark_type = str(getattr(texture_markup_info, "mark_type", "") or "")
        if mark_type not in ("Slot", "SharedSlot"):
            continue
        resource_name = texture_markup_info.get_resource_name()
        key = (texture_markup_info.mark_slot, resource_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        lines.append(texture_markup_info.mark_slot + " = " + resource_name)
    return lines


def _slot_texture_has_normal_map(drawib_model, submesh_model) -> bool:
    """Return whether any Slot texture of this SubMesh carries a normal map semantic."""
    for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
        mark_type = str(getattr(texture_markup_info, "mark_type", "") or "")
        if mark_type not in ("Slot", "SharedSlot"):
            continue
        values = (
            str(getattr(texture_markup_info, "mark_slot", "") or ""),
            str(getattr(texture_markup_info, "mark_name", "") or ""),
            str(getattr(texture_markup_info, "mark_filename", "") or ""),
            str(texture_markup_info.get_resource_name() or ""),
        )
        if any("normal" in value.casefold() for value in values):
            return True
    return False


def _append_slot_texture_lines(section, drawib_model, submesh_model):
    """Append the automatic slot texture lines plus the ORFix/NNFix command when enabled."""
    if MIMIGlobalProperties.forbid_auto_texture_ini():
        return
    slot_lines = _slot_texture_lines(drawib_model, submesh_model)
    if not slot_lines:
        return
    for line in slot_lines:
        section.append(line)
    if MIMIGlobalProperties.gimi_use_orfix():
        if _slot_texture_has_normal_map(drawib_model, submesh_model):
            section.append(r"run = CommandList\global\ORFix\ORFix")
        else:
            section.append(r"run = CommandList\global\ORFix\NNFix")


class Exporter(StandardExporter):
    """GIMI exporter: shared pipeline, GIMI-specific IB override sections."""

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

            # Automatic slot textures from the Submesh texture marks
            _append_slot_texture_lines(texture_override_ib_section, drawib_model, submesh_model)

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

        ini_builder.append_section(texture_override_ib_section)
