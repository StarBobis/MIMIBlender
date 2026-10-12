"""Blender-free regression checks for Generate Mod entry points.

Load the real entry-point definitions without importing Blender dependencies.
Exercise supported presets through direct, shared, and toolbar generation.
Keep invalid blueprint and unknown-exporter errors visible to callers.
Face Mod support is checked separately from regular game exporter dispatch.
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


class GenerationGuardTests(unittest.TestCase):
    def setUp(self):
        # Provide only the names needed by the actual export entry points.
        # Mocks capture generation side effects without writing any files.
        # The first four presets are the restored generation targets.
        # The remaining presets protect previously available generation paths.
        self.presets = ("GIMI", "SRMI", "HIMI", "ZZMI", "ZZMIDX12", "WWMI", "GF2")
        self.config = Mock(logic_name="GIMI")
        self.config.get_workspace_name.return_value = "workspace"
        self.timer = Mock()
        self.helper = Mock()
        self.manager = Mock()
        self.manager.refresh_all_nodes.return_value = {"missing_count": 0}
        self.command = Mock()
        # Translation stays deterministic so error messages can be asserted.
        # Timer and command mocks also catch premature generation side effects.
        self.namespace = {
            "GlobalConfig": self.config,
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
        # Substitute only the downstream file writer, not the entry points.
        # Output detection has separate tests that write actual temporary INIs.
        self.namespace["_export_regular_output"] = Mock()
        self.report = Mock()

    def test_supported_presets_generate_from_all_entry_points(self):
        # Every registered target must reach the same regular export flow.
        # Include DX12 and other presets to catch accidental dispatch changes.
        # Each route runs with a fresh mock history for precise side effects.
        for preset in self.presets:
            self.config.logic_name = preset
            # A regular output node should always dispatch to a game exporter.
            # No private workspace or scene objects are needed for routing.
            node = SimpleNamespace(bl_idname="MIMINode_Result_Output", name="Output")
            # Blender node collections support both iteration and named lookup.
            # Model both behaviors so toolbar resolution uses the real code.
            nodes = Mock()
            nodes.__iter__ = Mock(return_value=iter([node]))
            nodes.get.return_value = node
            tree = SimpleNamespace(nodes=nodes, name="Blueprint")
            # The quick-generation operator reads the scene's selected name.
            # Keep that name stable so the route tests do not modify selection.
            properties = SimpleNamespace(selected_blueprint_name=tree.name)
            context = SimpleNamespace(scene=SimpleNamespace(mimi_global_properties=properties))
            self.helper.get_current_blueprint_tree.return_value = tree
            self.helper.get_selected_blueprint_tree.return_value = tree
            # The first toolbar route resolves its output by node identity.
            # The second exercises its shared single-output shortcut as well.
            operator = self.namespace["MMTGenerateModBlueprint"]()
            operator.report = self.report
            operator.tree_name = ""
            operator.node_name = node.name
            quick = self.namespace["MMTGenerateSelectedBlueprintMod"]()
            quick.report = self.report
            # Do not mock either shared generation function in these routes.
            # This ensures both operator wrappers reach the actual export flow.
            actions = [
                lambda: self.namespace["generate_mod_from_output_node"](tree, context, node, self.report),
                lambda: self.namespace["generate_mod_from_tree"](tree, context, self.report),
                lambda: operator.execute(context),
                lambda: quick.execute(context),
            ]
            for index, action in enumerate(actions):
                with self.subTest(preset=preset, entry=index):
                    # Iterators are consumed, so reset the node collection.
                    # This mirrors Blender's reusable node collection behavior.
                    nodes.__iter__.return_value = iter([node])
                    self.report.reset_mock()
                    self.namespace["_export_regular_output"].reset_mock()
                    self.config.initialize_key_count.reset_mock()
                    self.manager.refresh_all_nodes.reset_mock()
                    self.command.OpenGeneratedModFolder.reset_mock()
                    self.assertEqual(action(), {"FINISHED"})
                    self.namespace["_export_regular_output"].assert_called_once_with(
                        tree, context, node, "workspace.ini"
                    )
                    # Success must initialize export state and refresh objects.
                    # Folder opening happens only after the output succeeds.
                    self.config.initialize_key_count.assert_called_once_with()
                    self.manager.refresh_all_nodes.assert_called_once_with(tree=tree, source="export")
                    self.command.OpenGeneratedModFolder.assert_called_once_with()
                    self.report.assert_called_once_with({"INFO"}, "Generate Mod Success!")
            self.namespace["export_face_mod_from_node"].assert_not_called()

    def test_gimi_face_node_uses_its_own_writer(self):
        # Face Mods are valid only for GIMI; the real writer validates that.
        # Confirm the shared entry point no longer rejects a valid GIMI node.
        node = SimpleNamespace(bl_idname="MIMINode_Face_Mod_Export")
        tree = SimpleNamespace(nodes=[node])
        result = self.namespace["generate_mod_from_tree"](tree, None, self.report)
        self.assertEqual(result, {"FINISHED"})
        self.namespace["export_face_mod_from_node"].assert_called_once_with(node)
        self.namespace["_export_regular_output"].assert_not_called()

    def test_invalid_blueprints_still_cancel_without_export(self):
        # Removing a preset restriction must not remove blueprint validation.
        # Cover absent trees, absent outputs, ambiguous outputs and bad nodes.
        node = SimpleNamespace(bl_idname="MIMINode_Result_Output")
        cases = [
            (None, "No valid blueprint found"),
            (SimpleNamespace(nodes=[]), "The current blueprint is missing a Generate Mod output node"),
            (SimpleNamespace(nodes=[node, node]), 'Multiple independent Outputs exist; click "Generate Mod" on the Output node you want to export'),
        ]
        for preset in self.presets:
            self.config.logic_name = preset
            for tree, message in cases:
                with self.subTest(preset=preset, message=message):
                    self.report.reset_mock()
                    result = self.namespace["generate_mod_from_tree"](tree, None, self.report)
                    self.assertEqual(result, {"CANCELLED"})
                    self.report.assert_called_once_with({"ERROR"}, message)
            # Invalid direct node selection must fail before any state change.
            # Neither the regular exporter nor the Face Mod writer may run.
            self.report.reset_mock()
            result = self.namespace["generate_mod_from_output_node"](None, None, object(), self.report)
            self.assertEqual(result, {"CANCELLED"})
            self.report.assert_called_once_with({"ERROR"}, "Please select a valid Output node")
        for dependency in (self.timer, self.helper, self.manager, self.command,
                           self.namespace["_export_regular_output"],
                           self.namespace["export_face_mod_from_node"]):
            self.assertEqual(dependency.mock_calls, [])

    def test_real_registry_dispatches_restored_presets_and_rejects_unknown(self):
        # Read the actual registry mapping rather than duplicating its routing.
        # Imported exporter classes are mocked; their identity is still checked.
        registry_path = SOURCE.parents[1] / "games" / "__init__.py"
        registry = ast.parse(registry_path.read_text(encoding="utf-8"))
        # Only the mapping and lookup function are executed from the registry.
        # This leaves Blender-dependent import statements out of the harness.
        mapping = next(node for node in registry.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "_LOGIC_EXPORTER_DICT"
                               for target in node.targets))
        lookup = next(node for node in registry.body if isinstance(node, ast.FunctionDef)
                      and node.name == "get_exporter_class")
        # Derive all preset constants from the production mapping itself.
        # Adding another exporter will not break this minimal namespace.
        logic_names = {key.attr: key.attr for key in mapping.value.keys}
        namespace = {"LogicName": SimpleNamespace(**logic_names)}
        for value in mapping.value.values:
            namespace.setdefault(value.id, Mock(name=value.id))
        exec(compile(ast.Module(body=[mapping, lookup], type_ignores=[]), str(registry_path), "exec"), namespace)
        self.namespace["get_exporter_class"] = namespace["get_exporter_class"]
        model = object()
        # These four mappings must stay registered after removing the UI gate.
        # The real dispatch function must instantiate and run each exporter.
        expected = {"GIMI": "GimiExporter", "SRMI": "ExportSRMI",
                    "HIMI": "UnityVsExporter", "ZZMI": "ExportZZMI"}
        for preset, name in expected.items():
            with self.subTest(preset=preset):
                self.config.logic_name = preset
                self.namespace["_export_blueprint_model"](model)
                namespace[name].assert_called_once_with(blueprint_model=model)
                namespace[name].return_value.export.assert_called_once_with()
        # Unknown game logic remains unsupported instead of reporting success.
        # Its existing actionable error is preserved at exporter dispatch.
        self.config.logic_name = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "does not yet support generating Mods"):
            self.namespace["_export_blueprint_model"](model)


# Plain unittest execution needs neither Blender nor private game workspace data.
# Mocked generation is supplemented by the filesystem output detection suite.
if __name__ == "__main__":
    unittest.main()
