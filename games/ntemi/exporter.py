"""
NTEMI (Neverness to Everness) mod exporter.

NTEMI uses the NTMIv1 skinning framework with its own INI layout (no
section reordering, custom collector / skin command list sections), so it
does not follow the standard single-INI pipeline.  This module only holds
the exporter itself; the buffer writers live in buffers.py and the INI
section builders in sections.py.
"""

import os
from dataclasses import dataclass, field

from ...model.blueprint_model import BluePrintModel
from ...model.drawib_model import DrawIBModel
from ...common.global_config import GlobalConfig
from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder
from ...common.m_ini_helper import M_IniHelper
from . import buffers
from . import sections


@dataclass
class Exporter:
    """NTEMI exporter: NTMIv1 buffers + custom INI layout."""

    blueprint_model: BluePrintModel
    drawib_model_list: list[DrawIBModel] = field(default_factory=list, init=False)

    def __post_init__(self):
        # Parse the blueprint into DrawIB models and resolve the aliases.
        self.drawib_model_list = self.blueprint_model.parse_drawib_model_list(combine_ib=False)
        for drawib_model in self.drawib_model_list:
            drawib_model.apply_drawib_alias()

    def generate_ini_file(self):
        """Assemble every INI section in output order, then write the file."""
        lines: list[str] = []

        drawib_drawibmodel_dict: dict[str, DrawIBModel] = {}
        draw_ib_active_index_dict: dict[str, int] = {}
        for index, drawib_model in enumerate(self.drawib_model_list):
            draw_ib = drawib_model.draw_ib
            drawib_drawibmodel_dict[draw_ib] = drawib_model
            draw_ib_active_index_dict[draw_ib] = index

        suffix = sections.source_suffix(self.drawib_model_list)

        sections.append_constants(lines)
        sections.append_present(lines)
        sections.append_setup_commandlist(lines)
        sections.append_resource_sections(lines, self.drawib_model_list, suffix)
        sections.append_collector(lines, suffix, self.drawib_model_list)
        sections.append_skin_commandlist(lines, suffix, self.drawib_model_list)
        sections.append_draw_overrides(
            lines,
            self.drawib_model_list,
            draw_ib_active_index_dict,
            suffix,
            self.blueprint_model.keyname_mkey_dict,
        )

        # Texture Bind node resources are explicit user intent: they apply
        # even when the automatic texture pipeline is disabled.
        sections.append_object_texture_binding_resources(lines, self.drawib_model_list)

        # Texture handling
        tex_ini_builder = M_IniBuilder()
        global_hash_rows = getattr(self.blueprint_model, "global_hash_texture_binding_list", [])
        M_IniHelper.generate_hash_style_global_texture_ini(
            ini_builder=tex_ini_builder,
            global_hash_texture_binding_list=global_hash_rows,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
        )
        if not MIMIGlobalProperties.forbid_auto_texture_ini():
            sections.append_texture_resources(lines, self.drawib_model_list)
            # Also generate hash-style texture overrides (standard for all game types)
            M_IniHelper.generate_hash_style_texture_ini(
                ini_builder=tex_ini_builder,
                drawib_drawibmodel_dict=drawib_drawibmodel_dict,
                global_hash_texture_binding_list=global_hash_rows,
            )
            M_IniHelper.generate_shared_slot_style_texture_ini(
                ini_builder=tex_ini_builder,
                drawib_drawibmodel_dict=drawib_drawibmodel_dict,
            )
            for drawib_model in self.drawib_model_list:
                M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)

        # Hash Texture Bind conditional overrides are explicit user intent
        # and are emitted even when the automatic texture pipeline is off.
        M_IniHelper.generate_hash_style_object_texture_ini(
            ini_builder=tex_ini_builder,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
            global_hash_texture_binding_list=global_hash_rows,
        )
        # Copy explicit replacements last so marked filenames keep the
        # external bytes instead of being restored by automatic Hash export.
        for drawib_model in self.drawib_model_list:
            M_IniHelper.move_object_texture_binding_files(draw_ib_model=drawib_model)
        for section in tex_ini_builder.ini_section_list:
            for sl in section.SectionLineList:
                if sl:
                    lines.append(sl)

        GlobalConfig.generated_mod_number = len(self.drawib_model_list)

        # Branch key sections
        key_lines = sections.build_branch_key_lines(self.blueprint_model.keyname_mkey_dict)
        lines.extend(key_lines)

        ini_filepath = os.path.join(
            GlobalConfig.path_generate_mod_folder(),
            GlobalConfig.get_generated_mod_name() + ".ini",
        )
        sections.write_ini(ini_filepath, lines)

    def export(self):
        """Write the NTMIv1 buffers, then generate the INI file."""
        buffers.generate_buffer_files(self.drawib_model_list)
        self.generate_ini_file()
