'''
Lightweight in-addon i18n (internationalization) support for MIMIBlender.

Why not Blender's built-in bpy.app.translations?
Blender's native system only follows Blender's global UI language. The addon
needs its own independent language switch inside the MIMITools panel, so this
module implements a tiny, self-contained translation layer instead.

Design rules (keep the addon safe):
- Only user-visible UI text is translated. Internal identifiers such as
  bl_idname, enum item identifiers, property keys, file paths and log output
  are never touched.
- The English source string doubles as the translation key (msgid), so the
  code stays readable and English always works even without a dictionary
  entry.
- tr() never raises and never returns None; on any miss it returns the
  original English text unchanged.

What updates live when the user switches language:
- Panel / Menu titles and everything drawn inside draw() functions
  (labels, buttons, property captions, menus, dialogs, reports).
- Operator button text (call sites pass text=tr(...)) and operator tooltips
  (I18nOperator.description is evaluated dynamically by Blender).
- Enum dropdown entries that use a dynamic items callback.

What only updates after the classes are re-registered (Blender restart or
add-on reload), because Blender freezes them into RNA at registration time:
- Plain property tooltips (name/description of bpy.props definitions).
- Operator names inside Blender's operator search menu.
This is a platform limitation, not a bug; both still display the language
that was active when the add-on was loaded.
'''
import bpy

from .zh_cn import TRANSLATIONS_ZH_CN

# Language codes used by the ui_language enum property.
LANG_EN = "en"
LANG_ZH = "zh"

# The module-level current language. tr() reads this on every call, so text
# drawn by draw() functions always follows the latest user choice.
_current_language = LANG_EN

# Root package name of the add-on (for example "MIMIBlender"). The
# AddonPreferences bl_idname must match the module name Blender loads.
_ADDON_MODULE_NAME = __package__.split(".")[0]

# Registry of (class, attribute name, original English text) entries for class
# attributes that Blender re-reads on redraw (Panel/Menu bl_label and
# bl_description). The language switch re-applies tr() to these attributes.
_tracked_class_attrs = []


def get_language():
    '''Return the currently active language code ("en" or "zh").'''
    return _current_language


def tr(text):
    '''Translate one UI string into the current language.

    The English source text is the dictionary key. Any value that is not a
    non-empty string, or that has no dictionary entry, is returned unchanged,
    so wrapping a string with tr() can never break the UI.
    '''
    if not isinstance(text, str) or not text:
        return text
    if _current_language != LANG_ZH:
        return text
    return TRANSLATIONS_ZH_CN.get(text, text)


def translatable(cls):
    '''Class decorator: remember the original English bl_label/bl_description.

    Panel and Menu classes re-read these attributes on every redraw, so the
    language switch can rewrite them with setattr and the new text shows up
    immediately. For Operators and Nodes the registered RNA name stays frozen,
    but applying the stored text before registration still makes freshly
    loaded classes follow the saved language.
    '''
    for attr in ("bl_label", "bl_description"):
        original = getattr(cls, attr, None)
        if isinstance(original, str) and original:
            _tracked_class_attrs.append((cls, attr, original))
    return cls


def apply_language(value):
    '''Switch the current language and refresh every tracked class attribute.'''
    global _current_language
    _current_language = LANG_ZH if value == LANG_ZH else LANG_EN
    for cls, attr, original in _tracked_class_attrs:
        try:
            setattr(cls, attr, tr(original))
        except Exception:
            # A half-registered class must never break the language switch.
            pass


def redraw_all_areas():
    '''Tag every area of every window for redraw so new text shows at once.'''
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        # During registration the window manager may be restricted; the next
        # regular redraw will pick up the new language anyway.
        pass


def get_preferences():
    '''Return the add-on preferences object, or None when unavailable.'''
    try:
        addon = bpy.context.preferences.addons.get(_ADDON_MODULE_NAME)
        if addon is not None:
            return addon.preferences
    except Exception:
        pass
    return None


def _on_ui_language_update(self, context):
    '''Enum update callback: apply the choice and refresh the whole UI.'''
    apply_language(self.ui_language)
    redraw_all_areas()


class I18nOperator(bpy.types.Operator):
    '''Operator base class whose tooltip follows the selected UI language.

    Blender freezes bl_description into RNA at registration time, but when a
    class provides this ``description`` classmethod Blender calls it every
    time a tooltip is shown, which makes operator tooltips switch language
    live without re-registration.
    '''

    @classmethod
    def description(cls, context, properties):
        # bl_description always holds the English source text (the msgid).
        return tr(getattr(cls, "bl_description", "") or "")


class MIMIAddonPreferences(bpy.types.AddonPreferences):
    '''Add-on preferences: hosts the persistent UI language choice.'''

    # Blender looks up add-on preferences by the module name of the add-on.
    bl_idname = _ADDON_MODULE_NAME

    ui_language: bpy.props.EnumProperty(
        # Bilingual fixed text on purpose: this control must stay readable
        # no matter which language is currently active.
        name="Language / 语言",
        description=(
            "Panel language of MIMIBlender. A few hover tips follow after "
            "restarting Blender. / MIMIBlender 面板语言。部分悬停提示将在"
            "重启 Blender 后完全生效。"
        ),
        items=[
            ("en", "English", "Show panels in English / 以英文显示面板"),
            ("zh", "简体中文", "Show panels in Simplified Chinese / 以简体中文显示面板"),
        ],
        default="en",
        update=_on_ui_language_update,
    )  # type: ignore

    def draw(self, context):
        # The same switch is also offered at the top of the Basic Information
        # panel; drawing it here keeps the add-on preferences page consistent.
        self.layout.prop(self, "ui_language", expand=True)


def register():
    '''Register the preferences first, then apply the saved language choice.'''
    try:
        bpy.utils.register_class(MIMIAddonPreferences)
    except ValueError:
        # Already registered (for example after a partial reload): reuse it.
        pass
    prefs = get_preferences()
    if prefs is not None:
        # Re-apply the saved language so freshly registered classes pick it up.
        apply_language(prefs.ui_language)


def unregister():
    # Restore the original English class attributes for a clean unload.
    apply_language(LANG_EN)
    try:
        bpy.utils.unregister_class(MIMIAddonPreferences)
    except (ValueError, RuntimeError):
        pass
