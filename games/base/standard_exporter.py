"""
Shared export skeleton for the "single INI file" game exporters.

Most game presets follow the exact same export flow:

1. write the IB/VB buffer files of every DrawIB,
2. emit the automatic Hash / SharedSlot texture sections,
3. emit the game-specific sections of every DrawIB,
4. emit the closing sections (branch keys + shape keys),
5. save the INI next to the buffers (flat layout).

Only step 3 really differs from game to game, so this module implements the
shared flow once and lets every game plug in its own section builders
through the hook methods of StandardExporter.
"""

import os

from ...common.global_config import GlobalConfig
from ...common.m_ini_builder import M_IniBuilder
from ...common.m_ini_helper import M_IniHelper


class StandardExporter:
    """Base class implementing the standard mod export pipeline.

    A game exporter subclasses this and overrides add_drawib_sections()
    with its own section assembly.  Everything else (buffer generation,
    texture automation, branch keys, shape keys, INI saving) is inherited.
    """

    def __init__(self, blueprint_model):
        # Parse the blueprint into DrawIB models (one per DrawIB hash) and
        # resolve the user-facing aliases before any section is generated.
        self.blueprint_model = blueprint_model
        self.drawib_model_list = blueprint_model.parse_drawib_model_list(combine_ib=False)
        for drawib_model in self.drawib_model_list:
            drawib_model.apply_drawib_alias()

    # ------------------------------------------------------------------
    # Hooks: the parts every game may customize
    # ------------------------------------------------------------------

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        """Append the game-specific INI sections of one DrawIB.

        Called once per DrawIB, right before its slot textures are moved and
        the generated mod number is incremented.
        """
        raise NotImplementedError

    def add_final_sections(self, ini_builder: M_IniBuilder, drawib_drawibmodel_dict: dict):
        """Append the sections closing the INI (branch keys + shape keys)."""
        M_IniHelper.add_branch_key_sections(
            ini_builder=ini_builder,
            key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict,
            # Time Position Switch needs the model context to emit its
            # per-frame Position resources and [Present] copy lines.
            blueprint_model=self.blueprint_model,
            drawib_models=list(drawib_drawibmodel_dict.values()),
        )
        M_IniHelper.add_shapekey_ini_sections(
            ini_builder=ini_builder,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
        )

    def get_ini_file_path(self) -> str:
        """Return the output path of the generated mod INI (flat layout)."""
        return os.path.join(
            GlobalConfig.path_generate_mod_folder(),
            GlobalConfig.get_generated_mod_name() + ".ini",
        )

    # ------------------------------------------------------------------
    # Shared pipeline pieces (normally not overridden)
    # ------------------------------------------------------------------

    def generate_buffer_files(self):
        # Write every DrawIB's IB/VB buffers next to the generated INI.
        for drawib_model in self.drawib_model_list:
            drawib_model.generate_buffer_files(GlobalConfig.path_generatemod_buffer_folder())

    def export(self):
        """Run the full export: buffers, INI sections, then save the INI."""
        self.generate_buffer_files()

        ini_builder = M_IniBuilder()
        drawib_drawibmodel_dict = {
            drawib_model.draw_ib: drawib_model
            for drawib_model in self.drawib_model_list
        }

        # Automatic Hash / SharedSlot texture INI sections and file copies.
        M_IniHelper.generate_hash_style_texture_ini(
            ini_builder=ini_builder,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
        )
        M_IniHelper.generate_shared_slot_style_texture_ini(
            ini_builder=ini_builder,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
        )

        # Per-DrawIB sections: the game-specific content comes from the hook.
        for drawib_model in self.drawib_model_list:
            self.add_drawib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
            M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)
            M_IniHelper.move_object_texture_binding_files(draw_ib_model=drawib_model)
            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1

        self.add_final_sections(
            ini_builder=ini_builder,
            drawib_drawibmodel_dict=drawib_drawibmodel_dict,
        )
        ini_builder.save_to_file(self.get_ini_file_path())
