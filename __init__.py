import bpy


from .common import global_properties
from .common import gimi_body_outline


# UI panels
from .ui import ui_panel_basic
from .ui import ui_panel_model
from .sword import ui_panel_sword
from .ui import ui_func_import_ssmt
from .ui import ui_panel_fast_texture

from .blueprint import blueprint_node_obj
from .blueprint import blueprint_node_base
from .blueprint import blueprint_node_menu
from .blueprint import blueprint_node_shapekey
from .blueprint import blueprint_node_panel

from .blueprint import blueprint_node_custom_shader
from .blueprint import blueprint_node_face_mod
from .blueprint import blueprint_node_group
from .blueprint import blueprint_file_drop
from .blueprint import blueprint_node_highlight

from .ui import ui_func_export

# Automatic update
from . import addon_updater_ops

# Texture combiner tool (texcomb) - material merge feature integrated from another add-on
from . import texcomb

# While developing, also keep addon_updater_ops up to date automatically
import importlib
importlib.reload(addon_updater_ops)

bl_info = {
    "name": "MIMIBlender",
    "description": "The Blender add-on for MIMITools",
    "blender": (5, 2, 0),
    "version": (1, 0, 2),
    "location": "View3D",
    "category": "Generic"
}


class UpdaterPanel(bpy.types.Panel):
    """Update Panel"""
    bl_label = "Check for Updates"
    bl_idname = "MIMI_PT_UpdaterPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_context = "objectmode"
    bl_category = "MIMITools"
    bl_order = 99
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        
        # Call to check for update in background.
        # Note: built-in checks ensure it runs at most once, and will run in
        # the background thread, not blocking or hanging blender.
        # Internally also checks to see if auto-check enabled and if the time
        # interval has passed.
        # addon_updater_ops.check_for_update_background()
        col = layout.column()
        col.scale_y = 0.7
        # Could also use your own custom drawing based on shared variables.
        if addon_updater_ops.updater.update_ready:
            layout.label(text="Update available!", icon="INFO")

        # Call built-in function with draw code/checks.
        # addon_updater_ops.update_notice_box_ui(self, context)
        addon_updater_ops.update_settings_ui(self, context)


class MIMIBlenderUpdatePreference(bpy.types.AddonPreferences):
    # Addon updater preferences.
    bl_label = "MIMIBlender Updater"
    bl_idname = __package__

    
    auto_check_update: bpy.props.BoolProperty(
        name="Automatically Check for Updates",
        description="If enabled, check for updates automatically at the configured interval.",
        default=True) # type: ignore

    updater_interval_months: bpy.props.IntProperty(
        name='Months',
        description="Number of months between automatic update checks.",
        default=0,
        min=0) # type: ignore

    updater_interval_days: bpy.props.IntProperty(
        name='Days',
        description="Number of days between automatic update checks.",
        default=1,
        min=0,
        max=31) # type: ignore

    updater_interval_hours: bpy.props.IntProperty(
        name='Hours',
        description="Number of hours between automatic update checks.",
        default=0,
        min=0,
        max=23) # type: ignore

    updater_interval_minutes: bpy.props.IntProperty(
        name='Minutes',
        description="Number of minutes between automatic update checks.",
        default=0,
        min=0,
        max=59) # type: ignore
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "auto_check_update")
        addon_updater_ops.update_settings_ui(self, context)

def register():
    # Fault-tolerant registration per module: in the past a single node class
    # failing to register broke the whole register chain and made all the
    # sidebar panels disappear. This guarantees that one failing module does
    # not affect the others; failures are printed to the console for debugging.
    for step in _register_steps():
        try:
            step()
        except Exception:
            import traceback
            print(f"[MIMIBlender] register step failed: {getattr(step, '__module__', step)}")
            traceback.print_exc()


def _register_steps():
    # 1. Configs
    yield global_properties.register
    yield gimi_body_outline.register

    # 2. Addon Updater (local classes)
    def _register_updater():
        addon_updater_ops.register(bl_info)
        bpy.utils.register_class(UpdaterPanel)
        bpy.utils.register_class(MIMIBlenderUpdatePreference)
    yield _register_updater

    # 3. UI Panels & Logic
    yield blueprint_node_base.register
    yield blueprint_node_group.register
    yield ui_panel_basic.register
    yield ui_panel_model.register
    yield ui_panel_sword.register
    yield ui_func_import_ssmt.register
    yield ui_panel_fast_texture.register

    # Blueprint system
    # The ShapeKey PropertyGroup must be registered before the Generate Mod node that references it.
    yield blueprint_node_shapekey.register
    yield blueprint_node_obj.register
    yield ui_func_export.register
    yield blueprint_node_menu.register
    yield blueprint_node_panel.register

    yield blueprint_node_custom_shader.register
    yield blueprint_node_face_mod.register
    yield blueprint_file_drop.register
    yield blueprint_node_highlight.register

    # Texture combiner tool (texcomb)
    yield texcomb.register


def unregister():
    # Unregister in the reverse order of register to avoid type dependency issues.
    # Step-by-step fault tolerance: a previous session may have left a half-registered
    # state (for example a class that never registered successfully). Unregistering it
    # directly would raise RuntimeError and break all later unregister steps, causing
    # "already registered" failures and missing panels on the next enable.
    def _unregister_updater():
        bpy.utils.unregister_class(MIMIBlenderUpdatePreference)
        bpy.utils.unregister_class(UpdaterPanel)
        addon_updater_ops.unregister()

    steps = [
        gimi_body_outline.unregister,
        texcomb.unregister,
        blueprint_node_highlight.unregister,
        blueprint_file_drop.unregister,
        blueprint_node_face_mod.unregister,
        blueprint_node_group.unregister,
        blueprint_node_custom_shader.unregister,
        blueprint_node_panel.unregister,
        blueprint_node_menu.unregister,
        ui_func_export.unregister,
        blueprint_node_obj.unregister,
        blueprint_node_shapekey.unregister,
        ui_panel_fast_texture.unregister,
        ui_func_import_ssmt.unregister,
        ui_panel_sword.unregister,
        ui_panel_model.unregister,
        ui_panel_basic.unregister,
        blueprint_node_base.unregister,
        _unregister_updater,
        global_properties.unregister,
    ]
    for step in steps:
        try:
            step()
        except Exception:
            import traceback
            print(f"[MIMIBlender] unregister step failed: {getattr(step, '__module__', step)}")
            traceback.print_exc()



