'''
Version Update Panel

Sidebar panel that hosts the MIMIBlender addon updater controls inside the
MIMITools category. The actual updater logic lives in the root-level
addon_updater_ops module; this file only provides the panel shell so the
UI registration order stays identical to the other ui_panel_* modules.
'''
import bpy

# Imported as a module (not names) so a partially reloaded addon can never
# leave stale function references behind in this panel.
from .. import addon_updater_ops
from ..i18n.i18n import translatable


@translatable
class MIMIPanelUpdater(bpy.types.Panel):
    '''Check for and install MIMIBlender updates from the sidebar.'''
    bl_label = "Version Update"
    bl_idname = "MIMI_PT_updater"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'
    # Draw at the very bottom of the MIMITools category: updating is a
    # maintenance action, not part of the daily modding workflow.
    bl_order = 99
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        # Kick the one-time background check. Built-in guards (global flag +
        # engine interval gating) ensure this runs at most once per session
        # even though the panel redraws constantly, and the actual network
        # request runs on a background thread so Blender never hangs.
        addon_updater_ops.check_for_update_background()

        # Red banner, only drawn while an update is ready to install.
        addon_updater_ops.update_notice_box_ui(self, context)

        # Full updater controls: auto-check toggle, check-now button,
        # update-now button, version target picker and backup restore.
        addon_updater_ops.update_settings_ui(self, context)


def register():
    bpy.utils.register_class(MIMIPanelUpdater)


def unregister():
    bpy.utils.unregister_class(MIMIPanelUpdater)
