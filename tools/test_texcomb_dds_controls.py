"""Verify silent DDS converter discovery with real Blender panel drawing.

Run with -b --factory-startup --python-exit-code 1. No user preferences,
scene files, or converter binaries are saved or changed by these checks.
"""
import os
import sys
from unittest.mock import patch

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


class Layout:
    """Record exactly the DDS properties and status labels that users see."""
    def __init__(self):
        self.properties = []
        self.labels = []

    def column(self, **kwargs):
        # Nested layouts share the recorder; no GUI window is required.
        return self

    def prop(self, data, name, **kwargs):
        self.properties.append(name)

    def label(self, **kwargs):
        self.labels.append(kwargs["text"])


def main():
    # Normal registration exercises the real Scene properties and resolver.
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from MIMIBlender.texcomb.core import texconv
    from MIMIBlender.texcomb.ui.main_panel import MIMIMaterialCombinerPanel
    from MIMIBlender.i18n.i18n import tr

    scene = bpy.context.scene
    bundled = texconv._bundled_path()
    assert os.path.isfile(bundled), "The repository must contain its bundled converter"
    missing = os.path.join(ROOT, "tmp", "nonexistent_texconv_for_ui_test.exe")
    assert not os.path.exists(missing)
    base_properties = ["mimi_smc_dds_format", "mimi_smc_dds_mipmaps"]

    def check(available):
        layout = Layout()
        MIMIMaterialCombinerPanel._add_dds_section(layout, scene)
        # Artist-facing pixel format and mip policy stay visible in both states.
        assert layout.properties[:2] == base_properties
        if available:
            # Finding any usable candidate suppresses both path and success text.
            assert layout.properties == base_properties
            assert not layout.labels
        else:
            assert layout.properties == base_properties + ["mimi_smc_texconv_path"]
            assert layout.labels == [tr("texconv.exe not found; DDS output unavailable")]

    # Clear external discoveries so the real bundled-copy path is proven first.
    with patch.dict(os.environ, {texconv.ENV_VAR: ""}), patch.object(texconv.shutil, "which", return_value=None):
        scene.mimi_smc_texconv_path = ""
        check(True)
        # A stale custom path does not expose controls if the bundle still works.
        scene.mimi_smc_texconv_path = missing
        check(True)
        with patch.object(texconv, "_bundled_path", return_value=missing):
            # No candidate: users get the recovery chooser and missing-tool hint.
            scene.mimi_smc_texconv_path = ""
            check(False)
            # Selecting a working explicit path immediately hides those controls.
            scene.mimi_smc_texconv_path = bundled
            check(True)
            # Environment discovery is equally silent; no second lookup rule.
            scene.mimi_smc_texconv_path = ""
            with patch.dict(os.environ, {texconv.ENV_VAR: bundled}):
                check(True)
            # If that converter disappears, recovery UI becomes available again.
            check(False)
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    print("DDS_CONTROLS_PASS available=bundled,custom,environment missing=recovery_ui")


if __name__ == "__main__":
    main()
