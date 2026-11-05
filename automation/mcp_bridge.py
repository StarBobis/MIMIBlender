"""Dependency-free MCP stdio adapter for the existing visible Blender desktop.

Run with python automation/mcp_bridge.py --port 9877. This process never starts
Blender, installs an add-on, opens a blend or exposes caller-provided Python.
"""
# Transport ownership:
# - stdout contains newline-delimited JSON-RPC only.
# - The user explicitly connects this adapter to an existing loopback listener.
# - Each call uses one connection and is never automatically replayed.
# - A timeout is ambiguous: inspect current state before retrying a mutation.
# - Only authored Python templates reach the generic Blender transport.
# - Caller arguments are encoded JSON data, never Python source expressions.
# - Live discovery uses the loaded automation registry, not a copied manifest.
# - Blender's existing bridge schedules the template on its main thread.
# - Automation retains validation, revision, mode and authorization boundaries.
# - No external MCP client can change the host or port through tool arguments.
# - MCP cancellation does not imply native-step interruption; use job.cancel.
# - Socket and stdio inputs have finite byte and time limits.
# - Diagnostic console output is separated by an exact result marker.
# - Transport errors do not manufacture failed or successful workflow state.
import argparse
import base64
import json
import socket
import sys
import time


MAX_BYTES = 32 * 1024 * 1024  # Bound both incoming MCP lines and returned Blender documents.
MARKER = "MIMI_AUTOMATION_JSON:"  # Ignore native diagnostic output outside this exact structured-result prefix.
VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")  # Negotiate only implemented newline-delimited MCP protocol revisions.


def encode(value):
    """Use strict finite JSON for both transport directions."""
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def blender_call(payload, port=9877, timeout=120):
    """Send only an authored template to a running loopback Blender bridge."""
    raw = encode(payload).encode("utf-8")
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Request exceeds the automation transport byte limit")
    data = base64.b64encode(raw).decode("ascii")  # The alphabet is safe inside the fixed single-quoted template literal.
    # Base64 has no quotes, slashes or executable delimiters.
    # JSON decoding happens before the automation contract handles arguments.
    # The two allowed operations are discovery and strict action dispatch.
    code = ("import base64, json\nfrom MIMIBlender import automation\n"
            "_mimi_request = json.loads(base64.b64decode('" + data + "'))\n"
            "_mimi_result = automation.tools() if _mimi_request['operation'] == 'tools' else automation.dispatch(_mimi_request['request'])\n"
            "print('" + MARKER + "' + json.dumps(_mimi_result, ensure_ascii=True, allow_nan=False))")
    command = encode({"type": "execute_code", "params": {"code": code}}).encode("utf-8")
    deadline = time.monotonic() + timeout  # One monotonic deadline covers the full fragmented socket response.
    buffer = bytearray()  # Retain incomplete UTF-8 and JSON fragments until the next socket read.
    # Always close this exact connection after one response or error.
    # A disconnected client may still have a queued main-thread action.
    # Never resend here, especially after an ambiguous timeout.
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
        connection.sendall(command)
        while len(buffer) <= MAX_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Blender response timed out; do not replay a mutation blindly")
            connection.settimeout(remaining)  # A fragmented response cannot reset the total request deadline.
            chunk = connection.recv(65536)
            if not chunk:  # Closed transport is not evidence that a queued action rolled back.
                raise ConnectionError("Blender disconnected before a complete response")
            buffer.extend(chunk)  # Parse only after preserving all bytes received for this call.
            try:
                response = json.loads(buffer.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if response.get("status") != "success":  # Reject upstream transport failure before parsing action output.
                raise RuntimeError(response.get("message", "Blender transport failed"))
            output = response.get("result", {}).get("result", "")  # The generic bridge nests captured Python stdout under its result.
            lines = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
            if len(lines) != 1:
                raise RuntimeError("Blender did not return one structured automation result")
            return json.loads(lines[0])
    raise ValueError("Blender response exceeds the transport byte limit")


class Server:
    """Small synchronous MCP server with live dedicated action tools."""

    def __init__(self, call=blender_call):
        self.call = call  # Inject only the transport boundary in offline protocol tests.

    def handle(self, message):
        """Return one JSON-RPC response, or None for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid JSON-RPC request"}}
        identifier = message.get("id")  # Echo the exact JSON-RPC id while action envelopes use a string id.
        if "id" not in message:
            return None
        try:
            method = message.get("method")  # Dispatch MCP methods explicitly rather than through attribute lookup.
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("MCP params must be an object")
            if method == "initialize":
                version = params.get("protocolVersion")  # A handshake never imports Blender or mutates its state.
                result = {"protocolVersion": version if version in VERSIONS else VERSIONS[-1],
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "mimiblender-automation", "version": "1.0.0"},
                          "instructions": "Use the existing visible Blender. Queued jobs require job.inspect; cancel with job.cancel. Generated files are not in-game verification. Transport timeouts must not be blindly replayed."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                # Advertise only actions supported by the actually connected add-on.
                # Mutation annotations do not grant user authorization.
                manifest = self.call({"operation": "tools"})  # Discover the loaded registry on every explicit tool-list request.
                result = {"tools": [{"name": item["name"], "description": item["description"],
                                     "inputSchema": item["inputSchema"],
                                     "annotations": {"readOnlyHint": not item["mutates"], "openWorldHint": False}}
                                    for item in manifest]}
            elif method == "tools/call":
                if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str):
                    raise ValueError("tools/call requires an exact action name and arguments")
                envelope = self.call({"operation": "dispatch", "request": {
                    "api_version": 1, "request_id": str(identifier), "action": params["name"], "params": params.get("arguments", {})}})
                result = {"content": [{"type": "text", "text": encode(envelope)}], "isError": not envelope["ok"]}
            else:
                return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "Method not found"}}
            return {"jsonrpc": "2.0", "id": identifier, "result": result}
        except (ValueError, KeyError, TypeError) as error:
            return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32602, "message": str(error)}}
        except Exception as error:
            # Failed communication has no trustworthy workflow acceptance state.
            # The caller must inspect the visible scene/job before another write.
            # Keep stdout valid JSON even if Blender is unavailable.
            return {"jsonrpc": "2.0", "id": identifier, "error": {
                "code": -32000, "message": str(error), "data": {"outcome_unknown": True, "retry_safe": False}}}


def main():
    """Serve bounded newline-delimited MCP messages until stdin closes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9877)
    parser.add_argument("--timeout", type=float, default=120)
    options = parser.parse_args()
    if not 1 <= options.port <= 65535 or not 0 < options.timeout <= 600:
        parser.error("Port must be 1..65535 and timeout must be 0..600 seconds")
    server = Server(lambda value: blender_call(value, options.port, options.timeout))  # Client configuration selects the endpoint, never tool arguments.
    while True:
        line = sys.stdin.buffer.readline(MAX_BYTES + 1)  # Bound one newline-framed message before allocating more input.
        if not line:
            break
        try:
            if len(line) > MAX_BYTES:
                raise ValueError("MCP input exceeds the byte limit")
            message = json.loads(line)  # Decode data only; no executable client expressions are evaluated.
            result = server.handle(message)
        except (ValueError, UnicodeDecodeError) as error:
            result = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}}
            if len(line) > MAX_BYTES:
                # Stop rather than treating the rest of an oversized line as calls.
                print(encode(result), flush=True)
                break
        if result is not None:
            print(encode(result), flush=True)


# Importing this adapter opens no sockets and imports no bpy module.
# Connection startup is an explicit client configuration decision.
if __name__ == "__main__":
    main()
