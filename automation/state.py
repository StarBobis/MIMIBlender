"""Read-only collaboration journal shared by tools and the real desktop UI."""
# Journal ownership:
# - Store plain JSON observations, never executable commands or bpy pointers.
# - Driver namespace retains the journal through development reloads.
# - Scene pointer keys separate unrelated open scenes.
# - Actual job records remain authoritative for progress and terminal errors.
# - Queries never advance timers, cancel jobs or restore data.
# - Keep bounded recent events instead of growing with every polling request.
# - Recovery entries identify retained versions, not automatic rollback promises.
# - Do not record query polling as a new user-facing task.
# - Task errors remain English structured automation errors.
# - Opening another blend does not make old scene observations current.
# - No preferences, user files or scene data are saved implicitly.
from copy import deepcopy
import time

import bpy

from .presentation import desktop_window, redraw


JOURNAL = bpy.app.driver_namespace.setdefault("mimi_ai_journal", {})
QUERIES = {"state.inspect", "job.inspect", "system.capabilities", "scene.inspect", "settings.inspect", "rna.describe", "blueprint.inspect", "blueprint.validate", "workspace.inspect", "reverse.inspect", "mod.audit"}


def record(action, params, envelope):
    """Publish completed synchronous outcomes without interfering with dispatch."""
    if action in QUERIES or bpy.context.scene is None:
        return
    pointer = str(bpy.context.scene.as_pointer())
    events = JOURNAL.setdefault(pointer, [])
    events.append({"action": action, "request_id": envelope.get("request_id"),
                   "time": time.time(), "ok": envelope["ok"], "error": deepcopy(envelope["error"]),
                   "result": deepcopy(envelope["result"]), "targets": {
                       key: params[key] for key in ("object", "tree", "base_tree") if isinstance(params.get(key), str)}})
    del events[:-20]
    redraw(bpy.context.window)


def snapshot():
    """Read actual current-scene events/jobs and explicit recovery candidates."""
    from .jobs import JOBS, public_job
    scene = bpy.context.scene
    events = JOURNAL.get(str(scene.as_pointer()), [])
    jobs = [public_job(item) for item in JOBS.values() if item["scene_pointer"] == scene.as_pointer()]
    jobs.sort(key=lambda item: item["created_at"], reverse=True)  # Recent records are presentation order only, not an implicit operation target.
    return {"scene": scene.name, "mode": bpy.context.mode, "events": deepcopy(events), "jobs": jobs[:20],
            "in_game_verified": False, "cancellation": "Cooperative; current native step cannot be interrupted"}


def state_inspect(params):
    """Require the same visible desktop as every production automation action."""
    desktop_window()
    return snapshot()


# UI drawing uses snapshot directly, avoiding dispatch or scene RNA assignment.
# The public action still validates its empty parameter schema in dispatch.
HANDLERS = {"state.inspect": state_inspect}
