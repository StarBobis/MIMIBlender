"""Run automation regressions inside a designated visible MCP test desktop.

Import run_visible_tests through Blender MCP instead of launching headless Blender.
The normal user scene is never a valid fixture target, even if it is unsaved.
The runner leaves Blender open so results can be inspected and edited manually.
"""
# Runner boundaries:
# - A visible Blender window is mandatory.
# - Background mode is rejected rather than treated as a faster fallback.
# - A designated unsaved test scene must already be open.
# - Existing saved user projects are never switched or replaced.
# - Fixture names are scoped by the individual suites.
# - Repeated runs retain their prior graph versions instead of overwriting them.
# - Source modules are reloaded in dependency order for live development.
# - Only automation modules are reloaded, not the registered add-on classes.
# - No registration chain is rerun in the user's desktop.
# - Tests return structured status without terminating Blender.
# - The selected suites use real bpy handlers and the public API.
# - The output log contains assertion diagnostics for developer review.
# - No file or physical Mod directory is created by this runner.
# - A successful test run does not certify game-rendering acceptance.
# - Production workflows operate in the actual user scene, unlike these fixtures.
# - This isolation is for verification, not a separate production processing mode.
import importlib
import io
from pathlib import Path
import runpy
import sys
import types
import unittest

import bpy


ROOT = Path(__file__).resolve().parents[1]
SUITES = ("test_automation_blender.py", "test_automation_graph_blender.py", "test_automation_workspaces_blender.py")


def run_visible_tests(suites=SUITES):
    """Verify explicit suites, returning their diagnostics in the live desktop."""
    if bpy.app.background or bpy.context.window is None:
        raise RuntimeError("Visible Blender desktop required; background testing is forbidden")
    if bpy.data.filepath or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
        raise RuntimeError("Use the designated unsaved test scene, never an existing user project")
    if bpy.context.mode != "OBJECT":
        raise RuntimeError("Do not start fixture tests while the user is editing/posing an object")
    if any(name not in SUITES for name in suites):
        raise ValueError("Unknown visible automation test suite")
    records = bpy.app.driver_namespace.get("mimi_ai_jobs", {})
    if any(item["status"] not in {"succeeded", "failed", "cancelled", "interrupted"} for item in records.values()):
        raise RuntimeError("Finish active workflow jobs before running/reloading the test suite")
    # Reload only already loaded automation implementations, preserving bpy data.
    # Pure contract tests are run separately in ordinary Python, not in Blender.
    prefix = ROOT.name + ".automation"
    for suffix in ("registry", "paths", "revisions", "inspection", "properties", "presentation", "context", "jobs", "blueprints", "workspaces", ""):
        name = prefix + ("." + suffix if suffix else "")
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    stream = io.StringIO()
    records = []
    for filename in suites:
        # runpy loads definitions without invoking unittest.main or sys.exit.
        # A temporary module lets the ordinary loader find test case classes.
        namespace = runpy.run_path(str(ROOT / "tools" / filename), run_name="visible_" + filename[:-3])
        module = types.ModuleType(namespace["__name__"])
        module.__dict__.update(namespace)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        records.append({"suite": filename, "tests": result.testsRun,
                        "errors": len(result.errors), "failures": len(result.failures),
                        "ok": result.wasSuccessful()})
    # Return diagnostics to MCP while leaving the real desktop responsive/open.
    # The user can then inspect the presented graph or resume manual editing.
    return {"visible": True, "background": bpy.app.background, "scene": bpy.context.scene.name,
            "ok": all(item["ok"] for item in records), "suites": records, "log": stream.getvalue()}
