"""Blender-free regression coverage for native UI callback argument dispatch."""
# Test scope:
# - Execute the production collaboration module, not a copied wrapper.
# - Replace only Blender discovery and workspace-context dependencies.
# - Model native dispatch with the callable's actual positional argument count.
# - functools.wraps metadata is not the callable's native argument capacity.
# - Never start Blender, change a scene, or write workspace resources.
# - These tests do not certify desktop drawing or game rendering.
# - The production contract exception remains real, not a test replacement.
# - Each fixture uses a fresh wrapper list in a fake driver namespace.
# - Discovery returns only classes explicitly owned by the fixture.
# - No test registers a class in an actual Blender runtime.
# - Empty/unbound owner trees exercise the original host-context path.
# - A nonempty workflow marker exercises the source-context path.
# - Source configuration is an explicit fixture dictionary.
# - Context entry is observed independently from the callback return.
# - Context restoration is observed after success and unexpected failure.
# - Unexpected native exceptions must remain visible to the caller.
# - Expected workflow errors must use the existing UI error surface.
# - Native drawing receives the identical layout object, not a substitute.
# - Keyword callers must reach the same diagnostic surface as native callers.
# - A rejected configuration must not call the original edit implementation.
# - Original execution status sets are forwarded without translation.
# - Operator error reports preserve their existing ERROR severity.
# - Extended drawing cannot silently fall back to the ordinary draw method.
# - Repeated registration must not accumulate duplicate wrappers.
# - Unregistration restores function identity, not just matching output.
# - Main-thread native redraw is deliberately left for desktop acceptance.
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NAME = "mimi_ui_callback_test"


class CallbackTests(unittest.TestCase):
    # Each test owns isolated discovery and driver-namespace state.
    # Stub modules are restored after loading the production module.
    # Callback globals retain only this test's isolated dependencies.
    def setUp(self):
        package = ModuleType(NAME)
        package.__path__ = [str(ROOT / "automation")]
        context = ModuleType(NAME + ".context")
        inspection = ModuleType(NAME + ".inspection")
        bpy = SimpleNamespace(app=SimpleNamespace(driver_namespace={}))
        self.active = False
        self.classes = []
        self.config = {"workspace": "fixture"}
        context.require_session_config = lambda tree: self.config
        context.readonly_workflow_context = self.scope
        inspection.addon_classes = lambda: self.classes
        modules = {NAME: package, NAME + ".context": context,
                   NAME + ".inspection": inspection, "bpy": bpy}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location(
                NAME + ".collaboration", ROOT / "automation" / "collaboration.py")
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.module.owner_tree = lambda owner, context: self.tree
        self.tree = None
        self.layout = SimpleNamespace(label=lambda **values: self.labels.append(values))
        self.labels = []

    @contextmanager
    def scope(self, config):
        # Observe entry and restoration without assigning any Blender RNA.
        # Restoration must also happen when the original callback raises.
        self.assertIs(config, self.config)
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def native_draw(self, callback):
        # Blender dispatch relies on concrete positional slots in Python code.
        # Passing all arguments directly would hide the original variadic bug.
        # Do not inspect.signature: wraps advertises the original signature.
        values = (object(), object(), self.layout)
        return callback(*values[:callback.__code__.co_argcount])

    def test_native_draw_has_explicit_layout_slot(self):
        # This is the minimum negative regression for the reported exception.
        # The old wrapper has two slots and drops layout before forwarding.
        # Both ordinary node UI and extended node UI use this same contract.
        def original(owner, context, layout):
            self.assertIs(layout, self.layout)
            return "drawn"
        callback = self.module.wrap_callback(original, True)
        self.assertEqual(self.native_draw(callback), "drawn")
        self.assertEqual(callback.__code__.co_argcount, 3)
        self.assertIs(callback.__wrapped__, original)

    def test_bound_draw_enters_and_restores_source_scope(self):
        # A bound tree must keep the existing source-context routing.
        # Successful drawing must leave no context active afterward.
        self.tree = {"mimi_ai_workflow": "fixture"}
        def original(owner, context, layout):
            self.assertTrue(self.active)
            self.assertIs(layout, self.layout)
        self.native_draw(self.module.wrap_callback(original, True))
        self.assertFalse(self.active)

    def test_draw_error_is_shown_on_keyword_layout(self):
        # Keyword layout is supported as well as native positional dispatch.
        # A malformed AI binding draws an error instead of invoking the node.
        self.tree = {"mimi_ai_workflow": "fixture"}
        def reject(tree):
            raise self.module.AutomationError("INVALID", "broken workspace")
        self.module.require_session_config = reject
        callback = self.module.wrap_callback(lambda *args: self.fail("called"), True)
        self.assertIsNone(callback(object(), object(), layout=self.layout))
        self.assertEqual(self.labels, [{"text": "AI workspace: broken workspace", "icon": "ERROR"}])

    def test_native_operator_keeps_two_argument_signature(self):
        # Operators have no layout parameter; do not widen their native contract.
        # Their original result and wrapped identity must remain intact.
        def original(owner, context):
            return {"FINISHED"}
        callback = self.module.wrap_callback(original, False)
        self.assertEqual(callback.__code__.co_argcount, 2)
        self.assertEqual(callback(object(), object()), {"FINISHED"})

    def test_operator_error_reports_and_cancels(self):
        # Operator errors remain reports, not drawing labels or exceptions.
        # This preserves the existing edit failure behavior.
        self.tree = {"mimi_ai_workflow": "fixture"}
        def reject(tree):
            raise self.module.AutomationError("INVALID", "broken workspace")
        self.module.require_session_config = reject
        owner = SimpleNamespace(report=lambda level, text: self.labels.append((level, text)))
        callback = self.module.wrap_callback(lambda *args: self.fail("called"), False)
        self.assertEqual(callback(owner, object()), {"CANCELLED"})
        self.assertEqual(self.labels, [({"ERROR"}, "broken workspace")])

    def test_unexpected_error_propagates_and_restores_scope(self):
        # Do not hide unrelated node bugs behind AI metadata diagnostics.
        # The source context still must restore when a node itself fails.
        self.tree = {"mimi_ai_workflow": "fixture"}
        def original(owner, context, layout):
            raise ValueError("node failure")
        with self.assertRaisesRegex(ValueError, "node failure"):
            self.native_draw(self.module.wrap_callback(original, True))
        self.assertFalse(self.active)

    def test_registration_restores_both_draw_callbacks(self):
        # Cover the real wrapper installation loop and extended drawing path.
        # A second registration must not wrap an already wrapped callback.
        # Unregister must return the exact original callback identities.
        def draw(owner, context, layout):
            return layout
        node = type("FixtureNode", (), {"draw_buttons": draw, "draw_buttons_ext": draw})
        self.classes = [(node, "Node")]
        self.module.register()
        self.module.register()
        self.assertEqual(len(self.module._WRAPPED), 2)
        for name in ("draw_buttons", "draw_buttons_ext"):
            self.assertIs(self.native_draw(getattr(node, name)), self.layout)
        self.module.unregister()
        self.assertIs(node.draw_buttons, draw)
        self.assertIs(node.draw_buttons_ext, draw)


# Ordinary Python only: this suite must never import the Blender add-on root.
# Native desktop redraw remains a separate acceptance layer.
if __name__ == "__main__":
    unittest.main()
