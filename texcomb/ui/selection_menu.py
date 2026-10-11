"""UI menu for material selection operations.

This module provides a dropdown menu with options for selecting or deselecting
all materials in the Material Combiner addon.
"""

import bpy

from ...i18n.i18n import tr, translatable


@translatable
class MIMISMC_MT_SelectionMenu(bpy.types.Menu):
    """Dropdown menu for material selection actions.

    This class implements a Blender menu that allows users to quickly
    select or deselect all materials in the Material Combiner UI.
    """

    bl_label = "Selection Operations"
    bl_idname = "MIMISMC_MT_SelectionMenu"

    def draw(self, context):
        """Define the contents of the menu.

        Args:
            context: The current Blender context.
        """
        layout = self.layout
        layout.operator("mimi.select_all", text=tr("Select All"))
        layout.operator("mimi.select_none", text=tr("Deselect All"))
