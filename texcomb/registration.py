"""Registration module for the Material Combiner addon.

This module handles the registration and unregistration of all Blender classes
used by the addon. It also manages version-specific property annotations.
"""

import bpy

from . import (
    extend_lists,
    extend_types,
    globs,
    operators,
    ui,
)

__bl_classes = [
    ui.selection_menu.SMC_MT_SelectionMenu,
    ui.main_panel.MaterialCombinerPanel,
    ui.property_panel.PropertyMenu,
    operators.combine_list.MaterialListRefreshOperator,
    operators.combine_list.MaterialListToggleOperator,
    operators.combine_list.SelectAllMaterials,
    operators.combine_list.SelectNoneMaterials,
    operators.combiner.Combiner,
    operators.get_pillow.InstallPIL,
    operators.get_pillow.CheckPillow,
    extend_types.CombineListEntry,
    extend_lists.SMC_UL_Combine_List,
]


def register_all() -> None:
    """Register all components of the addon.

    Registers all classes and properties used by the material combiner.
    Called from the main TheHerta4 plugin's register().
    """
    _register_classes()
    extend_types.register()


def unregister_all() -> None:
    """Unregister all components of the addon.

    Unregisters all classes and properties used by the material combiner.
    Called from the main TheHerta4 plugin's unregister().
    """
    _unregister_classes()
    extend_types.unregister()


def _register_classes() -> None:
    """Register all Blender classes used by the addon.

    Blender 5.2 reads add-on properties directly from class annotations.
    """
    count = 0
    for cls in __bl_classes:
        try:
            bpy.utils.register_class(cls)
            count += 1
        except ValueError as e:
            print("Error:", cls, e)
    print("Registered", count, "Material Combiner classes.")
    if count < len(__bl_classes):
        print(
            "Skipped", len(__bl_classes) - count, "Material Combiner classes."
        )


def _unregister_classes() -> None:
    """Unregister all Blender classes used by the addon.

    Classes are unregistered in reverse order to handle dependencies.
    """
    count = 0
    for cls in reversed(__bl_classes):
        try:
            bpy.utils.unregister_class(cls)
            count += 1
        except (ValueError, RuntimeError) as e:
            print("Error:", cls, e)
    print("Unregistered", count, "Material Combiner classes.")
