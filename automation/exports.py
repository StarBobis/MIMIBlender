"""Validated native Mod export jobs and manual UI handoff for bound AI trees.

All generation uses the existing game exporter registry in the current visible
scene. New output roots are exclusive, source workspaces are read-only, and
successful results require actual INI/resources plus scene preservation checks.
"""
# Export ownership:
# - A tree and its current revision identify the exact user/AI work to export.
# - Multiple output nodes require one explicit output-node identity.
# - A persisted workspace context is required; host-selected games cannot substitute.
# - Output directories are new paths outside the declared source root.
# - Native generation retains its existing format/material/shape-key behavior.
# - Conversion planning happens under the bound tree's source context.
# - Only file conversion uses the existing non-bpy worker service.
# - Every Blender export operation runs on the visible main thread.
# - Failed/partial output folders are retained, never recursively deleted.
# - Native auxiliary writers share the same explicit output root.
# - A native success report is not sufficient without independent artifact audit.
# - Scene fingerprints verify that native temporary copies did not change user data.
# - User graph edits between steps interrupt instead of exporting stale work.
# - Manual Generate Mod routes bound AI trees through the same validated job path.
# - Ordinary unbound blueprints keep their preexisting UI/export behavior.
# - No generated Mod is installed or launched in a game automatically.
import contextlib
import io
import json
from pathlib import Path
import uuid

import bpy

from .audits import audit_directory
from .contract import AutomationError
from .context import require_session_config, workflow_context
from .inspection import require_tree
from .jobs import start_job
from .paths import absolute_path, contained, read_metadata, safe_workspace_name
from .preservation import scene_snapshot, verify_scene_snapshot
from .presentation import desktop_window, redraw
from .revisions import blueprint_revision
from .workspaces import preserve_selection, data_snapshot, discard_uncommitted, scan_workspace


OUTPUT_TYPES = {"MIMINode_Result_Output", "MIMINode_Face_Mod_Export"}


def resolve_export(params):
    """Validate explicit tree/output/source targets before allocating output files."""
    from .blueprints import blueprint_validate
    from ..games import get_exporter_class
    tree = require_tree(params["tree"])  # Never substitute a currently selected different blueprint.
    current = blueprint_revision(tree)  # Covers graph and persisted source binding semantics.
    if params.get("revision") != current:  # Old observations cannot overwrite user changes.
        raise AutomationError("STALE_REVISION", "Blueprint changed since the caller's observation", {"current_revision": current})
    config = require_session_config(tree)  # Read the user-saveable bound workflow, not host defaults.
    source = absolute_path(config["workspace"], "directory")  # Required original source data must be online.
    work = absolute_path(config["work_directory"], "directory")  # Session records belong to this explicit working root.
    record = absolute_path(config["import_selection"], "file")  # The native importer/exporter share this exact record.
    if not contained(record, work) or contained(work, source):  # Resolve canonical ancestry before accepting paths.
        raise AutomationError("INVALID_SESSION", "AI selection records must be isolated outside source assets")
    safe_workspace_name(config["workspace_name"])  # Native INI stems cannot contain path traversal.
    if get_exporter_class(config["logic"]) is None:  # Use the real supported game registry.
        raise AutomationError("UNSUPPORTED_PRESET", "Workspace game exporter is not registered")
    root, model, records, observed = scan_workspace(str(source))  # Reobserve required buffer/declaration stats.
    if config.get("source_revision") and observed != config["source_revision"]:  # A re-extraction needs an explicit rebind/reimport.
        raise AutomationError("STALE_SOURCE", "Source buffers/metadata changed after import; rebind or reimport explicitly")
    validation = blueprint_validate({"tree": tree.name})  # Reject broken references and cycles before generation.
    if not validation["valid"]:  # Structural validity is separate from game compatibility.
        raise AutomationError("INVALID_BLUEPRINT", "Blueprint failed structural export preflight", validation)
    candidates = [node for node in tree.nodes if node.bl_idname in OUTPUT_TYPES]  # Only supported export boundaries are targets.
    if params.get("output_node"):  # Multiple independent branches need explicit identity.
        candidates = [node for node in candidates if node.name == params["output_node"]]  # Exact names preserve branch ownership.
    if len(candidates) != 1:  # Neither an empty nor ambiguous output selection is success.
        raise AutomationError("OUTPUT_REQUIRED", "Select exactly one supported output node", {"outputs": [node.name for node in candidates]})
    output = absolute_path(params["output_directory"])  # No implicit game Mods destination.
    if output.exists():  # Existing user-generated files are not overwrite permission.
        raise AutomationError("ALREADY_EXISTS", "AI export requires a new output directory", {"output": str(output)})
    if contained(output, source):  # Original extraction assets remain read-only.
        raise AutomationError("SOURCE_WRITE_FORBIDDEN", "Generated Mod directory cannot be inside source assets")
    # Source category/mark names can participate in native output filenames.
    # Reject unsafe stems before any legacy writer could escape the output root.
    for item in records:
        safe_workspace_name(item["draw_ib"])
        safe_workspace_name(item["display_name"])
        for candidate in item["choices"]:
            if not candidate["valid"]:
                continue
            metadata = read_metadata(Path(candidate["json"]))
            for category in metadata.get("CategoryHash", {}):
                safe_workspace_name(category)
            for row in metadata.get("TextureMarkUpInfoList", []):
                if row.get("MarkName"):
                    safe_workspace_name(row["MarkName"])
    from ..blueprint.blueprint_graph import iter_object_sources
    from ..blueprint.blueprint_node_obj import ObjectPersistentIdManager
    for source_item in iter_object_sources(candidates[0], strict=True):
        obj = getattr(source_item, "object_ref", None)
        if obj is None and getattr(source_item, "bl_idname", "") == "MIMINode_Object_Info":
            obj = ObjectPersistentIdManager.resolve_node_target(source_item)
        if obj is None:
            obj = bpy.data.objects.get(getattr(source_item, "object_name", ""))
        if obj is not None and obj.type == "MESH" and obj.data.shape_keys:
            for key in obj.data.shape_keys.key_blocks:
                safe_workspace_name(key.name)
    config = dict(config, output=str(output))
    return tree, candidates[0], config, current


def _export_steps_impl(tree, output_node, config, expected_revision, requested_settings, tracker):
    """Prepare native textures, generate once, then independently accept outputs."""
    from ..common import texture_format_service as textures
    from ..ui.ui_func_export import _export_regular_output
    from ..blueprint.blueprint_node_face_mod import export_face_mod_from_node
    from ..blueprint.blueprint_export_helper import BlueprintExportHelper
    source_state = scene_snapshot()  # Independently fingerprint every existing user scene object.
    settings = dict(config.get("import_settings", {}))  # Preserve the imported merged/mirror semantics.
    settings.update(requested_settings)  # Only typed explicit overrides supplement those defaults.
    # Frozen import semantics retain merged/mirror compatibility by default.
    # Explicit requested settings still go through the native typed scope.
    with workflow_context(config, settings):
        jobs = textures.collect_tree_jobs(tree)
        for job in jobs:
            textures.plan_for_job(job)
        if textures.is_running():
            raise AutomationError("TEXTURE_CONVERSION_BUSY", "Another texture conversion batch is active")
        converted = textures.start_conversion(jobs) if jobs else 0
        if converted:
            tracker["worker"] = getattr(textures, "_WORKER", None)
    while converted and textures.is_running():
        snapshot = textures.progress_snapshot()
        yield {"phase": "converting", "done": snapshot.get("done", 0), "total": snapshot.get("total", 0),
               "current": snapshot.get("current", ""), "output": config["output"]}
    if converted:
        snapshot = textures.progress_snapshot()
        if snapshot.get("cancelled") or snapshot.get("errors"):
            raise AutomationError("TEXTURE_CONVERSION_FAILED", "Native texture conversion did not complete", snapshot)
    if blueprint_revision(tree) != expected_revision:
        raise AutomationError("USER_EDIT_DETECTED", "User changed the graph during export preparation")
    verify_scene_snapshot(source_state)
    output = Path(config["output"])  # This exact root was checked before queuing.
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite a directory created by another actor.
    yield {"phase": "exporting", "done": 0, "total": 1, "output": str(output)}  # Let the real desktop redraw before native generation.
    if blueprint_revision(tree) != expected_revision:
        raise AutomationError("USER_EDIT_DETECTED", "User changed the graph before native generation")
    native_state = data_snapshot()
    log = io.StringIO()
    try:
        with workflow_context(config, settings), preserve_selection(), contextlib.redirect_stdout(log):
            from ..common.global_config import GlobalConfig
            GlobalConfig.initialize_key_count()
            BlueprintExportHelper.set_runtime_blueprint_tree(tree)
            if output_node.bl_idname == "MIMINode_Face_Mod_Export":
                export_face_mod_from_node(output_node)
            else:
                _export_regular_output(tree, bpy.context, output_node, config["workspace_name"] + ".ini")
    finally:
        # Native failures may leave unfinished temp copies; remove only allocations
        # that did not exist before this generation, never the user's originals.
        discard_uncommitted(native_state)
    verify_scene_snapshot(source_state)
    yield {"phase": "auditing", "done": 1, "total": 1, "output": str(output), "log_tail": log.getvalue()[-4000:]}
    audit = audit_directory(str(output))  # Require actual generated resource-file closure and hashes.
    verify_scene_snapshot(source_state)  # Recheck after the audit's cooperative phase boundary.
    if blueprint_revision(tree) != expected_revision:  # A later user graph edit still owns final acceptance.
        raise AutomationError("USER_EDIT_DETECTED", "User changed the graph before artifact acceptance completed")
    audit.update(tree=tree.name, output_node=output_node.name, revision=expected_revision,
                 scene_preserved=True, warnings=[], log_tail=log.getvalue()[-4000:])
    redraw(bpy.context.window)
    return audit


def export_steps(tree, output_node, config, expected_revision, requested_settings):
    """Cancel only this job's owned file conversion when the generator closes."""
    from ..common import texture_format_service as textures
    tracker = {}
    try:
        return (yield from _export_steps_impl(tree, output_node, config, expected_revision, requested_settings, tracker))
    finally:
        # Cancelling an AI export must stop future conversion work as well.
        # A newer independent user batch must never be cancelled by this owner.
        worker = tracker.get("worker")
        if worker is not None and worker is getattr(textures, "_WORKER", None) and textures.is_running():
            textures.cancel_conversion()


def mod_export(params):
    """Start one validated native export against the current visible user scene."""
    desktop_window()
    tree, output, config, revision = resolve_export(params)
    from .properties import prepared_value
    owner = bpy.context.scene.mimi_global_properties
    for name, value in params.get("settings", {}).items():
        prepared_value(owner, name, value)
    return start_job("mod.export", export_steps(tree, output, config, revision, params.get("settings", {})),
                     {"phase": "queued", "done": 0, "total": 1, "output": config["output"]})


def export_for_ui(tree, output_node, report_callback):
    """Route a user's native Generate Mod click without changing host defaults."""
    try:
        config = require_session_config(tree)
        properties = bpy.context.scene.mimi_global_properties
        root = properties.generate_mod_folder_path if properties.use_specific_generate_mod_folder_path else str(Path(config["work_directory"]) / "exports")
        target = absolute_path(root) / ("export-" + uuid.uuid4().hex)
        job = mod_export({"tree": tree.name, "revision": blueprint_revision(tree),
                          "output_node": output_node.name, "output_directory": str(target)})
    except AutomationError as error:
        report_callback({"ERROR"}, str(error))
        return {"CANCELLED"}
    tree["mimi_ai_last_export_job"] = job["id"]
    report_callback({"INFO"}, "AI Mod export queued: " + job["id"])
    return {"FINISHED"}


def mod_audit(params):
    """Audit through the same visible desktop API without launching a game."""
    desktop_window()
    return audit_directory(params["output_directory"])


HANDLERS = {"mod.export": mod_export, "mod.audit": mod_audit}
