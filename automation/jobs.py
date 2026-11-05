"""Cooperative main-thread jobs for visible AI workflows.

Each generator step finishes before returning control to Blender's normal UI.
The user sees intermediate imported objects and can continue manual navigation.
No bpy work is executed in worker threads or in a headless Blender process.
"""
# Job ownership:
# - Generators yield only after transient configuration scopes have exited.
# - A job never keeps the user's scene settings overridden between UI events.
# - The current scene identity is checked before every operation step.
# - Switching/opening a scene interrupts a job instead of switching the user back.
# - Entering Edit/Pose mode interrupts import steps rather than changing modes.
# - Already visible partial artifacts are retained for user review/recovery.
# - Cancellation prevents future steps; it cannot interrupt native bpy mid-call.
# - A step shares the dispatcher's lock to prevent reentrant exporter state.
# - Status inspection never advances a job or manufactures success.
# - Error codes remain structured and separate from human-readable logs.
# - A successful job result must be finite JSON before it is published.
# - Progress describes actual finished steps, not an estimated completion claim.
# - Terminal status is required before generated artifacts can be accepted.
# - Live module reload keeps job records in the Blender driver namespace.
# - Opening a different blend interrupts unfinished records explicitly.
# - A timer callback never sleeps or busy-polls a worker process.
# - Every callback returns control to the existing visible Blender desktop.
# - Job IDs are random data, never filesystem or Python attribute expressions.
# - The implementation does not delete user objects on cancellation.
# - New artifacts are owned by the workflow, not by a generic cleanup routine.
from copy import deepcopy
import json
import time
import uuid

import bpy

from .contract import AutomationError
from .presentation import desktop_window


# Keep status records alive across development reloads without retaining a lock.
# The generator is private runtime state and is never serialized to MCP clients.
JOBS = bpy.app.driver_namespace.setdefault("mimi_ai_jobs", {})
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def public_job(record):
    """Return JSON state only; clients cannot edit the runtime generator."""
    fields = ("id", "action", "status", "scene", "created_at", "updated_at",
              "progress", "result", "error", "warnings")
    return {name: deepcopy(record.get(name)) for name in fields}


def start_job(action, generator, progress=None):
    """Queue a visible job, refusing competing writes to the same active scene."""
    desktop_window()
    scene = bpy.context.scene
    if bpy.context.mode != "OBJECT":
        raise AutomationError("USER_EDIT_IN_PROGRESS", "Finish the current edit/pose operation before starting a workflow job")
    if any(item["status"] not in TERMINAL and item["scene_pointer"] == scene.as_pointer() for item in JOBS.values()):
        raise AutomationError("SCENE_BUSY", "Another workflow job is already active in this scene")
    identifier = uuid.uuid4().hex
    record = {"id": identifier, "action": action, "status": "queued", "scene": scene.name,
              "scene_pointer": scene.as_pointer(), "created_at": time.time(), "updated_at": time.time(),
              "progress": progress or {}, "result": None, "error": None, "warnings": [], "generator": generator}
    JOBS[identifier] = record
    bpy.app.timers.register(lambda: step_job(identifier), first_interval=0.05)
    return public_job(record)


def finish_job(record, status, result=None, error=None):
    """Make terminal state explicit and release the private generator reference."""
    record.update(status=status, result=result, error=error.as_dict() if error else None,
                  updated_at=time.time())
    if isinstance(result, dict):
        record["warnings"] = deepcopy(result.get("warnings", record["warnings"]))
    generator = record.pop("generator", None)
    if generator is not None:
        generator.close()


def step_job(identifier):
    """Perform one bounded native step, then return to the real UI event loop."""
    from . import _LOCK
    record = JOBS.get(identifier)  # Resolve one exact queued runtime record.
    if record is None or record["status"] in TERMINAL:  # Completed/cancelled timers stop naturally.
        return None
    if not _LOCK.acquire(blocking=False):  # Reentrant UI callbacks cannot interleave a native step.
        return 0.05  # Yield instead of waiting or spinning on the main thread.
    try:
        desktop_window()  # Restore/require the actual visible collaborative desktop.
        if bpy.context.scene.as_pointer() != record["scene_pointer"]:  # Never switch the user back to an old scene.
            raise AutomationError("SCENE_CHANGED", "User changed scenes; workflow was interrupted")
        if bpy.context.mode != "OBJECT":  # A user's ongoing edit/pose/paint mode owns current input.
            raise AutomationError("USER_EDIT_IN_PROGRESS", "User entered edit/pose mode; workflow was interrupted")
        if record.get("cancel_requested"):  # Cancellation takes effect before starting another native step.
            finish_job(record, "cancelled")  # Retain already committed partial artifacts.
            return None
        record["status"] = "running"  # Progress is not an artifact-acceptance claim.
        record["updated_at"] = time.time()  # Let clients observe when a real step ran.
        try:
            progress = next(record["generator"])
            json.dumps(progress, allow_nan=False)
            record["progress"] = progress
        except StopIteration as completion:
            json.dumps(completion.value, allow_nan=False)
            finish_job(record, "succeeded", result=completion.value)
            return None
    except AutomationError as error:
        status = "interrupted" if error.code in {"SCENE_CHANGED", "USER_EDIT_IN_PROGRESS", "USER_EDIT_DETECTED"} else "failed"
        finish_job(record, status, error=error)
        return None
    except Exception as error:
        finish_job(record, "failed", error=AutomationError("WORKFLOW_FAILED", str(error)))
        return None
    finally:
        _LOCK.release()
    return 0.05


def require_job(identifier):
    """Resolve exact runtime identity rather than the most recent UI operation."""
    record = JOBS.get(identifier)
    if record is None:
        raise AutomationError("JOB_NOT_FOUND", "Workflow job was not found", {"job": identifier})
    return record


def job_inspect(params):
    """Observe current progress or terminal result without advancing the job."""
    desktop_window()
    return public_job(require_job(params["job"]))


def job_cancel(params):
    """Request cooperative cancellation; retain already visible partial work."""
    desktop_window()
    record = require_job(params["job"])
    if record["status"] not in TERMINAL:
        record["cancel_requested"] = True
        record["updated_at"] = time.time()
    return public_job(record)


@bpy.app.handlers.persistent
def interrupt_jobs_on_load(*args):
    """Opening another blend must not leave a permanently running status."""
    for record in list(JOBS.values()):
        if record["status"] not in TERMINAL:
            finish_job(record, "interrupted", error=AutomationError("SCENE_CHANGED", "User opened another blend file"))


# Register only this module's interruption hook, retaining unrelated user hooks.
# Development reloads must not duplicate persistent handlers.
if not any(getattr(item, "__module__", "") == __name__ and getattr(item, "__name__", "") == "interrupt_jobs_on_load"
           for item in bpy.app.handlers.load_post):
    bpy.app.handlers.load_post.append(interrupt_jobs_on_load)

HANDLERS = {"job.inspect": job_inspect, "job.cancel": job_cancel}
