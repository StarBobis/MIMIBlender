"""Run fixture-only cross-flow acceptance through the real dedicated MCP stdio."""
# Live acceptance ownership:
# - Connect only to the already running visible Blender on port 9877.
# - Reject saved/user projects and active user editing before creating fixtures.
# - Generate synthetic native source bytes under an exclusive repository tmp root.
# - Invoke only dedicated tools; no caller Python, generic bpy ops or headless mode.
# - Each stdio session negotiates MCP and calls one exact implemented action.
# - No ambiguous transport failure is automatically retried as a mutation.
# - Real Blender timers advance imports/exports between bounded status queries.
# - Track exact job IDs and request cancellation only for this test's active jobs.
# - Check source SHA256 separately from production source-stat revisions.
# - User-style geometry changes and AI recovery remain on one scene object.
# - A stale revision must reject the second patch rather than overwrite resumed work.
# - Validate actual native INI/buffer closure, not just queued/successful messages.
# - Earlier graph versions and generated files remain available for review.
# - No files are installed into Mods folders and no game is launched.
# - Successful artifact generation always keeps in_game_verified false.
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from automation_fixture import source_hashes, write_native_workspace


ROOT = Path(__file__).resolve().parents[1]


class Client:
    """Exercise actual stdio framing, not an in-process protocol stub."""

    def __init__(self):
        self.identifier = 0  # Correlate every handshake and tool call independently.

    def call(self, action, params=None, ok=True):
        self.identifier += 1  # Request identities never select a scene or job implicitly.
        messages = [
            {"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": self.identifier, "method": "tools/call", "params": {"name": action, "arguments": params or {}}},
        ]
        completed = subprocess.run([sys.executable, str(ROOT / "automation" / "mcp_bridge.py"), "--port", "9877"],
                                   input="\n".join(json.dumps(item) for item in messages) + "\n",
                                   text=True, capture_output=True, timeout=150)
        if completed.returncode:
            raise RuntimeError("Dedicated MCP adapter failed: " + completed.stderr)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]  # stdout must contain protocol JSON only.
        if len(responses) != 2 or responses[-1].get("id") != self.identifier:
            raise RuntimeError("Dedicated MCP stdio response framing failed")
        result = responses[-1]
        if "error" in result:
            raise RuntimeError("Transport outcome unknown; do not replay: " + json.dumps(result["error"]))
        envelope = json.loads(result["result"]["content"][0]["text"])  # Decode the shared automation result envelope.
        if envelope["ok"] != ok:
            raise AssertionError(envelope)
        return envelope["result"] if ok else envelope["error"]

    def wait(self, identifier):
        deadline = time.monotonic() + 60  # Bound real main-thread timer acceptance without a background Blender.
        for attempt in range(100):
            state = self.call("job.inspect", {"job": identifier})  # Inspection does not itself advance a workflow.
            if state["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                if state["status"] != "succeeded":
                    raise AssertionError(state)
                return state["result"]  # Queued/running is never accepted as completed work.
            if time.monotonic() >= deadline:
                break
        raise TimeoutError("Visible workflow did not reach terminal success in its bounded acceptance window")


def run():
    """Import, edit, reject stale work, recover, version a graph and export visibly."""
    client = Client()
    scene = client.call("scene.inspect", {"limit": 1})  # Never assume the previous visible test scene is still active.
    if scene["filepath"] or scene["mode"] != "OBJECT" or not scene["scene"].startswith("MIMIBlender MCP Capability Probe"):
        raise RuntimeError("Use the designated unsaved visible test scene; do not touch a user's project")
    base = ROOT / "tmp" / "ai-mcp-acceptance" / uuid.uuid4().hex  # Keep all generated inputs, outputs and reports in an exclusive retained tmp directory.
    source = write_native_workspace(base / "source")  # Only this inert fixture is created outside Blender.
    before = source_hashes(source)  # Independent byte-level source checks cannot inherit a production success flag.
    identifiers = []  # Cleanup may cancel only these exact owned cooperative jobs.
    try:
        observed = client.call("workspace.inspect", {"source": str(source)})
        started = client.call("workspace.import", {"source": str(source), "source_revision": observed["revision"],
            "logic": "PGR", "name": "mcp-acceptance-" + uuid.uuid4().hex[:8], "work_directory": str(base / "sessions"), "present": True})
        identifiers.append(started["id"])
        imported = client.wait(started["id"])
        obj = imported["objects"][0]  # Every edit targets this exact native visible scene object.
        mesh = client.call("mesh.inspect", {"object": obj, "limit": 1})
        value = list(mesh["vertices"][0]["value"])
        value[0] += 0.25  # Model a partial user/AI edit on native local-space coordinates.
        params = {"object": obj, "revision": mesh["revision"], "vertices": [{"index": 0, "value": value}], "present": True}
        edited = client.call("mesh.patch", params)
        stale = client.call("mesh.patch", params, ok=False)
        if stale["code"] != "STALE_REVISION":
            raise AssertionError(stale)
        current = client.call("mesh.inspect", {"object": obj, "limit": 1})
        client.call("mesh.restore", {"object": obj, "revision": current["revision"], "checkpoint": edited["checkpoint"], "present": True})
        recovered = client.call("mesh.inspect", {"object": obj, "limit": 1})
        if recovered["vertices"][0]["value"] != mesh["vertices"][0]["value"]:
            raise AssertionError("Recovered native coordinates differ from the pre-edit user version")
        graph = client.call("blueprint.inspect", {"tree": imported["tree"]})
        version = client.call("blueprint.build", {"name": "mcp-graph-version-" + uuid.uuid4().hex[:8],
            "base_tree": imported["tree"], "base_revision": graph["revision"], "nodes": [], "present": True})
        client.call("blueprint.inspect", {"tree": imported["tree"]})  # The original retained graph still exists after versioning.
        graph = client.call("blueprint.inspect", {"tree": version["tree"]})
        started = client.call("mod.export", {"tree": version["tree"], "revision": graph["revision"], "output_directory": str(base / "mod")})
        identifiers.append(started["id"])
        artifact = client.wait(started["id"])
        audit = client.call("mod.audit", {"output_directory": str(base / "mod")})
        if not artifact["scene_preserved"] or audit["in_game_verified"] or source_hashes(source) != before:
            raise AssertionError("Cross-flow acceptance failed independent preservation or artifact boundaries")
        report = {"ok": True, "scene": scene["scene"], "object": obj, "tree": version["tree"], "jobs": identifiers,
                  "artifact_files": len(audit["files"]), "source_preserved": True, "in_game_verified": False}
        (base / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")  # Retain exact accepted fixture/result identities.
        return report
    finally:
        for identifier in identifiers:
            state = client.call("job.inspect", {"job": identifier})  # Observe before requesting owned cancellation.
            if state["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
                client.call("job.cancel", {"job": identifier})  # Cancellation retains visible partial work; it never deletes it.


# Direct execution touches only the designated live test desktop and tmp fixtures.
# Closing each adapter session does not close or restart the user's Blender.
if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
