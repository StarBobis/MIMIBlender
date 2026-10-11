# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

"""Blender UI integrations for the MIMIBlender addon updater.

Implements draw calls, popups, and operators that drive the addon_updater
engine. The code is derived from the CGCookie blender-addon-updater demo
file (same integration TheHerta4 uses), adapted to the MIMIBlender
architecture:

- All user-visible text is routed through the addon's own i18n layer
  (tr / translatable / I18nOperator) instead of bpy.app.translations, so
  the updater UI follows the language picked in the addon preferences.
- Operators pass an explicit text=tr(...) at every draw site, because
  Blender freezes the RNA operator name at registration time while an
  explicit button label is evaluated on every redraw.
- The updater settings (auto-check toggle and check interval) live on the
  single MIMIAddonPreferences class defined in i18n/i18n.py, because one
  addon module can only own one AddonPreferences bl_idname.
"""

import os
import traceback

import bpy
from bpy.app.handlers import persistent

from .i18n.i18n import I18nOperator, tr, translatable

# Safely import the updater engine.
# Prevents popups for users with invalid python installs e.g. missing
# libraries, and replaces the engine with a fake class instead if it fails
# (so the UI draw calls below can never crash the whole addon).
try:
    from .addon_updater import Updater as updater
except Exception as e:
    print("ERROR INITIALIZING UPDATER")
    print(str(e))
    traceback.print_exc()

    class SingletonUpdaterNone(object):
        """Fake, bare minimum fields and functions for the updater object."""

        def __init__(self):
            self.invalid_updater = True  # Used to distinguish bad install.

            self.addon = None
            self.verbose = False
            self.use_print_traces = True
            self.error = None
            self.error_msg = None
            self.async_checking = None

        def clear_state(self):
            self.addon = None
            self.verbose = False
            self.invalid_updater = True
            self.error = None
            self.error_msg = None
            self.async_checking = None

        def run_update(self, force, callback, clean):
            pass

        def check_for_update(self, now):
            pass

    updater = SingletonUpdaterNone()
    updater.error = "Error initializing updater module"
    updater.error_msg = str(e)

# Must declare this before classes are loaded, otherwise the bl_idname's will
# not match and have errors. Must be all lowercase and no spaces! Should also
# be unique among any other addons that could exist (using this updater code),
# to avoid clashes in operator registration.
updater.addon = "mimiblender"

# Repository the updater pulls new versions from. Only these three constants
# need to change if the addon ever moves to another GitHub location.
GITHUB_OWNER = "StarBobis"
GITHUB_REPOSITORY = "MIMIBlender"
GITHUB_REPOSITORY_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPOSITORY}"
)


# -----------------------------------------------------------------------------
# Blender version utils
# -----------------------------------------------------------------------------

def layout_split(layout, factor=0.0, align=False):
    """Split a layout using Blender 5.2's factor API."""
    return layout.split(factor=factor, align=align)


def get_user_preferences(context=None):
    """Return this add-on's preferences object, or None when unavailable."""
    if not context:
        context = bpy.context
    # The preferences bl_idname matches the addon root module name, which is
    # exactly what __package__ resolves to for this root-level module.
    prefs = context.preferences.addons.get(__package__, None)
    if prefs:
        return prefs.preferences
    # To make the addon stable and non-exception prone, return None.
    return None


# -----------------------------------------------------------------------------
# Updater operators
# -----------------------------------------------------------------------------


# Simple popup to prompt the user to check for an update & offer install if
# one is available.
@translatable
class AddonUpdaterInstallPopup(I18nOperator):
    """Check and install update if available"""
    bl_label = "Update MIMIBlender Addon"
    bl_idname = updater.addon + ".updater_install_popup"
    bl_description = "Popup to check and display current updates available"
    bl_options = {'REGISTER', 'INTERNAL'}

    # If true, run a clean install - ie remove all files before adding the
    # new ones; equivalent to deleting the addon and reinstalling, except
    # the updater staging/backup folders remain.
    clean_install: bpy.props.BoolProperty(
        name="Clean install",
        description=("If enabled, completely clear the addon's folder before "
                     "installing the new update, creating a fresh install"),
        default=False,
        options={'HIDDEN'}
    )  # type: ignore

    def _ignore_items(self, context):
        # Dynamic enum items so the radio button labels follow the selected
        # UI language live (static enum items freeze at registration time).
        return [
            ("install", tr("Update Now"),
             tr("Install the update now")),
            ("ignore", tr("Ignore"),
             tr("Ignore this update to prevent future popups")),
            ("defer", tr("Defer"),
             tr("Defer the choice until the next Blender session")),
        ]

    ignore_enum: bpy.props.EnumProperty(
        name="Process update",
        description="Decide to install, ignore, or defer the new addon update",
        items=_ignore_items,
        options={'HIDDEN'}
    )  # type: ignore

    def check(self, context):
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        if updater.invalid_updater:
            layout.label(text=tr("Updater module error"))
            return
        elif updater.update_ready:
            col = layout.column()
            col.scale_y = 0.7
            col.label(
                text=tr("Update {version} ready!").format(
                    version=updater.update_version),
                icon="LOOP_FORWARDS")
            col.label(text=tr("Choose 'Update Now' & press OK to install,"),
                      icon="BLANK1")
            col.label(text=tr("or click outside the window to defer"),
                      icon="BLANK1")
            row = col.row()
            row.prop(self, "ignore_enum", expand=True)
            col.split()
        elif not updater.update_ready:
            col = layout.column()
            col.scale_y = 0.7
            col.label(text=tr("No updates available"))
            col.label(text=tr("Press OK to dismiss the dialog"))
            # Could add an option here to force a reinstall.
        else:
            # Case: updater.update_ready = None, ie we have not yet checked
            # for an update in this session.
            layout.label(text=tr("Check for update now?"))

        # Potentially in future, UI to 'check to select/revert to old version'.

    def execute(self, context):
        # In case of error importing the updater engine.
        if updater.invalid_updater:
            return {'CANCELLED'}

        if updater.manual_only:
            bpy.ops.wm.url_open(url=updater.website)
        elif updater.update_ready:

            # Action based on the enum selection.
            if self.ignore_enum == 'defer':
                return {'FINISHED'}
            elif self.ignore_enum == 'ignore':
                updater.ignore_update()
                return {'FINISHED'}

            res = updater.run_update(force=False,
                                     callback=post_update_callback,
                                     clean=self.clean_install)

            # Should return 0, if not something happened.
            if updater.verbose:
                if res == 0:
                    print("Updater returned successful")
                else:
                    print("Updater returned {}, error occurred".format(res))
        elif updater.update_ready is None:
            _ = updater.check_for_update(now=True)

            # Re-launch this dialog.
            atr = AddonUpdaterInstallPopup.bl_idname.split(".")
            getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')
        else:
            updater.print_verbose("Doing nothing, not ready for update")
        return {'FINISHED'}


# User preference check-now operator.
@translatable
class AddonUpdaterCheckNow(I18nOperator):
    bl_label = "Check for Update Now"
    bl_idname = updater.addon + ".updater_check_now"
    bl_description = "Check for an update to the MIMIBlender addon"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        if updater.invalid_updater:
            return {'CANCELLED'}

        if updater.async_checking and updater.error is None:
            # Check already happened.
            # Used here to just avoid constant applying settings below.
            # Ignoring if error, to prevent being stuck on the error screen.
            return {'CANCELLED'}

        # Apply the UI settings (interval gating honors the user preference).
        settings = get_user_preferences(context)
        if not settings:
            updater.print_verbose(
                "Could not get {} preferences, update check skipped".format(
                    __package__))
            return {'CANCELLED'}
        updater.set_check_interval(
            enabled=settings.auto_check_update,
            months=settings.updater_interval_months,
            days=settings.updater_interval_days,
            hours=settings.updater_interval_hours,
            minutes=settings.updater_interval_minutes)

        # Input is an optional callback function. This function should take a
        # bool input. If true: update ready, if false: no update ready.
        updater.check_for_update_now(ui_refresh)

        return {'FINISHED'}


@translatable
class AddonUpdaterUpdateNow(I18nOperator):
    bl_label = "Update MIMIBlender Now"
    bl_idname = updater.addon + ".updater_update_now"
    bl_description = "Update to the latest version of the MIMIBlender addon"
    bl_options = {'REGISTER', 'INTERNAL'}

    # If true, run a clean install - ie remove all files before adding the
    # new ones; equivalent to deleting the addon and reinstalling, except
    # the updater staging/backup folders remain.
    clean_install: bpy.props.BoolProperty(
        name="Clean install",
        description=("If enabled, completely clear the addon's folder before "
                     "installing the new update, creating a fresh install"),
        default=False,
        options={'HIDDEN'}
    )  # type: ignore

    def execute(self, context):

        # In case of error importing the updater engine.
        if updater.invalid_updater:
            return {'CANCELLED'}

        if updater.manual_only:
            bpy.ops.wm.url_open(url=updater.website)
        if updater.update_ready:
            # If it fails, offer to open the website instead.
            try:
                res = updater.run_update(force=False,
                                         callback=post_update_callback,
                                         clean=self.clean_install)

                # Should return 0, if not something happened.
                if updater.verbose:
                    if res == 0:
                        print("Updater returned successful")
                    else:
                        print("Updater error response: {}".format(res))
            except Exception as expt:
                updater._error = "Error trying to run update"
                updater._error_msg = str(expt)
                updater.print_trace()
                atr = AddonUpdaterInstallManually.bl_idname.split(".")
                getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')
        elif updater.update_ready is None:
            (update_ready, version, link) = updater.check_for_update(now=True)
            # Re-launch this dialog.
            atr = AddonUpdaterInstallPopup.bl_idname.split(".")
            getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')

        elif not updater.update_ready:
            self.report({'INFO'}, tr("Nothing to update"))
            return {'CANCELLED'}
        else:
            self.report(
                {'ERROR'},
                tr("Encountered a problem while trying to update"))
            return {'CANCELLED'}

        return {'FINISHED'}


@translatable
class AddonUpdaterUpdateTarget(I18nOperator):
    bl_label = "Target Version"
    bl_idname = updater.addon + ".updater_update_target"
    bl_description = "Install a specific version of the MIMIBlender addon"
    bl_options = {'REGISTER', 'INTERNAL'}

    def target_version(self, context):
        # In case of error importing the updater engine.
        if updater.invalid_updater:
            return []

        # Dynamic enum over the tags fetched from the repository; the item
        # description is translated live on every redraw.
        ret = []
        for tag in updater.tags:
            ret.append(
                (tag, tag,
                 tr("Select to install version {tag}").format(tag=tag)))
        return ret

    target: bpy.props.EnumProperty(
        name="Target version to install",
        description="Select the version to install",
        items=target_version
    )  # type: ignore

    # If true, run a clean install - ie remove all files before adding the
    # new ones; equivalent to deleting the addon and reinstalling, except
    # the updater staging/backup folders remain.
    clean_install: bpy.props.BoolProperty(
        name="Clean install",
        description=("If enabled, completely clear the addon's folder before "
                     "installing the new update, creating a fresh install"),
        default=False,
        options={'HIDDEN'}
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        if updater.invalid_updater:
            return False
        return updater.update_ready is not None and len(updater.tags) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        if updater.invalid_updater:
            layout.label(text=tr("Updater error"))
            return
        split = layout_split(layout, factor=0.5)
        sub_col = split.column()
        sub_col.label(text=tr("Select install version"))
        sub_col = split.column()
        sub_col.prop(self, "target", text="")

    def execute(self, context):
        # In case of error importing the updater engine.
        if updater.invalid_updater:
            return {'CANCELLED'}

        res = updater.run_update(
            force=False,
            revert_tag=self.target,
            callback=post_update_callback,
            clean=self.clean_install)

        # Should return 0, if not something happened.
        if res == 0:
            updater.print_verbose("Updater returned successful")
        else:
            updater.print_verbose(
                "Updater returned {}, error occurred".format(res))
            return {'CANCELLED'}

        return {'FINISHED'}


@translatable
class AddonUpdaterInstallManually(I18nOperator):
    """As a fallback, direct the user to download the addon manually"""
    bl_label = "Install Update Manually"
    bl_idname = updater.addon + ".updater_install_manually"
    bl_description = "Proceed to manually install the update"
    bl_options = {'REGISTER', 'INTERNAL'}

    error: bpy.props.StringProperty(
        name="Error Occurred",
        default="",
        options={'HIDDEN'}
    )  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self)

    def draw(self, context):
        layout = self.layout

        if updater.invalid_updater:
            layout.label(text=tr("Updater error"))
            return

        # Display the error if a prior automated install failed.
        if self.error != "":
            col = layout.column()
            col.scale_y = 0.7
            col.label(text=tr("There was an issue trying to auto-install"),
                      icon="ERROR")
            col.label(text=tr("Press the download button below and install"),
                      icon="BLANK1")
            col.label(text=tr("the zip file like a normal addon."),
                      icon="BLANK1")
        else:
            col = layout.column()
            col.scale_y = 0.7
            col.label(text=tr("Install the addon update manually"))
            col.label(text=tr("Press the download button below and install"))
            col.label(text=tr("the zip file like a normal addon."))

        # If the check hasn't happened, ie this menu was opened by accident,
        # still allow fetching the download here.
        row = layout.row()

        if updater.update_link is not None:
            row.operator(
                "wm.url_open",
                text=tr("Direct download")).url = updater.update_link
        else:
            row.operator(
                "wm.url_open",
                text=tr("(failed to retrieve direct download)"))
            row.enabled = False

            if updater.website is not None:
                row = layout.row()
                ops = row.operator("wm.url_open", text=tr("Open website"))
                ops.url = updater.website
            else:
                row = layout.row()
                row.label(text=tr("See source website to download the update"))

    def execute(self, context):
        return {'FINISHED'}


@translatable
class AddonUpdaterUpdatedSuccessful(I18nOperator):
    """Addon in place, popup telling user it completed or what went wrong"""
    bl_label = "Installation Report"
    bl_idname = updater.addon + ".updater_update_successful"
    bl_description = "Update installation result report"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    error: bpy.props.StringProperty(
        name="Error Occurred",
        default="",
        options={'HIDDEN'}
    )  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_props_popup(self, event)

    def draw(self, context):
        layout = self.layout

        if updater.invalid_updater:
            layout.label(text=tr("Updater error"))
            return

        saved = updater.json
        if self.error != "":
            col = layout.column()
            col.scale_y = 0.7
            col.label(text=tr("Error occurred, did not install"), icon="ERROR")
            if updater.error_msg:
                msg = updater.error_msg
            else:
                msg = self.error
            col.label(text=str(msg), icon="BLANK1")
            rw = col.row()
            rw.scale_y = 2
            rw.operator(
                "wm.url_open",
                text=tr("Click for manual download."),
                icon="BLANK1").url = updater.website
        elif not updater.auto_reload_post_update:
            # Tell the user to restart blender after an update/restore!
            if "just_restored" in saved and saved["just_restored"]:
                col = layout.column()
                col.label(text=tr("Addon restored"), icon="RECOVER_LAST")
                alert_row = col.row()
                alert_row.alert = True
                alert_row.operator(
                    "wm.quit_blender",
                    text=tr("Restart Blender to reload"),
                    icon="BLANK1")
                updater.json_reset_restore()
            else:
                col = layout.column()
                col.label(text=tr("Addon successfully installed"),
                          icon="FILE_TICK")
                alert_row = col.row()
                alert_row.alert = True
                alert_row.operator(
                    "wm.quit_blender",
                    text=tr("Restart Blender to reload"),
                    icon="BLANK1")

        else:
            # Reload the addon, but still recommend a full blender restart.
            if "just_restored" in saved and saved["just_restored"]:
                col = layout.column()
                col.scale_y = 0.7
                col.label(text=tr("Addon restored"), icon="RECOVER_LAST")
                col.label(
                    text=tr("Consider restarting Blender to fully reload."),
                    icon="BLANK1")
                updater.json_reset_restore()
            else:
                col = layout.column()
                col.scale_y = 0.7
                col.label(text=tr("Addon successfully installed"),
                          icon="FILE_TICK")
                col.label(
                    text=tr("Consider restarting Blender to fully reload."),
                    icon="BLANK1")

    def execute(self, context):
        return {'FINISHED'}


@translatable
class AddonUpdaterRestoreBackup(I18nOperator):
    """Restore the addon from a previously created backup"""
    bl_label = "Restore Backup"
    bl_idname = updater.addon + ".updater_restore_backup"
    bl_description = "Restore the addon from a backup"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        try:
            return os.path.isdir(os.path.join(updater.stage_path, "backup"))
        except Exception:
            return False

    def execute(self, context):
        # In case of error importing the updater engine.
        if updater.invalid_updater:
            return {'CANCELLED'}
        updater.restore_backup()
        return {'FINISHED'}


@translatable
class AddonUpdaterIgnore(I18nOperator):
    """Ignore an update to prevent future popups"""
    bl_label = "Ignore Update"
    bl_idname = updater.addon + ".updater_ignore"
    bl_description = "Ignore this update to prevent future popups"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if updater.invalid_updater:
            return False
        elif updater.update_ready:
            return True
        else:
            return False

    def execute(self, context):
        # In case of error importing the updater engine.
        if updater.invalid_updater:
            return {'CANCELLED'}
        updater.ignore_update()
        self.report({"INFO"},
                    tr("Open addon preferences for updater options"))
        return {'FINISHED'}


@translatable
class AddonUpdaterEndBackground(I18nOperator):
    """Stop checking for an update in the background"""
    bl_label = "End Background Check"
    bl_idname = updater.addon + ".end_background_check"
    bl_description = "Stop checking for updates in the background"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        # In case of error importing the updater engine.
        if updater.invalid_updater:
            return {'CANCELLED'}
        updater.stop_async_check_update()
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Handler related, to create popups
# -----------------------------------------------------------------------------


# Global vars used to prevent duplicate popup handlers.
ran_auto_check_install_popup = False
ran_update_success_popup = False

# Global var for preventing successive background check calls.
ran_background_check = False


@persistent
def updater_run_success_popup_handler(scene):
    global ran_update_success_popup
    ran_update_success_popup = True

    # In case of error importing the updater engine.
    if updater.invalid_updater:
        return

    try:
        if "scene_update_post" in dir(bpy.app.handlers):
            bpy.app.handlers.scene_update_post.remove(
                updater_run_success_popup_handler)
        else:
            bpy.app.handlers.depsgraph_update_post.remove(
                updater_run_success_popup_handler)
    except Exception:
        pass

    atr = AddonUpdaterUpdatedSuccessful.bl_idname.split(".")
    getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')


@persistent
def updater_run_install_popup_handler(scene):
    global ran_auto_check_install_popup
    ran_auto_check_install_popup = True
    updater.print_verbose("Running the install popup handler.")

    # In case of error importing the updater engine.
    if updater.invalid_updater:
        return

    try:
        if "scene_update_post" in dir(bpy.app.handlers):
            bpy.app.handlers.scene_update_post.remove(
                updater_run_install_popup_handler)
        else:
            bpy.app.handlers.depsgraph_update_post.remove(
                updater_run_install_popup_handler)
    except Exception:
        pass

    if "ignore" in updater.json and updater.json["ignore"]:
        return  # Don't do the popup if the user pressed ignore.
    elif "version_text" in updater.json and updater.json["version_text"].get("version"):
        version = updater.json["version_text"]["version"]
        ver_tuple = updater.version_tuple_from_text(version)

        if ver_tuple < updater.current_version:
            # User probably manually installed to get the up to date addon
            # in here. Clear out the update flag using this function.
            updater.print_verbose(
                "{} updater: appears user updated, clearing flag".format(
                    updater.addon))
            updater.json_reset_restore()
            return
    atr = AddonUpdaterInstallPopup.bl_idname.split(".")
    getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')


def background_update_callback(update_ready):
    """Passed into the updater, called by the background check thread."""
    global ran_auto_check_install_popup
    updater.print_verbose("Running background update callback")

    # In case of error importing the updater engine.
    if updater.invalid_updater:
        return
    if not updater.show_popups:
        return
    if not update_ready:
        return

    # See if we need to add the update handler to trigger the popup.
    handlers = []
    if "scene_update_post" in dir(bpy.app.handlers):  # 2.7x
        handlers = bpy.app.handlers.scene_update_post
    else:  # 2.8+
        handlers = bpy.app.handlers.depsgraph_update_post
    in_handles = updater_run_install_popup_handler in handlers

    if in_handles or ran_auto_check_install_popup:
        return

    if "scene_update_post" in dir(bpy.app.handlers):  # 2.7x
        bpy.app.handlers.scene_update_post.append(
            updater_run_install_popup_handler)
    else:  # 2.8+
        bpy.app.handlers.depsgraph_update_post.append(
            updater_run_install_popup_handler)
    ran_auto_check_install_popup = True
    updater.print_verbose("Attempted popup prompt")


def post_update_callback(module_name, res=None):
    """Callback for once the run_update function has completed.

    Only makes sense to use this if "auto_reload_post_update" == False,
    ie the addon is not auto-restarted after the update.

    Arguments:
        module_name: returns the module name from updater, but unused here.
        res: If an error occurred, this is the detail string.
    """

    # In case of error importing the updater engine.
    if updater.invalid_updater:
        return

    if res is None:
        # This is the same code as in the conditional at the end of the
        # register function, ie if "auto_reload_post_update" == True, skip.
        updater.print_verbose(
            "{} updater: Running post update callback".format(updater.addon))

        atr = AddonUpdaterUpdatedSuccessful.bl_idname.split(".")
        getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')
        global ran_update_success_popup
        ran_update_success_popup = True
    else:
        # Some kind of error occurred and it was unable to install, offer
        # a manual download instead.
        atr = AddonUpdaterUpdatedSuccessful.bl_idname.split(".")
        getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT', error=res)
    return


def ui_refresh(update_status):
    """Redraw the UI once an async thread has completed."""
    for windowManager in bpy.data.window_managers:
        for window in windowManager.windows:
            for area in window.screen.areas:
                area.tag_redraw()


def check_for_update_background():
    """Function for the asynchronous background check.

    *Could* be called on register, but that would be bad practice as the bare
    minimum code should run at the moment of registration (addon ticked).
    The updater panel calls this on every draw instead; the global var and
    the engine's own interval gating ensure the actual network check runs at
    most once per configured interval.
    """
    if updater.invalid_updater:
        return
    global ran_background_check
    if ran_background_check:
        # Global var ensures the check only happens once per session.
        return
    elif updater.update_ready is not None or updater.async_checking:
        # Check already happened.
        # Used here to just avoid constant applying settings below.
        return

    # Apply the UI settings.
    settings = get_user_preferences(bpy.context)
    if not settings:
        return
    updater.set_check_interval(enabled=settings.auto_check_update,
                               months=settings.updater_interval_months,
                               days=settings.updater_interval_days,
                               hours=settings.updater_interval_hours,
                               minutes=settings.updater_interval_minutes)

    # Input is an optional callback function. This function should take a
    # bool input, if true: update ready, if false: no update ready.
    updater.check_for_update_async(background_update_callback)
    ran_background_check = True


def check_for_update_nonthreaded(self, context):
    """Can be placed in front of other operators to launch when pressed"""
    if updater.invalid_updater:
        return

    # Only check if it's ready, ie after the time interval specified should
    # the async wrapper call here.
    settings = get_user_preferences(bpy.context)
    if not settings:
        updater.print_verbose(
            "Could not get {} preferences, update check skipped".format(
                __package__))
        return
    updater.set_check_interval(enabled=settings.auto_check_update,
                               months=settings.updater_interval_months,
                               days=settings.updater_interval_days,
                               hours=settings.updater_interval_hours,
                               minutes=settings.updater_interval_minutes)

    (update_ready, version, link) = updater.check_for_update(now=False)
    if update_ready:
        atr = AddonUpdaterInstallPopup.bl_idname.split(".")
        getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')
    else:
        updater.print_verbose("No update ready")
        self.report({'INFO'}, tr("No update ready"))


def show_reload_popup():
    """For use in register only, to show a popup after re-enabling the addon.

    Must be enabled by the developer.
    """
    if updater.invalid_updater:
        return
    saved_state = updater.json
    global ran_update_success_popup

    has_state = saved_state is not None
    just_updated = "just_updated" in saved_state
    updated_info = saved_state["just_updated"]

    if not (has_state and just_updated and updated_info):
        return

    updater.json_reset_postupdate()  # So this only runs once.

    # No handlers in this case.
    if not updater.auto_reload_post_update:
        return

    # See if we need to add the update handler to trigger the popup.
    handlers = []
    if "scene_update_post" in dir(bpy.app.handlers):  # 2.7x
        handlers = bpy.app.handlers.scene_update_post
    else:  # 2.8+
        handlers = bpy.app.handlers.depsgraph_update_post
    in_handles = updater_run_success_popup_handler in handlers

    if in_handles or ran_update_success_popup:
        return

    if "scene_update_post" in dir(bpy.app.handlers):  # 2.7x
        bpy.app.handlers.scene_update_post.append(
            updater_run_success_popup_handler)
    else:  # 2.8+
        bpy.app.handlers.depsgraph_update_post.append(
            updater_run_success_popup_handler)
    ran_update_success_popup = True


# -----------------------------------------------------------------------------
# Example UI integrations
# -----------------------------------------------------------------------------


def update_notice_box_ui(self, context):
    """Update notice draw, to add to the end or beginning of a panel.

    After a check for update has occurred, this function will draw a box
    saying an update is ready, and give buttons for: update now, open
    website, or ignore the popup. Ideal to be placed at the end / beginning
    of a panel.
    """

    if updater.invalid_updater:
        return

    saved_state = updater.json
    if not updater.auto_reload_post_update:
        if "just_updated" in saved_state and saved_state["just_updated"]:
            layout = self.layout
            box = layout.box()
            col = box.column()
            alert_row = col.row()
            alert_row.alert = True
            alert_row.operator(
                "wm.quit_blender",
                text=tr("Restart Blender"),
                icon="ERROR")
            col.label(text=tr("to complete update"))
            return

    # If the user pressed ignore, don't draw the box.
    if "ignore" in updater.json and updater.json["ignore"]:
        return
    if not updater.update_ready:
        return

    layout = self.layout
    box = layout.box()
    col = box.column(align=True)
    col.alert = True
    col.label(text=tr("Update ready!"), icon="ERROR")
    col.alert = False
    col.separator()
    row = col.row(align=True)
    split = row.split(align=True)
    colL = split.column(align=True)
    colL.scale_y = 1.5
    colL.operator(AddonUpdaterIgnore.bl_idname, icon="X", text=tr("Ignore"))
    colR = split.column(align=True)
    colR.scale_y = 1.5
    if not updater.manual_only:
        colR.operator(AddonUpdaterUpdateNow.bl_idname,
                      text=tr("Update"), icon="LOOP_FORWARDS")
        col.operator("wm.url_open",
                     text=tr("Open website")).url = updater.website
        # Direct download button alternative:
        # ops = col.operator("wm.url_open", text=tr("Direct download"))
        # ops.url = updater.update_link
        col.operator(AddonUpdaterInstallManually.bl_idname,
                     text=tr("Install manually"))
    else:
        col.operator("wm.url_open",
                     text=tr("Get it now")).url = updater.website


def update_settings_ui(self, context, element=None):
    """Preferences - for drawing with full width inside user preferences.

    A function that can be run inside a user preferences panel or any sidebar
    panel for the updater UI. Place inside a UI draw using:
        addon_updater_ops.update_settings_ui(self, context)
    """

    # Element is a UI element, such as a layout, row, column, or box.
    if element is None:
        element = self.layout
    box = element.box()

    # In case of error importing the updater engine.
    if updater.invalid_updater:
        box.label(text=tr("Error initializing updater code:"))
        box.label(text=updater.error_msg)
        return
    settings = get_user_preferences(context)
    if not settings:
        box.label(text=tr("Error getting updater preferences"), icon='ERROR')
        return

    # Auto-update settings.
    box.label(text=tr("Updater Settings"))
    row = box.row()

    # Special case to tell the user to restart blender, if set that way.
    if not updater.auto_reload_post_update:
        saved_state = updater.json
        if "just_updated" in saved_state and saved_state["just_updated"]:
            row.alert = True
            row.operator("wm.quit_blender",
                         text=tr("Restart Blender to complete update"),
                         icon="ERROR")
            return

    # Draw the auto-check toggle and the check interval. Every prop gets an
    # explicit text=tr(...) override so the captions follow the UI language
    # live; the frozen RNA labels stay English (platform limitation).
    split = layout_split(row, factor=0.4)
    sub_col = split.column()
    sub_col.prop(settings, "auto_check_update",
                 text=tr("Auto-check for update"))
    sub_col = split.column()
    if not settings.auto_check_update:
        sub_col.enabled = False
    sub_row = sub_col.row()
    sub_row.label(text=tr("Interval between checks"))
    sub_row = sub_col.row(align=True)
    check_col = sub_row.column(align=True)
    check_col.prop(settings, "updater_interval_months", text=tr("Months"))
    check_col = sub_row.column(align=True)
    check_col.prop(settings, "updater_interval_days", text=tr("Days"))
    check_col = sub_row.column(align=True)
    check_col.prop(settings, "updater_interval_hours", text=tr("Hours"))
    check_col = sub_row.column(align=True)
    check_col.prop(settings, "updater_interval_minutes", text=tr("Minutes"))

    # Checking / managing updates.
    row = box.row()
    col = row.column()
    if updater.error is not None:
        sub_col = col.row(align=True)
        sub_col.scale_y = 1
        split = sub_col.split(align=True)
        split.scale_y = 2
        if "ssl" in updater.error_msg.lower():
            split.enabled = True
            split.operator(AddonUpdaterInstallManually.bl_idname,
                           text=updater.error)
        else:
            split.enabled = False
            split.operator(AddonUpdaterCheckNow.bl_idname,
                           text=updater.error)
        split = sub_col.split(align=True)
        split.scale_y = 2
        split.operator(AddonUpdaterCheckNow.bl_idname,
                       text="", icon="FILE_REFRESH")

    elif updater.update_ready is None and not updater.async_checking:
        col.scale_y = 2
        col.operator(AddonUpdaterCheckNow.bl_idname,
                     text=tr("Check for Update Now"))
    elif updater.update_ready is None:  # Async is running.
        sub_col = col.row(align=True)
        sub_col.scale_y = 1
        split = sub_col.split(align=True)
        split.enabled = False
        split.scale_y = 2
        split.operator(AddonUpdaterCheckNow.bl_idname, text=tr("Checking..."))
        split = sub_col.split(align=True)
        split.scale_y = 2
        split.operator(AddonUpdaterEndBackground.bl_idname, text="", icon="X")

    elif updater.include_branches and \
            len(updater.tags) == len(updater.include_branch_list) and not \
            updater.manual_only:
        # No releases found, but still show the appropriate branch.
        sub_col = col.row(align=True)
        sub_col.scale_y = 1
        split = sub_col.split(align=True)
        split.scale_y = 2
        update_now_txt = tr("Update directly to {branch}").format(
            branch=updater.include_branch_list[0])
        split.operator(AddonUpdaterUpdateNow.bl_idname, text=update_now_txt)
        split = sub_col.split(align=True)
        split.scale_y = 2
        split.operator(AddonUpdaterCheckNow.bl_idname,
                       text="", icon="FILE_REFRESH")

    elif updater.update_ready and not updater.manual_only:
        sub_col = col.row(align=True)
        sub_col.scale_y = 1
        split = sub_col.split(align=True)
        split.scale_y = 2
        split.operator(
            AddonUpdaterUpdateNow.bl_idname,
            text=tr("Update now to {version}").format(
                version=str(updater.update_version)))
        split = sub_col.split(align=True)
        split.scale_y = 2
        split.operator(AddonUpdaterCheckNow.bl_idname,
                       text="", icon="FILE_REFRESH")

    elif updater.update_ready and updater.manual_only:
        col.scale_y = 2
        dl_now_txt = tr("Download {version}").format(
            version=str(updater.update_version))
        col.operator("wm.url_open",
                     text=dl_now_txt).url = updater.website
    else:  # ie updater.update_ready == False.
        sub_col = col.row(align=True)
        sub_col.scale_y = 1
        split = sub_col.split(align=True)
        split.enabled = False
        split.scale_y = 2
        split.operator(AddonUpdaterCheckNow.bl_idname,
                       text=tr("Addon is up to date"))
        split = sub_col.split(align=True)
        split.scale_y = 2
        split.operator(AddonUpdaterCheckNow.bl_idname,
                       text="", icon="FILE_REFRESH")

    if not updater.manual_only:
        col = row.column(align=True)
        if updater.include_branches and len(updater.include_branch_list) > 0:
            branch = updater.include_branch_list[0]
            col.operator(
                AddonUpdaterUpdateTarget.bl_idname,
                text=tr("Install {branch} / old version").format(
                    branch=branch))
        else:
            col.operator(AddonUpdaterUpdateTarget.bl_idname,
                         text=tr("(Re)install addon version"))

        # The restore button shows the date of the newest available backup.
        last_date = tr("Date not found")
        backup_path = os.path.join(updater.stage_path, "backup")
        if "backup_date" in updater.json and os.path.isdir(backup_path):
            if updater.json["backup_date"] != "":
                last_date = updater.json["backup_date"]
        backup_text = tr("Restore addon backup ({date})").format(
            date=last_date)
        col.operator(AddonUpdaterRestoreBackup.bl_idname, text=backup_text)

    row = box.row()
    row.scale_y = 0.7
    last_check = updater.json["last_check"]
    if updater.error is not None and updater.error_msg is not None:
        row.label(text=updater.error_msg)
    elif last_check:
        # Strip the sub-second part of the stored timestamp for display;
        # split() never raises even if a hand-edited json lost the dot.
        last_check = last_check.split(".")[0]
        row.label(text=tr("Last update check: {time}").format(
            time=last_check))
    else:
        row.label(text=tr("Last update check: Never"))


def skip_tag_function(self, tag):
    """A global function for tag skipping.

    A way to filter which tags are displayed, e.g. to limit downgrading too
    long ago.

    Args:
        self: The instance of the singleton addon updater.
        tag: the text content of a tag from the repo, e.g. "v1.2.3".

    Returns:
        bool: True to skip this tag name (ie don't allow downloading this
            version), or False if the tag is allowed.
    """

    # In case of error importing the updater engine.
    if self.invalid_updater:
        return False

    # ---- write any custom code here, return true to disallow version ---- #
    #
    # # Filter out e.g. if 'beta' is in the name of the release
    # if 'beta' in tag.lower():
    # 	return True
    # ---- write any custom code above, return true to disallow version --- #

    if self.include_branches:
        for branch in self.include_branch_list:
            if tag["name"].lower() == branch:
                return False

    # Function converting string to tuple, ignoring e.g. the leading 'v'.
    # Be aware that this strips out other text that you might otherwise
    # want to be kept and accounted for when checking tags (e.g. v1.1a vs
    # 1.1b).
    tupled = self.version_tuple_from_text(tag["name"])
    if not isinstance(tupled, tuple):
        return True

    # Select the min tag version - change the tuple accordingly.
    if self.version_min_update is not None:
        if tupled < self.version_min_update:
            return True  # Skip if the current version is below this.

    # Select the max tag version.
    if self.version_max_update is not None:
        if tupled >= self.version_max_update:
            return True  # Skip if the current version is at or above this.

    # In all other cases, allow showing the tag for updating/reverting.
    # To simply and always show all tags, this return False could be moved
    # to the start of the function definition so all tags are allowed.
    return False


def select_link_function(self, tag):
    """Only customize if trying to leverage "attachments" in *GitHub* releases.

    A way to select from one or multiple attached downloadable files from the
    server, instead of downloading the default release/tag source code.
    """

    # -- Default, universal case (and is the only option for GitLab/Bitbucket)
    link = tag["zipball_url"]

    # -- Example: select the first (or only) asset instead of source code --
    # if "assets" in tag and "browser_download_url" in tag["assets"][0]:
    # 	link = tag["assets"][0]["browser_download_url"]

    return link


# -----------------------------------------------------------------------------
# Register, should be run in the register function of the addon __init__
# -----------------------------------------------------------------------------

# The register line items for all updater operators.
classes = (
    AddonUpdaterInstallPopup,
    AddonUpdaterCheckNow,
    AddonUpdaterUpdateNow,
    AddonUpdaterUpdateTarget,
    AddonUpdaterInstallManually,
    AddonUpdaterUpdatedSuccessful,
    AddonUpdaterRestoreBackup,
    AddonUpdaterIgnore,
    AddonUpdaterEndBackground
)


def register(bl_info):
    """Register the updater operators and configure the updater engine."""
    # Safer failure in case of an issue loading the module.
    if updater.error:
        print("Exiting updater registration, " + updater.error)
        return
    updater.clear_state()  # Clear internal vars, avoids reloading oddities.

    # Confirm the updater "engine" (Github is the default if not specified).
    updater.engine = "Github"
    # updater.engine = "GitLab"
    # updater.engine = "Bitbucket"

    # If using a private repository, indicate the token here.
    # Must be set after assigning the engine.
    # **WARNING** Depending on the engine, this token can act like a
    # password!! Only provide a token if the project is *non-public*.
    updater.private_token = None  # "tokenstring"

    # The GitHub user/organization owning the repository.
    updater.user = GITHUB_OWNER

    # The GitHub repository name itself.
    updater.repo = GITHUB_REPOSITORY

    # updater.addon = # defined at the top of this module, MUST be done first

    # Website for manual addon downloads, optional but recommended to set.
    updater.website = f"{GITHUB_REPOSITORY_URL}/releases"

    # Addon subfolder path, e.g. "sample/path/to/addon".
    # The default is "" or None, meaning the repository root.
    updater.subfolder_path = ""

    # Used to check/compare versions against the running addon.
    updater.current_version = bl_info["version"]

    # Optional, to hard-set the update frequency - however, this addon sets
    # it via UI properties instead.
    # updater.set_check_interval(enabled=False, months=0, days=0, hours=0,
    #                            minutes=2)

    # Optional, consider turning off for production or allowing as an option.
    # This prints out additional debugging info to the console.
    updater.verbose = False  # Make True for debugging the updater itself.

    # Optional, customize where the addon updater processing subfolder is,
    # essentially a staging folder used by the updater on its own. It needs
    # to be within the same folder as the addon itself, supplied as a full,
    # absolute path. By default:
    # 			/addons/{__package__}/{__package__}_updater
    # updater.updater_path = ...

    # Auto-create a backup of the addon when installing other versions.
    updater.backup_current = True  # True by default

    # Sample ignore patterns for when creating a backup of the current addon
    # during an update.
    updater.backup_ignore_patterns = ["__pycache__"]
    # Alternate example patterns:
    # [".git", "__pycache__", "*.bat", ".gitignore", "*.exe"]

    # Patterns for files to actively overwrite if found in the new update
    # file and also found in the currently installed addon. Note that by
    # default (ie if set to []), updates are installed the same way Blender
    # does it: .py files are replaced, but other file types (e.g. json, txt,
    # blend) will NOT be overwritten if already present in the current
    # install. Thus if you want to automatically update resources/non-py
    # files, add them as part of the pattern list below so they will always
    # be overwritten by an update. If a pattern file is not found in the new
    # update, no action is taken.
    # NOTE: This does NOT delete anything proactively, it only defines what
    # is allowed to be overwritten during an update execution.
    updater.overwrite_patterns = ["*.png", "*.jpg", "*.hlsl", "*.dds"]
    # Other examples:
    # ["*"] means ALL files/folders will be overwritten by an update.
    # ["*.json"] means all json files found in the addon update will
    # overwrite those of the same name in the current install.

    # Patterns for files to actively remove prior to running an update.
    # Useful for removing old code due to changes in file names that would
    # otherwise accumulate. Note: this runs after taking a backup (if
    # enabled) but before placing in the new update. If the same file name
    # removed exists in the update, then it acts as if the pattern is placed
    # in the overwrite_patterns property. Note this is effectively ignored
    # if clean=True in the run_update method.
    updater.remove_pre_update_patterns = ["*.py", "*.pyc"]
    # Note: setting ["*"] here is equivalent to always running updates with
    # clean=True, ie the equivalent of a fresh, new install. This would also
    # delete any resources or user-made/modified files. The configuration of
    # ["*.py", "*.pyc"] is a safe option as this ensures no old python
    # files/caches remain in the event different addon versions have
    # different file names or structures.

    # Allow branches like 'main' as an option to update to, regardless of
    # release or version. Default behavior: releases are still used for the
    # auto check (popup), but the user has the option from the updater UI to
    # directly update to the main branch or any other branch specified using
    # the "install {branch}/older version" operator.
    updater.include_branches = True

    # (GitHub only) This option allows using "releases" instead of "tags",
    # which enables pulling down release logs/notes, as well as installing
    # updates from release-attached zips (instead of the auto-packaged code
    # generated with a release/tag). The setting has no impact on BitBucket
    # or GitLab repos.
    updater.use_releases = False
    # Note: Releases always have a tag, but a tag may not always be a
    # release. Therefore, setting True above will filter out any
    # non-annotated tags.
    # Note 2: Using this option will also display (and filter by) the release
    # name instead of the tag name, bear this in mind given the
    # skip_tag_function filtering above.

    # Populate if using the "include_branches" option above.
    # Note: updater.include_branch_list defaults to ['master'] if set to
    # None. Keep this aligned with the repository's default branch; this
    # branch is exposed as an optional install target alongside version tags.
    updater.include_branch_list = ['main']

    # Only allow manual install, thus prompting the user to open the addon's
    # web page to download, specifically: updater.website. Useful if only
    # wanting to get a notification of updates but not directly install.
    updater.manual_only = False

    # Used for development only, "pretend" to install an update to test
    # reloading conditions.
    updater.fake_install = False  # Set to True to test callback/reloading.

    # Show popups, ie if auto-check for update is enabled or a previous check
    # for update in the user preferences found a new version, show a popup
    # (at most once per blender session, and it provides an option to ignore
    # for future sessions); the default behavior is True.
    updater.show_popups = True
    # Note: if set to False, there will still be an "update ready" box drawn
    # using the `update_notice_box_ui` panel function.

    # Override with a custom function on what tags to skip showing for the
    # updater; see the code for the function above. Set the min and max
    # versions allowed to install. Optional, default None.
    # Min install (>=) will install this and higher.
    updater.version_min_update = (0, 0, 0)
    # updater.version_min_update = None  # None or default for no minimum.

    # Max install (<) will install strictly anything lower than this version
    # number, useful to limit the max version a given user can install (e.g.
    # if support for a future version of blender is going away, and you
    # don't want users to be prompted to install a non-functioning addon).
    # updater.version_max_update = (9, 9, 9)
    updater.version_max_update = None  # None or default for no max.

    # Function defined above, customize as appropriate per repository.
    updater.skip_tag = skip_tag_function  # min and max used in this function

    # Function defined above, optionally customize as needed per repository.
    updater.select_link = select_link_function

    # Recommended False to encourage blender restarts on update completion.
    # Setting this option to True is NOT as stable as False (could cause
    # blender crashes).
    updater.auto_reload_post_update = False

    # Register all updater operators. Registration is fault-tolerant like the
    # rest of the addon: one failing class must not break the others.
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            # Already registered (for example after a partial reload).
            pass

    # Special situation: we just updated the addon, show a popup to tell the
    # user it worked. Could be enclosed in try/except in case other issues
    # arise.
    show_reload_popup()


def unregister():
    """Unregister the updater operators and clear the engine state."""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            # Never registered (half-registered state from a prior session).
            pass

    # Clear global vars since they may persist if blender is not restarted.
    updater.clear_state()  # Clear internal vars, avoids reloading oddities.

    global ran_auto_check_install_popup
    ran_auto_check_install_popup = False

    global ran_update_success_popup
    ran_update_success_popup = False

    global ran_background_check
    ran_background_check = False
