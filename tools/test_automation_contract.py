"""Blender-free regression tests for structured AI requests and dispatch.

Load only the automation package so bpy and game exporter imports stay absent.
Stub the handler boundary, not production validation or response construction.
These tests cover failure safety; actual RNA inspection has a Blender suite.
"""
# Test boundaries:
# - The production request parser is never replaced by a mock.
# - The production schema validator is never replaced by a mock.
# - The production action registry is used without copied schemas.
# - The production response constructor is used for every failure.
# - The handler stub models only the Blender implementation boundary.
# - Invalid requests must fail before that boundary is imported.
# - No test imports the Blender-dependent root package.
# - No test modifies a user's host settings or workspace files.
# - Type mistakes include bool-as-integer and numeric strings.
# - Range mistakes include values both below and above the published bounds.
# - Unknown keys cannot quietly change the intended operation.
# - Missing required fields cannot be inferred from UI state.
# - Unsupported API versions cannot be treated as compatible.
# - Nonfinite JSON tokens are rejected even in string requests.
# - Python objects cannot become executable transport values.
# - Caller request IDs survive action-level validation failures.
# - Successful handler outputs must also be valid JSON.
# - A bad handler result must release the dispatcher lock.
# - Reentrant calls produce BUSY rather than waiting on themselves.
# - Main-thread validation runs before optional Blender module imports.
# - Expected internal-error diagnostics are asserted, not ignored.
# - Error-envelope assertions avoid localized operator status messages.
# - These tests do not claim that a game exporter produced valid artifacts.
# - That stronger acceptance is covered by Blender workflow tests.
import importlib.util
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


# A private module name avoids importing the add-on's Blender-dependent root.
# The tested files are exactly the production automation package on disk.
# Stubs live only in sys.modules while each handler-boundary test runs.
ROOT = Path(__file__).resolve().parents[1]
NAME = "mimi_automation_contract_test"
spec = importlib.util.spec_from_file_location(NAME, ROOT / "automation" / "__init__.py",
                                             submodule_search_locations=[str(ROOT / "automation")])
automation = importlib.util.module_from_spec(spec)
sys.modules[NAME] = automation
spec.loader.exec_module(automation)
contract = sys.modules[NAME + ".contract"]
registry = sys.modules[NAME + ".registry"]


class ContractTests(unittest.TestCase):
    """No invalid request may get as far as the Blender handler import."""

    def test_manifest_is_independent_and_strict(self):
        # Mutation annotations and schemas are the client discovery contract.
        # Returning a deepcopy prevents a client from widening later validation.
        first = automation.tools()
        self.assertTrue({"system.capabilities", "scene.inspect", "settings.inspect", "rna.describe",
                         "blueprint.inspect", "settings.update", "blueprint.build", "blueprint.validate"}
                        .issubset({item["name"] for item in first}))
        self.assertTrue(all(item["inputSchema"]["additionalProperties"] is False for item in first))
        first[0]["inputSchema"]["properties"]["injected"] = {}
        self.assertFalse(any("injected" in item["inputSchema"]["properties"] for item in automation.tools()))

    def test_invalid_requests_fail_with_stable_envelopes(self):
        # Include ambiguous numeric values that Blender would otherwise coerce.
        # Neither malformed JSON nor a Python object is a transport instruction.
        cases = ["{", [], {}, {"action": "unknown"},
                 {"action": "scene.inspect", "params": {"limit": True}},
                 {"action": "scene.inspect", "params": {"limit": 0}},
                 {"action": "scene.inspect", "params": {"limit": 201}},
                 {"action": "scene.inspect", "params": {"surprise": 1}},
                 {"action": "rna.describe", "params": {"kind": "node"}},
                 {"api_version": 2, "action": "scene.inspect"},
                 {"action": "scene.inspect", "params": {"offset": float("nan")}},
                 '{"action":"scene.inspect","params":{"offset":Infinity}}']
        for value in cases:
            with self.subTest(request=str(value)):
                result = automation.dispatch(value)
                self.assertFalse(result["ok"])
                self.assertIsNone(result["result"])
                self.assertIn("code", result["error"])
                self.assertEqual(result["api_version"], 1)
                json.dumps(result, allow_nan=False)

    def test_parameter_validation_happens_before_handler(self):
        # A valid request ID survives action-parameter validation failures.
        # This allows a client to correlate failures without parsing messages.
        result = automation.dispatch({"action": "scene.inspect", "request_id": "bad-limit",
                                      "params": {"limit": "2"}})
        self.assertEqual(result["request_id"], "bad-limit")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertNotIn(NAME + ".inspection", sys.modules)

    def test_request_limits_and_non_json_objects(self):
        # Protect the bridge from oversized documents and unsupported values.
        # Request byte limits apply to both dictionary and string entry points.
        result = automation.dispatch(" " * (contract.MAX_REQUEST_BYTES + 1))
        self.assertEqual(result["error"]["code"], "REQUEST_TOO_LARGE")
        self.assertEqual(automation.dispatch(object())["error"]["code"], "INVALID_REQUEST")
        nested = None
        for _ in range(contract.MAX_DEPTH + 2):
            nested = {"child": nested}
        with self.assertRaises(contract.AutomationError):
            contract.validate(nested, {})

    def test_handler_result_and_lock_are_safe(self):
        # Only the Blender-dependent implementation is replaced by this stub.
        # Production routing, validation, locking and JSON checks still execute.
        stub = SimpleNamespace(HANDLERS={"scene.inspect": lambda params: {"limit": params.get("limit", 50)}})
        with patch.dict(sys.modules, {NAME + ".inspection": stub}):
            request = {"action": "scene.inspect", "params": {"limit": 2}, "request_id": "q1"}
            result = automation.dispatch(request)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"], {"limit": 2})
            self.assertEqual(json.loads(automation.dispatch_json(request)), result)
            automation._LOCK.acquire()
            try:
                self.assertEqual(automation.dispatch(request)["error"]["code"], "BUSY")
            finally:
                automation._LOCK.release()
            # An invalid result must fail, release the lock, then allow retry.
            stub.HANDLERS["scene.inspect"] = lambda params: object()
            with patch("traceback.print_exc") as diagnostic:
                self.assertEqual(automation.dispatch(request)["error"]["code"], "INTERNAL_ERROR")
                diagnostic.assert_called_once()
            stub.HANDLERS["scene.inspect"] = lambda params: {}
            self.assertTrue(automation.dispatch(request)["ok"])

    def test_worker_threads_never_access_blender(self):
        # Main-thread ownership is necessary even if a transport uses workers.
        # This fails before the optional bpy inspection module could be imported.
        results = []
        worker = threading.Thread(target=lambda: results.append(automation.dispatch({"action": "scene.inspect"})))
        worker.start()
        worker.join()
        self.assertEqual(results[0]["error"]["code"], "MAIN_THREAD_REQUIRED")
        self.assertNotIn(NAME + ".inspection", sys.modules)


# Ordinary unittest runs in an existing Python; no installation is required.
# All filesystem reads above are repository source reads, not fixture mutation.
if __name__ == "__main__":
    unittest.main()
