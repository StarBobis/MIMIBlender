"""Blender-free regression checks for the Generate Mod entry-point guard.

Load the real entry-point definitions without importing Blender dependencies.
Fail-fast objects expose any attempt to inspect a blueprint before rejection.
Mocks also verify that blocked clicks cannot start export or mutate state.
Supported presets still exercise both regular and Face Mod generation paths.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


# Extract definitions only; production imports require a running Blender.
# The real function and operator bodies remain unchanged in these tests.
SOURCE = Path(__file__).resolve().parents[1] / "ui" / "ui_func_export.py"
parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
definitions = [node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
module = ast.Module(body=definitions, type_ignores=[])


class Untouchable:
    # Blocked entry points must return before reading tree or context data.
    # Raising here makes premature validation visible as a test failure.
    def __getattr__(self, name):
        raise AssertionError("Blocked generation accessed " + name)


class GenerationGuardTests(unittest.TestCase):
    def setUp(self):
        # Provide only the names needed by the actual export entry points.
        # Mocks capture generation side effects without writing any files.
        presets = ("GIMI", "SRMI", "HIMI", "ZZMI", "ZZMIDX12", "WWMI", "GF2")
        self.config = Mock(logic_name="GIMI")
        self.timer = Mock()
        self.helper = Mock()
        self.manager = Mock()
        self.manager.refresh_all_nodes.return_value = {"missing_count": 0}
        self.command = Mock()
        self.namespace = {
            "GlobalConfig": self.config,
            "LogicName": SimpleNamespace(**{name: name for name in presets}),
            "TimerUtils": self.timer,
            "BlueprintExportHelper": self.helper,
            "ObjectPersistentIdManager": self.manager,
            "CommandUtils": self.command,
            "BluePrintModel": Mock(),
            "FaceModExportError": type("FaceModExportError", (Exception,), {}),
            "I18nOperator": object,
            "bpy": SimpleNamespace(props=SimpleNamespace(StringProperty=lambda: None)),
            "tr": lambda text: text,
            "_OUTPUT_NODE_IDS": {"MIMINode_Result_Output", "MIMINode_Face_Mod_Export"},
            "export_face_mod_from_node": Mock(),
        }
        exec(compile(module, str(SOURCE), "exec"), self.namespace)
        # Replace the downstream file writer, never the guard or entry points.
        # A blocked request must leave this mock completely untouched.
        self.namespace["_export_regular_output"] = Mock()
        self.report = Mock()

    def test_blocked_presets_reject_all_entry_points_without_side_effects(self):
        # Include invalid blueprints: the preset message must take priority.
        # Both toolbar operators and both shared functions are protected.
        # Face nodes use the same shared entry point and cannot bypass it.
        for preset in ("GIMI", "SRMI", "HIMI", "ZZMI"):
            self.config.logic_name = preset
            actions = [
                lambda: self.namespace["generate_mod_from_tree"](Untouchable(), Untouchable(), self.report),
                lambda: self.namespace["generate_mod_from_output_node"](Untouchable(), Untouchable(), Untouchable(), self.report),
            ]
            for name in ("MMTGenerateModBlueprint", "MMTGenerateSelectedBlueprintMod"):
                operator = self.namespace[name]()
                operator.report = self.report
                actions.append(lambda operator=operator: operator.execute(Untouchable()))
            for action in actions:
                with self.subTest(preset=preset, entry=action):
                    self.report.reset_mock()
                    self.assertEqual(action(), {"CANCELLED"})
                    self.report.assert_called_once_with(
                        {"ERROR"}, "The current game preset does not yet support generating Mods"
                    )
            # No timers, key resets, object refreshes, or folder opens may run.
            # Exporters and Face Mod writers must remain untouched as well.
            for dependency in (self.config, self.timer, self.helper, self.manager, self.command,
                               self.namespace["_export_regular_output"],
                               self.namespace["export_face_mod_from_node"]):
                self.assertEqual(dependency.mock_calls, [])

    def test_other_presets_keep_regular_and_face_generation(self):
        # Exact matching is important: ZZMI must not accidentally block DX12.
        # Run actual shared flow to confirm success reports and folder opening.
        for preset in ("ZZMIDX12", "WWMI", "GF2"):
            for node_id in ("MIMINode_Result_Output", "MIMINode_Face_Mod_Export"):
                with self.subTest(preset=preset, node=node_id):
                    self.config.logic_name = preset
                    node = SimpleNamespace(bl_idname=node_id)
                    tree = SimpleNamespace(nodes=[node])
                    self.report.reset_mock()
                    result = self.namespace["generate_mod_from_tree"](tree, None, self.report)
                    self.assertEqual(result, {"FINISHED"})
                    self.report.assert_called_once_with({"INFO"}, "Generate Mod Success!")
        self.assertEqual(self.namespace["_export_regular_output"].call_count, 3)
        self.assertEqual(self.namespace["export_face_mod_from_node"].call_count, 3)
        self.assertEqual(self.command.OpenGeneratedModFolder.call_count, 6)


# Standard unittest execution keeps this regression runnable with plain Python.
# Blender integration is not needed to check the early cancellation contract.
if __name__ == "__main__":
    unittest.main()
