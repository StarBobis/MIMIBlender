"""Explicit visible import of native ssmt_fmt Mod reverse output candidates.

This adapter keeps the native DrawIB/component/segment naming and skeleton path.
A reverse viewer import is not silently promoted to a normal extraction workspace;
Mod generation requires an explicit original-workspace binding after review.
"""
# Reverse import ownership:
# - Source root and one candidate per DrawIB are explicit and read-only.
# - Ambiguous layouts fail before any scene object/session is allocated.
# - Native ssmt_fmt buffer parsing and component-map rules remain authoritative.
# - Every created segment is retained with its original source JSON identity.
# - Source dependencies cannot leave the explicitly named reverse root.
# - Native operations run on the existing visible desktop's main thread.
# - Timer steps restore transient settings and selection before yielding.
# - Failed uncommitted candidates remove only their own temporary data.
# - Already visible partial artifacts remain available after interruption.
# - No old user blueprint or collection is cleared to make room for the result.
# - User edits between steps stop final binding rather than overwrite changes.
# - Export needs explicit source workspace metadata, not guessed folder conversion.
import contextlib
import hashlib
import io
import json
from pathlib import Path
import uuid

import bpy

from .contract import AutomationError
from .context import workflow_context
from .jobs import start_job
from .paths import absolute_path, contained, create_session_directory, read_metadata
from .presentation import desktop_window, present_objects, redraw
from .workspaces import candidate_info, freeze_import_settings, preserve_selection, data_snapshot, discard_uncommitted, owned_mesh_state, ImportReporter


def scan_reverse(source):
    """Discover actual DrawIB JSON candidates without executing source content."""
    root = absolute_path(source, "directory")  # The caller authorizes one exact read-only reverse root.
    groups = []  # Separate DrawIB identity from candidate vertex-layout identity.
    for folder in sorted(root.iterdir()):  # Stable discovery order avoids arbitrary layout selection.
        if not folder.is_dir():  # Root sidecar metadata is not a DrawIB group.
            continue
        candidates = []  # Each group can contain several valid but ambiguous layouts.
        for path in sorted(folder.glob("*.json")):  # Parse inert source descriptions only.
            try:
                metadata = read_metadata(path)  # Bound bytes and reject malformed metadata.
            except AutomationError:  # Invalid non-candidate sidecars cannot become geometry.
                continue
            if metadata.get("CategoryBufferList") and metadata.get("IndexBufferList"):  # Recognize native ssmt_fmt declarations.
                item = candidate_info(path, root, metadata.get("WorkGameType", ""))  # Enforce dependency containment/existence.
                candidates.append(item)  # Retain usable and unusable framed candidate facts.
        if candidates:  # Avoid claiming an empty directory is an importable model group.
            groups.append({"draw_ib": folder.name, "candidates": candidates})  # Preserve native original group naming.
        if len(groups) > 2000:  # Bound main-thread source discovery population.
            raise AutomationError("REVERSE_TOO_LARGE", "Reverse output exceeds its DrawIB group bound")
    if not groups:  # Existing disk paths alone are not successful source discovery.
        raise AutomationError("EMPTY_REVERSE_OUTPUT", "No native ssmt_fmt DrawIB JSON groups were found")
    revision = hashlib.sha256(json.dumps(groups, sort_keys=True).encode("utf-8")).hexdigest()  # Opaque source-stat observation.
    return root, groups, revision  # Import validates this same observed population.


def reverse_inspect(params):
    """Read candidate identities and dependency errors before an AI chooses layouts."""
    desktop_window()  # Import/inspection always belongs to the real visible user desktop.
    root, groups, revision = scan_reverse(params["source"])
    offset, limit = params.get("offset", 0), params.get("limit", 50)
    end = min(offset + limit, len(groups))
    return {"source": str(root), "format": "ssmt_fmt", "revision": revision,
            "total_groups": len(groups), "groups": groups[offset:end],
            "next_offset": end if end < len(groups) else None, "export_requires_workspace_binding": True}


def select_reverse(groups, choices, logic):
    """Select one declared native layout per DrawIB; do not guess the original."""
    known = {item["draw_ib"] for item in groups}  # Select only discovered native groups.
    if set(choices) - known:  # Mistyped identities cannot fall back to another DrawIB.
        raise AutomationError("UNKNOWN_DRAWIB", "Reverse selection contains unknown DrawIB groups")
    result = []  # Resolve all requested groups before scene/session allocation.
    for group in groups:  # A partial candidate population is not complete import acceptance.
        selected = [item for item in group["candidates"] if item["valid"] and item.get("game") == logic]  # Keep only matching native source presets.
        if choices.get(group["draw_ib"]):  # Explicit caller layout choices take priority.
            selected = [item for item in selected if item["type"] == choices[group["draw_ib"]]]  # Exact type identity, never name sanitization.
        if len(selected) != 1:  # Missing or multiple usable candidates remain actionable errors.
            raise AutomationError("AMBIGUOUS_DATATYPE" if len(selected) > 1 else "NO_VALID_DATATYPE",
                                  "Reverse DrawIB needs one explicit usable layout", group)
        result.append((group, selected[0]))  # Native component-map facts stay associated with their chosen JSON.
    return result  # The importer receives no unreviewed alternative layout.


def reverse_steps(params, root, selected, revision, settings):
    """Yield one completed native candidate while preserving normal desktop work."""
    from ..common.mmt_import_helper import MMTImportHelper
    from ..sword.ui_panel_sword import SwordImportAllReversed
    session = create_session_directory(params["work_directory"], root, "reverse-" + uuid.uuid4().hex)
    config = {"workspace": str(root), "workspace_name": root.name, "logic": params["logic"],
              "work_directory": str(session), "import_selection": str(session / "import.json"),
              "output": str(session / "preview-output"), "session": session.name}
    with Path(config["import_selection"]).open("x", encoding="utf-8") as handle:
        json.dump({group["draw_ib"]: item["type"] for group, item in selected}, handle)
    result_collection = bpy.data.collections.new(params["name"])
    bpy.context.scene.collection.children.link(result_collection)
    result_collection["mimi_ai_reverse_source"] = str(root)
    result_collection["mimi_ai_session"] = session.name
    result_collection["mimi_ai_import_status"] = "running"
    objects, draw_objects, skeletons, states, warnings = [], {}, {}, {}, []
    reporter = ImportReporter(warnings)
    try:
        for done, (group, item) in enumerate(selected, 1):
            for source in item["files"]:
                stat = Path(source["path"]).stat()
                if stat.st_size != source["bytes"] or stat.st_mtime_ns != source["mtime_ns"]:
                    raise AutomationError("STALE_SOURCE", "Reverse source changed after inspection")
            collection = bpy.data.collections.new(group["draw_ib"])
            result_collection.children.link(collection)
            snapshot = data_snapshot()
            log = io.StringIO()
            try:
                with workflow_context(config, settings), preserve_selection(), contextlib.redirect_stdout(log):
                    paths = [candidate["json"] for candidate in group["candidates"] if candidate["valid"]]
                    component_map = SwordImportAllReversed._build_match_component_map(paths)
                    first = MMTImportHelper.create_mesh_from_json(item["json"], import_collection=collection,
                        submesh_name_prefix=group["draw_ib"], match_component_map=component_map)
                    created = [obj for obj in set(bpy.data.objects) - snapshot["objects"] if obj.type == "MESH"]
                    if first is None or not created:
                        raise AutomationError("IMPORT_EMPTY", "Native reverse candidate produced no mesh segments")
                    for obj in created:
                        obj["mimi_ai_source_json"] = item["json"]
                        obj["mimi_ai_session"] = session.name
                        states[obj] = owned_mesh_state(obj)
                    objects.extend(created)
                    draw_objects[group["draw_ib"]] = created
                    skeletons[group["draw_ib"]] = read_metadata(Path(item["json"])).get("Skeleton")
            except Exception:
                discard_uncommitted(snapshot)
                raise
            if done == 1 and params.get("present", True):
                present_objects([obj.name for obj in created])
            redraw(bpy.context.window)
            yield {"phase": "reverse_importing", "done": done, "total": len(selected),
                   "collection": result_collection.name, "session": session.name,
                   "objects": [obj.name for obj in objects], "log_tail": log.getvalue()[-4000:]}
        for obj, state in states.items():
            if owned_mesh_state(obj) != state:
                raise AutomationError("USER_EDIT_DETECTED", "User changed reverse meshes before final binding")
        with workflow_context(config, settings):
            SwordImportAllReversed._bind_skeleton(reporter, bpy.context, str(root), draw_objects, skeletons, result_collection)
        result_collection["mimi_ai_import_status"] = "succeeded"
        return {"collection": result_collection.name, "objects": [obj.name for obj in objects],
                "source": str(root), "source_revision": revision, "session": session.name, "warnings": warnings,
                "export_requires_workspace_binding": True, "format": "ssmt_fmt"}
    finally:
        if result_collection.get("mimi_ai_import_status") != "succeeded":
            result_collection["mimi_ai_import_status"] = "partial"


def reverse_import(params):
    """Queue one explicit source-layout import per group in the current desktop."""
    desktop_window()  # Import/inspection always belongs to the real visible user desktop.
    root, groups, revision = scan_reverse(params["source"])
    if params.get("source_revision") and params["source_revision"] != revision:
        raise AutomationError("STALE_SOURCE", "Reverse output changed after the caller's observation")
    work = absolute_path(params["work_directory"])
    if contained(work, root):
        raise AutomationError("SOURCE_WRITE_FORBIDDEN", "Reverse working roots must be outside source assets")
    selected = select_reverse(groups, params.get("types", {}), params["logic"])
    settings = freeze_import_settings(params.get("settings", {}))
    return start_job("reverse.import", reverse_steps(params, root, selected, revision, settings),
                     {"phase": "queued", "done": 0, "total": len(selected)})


HANDLERS = {"reverse.inspect": reverse_inspect, "reverse.import": reverse_import}
