"""Blender-free dedicated MCP protocol and safe transport regression tests."""
# Test ownership:
# - Load the adapter without importing the Blender-dependent root package.
# - Production JSON-RPC handling and socket decoding stay real.
# - Only the live Blender endpoint is replaced for offline cases.
# - The socket fixture never starts Blender or executes incoming Python.
# - Untrusted strings must occur only inside encoded JSON data.
# - Dedicated tools expose actual action schemas rather than execute_code.
# - Failed workflow envelopes remain MCP tool errors.
# - Transport failure is explicitly ambiguous and is never retried.
# - Notifications do not produce invalid JSON-RPC responses.
# - Native visible acceptance is run separately against port 9877.
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]  # Read production source directly rather than a copied adapter fixture.
spec = importlib.util.spec_from_file_location("mimi_mcp_adapter_test", ROOT / "automation" / "mcp_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class McpTests(unittest.TestCase):
    """Require stable wire results and a strictly data-only template boundary."""

    def message(self, method, params=None):
        return {"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}}

    def test_initialize_and_notifications(self):
        # Handshake negotiation does not require starting or connecting Blender.
        # Notifications have no id and therefore never receive a reply.
        server = bridge.Server(lambda request: self.fail("Unexpected Blender call"))
        for version in bridge.VERSIONS:
            result = server.handle(self.message("initialize", {"protocolVersion": version}))
            self.assertEqual(result["result"]["protocolVersion"], version)
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(server.handle(self.message("missing"))["error"]["code"], -32601)

    def test_live_manifest_and_errors(self):
        # A registry stub represents the already loaded production manifest.
        # The adapter itself must not add a generic execute-code tool.
        manifest = [{"name": "mesh.patch", "description": "Edit", "inputSchema": {"type": "object"}, "mutates": True}]
        seen = []
        def call(value):
            seen.append(value)
            return manifest if value["operation"] == "tools" else {"ok": False, "error": {"code": "STALE_REVISION"}}
        server = bridge.Server(call)  # Mock transport only; production protocol handling remains active.
        tools = server.handle(self.message("tools/list"))["result"]["tools"]
        self.assertEqual([item["name"] for item in tools], ["mesh.patch"])
        self.assertFalse(tools[0]["annotations"]["readOnlyHint"])  # Mutation hints do not accidentally advertise writes as read-only.
        result = server.handle(self.message("tools/call", {"name": "mesh.patch", "arguments": {"revision": "old"}}))
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(seen[-1]["request"]["request_id"], "7")  # Correlate action errors with the original MCP request identity.

    def test_timeout_is_never_replayed(self):
        # A queued mutation can run after the socket timeout.
        # Report ambiguity instead of pretending failure rolled back Blender.
        seen = []
        def call(value):
            seen.append(value)
            raise TimeoutError("ambiguous")
        result = bridge.Server(call).handle(self.message("tools/call", {"name": "mesh.patch"}))
        self.assertEqual(len(seen), 1)  # Timeout handling must never duplicate an ambiguous mutation.
        self.assertFalse(result["error"]["data"]["retry_safe"])
        self.assertTrue(result["error"]["data"]["outcome_unknown"])

    def test_socket_template_keeps_payload_inert(self):
        # The fake endpoint only reads the command and returns a split response.
        # This exercises real UTF-8/JSON socket framing without running source.
        # Malicious-looking strings are allowed data but cannot become code.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))  # Use an ephemeral loopback port without touching the real desktop listener.
        listener.listen(1)
        port = listener.getsockname()[1]
        captured = []
        errors = []
        def endpoint():
            try:
                with listener, listener.accept()[0] as client:
                    buffer = b""  # Accumulate real socket fragments without interpreting command code.
                    while True:
                        buffer += client.recv(65536)
                        try:
                            captured.append(json.loads(buffer))  # Retain the actual wire command for inert-payload assertions.
                            break
                        except json.JSONDecodeError:
                            continue
                    response = bridge.encode({"status": "success", "result": {"result": bridge.MARKER + '{"ok": true}'}}).encode()
                    client.sendall(response[:15])
                    client.sendall(response[15:])
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=endpoint)
        worker.start()
        payload = {"operation": "dispatch", "request": {"params": {"object": "'); __import__('os').system('bad') #"}}}
        self.assertEqual(bridge.blender_call(payload, port, 5), {"ok": True})
        worker.join(5)  # A bounded join prevents a failed test from waiting indefinitely.
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        code = captured[0]["params"]["code"]
        self.assertNotIn("system('bad')", code)  # Untrusted Python-like text must never appear as executable template code.
        self.assertEqual(captured[0]["type"], "execute_code")


# Direct execution uses ordinary Python; it does not install dependencies.
# No temporary files or user scene assets are written by these tests.
if __name__ == "__main__":
    unittest.main()
