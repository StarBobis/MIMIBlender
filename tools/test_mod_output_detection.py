"""Exercise real output validation without importing Blender.

The fake exporter writes actual INI files in an isolated temporary folder.
Production output-path validation and runtime cleanup run without changes.
This catches naming mismatches that mocked generation success tests miss.
"""
import glob
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import test_mod_generation_guard as harness


class OutputDetectionTests(unittest.TestCase):
    def setUp(self):
        # Load the real function bodies using the existing Blender-free harness.
        # Only blueprint parsing and exporting are substituted for these tests.
        self.config = Mock(logic_name="WWMI")
        self.helper = SimpleNamespace(runtime_output_node=None)
        self.cleanup = Mock()
        self.model = object()
        self.namespace = {
            "os": os,
            "glob": glob,
            "GlobalConfig": self.config,
            "LogicName": SimpleNamespace(WWMI="WWMI"),
            "BlueprintExportHelper": self.helper,
            "BluePrintModel": Mock(return_value=self.model),
            "I18nOperator": object,
            "bpy": SimpleNamespace(props=SimpleNamespace(StringProperty=lambda: None)),
            "tr": lambda text: text,
        }
        exec(compile(harness.module, str(harness.SOURCE), "exec"), self.namespace)
        self.namespace["_cleanup_unico_temp_objects"] = self.cleanup
        self.node = SimpleNamespace(name="Generate Mod")

    def export_files(self, folder, names):
        # Match the exporter contract: write files before output validation.
        # Assert the workspace override is active while the exporter runs.
        def write(model):
            self.assertIs(model, self.model)
            self.assertEqual(self.config.generated_mod_name_override, "workspace")
            self.assertIs(self.helper.runtime_output_node, self.node)
            for name in names:
                (Path(folder) / name).write_text("[Constants]\n", encoding="utf-8")
        self.namespace["_export_blueprint_model"] = write
        self.config.path_generate_mod_folder.return_value = folder
        return self.namespace["_export_regular_output"](None, None, self.node, "workspace.ini")

    def test_wwmi_consolidated_ini_is_detected(self):
        # Since 1.0.42 WWMI writes one workspace-named INI, not one per DrawIB.
        # The real file must be accepted and runtime state must be cleared.
        with TemporaryDirectory() as folder:
            result = self.export_files(folder, ["workspace.ini"])
            self.assertEqual(result, [os.path.join(folder, "workspace.ini")])
        self.cleanup.assert_called_once_with(self.model)
        self.assertIsNone(self.helper.runtime_output_node)
        self.assertEqual(self.config.generated_mod_name_override, "")

    def test_legacy_scoped_ini_cannot_mask_missing_consolidated_output(self):
        # Leftover files from old exports must not produce false success.
        # The current export needs the exact consolidated workspace filename.
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "did not generate an INI file"):
                self.export_files(folder, ["workspace_12345678.ini"])

    def test_missing_ini_still_reports_error_and_cleans_runtime(self):
        # Fixing the name check must not disable the missing-output safeguard.
        # Cleanup runs even when no INI was written by the exporter.
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "did not generate an INI file"):
                self.export_files(folder, [])
        self.cleanup.assert_called_once_with(self.model)
        self.assertIsNone(self.helper.runtime_output_node)
        self.assertEqual(self.config.generated_mod_name_override, "")

    def test_other_presets_keep_workspace_named_output(self):
        # Standard exporters already use the exact workspace filename.
        # Keep this behavior unchanged for a non-WWMI supported preset.
        self.config.logic_name = "CPUSkinning"
        with TemporaryDirectory() as folder:
            result = self.export_files(folder, ["workspace.ini"])
            self.assertEqual(result, [os.path.join(folder, "workspace.ini")])


# Plain Python is enough for filesystem validation; no scene is modified.
# TemporaryDirectory automatically removes only its own isolated test files.
if __name__ == "__main__":
    unittest.main()
