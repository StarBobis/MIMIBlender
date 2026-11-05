"""Public structured AI interface, usable through any Blender Python bridge.

Example: from MIMIBlender import automation; automation.dispatch(
    {"action": "system.capabilities", "params": {}})
The same request/result contract will back dedicated MCP tools and local tests.
"""
import json
import threading
import traceback

from .contract import AutomationError, parse_request, response, validate
from .registry import ACTIONS, tools


# The lock protects one Blender instance, not an external distributed queue.
# A timer job must release it between bounded main-thread steps.
# Failed handlers cannot retain ownership after the finally block below.
# Query and mutation clients use the same execution and error boundary.
# No caller is allowed to inject a new handler through its request document.
_LOCK = threading.Lock()


def dispatch(request):
    """Validate a request, run its named handler and return a JSON envelope.

    Blender data access is main-thread-only. Do not move bpy operations into a
    worker thread merely to make an external MCP call appear asynchronous.
    """
    request_id = None
    try:
        parsed = parse_request(request)
        request_id = parsed.get("request_id")
        name = parsed["action"]
        definition = ACTIONS.get(name)
        if definition is None:
            raise AutomationError("UNKNOWN_ACTION", "Action is not implemented", {"action": name})
        params = parsed.get("params", {})
        validate(params, definition["inputSchema"])
        if threading.current_thread() is not threading.main_thread():
            raise AutomationError("MAIN_THREAD_REQUIRED", "Blender actions must run on its main thread")
        # Reject reentrant calls rather than interleaving shared exporter state.
        if not _LOCK.acquire(blocking=False):
            raise AutomationError("BUSY", "Another automation action is running")
        try:
            # Import only the selected implementation boundary. Query-only
            # clients do not need to initialize graph mutation helpers.
            if name in {"workspace.inspect", "workspace.import"}:  # Explicit source discovery/import handlers.
                from .workspaces import HANDLERS
                handler = HANDLERS[name]
            elif name in {"job.inspect", "job.cancel"}:  # Cooperative status/control never advances a job implicitly.
                from .jobs import HANDLERS
                handler = HANDLERS[name]
            elif name == "scene.present":
                from .presentation import scene_present
                handler = scene_present
            elif name == "settings.update":
                from .properties import settings_update
                handler = settings_update
            elif name in {"blueprint.build", "blueprint.validate"}:
                from .blueprints import HANDLERS
                handler = HANDLERS[name]
            else:
                from .inspection import HANDLERS
                handler = HANDLERS[name]
            result = handler(params)
            # Non-JSON results are bugs; never leak pointers into MCP responses.
            json.dumps(result, allow_nan=False)
            return response(request_id, result=result)
        finally:
            _LOCK.release()
    except AutomationError as error:
        return response(request_id, error=error)
    except Exception as error:
        # Tracebacks stay in Blender's diagnostic console, not in tool content.
        traceback.print_exc()
        return response(request_id, error=AutomationError("INTERNAL_ERROR", str(error)))


def dispatch_json(request):
    """Return a single serialized response for socket or stdio bridge adapters."""
    return json.dumps(dispatch(request), ensure_ascii=True, allow_nan=False)


# Expose only stable entry points; transport clients need no internal imports.
# Loading this package does not register classes, open ports or touch a scene.
# Capability manifests are available even before Blender-dependent handlers load.
__all__ = ["dispatch", "dispatch_json", "tools"]
