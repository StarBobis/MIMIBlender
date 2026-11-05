"""Persistent atlas output defaults, independent of the current blend file."""
import os

import bpy

from ..i18n.i18n import I18nOperator, tr


def addon_preferences(context):
    """Use the actual loaded package name, including renamed addon installs."""
    # Blender indexes preferences by root module, not by the product title.
    module = __package__.split(".")[0]
    addon = context.preferences.addons.get(module)
    return addon.preferences if addon else None


def default_output_directory(context):
    """Return the remembered absolute path, never a scene-specific fallback."""
    prefs = addon_preferences(context)
    path = str(getattr(prefs, "atlas_output_directory", "") or "").strip()
    # Absolute storage prevents a new blend from changing relative resolution.
    return os.path.normpath(bpy.path.abspath(path)) if path else ""


def remember_output_directory(context, directory):
    """Persist a validated directory even when automatic saving is disabled."""
    path = os.path.normpath(bpy.path.abspath(directory))
    if not os.path.isdir(path):
        raise ValueError(tr("Please select an existing output folder"))
    prefs = addon_preferences(context)
    if prefs is None:
        raise RuntimeError(tr("Add-on preferences are unavailable"))
    # Keep the previous value if writing Blender's preferences fails.
    previous = prefs.atlas_output_directory
    prefs.atlas_output_directory = path
    try:
        if bpy.ops.wm.save_userpref() != {"FINISHED"}:
            raise RuntimeError(tr("Could not save the default output folder"))
    except Exception:
        prefs.atlas_output_directory = previous
        raise
    return path


def draw_output_directory(layout, context):
    """Show the default alongside an explicit folder chooser."""
    path = default_output_directory(context)
    row = layout.row(align=True)
    # Avoid a raw editable property: selecting a folder is the persistence action.
    row.label(text=tr("Default Output Folder"), icon="FILE_FOLDER")
    row.operator("mimi.choose_atlas_output_directory", text=tr("Choose Folder"))
    layout.label(text=path or tr("Choose once; future merges use this folder"))


class ChooseAtlasOutputDirectory(I18nOperator):
    """Choose and persist a default without running a destructive merge."""
    bl_idname = "mimi.choose_atlas_output_directory"
    bl_label = "Default Output Folder"
    bl_description = "Remember this folder for future texture merges"
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN"})
    filter_glob: bpy.props.StringProperty(default="", options={"HIDDEN"})

    def invoke(self, context, event):
        # The folder browser starts at the remembered location when available.
        self.directory = default_output_directory(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            remember_output_directory(context, self.directory)
        except (ValueError, RuntimeError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Default output folder saved"))
        return {"FINISHED"}

    def draw(self, context):
        # Directory-only browsing needs no extra operator controls.
        pass


classes = (ChooseAtlasOutputDirectory,)
