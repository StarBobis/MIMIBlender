"""Bind an existing user blueprint to explicit read-only source workspace data.

This handoff does not reimport or replace the user's partially edited geometry.
It creates a recoverable blueprint version and an isolated type-selection record.
The user may continue manual editing or invoke the same validated export jobs.
"""
# Binding contract:
# - The caller supplies the exact existing tree and its fresh revision token.
# - Source/type discovery uses the same validated native workspace contract.
# - Existing user objects, mesh edits and original blueprints stay untouched.
# - Type-selection records never overwrite the source workspace's Import.json.
# - A new graph version receives persisted source metadata before presentation.
# - Source changes require an explicit rebind/reimport, not silent host fallback.
# - Import semantics are explicit settings or current-scene defaults at binding.
# - No output Mod, game launch or asset-generation request occurs here.
# - The working root must be outside the declared source directory.
# - Generated session names are internal random identifiers, not caller code.
# - Every user/AI continuation reads the new graph's returned revision token.
import json
from pathlib import Path
import uuid

import bpy

from .contract import AutomationError
from .inspection import require_tree, blueprint_inspect
from .paths import absolute_path, contained, create_session_directory, safe_workspace_name
from .presentation import desktop_window, present_tree
from .revisions import blueprint_revision
from .workspaces import scan_workspace, choose_candidates, freeze_import_settings


def workspace_bind(params):
    """Create an explicit source-bound graph version without changing its meshes."""
    from .blueprints import blueprint_build
    desktop_window()
    original = require_tree(params["tree"])  # Keep the user's partially edited graph as the preserved base.
    revision = blueprint_revision(original)  # Observe current graph/source semantics before binding.
    if params.get("revision") != revision:  # Binding may not replace a newly edited user version.
        raise AutomationError("STALE_REVISION", "User graph changed before workspace binding", {"current_revision": revision})
    name = params.get("name") or (original.name[:30] + "-ai-" + uuid.uuid4().hex[:8])
    if bpy.data.node_groups.get(name) is not None:
        raise AutomationError("ALREADY_EXISTS", "Bound blueprint version name already exists")
    root, model, records, source_revision = scan_workspace(params["source"])
    selected = choose_candidates(root, records, params["logic"], params.get("types", {}))
    settings = freeze_import_settings(params.get("settings", {}))
    workspace_name = safe_workspace_name(params.get("workspace_name") or root.name)
    work = absolute_path(params["work_directory"])
    if contained(work, root):
        raise AutomationError("SOURCE_WRITE_FORBIDDEN", "Binding sessions cannot be placed inside source assets")
    session = create_session_directory(str(work), root, "session-" + uuid.uuid4().hex)
    record = session / "import.json"
    choices = {}
    for item, candidate in selected:
        for key in (item["submesh"], item["display_name"],
                    (item["lod"] + "." if item["lod"] else "") + item["folder_name"]):
            choices[key] = candidate["type"]
    with record.open("x", encoding="utf-8") as handle:
        json.dump(choices, handle, indent=2, ensure_ascii=True)
    config = {"workspace": str(root), "workspace_name": workspace_name, "logic": params["logic"],
              "import_selection": str(record), "work_directory": str(session), "session": session.name,
              "output": str(session / "preview-output"), "source_revision": source_revision,
              "import_settings": settings}
    result = blueprint_build({"name": name, "base_tree": original.name, "base_revision": revision,
                              "nodes": [], "present": False})
    tree = require_tree(result["tree"])
    tree["mimi_ai_workflow"] = json.dumps(config, sort_keys=True)
    if params.get("present", True):
        result["presentation"] = present_tree(tree)
    result.update(workflow=config, revision=blueprint_revision(tree), original_tree=original.name,
                  graph=blueprint_inspect({"tree": tree.name, "limit": 200}))
    return result
