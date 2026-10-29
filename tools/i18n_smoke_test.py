"""Headless smoke test for MIMIBlender i18n.

Run with Blender 5.2:
    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        -b --factory-startup --python tools/i18n_smoke_test.py

The test:
1. Imports the addon package and calls register() (same path as enabling it).
2. Verifies the language preference exists and defaults to English.
3. Switches to Simplified Chinese and checks that tr(), a panel label, an
   operator tooltip and a dynamic enum callback all follow the switch.
4. Switches to Traditional Chinese and checks the same surface again, so the
   third language is wired exactly like the second one.
5. Switches back to English, verifies the fallback, then unregisters.

Exits with code 0 on success and 1 on the first failed assertion.
"""

import os
import sys

# Make the addon package importable: the repo root is the package itself, so
# its parent directory must be on sys.path (same as Blender's addon folder).
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT_DIR = os.path.dirname(_REPO_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

import bpy  # noqa: E402

_FAILURES = []


def check(label, condition):
    """Record one assertion result and print it immediately."""
    status = "PASS" if condition else "FAIL"
    print("[SMOKE {}] {}".format(status, label))
    if not condition:
        _FAILURES.append(label)


def main():
    import MIMIBlender
    from MIMIBlender.i18n import i18n

    # 1. Enable the addon through Blender's addon system. This is the same
    # path as Edit > Preferences > Add-ons, and it creates the persistent
    # preferences entry that a bare register() call would not create.
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    check("addon_enable completed", True)

    # 2. The preferences object must exist with the language property.
    prefs = i18n.get_preferences()
    check("preferences object available", prefs is not None)
    check("ui_language defaults to en", prefs is not None and prefs.ui_language == "en")
    check("tr() passes English through by default", i18n.tr("Generate Mod") == "Generate Mod")

    # 3. Switch to Simplified Chinese through the preference (update callback).
    prefs.ui_language = "zh"
    check("tr() translates after switching to zh", i18n.tr("Generate Mod") == "生成 Mod")
    check("tr() falls back for unknown keys", i18n.tr("Some Untranslated Text") == "Some Untranslated Text")

    # A @translatable panel label must have been rewritten in place.
    from MIMIBlender.ui.ui_panel_basic import MIMIPanelBasicInformation
    check(
        "panel bl_label switched to zh",
        MIMIPanelBasicInformation.bl_label == i18n.tr("Basic Information Panel"),
    )

    # An I18nOperator description classmethod must translate live.
    from MIMIBlender.ui.ui_func_export import MMTGenerateModBlueprint
    operator_description = MMTGenerateModBlueprint.description(bpy.context, None)
    check(
        "operator description translates live",
        operator_description == i18n.tr(MMTGenerateModBlueprint.bl_description),
    )

    # A dynamic enum items callback must return translated display names while
    # keeping the identifiers untouched.
    from MIMIBlender.common.mimi_global_properties import _get_workspace_source_mode_items
    items = _get_workspace_source_mode_items(None, bpy.context)
    identifiers = [entry[0] for entry in items]
    check("enum identifiers unchanged", identifiers == ["SYNC", "SPECIFIC", "CUSTOM"])
    check("enum display names translated", any(entry[1] != entry[0] for entry in items))
    # Remember the Simplified display names, so the next section can prove that
    # switching language really rewrites them instead of reusing old strings.
    simplified_display_names = [entry[1] for entry in items]

    # 4. Switch to Traditional Chinese. The third language uses exactly the
    # same plumbing, so it has to pass the same surface checks as Chinese.
    from MIMIBlender.i18n.zh_tw import TRANSLATIONS_ZH_TW

    prefs.ui_language = "zh_tw"
    check("get_language reports zh_tw", i18n.get_language() == "zh_tw")
    check(
        "tr() translates after switching to zh_tw",
        i18n.tr("Generate Mod") == TRANSLATIONS_ZH_TW["Generate Mod"],
    )
    check(
        "zh_tw value differs from the English source",
        i18n.tr("Generate Mod") != "Generate Mod",
    )
    check(
        "tr() falls back for unknown keys in zh_tw",
        i18n.tr("Some Untranslated Text") == "Some Untranslated Text",
    )
    check(
        "panel bl_label switched to zh_tw",
        MIMIPanelBasicInformation.bl_label == i18n.tr("Basic Information Panel"),
    )
    check(
        "panel bl_label is the Traditional wording",
        MIMIPanelBasicInformation.bl_label == TRANSLATIONS_ZH_TW["Basic Information Panel"],
    )
    check(
        "operator description translates live in zh_tw",
        MMTGenerateModBlueprint.description(bpy.context, None)
        == TRANSLATIONS_ZH_TW[MMTGenerateModBlueprint.bl_description],
    )
    items = _get_workspace_source_mode_items(None, bpy.context)
    check(
        "enum identifiers unchanged in zh_tw",
        [entry[0] for entry in items] == ["SYNC", "SPECIFIC", "CUSTOM"],
    )
    check(
        "enum display names use the Traditional wording",
        any(
            entry[1] != simplified_name
            for entry, simplified_name in zip(items, simplified_display_names)
        ),
    )

    # Switching straight from one translation to the other must not leave any
    # text of the previous language behind.
    prefs.ui_language = "zh"
    check(
        "switching back to zh restores the Simplified wording",
        i18n.tr("Generate Mod") == "生成 Mod",
    )

    # 5. Switch back to English; everything must fall back cleanly.
    prefs.ui_language = "en"
    check("tr() falls back to English", i18n.tr("Generate Mod") == "Generate Mod")
    check("get_language reports en", i18n.get_language() == "en")
    check(
        "panel bl_label restored to English",
        MIMIPanelBasicInformation.bl_label == "Basic Information Panel",
    )

    # 6. Clean unload through the addon system.
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    check("addon_disable completed", True)

    if _FAILURES:
        print("[SMOKE] {} check(s) FAILED".format(len(_FAILURES)))
        sys.exit(1)
    print("[SMOKE] all checks passed")
    sys.exit(0)


main()
