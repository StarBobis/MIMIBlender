"""Discover and import explicit source workspaces into a visible user scene.

Native buffer parsing, material creation and skeleton binding remain the add-on's
production implementations. The AI adapter makes ambiguity, partial artifacts,
source boundaries and progress explicit instead of trusting UI status strings.
"""
# Workspace invariants:
# - Source scanning is read-only and uses an explicit absolute root.
# - Type candidates are discovered through the native LOD/component scanner.
# - Ambiguous candidates require an explicit type choice or a valid source record.
# - A malformed candidate remains visible with its precise validation errors.
# - Source dependencies cannot escape their declared workspace root.
# - VertexCount zero is legal: native formats may infer it from buffer lengths.
# - A chosen candidate's preset must match the requested exporter logic.
# - Import steps use the native MMTImportHelper, not a parallel geometry decoder.
# - Every newly created segment object is captured, not only the first return value.
# - A failed component removes only data allocated during that uncommitted step.
# - Already yielded/visible components remain available after cancellation.
# - Selection is restored between steps so the user can continue manual work.
# - Frozen import settings apply only during each native operation step.
# - Session Import.json is separate from the source workspace's original record.
# - The final graph references every imported mesh and explicit source Submesh.
# - Face branches are built through the native Face Mod helpers.
# - Final structural validation is mandatory before publishing a graph result.
# - Native skeleton warnings stay visible and do not become fake binding proof.
# - No game process, launcher or automatic Mod installation is invoked.
# - Output/workflow metadata survives an ordinary user save of the blueprint.
# - Progress is yielded only after transient configuration has been restored.
# - Scene identity/mode checks belong to the cooperative job scheduler.
# - Native shape-key/material semantics stay owned by the existing importer.
# - User projects and preexisting objects are not replaced by a test scene.
import contextlib
import hashlib
import io
import json
from pathlib import Path
import uuid

import bpy

from .contract import AutomationError, validate
from .context import workflow_context
from .jobs import start_job
from .paths import absolute_path, contained, source_reference, read_metadata, create_session_directory, safe_workspace_name
from .presentation import desktop_window, redraw, present_objects, present_tree


# Freeze only import-relevant scene settings, not workspace/output UI selections.
# User edits outside a short native step keep their normal current settings.
IMPORT_FIELDS = ("mirror_workflow_mode", "import_merged_vgmap", "import_skip_empty_vertex_groups",
                 "gimi_high_fidelity_rendering", "align_face_on_import", "gimi_body_outline_enabled",
                 "gimi_body_outline_width_ratio")


def candidate_info(path, source_root, type_name):
    """Describe one inert source candidate and its required buffer dependencies."""
    result = {"type": type_name, "json": str(path), "valid": False, "errors": [], "files": []}  # Invalid candidates remain discoverable.
    try:
        if not contained(path.resolve(), source_root):  # Resolve links before checking authorization boundaries.
            raise AutomationError("SOURCE_PATH_ESCAPE", "Submesh JSON leaves the source root")
        data = read_metadata(path)  # Bound the actual bytes parsed as inert JSON.
        validate(data, {}, "source")  # Reject nonfinite values and unsupported deep structures.
        for key in ("GamePreset", "WorkGameType"):  # Both source identity fields are mandatory.
            if not isinstance(data.get(key), str) or not data[key]:  # A numeric/empty identity is not a preset.
                raise AutomationError("INVALID_SOURCE", "Submesh identity field is missing", {"field": key})
        if data["WorkGameType"] != type_name:  # Directory and declared layout must describe the same candidate.
            raise AutomationError("TYPE_MISMATCH", "Type directory and Submesh WorkGameType disagree")
        if not data.get("CategoryBufferList") or not data.get("IndexBufferList"):  # Geometry needs both stream classes.
            raise AutomationError("INVALID_SOURCE", "Submesh has no vertex or index buffer declarations")
        files = [path.resolve()]  # The metadata file itself participates in the source observation.
        for field in ("CategoryBufferList", "IndexBufferList", "ShapeKeyPositionBufferList"):  # Include explicitly declared morph streams.
            for row in data.get(field, []):  # Preserve every declared dependency, not only position data.
                files.append(source_reference(path.parent, row.get("FileName"), source_root))  # Missing/escaping buffers invalidate this candidate.
        if data.get("BoneMatrixFileName"):  # Optional native matrix data is required when actually declared.
            files.append(source_reference(path.parent, data["BoneMatrixFileName"], source_root))  # Retain its exact source coordinates.
        result.update(game=data["GamePreset"], vertex_count=data.get("VertexCount"),  # Counts remain declarations until native parsing.
                      index_count=data.get("IndexCount"), valid=True)  # Valid means bounded source/dependency framing, not game rendering.
        result["files"] = [{"path": str(item), "bytes": item.stat().st_size,  # Record size for the later pre-read stale check.
                            "mtime_ns": item.stat().st_mtime_ns} for item in dict.fromkeys(files)]  # Deduplicate aliases without dropping dependencies.
    except AutomationError as error:  # Keep stable source errors alongside the unusable candidate.
        result["errors"].append(error.as_dict())  # Clients can repair/choose layouts without parsing console messages.
    except (OSError, TypeError, AttributeError) as error:  # Malformed source rows remain failed candidates.
        result["errors"].append(AutomationError("INVALID_SOURCE", str(error)).as_dict())  # Do not guess geometry after malformed metadata.
    return result  # Discovery includes both accepted and rejected choices.


def scan_workspace(source):
    """Discover native components and exact candidate identities without imports."""
    from ..workspace.mmt_workspace import WorkSpaceModel
    root = absolute_path(source, "directory")  # No implicit host cache path is consulted.
    model = WorkSpaceModel(workspace_path=str(root))  # Keep native component ordering and alias semantics.
    records = []  # This population is paginated only when returned to the client.
    for lod in sorted(model.lod_components):  # Old no-LOD layouts use the native empty LOD key.
        for draw_ib, components in sorted(model.lod_components[lod].items()):  # Stable order makes observations reproducible.
            for index in sorted(components):  # Component identity comes from native first-index ordering.
                folder = Path(model.get_folder_path(lod, draw_ib, index)).resolve()  # Use the scanner's actual original folder.
                choices = [candidate_info(item / (components[index] + ".json"), root, item.name[5:])  # Metadata filename retains its original component identity.
                           for item in sorted(folder.iterdir()) if item.is_dir() and item.name.startswith("TYPE_")]  # Native type directories, not arbitrary JSON files.
                records.append({"lod": lod, "draw_ib": draw_ib, "component": index,
                                "submesh": model.get_new_submesh_name(lod, draw_ib, index),  # This is the stable explicit type-map key.
                                "display_name": model.get_display_name(lod, draw_ib, index),  # Preserve user-facing source aliases separately.
                                "folder_name": components[index], "choices": choices})
                if len(records) > 2000:  # Bound main-thread source discovery work.
                    raise AutomationError("WORKSPACE_TOO_LARGE", "Workspace exceeds the component bound")
    if not records:  # A folder existing on disk is not proof of importable models.
        raise AutomationError("EMPTY_WORKSPACE", "No native LOD/component source directories were found")
    revision = hashlib.sha256(json.dumps(records, sort_keys=True).encode("utf-8")).hexdigest()  # Opaque source-stat observation token.
    return root, model, records, revision  # The importer reuses exactly the observed native mapping.


def workspace_inspect(params):
    """Return paginated source facts so an AI can resolve type ambiguity first."""
    desktop_window()
    root, model, records, revision = scan_workspace(params["source"])
    offset, limit = params.get("offset", 0), params.get("limit", 50)
    end = min(offset + limit, len(records))
    return {"source": str(root), "revision": revision, "total_components": len(records),
            "components": records[offset:end], "next_offset": end if end < len(records) else None}


def choose_candidates(root, records, logic, requested):
    """Fail ambiguity before creating any Blender object or session directory."""
    from ..games import get_exporter_class
    if get_exporter_class(logic) is None:
        raise AutomationError("UNSUPPORTED_PRESET", "Requested game exporter is not registered", {"logic": logic})
    known = {record["submesh"] for record in records}  # Only observed components can be selected.
    if set(requested) - known:  # Typos must not silently fall back to unrelated source rows.
        raise AutomationError("UNKNOWN_SUBMESH", "Type selection contains unknown source components")
    original = read_metadata(root / "Import.json") if (root / "Import.json").is_file() else {}  # Read, never rewrite, a user's prior type choices.
    selected = []  # Every component must resolve before a job allocates a session.
    for record in records:  # A partial source population is not accepted as complete.
        choice = requested.get(record["submesh"]) or original.get(record["submesh"]) or original.get(record["display_name"])  # Explicit caller choices win.
        candidates = [item for item in record["choices"] if item["valid"] and item.get("game") == logic]  # Reject cross-preset layouts.
        if choice:  # Match the exact recorded/native type identity.
            candidates = [item for item in candidates if item["type"] == choice]  # Never sanitize into another candidate.
        if len(candidates) != 1:  # Neither zero nor multiple usable choices is success.
            raise AutomationError("AMBIGUOUS_DATATYPE" if len(candidates) > 1 else "NO_VALID_DATATYPE",
                                  "Source component needs one valid explicit data type", {"submesh": record["submesh"], "choices": record["choices"]})
        selected.append((record, candidates[0]))  # Preserve the original component facts with its one accepted layout.
    return selected  # The native importer receives this exact resolved population.


def freeze_import_settings(requested):
    """Validate requested native import fields and capture defaults at submission."""
    from .properties import prepared_value
    owner = bpy.context.scene.mimi_global_properties  # Read defaults from this same collaborative scene.
    values = {name: getattr(owner, name) for name in IMPORT_FIELDS}  # Freeze import semantics at request submission.
    for name, value in requested.items():  # Only explicitly supported import settings may be overridden.
        values[name] = prepared_value(owner, name, value, set(IMPORT_FIELDS))  # Validate real RNA enums and numeric bounds.
    return values  # Scoped application does not change the user's between-step defaults.


@contextlib.contextmanager
def preserve_selection():
    """Restore the user's current selection after one native component import."""
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    try:
        yield
    finally:
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj in selected)
        bpy.context.view_layer.objects.active = active


def data_snapshot():
    """Capture pre-step datablock identities for disposable-failure cleanup."""
    return {name: set(getattr(bpy.data, name)) for name in
            ("objects", "meshes", "materials", "images", "armatures", "node_groups")}


def discard_uncommitted(snapshot):
    """Remove only this failed, not-yet-yielded native import's new datablocks."""
    for name in ("objects", "meshes", "armatures", "materials", "node_groups", "images"):
        collection = getattr(bpy.data, name)
        for item in set(collection) - snapshot[name]:
            collection.remove(item)


def make_import_graph(name, model, imported, source_jsons, config):
    """Build native Object List/Face branches without clearing a user blueprint."""
    from ..ui import ui_func_import_mmt as native
    from .blueprints import blueprint_validate
    from ..blueprint.blueprint_export_helper import BlueprintExportHelper
    if bpy.data.node_groups.get(name) is not None:
        raise AutomationError("ALREADY_EXISTS", "Import blueprint name already exists", {"tree": name})
    tree = bpy.data.node_groups.new(name, "MIMIBlueprintTreeType")
    tree.use_fake_user = True
    try:
        BlueprintExportHelper.set_tree_submesh_names([display for obj, display in imported.values()], tree=tree)
        group = tree.nodes.new("MIMINode_Object_Group")
        native._create_and_layout_obj_info_nodes(tree, group, imported, model)
        output = tree.nodes.new("MIMINode_Result_Output")
        # Rebuild native Face metadata for every imported segment, not only
        # the first object returned by a segmented MMTImportHelper call.
        objects = next(node for node in tree.nodes if node.bl_idname == "MIMINode_Object_List")
        mapping = {str(index): (objects.name, item.object_name) for index, item in enumerate(objects.object_items)}
        paths = {str(index): source_jsons[item.object_ref or bpy.data.objects.get(item.object_name)]
                 for index, item in enumerate(objects.object_items)}
        face = native._create_face_mod_export_node(tree, mapping, paths, (0, 0))
        native._link_group_to_output(tree, face, output)
        native._link_group_to_output(tree, group, output)
        native._exclude_marked_face_objects_from_regular_group(tree, group, mapping, paths)
        native._layout_imported_blueprint(tree)
        native._clear_blueprint_node_selection(tree)
        validation = blueprint_validate({"tree": tree.name})
        if not validation["valid"]:
            raise AutomationError("INVALID_BLUEPRINT", "Imported graph failed structural validation", validation)
        tree["mimi_ai_workflow"] = json.dumps(config, sort_keys=True)
        return tree
    except Exception:
        bpy.data.node_groups.remove(tree)
        raise


def owned_mesh_state(obj):
    """Detect user ownership/layout edits before final native rig/alignment work.

    Names are intentionally excluded so ordinary user renames remain supported.
    Manual mesh/pose/paint modes are already interrupted by the job scheduler.
    """
    keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
    return {"data": obj.data.as_pointer(), "vertices": len(obj.data.vertices),
            "polygons": len(obj.data.polygons), "matrix": [list(row) for row in obj.matrix_world],
            "location": list(obj.location), "rotation": list(obj.rotation_euler), "scale": list(obj.scale),
            "parent": obj.parent.as_pointer() if obj.parent else None,
            "groups": [group.name for group in obj.vertex_groups],
            "keys": [(key.name, key.value, key.mute) for key in keys],
            "modifiers": [(modifier.name, modifier.type) for modifier in obj.modifiers]}


class ImportReporter:
    """Retain native warnings and stop on native error reports."""
    def __init__(self, warnings):
        self.warnings = warnings

    def report(self, levels, message):
        if "ERROR" in levels:
            raise AutomationError("NATIVE_IMPORT_ERROR", str(message))
        if "WARNING" in levels:
            self.warnings.append(str(message))


def import_steps(params, root, model, selected, revision, settings):
    """Yield completed native components so the existing desktop can redraw."""
    from ..common.mmt_import_helper import MMTImportHelper
    from ..ui import ui_func_import_mmt as native
    from ..utils.skeleton_helper import COMPONENT_INDEX_PROPERTY
    session = create_session_directory(params["work_directory"], root, "session-" + uuid.uuid4().hex)
    config = {"workspace": str(root), "workspace_name": params.get("workspace_name") or root.name,
              "logic": params["logic"], "import_selection": str(session / "import.json"),
              "work_directory": str(session), "output": str(session / "preview-output"),
              "import_settings": settings, "source_revision": revision, "session": session.name}
    selection = {}
    for record, candidate in selected:
        for key in (record["submesh"], record["display_name"],
                    (record["lod"] + "." if record["lod"] else "") + record["folder_name"]):
            selection[key] = candidate["type"]
    with Path(config["import_selection"]).open("x", encoding="utf-8") as handle:
        json.dump(selection, handle, indent=2, ensure_ascii=True)
    collection = bpy.data.collections.new(params["name"])
    bpy.context.scene.collection.children.link(collection)
    collection["mimi_ai_workflow"] = json.dumps(config, sort_keys=True)
    collection["mimi_ai_import_status"] = "running"
    collection["mimi_ai_session"] = session.name
    imported, source_jsons, draw_objects, skeletons, lods = {}, {}, {}, {}, {}
    owned_states = {}
    warnings = []
    reporter = ImportReporter(warnings)
    try:
        for done, (record, candidate) in enumerate(selected, 1):
            for item in candidate["files"]:
                stat = Path(item["path"]).stat()
                if stat.st_size != item["bytes"] or stat.st_mtime_ns != item["mtime_ns"]:
                    raise AutomationError("STALE_SOURCE", "Source file changed after workspace inspection", {"path": item["path"]})
            if record["lod"] not in lods:
                lod = bpy.data.collections.new(record["lod"] or "Source")
                collection.children.link(lod)
                lods[record["lod"]] = lod
            snapshot = data_snapshot()
            log = io.StringIO()
            try:
                with workflow_context(config, settings), preserve_selection(), contextlib.redirect_stdout(log):
                    first = MMTImportHelper.create_mesh_from_json(candidate["json"], import_collection=lods[record["lod"]])
                    created = sorted(set(bpy.data.objects) - snapshot["objects"], key=lambda obj: obj.name)
                    meshes = [obj for obj in created if obj.type == "MESH"]
                    if first is None or not meshes or any(not obj.data.vertices for obj in meshes):
                        raise AutomationError("IMPORT_EMPTY", "Native import produced no valid mesh")
                    for index, obj in enumerate(meshes):
                        obj.name = record["display_name"] if len(meshes) == 1 else record["display_name"] + ".segment" + str(index)
                        obj[COMPONENT_INDEX_PROPERTY] = record["component"]
                        role = native._read_submesh_role(candidate["json"])
                        obj["SSMT:SubMeshRole"] = role
                        native._apply_submesh_role_rendering(obj, role, candidate["json"])
                        obj["mimi_ai_source_json"] = candidate["json"]
                        obj["mimi_ai_session"] = session.name
                        imported[record["submesh"] + ".ai" + str(index)] = (obj, record["display_name"])
                        source_jsons[obj] = candidate["json"]
                        draw_objects.setdefault(record["draw_ib"], []).append(obj)
                    if record["draw_ib"] not in skeletons:
                        skeletons[record["draw_ib"]] = native._read_embedded_skeleton(candidate["json"])
            except Exception:
                discard_uncommitted(snapshot)
                raise
            for obj in meshes:
                owned_states[obj] = owned_mesh_state(obj)
            if done == 1 and params.get("present", True):
                present_objects([obj.name for obj in meshes])
            redraw(bpy.context.window)
            yield {"phase": "importing", "done": done, "total": len(selected), "submesh": record["submesh"],
                   "collection": collection.name, "session": session.name, "work_directory": str(session),
                   "objects": [obj.name for obj, display in imported.values()],
                   "log_tail": log.getvalue()[-4000:]}
        for obj, expected in owned_states.items():
            if owned_mesh_state(obj) != expected:
                raise AutomationError("USER_EDIT_DETECTED", "User changed imported data; final binding was interrupted", {"object": obj.name})
        with workflow_context(config, settings):
            native._auto_bind_workspace_skeleton(reporter, draw_objects, skeletons, collection)
            if settings.get("align_face_on_import"):
                native._apply_face_neck_object_alignment(imported)
            tree = make_import_graph(params["name"], model, imported, source_jsons, config)
        presentation = present_tree(tree) if params.get("present", True) else {"visible": False, "deferred": True}
        from .revisions import blueprint_revision
        revision_token = blueprint_revision(tree)
        collection["mimi_ai_import_status"] = "succeeded"
        return {"tree": tree.name, "revision": revision_token, "collection": collection.name,
                "objects": [obj.name for obj, display in imported.values()], "components": len(selected),
                "workflow": config, "warnings": warnings, "presentation": presentation}
    finally:
        if collection.get("mimi_ai_import_status") != "succeeded":
            collection["mimi_ai_import_status"] = "partial"


def workspace_import(params):
    """Validate explicit sources/settings, then start a cooperative visible job."""
    desktop_window()
    if bpy.data.node_groups.get(params["name"]) is not None:
        raise AutomationError("ALREADY_EXISTS", "Import blueprint name already exists")
    root, model, records, revision = scan_workspace(params["source"])
    if params.get("source_revision") and params["source_revision"] != revision:
        raise AutomationError("STALE_SOURCE", "Workspace changed after the caller's source inspection", {"current_revision": revision})
    safe_workspace_name(params.get("workspace_name") or root.name)
    selected = choose_candidates(root, records, params["logic"], params.get("types", {}))
    settings = freeze_import_settings(params.get("settings", {}))
    work_root = absolute_path(params["work_directory"])
    if contained(work_root, root):
        raise AutomationError("SOURCE_WRITE_FORBIDDEN", "Working directory cannot be inside source assets")
    return start_job("workspace.import", import_steps(params, root, model, selected, revision, settings),
                     {"phase": "queued", "done": 0, "total": len(selected)})


HANDLERS = {"workspace.inspect": workspace_inspect, "workspace.import": workspace_import}
