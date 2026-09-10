"""UI integration module for Material Combiner.

This module provides functions to draw the Material Combiner UI within other
addons or UI panels. It handles the main UI parts including the material
list, action buttons, and support links.
"""

import bpy
import textwrap

from ....i18n.i18n import tr
from ... import globs
from ...type_annotations import Scene
from ...ui.main_panel import MaterialCombinerPanel


def draw_ui(context: bpy.types.Context, m_col: bpy.types.UILayout) -> None:
    """Draw the Material Combiner UI in the provided layout.

    Args:
        context: Current Blender context.
        m_col: UILayout to draw the Material Combiner interface in.
    """
    if globs.pil_available:
        _materials_list(context.scene, m_col)
    elif globs.pil_install_attempted:
        if globs.pil_install_success:
            col = m_col.box().column()
            col.label(text=tr("Installation Complete"), icon="CHECKMARK")
            col.label(text=tr("Pillow is installed; restart Blender to use it"))
        else:
            box = m_col.box().column()
            box.label(text=tr("Installation Failed"), icon="ERROR")
            box.separator()

            if globs.pil_install_error_message:
                error_box = box.box()
                error_col = error_box.column()
                error_col.label(text=tr("Error details:"), icon="INFO")
                for line in textwrap.wrap(globs.pil_install_error_message, width=60):
                    error_col.label(text=line)
                box.separator()

            row = box.row(align=True)
            row.scale_y = 1.2
            row.operator("smc.get_pillow", text=tr("Retry Install"), icon="FILE_REFRESH")
            row.operator("smc.check_pillow", text=tr("Check Install"), icon="FILE_TICK")
    else:
        MaterialCombinerPanel.draw_pillow_installer(context, m_col)


def _materials_list(scn: Scene, m_col: bpy.types.UILayout) -> None:
    """Draw the material list and associated UI components.

    Draws the material list template, update button, save atlas button,
    and support links for the addon.

    Args:
        scn: Current Blender scene.
        m_col: UILayout to draw the material list in.
    """

    if scn.smc_ob_data:
        m_col.template_list(
            "SMC_UL_Combine_List",
            "combine_list",
            scn,
            "smc_ob_data",
            scn,
            "smc_ob_data_id",
            rows=12,
            type="DEFAULT",
        )
    col = m_col.column(align=True)
    col.scale_y = 1.2
    col.operator(
        "smc.refresh_ob_data",
        text=tr("Refresh Material List")
        if scn.smc_ob_data
        else tr("Generate Material List"),
    )
    col = m_col.column()
    col.scale_y = 1.5
    col.operator(
        "smc.combiner", text=tr("Save Atlas to...")
    ).cats = True
    col.separator()
    col = m_col.column()
    col.label(text=tr("If this addon saved you some time:"))

