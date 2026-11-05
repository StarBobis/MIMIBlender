"""Refresh authored automation code without restarting a visible Blender scene.

This development helper preserves the identity of legacy configuration classes
already imported throughout the add-on. It does not unregister the add-on,
replace the current scene, reload assets, or execute caller-provided source.
"""
# Live development boundaries:
# - Only this checkout's fixed source files are compiled.
# - No source text is accepted from an MCP action parameter.
# - A real interactive Blender window is required.
# - Active jobs must finish before implementation definitions are refreshed.
# - User objects, meshes, images and blueprints remain untouched.
# - Existing GlobalConfig class identity is retained for imported references.
# - Only the named new/changed path methods are replaced on that class.
# - Existing host-selected configuration field values are not reset.
# - MMTWorkSpace identity is retained for legacy caller imports as well.
# - UI operators stay registered; their two module-level import functions refresh.
# - Source definitions are compiled in their normal dependency namespace.
# - Automation modules reload in dependency order.
# - Job records survive through the shared driver namespace.
# - No preferences, startup file or blend file is saved by this helper.
# - This is a development reload path, not a public code-evaluation endpoint.
import ast
import importlib
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]


def patch_class(module, path, class_name, names):
    """Install selected authored descriptors while preserving legacy identity."""
    original = getattr(module, class_name)  # Preserve the registered/imported class object identity.
    source = ast.parse(path.read_text(encoding="utf-8"))  # Compile only this authored fixed source file.
    definition = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == class_name)  # Never select arbitrary client definitions.
    namespace = dict(module.__dict__)  # Resolve the same existing production dependencies.
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(path), "exec"), namespace)
    replacement = namespace[class_name]
    namespace[class_name] = original
    for name in names:
        value = vars(replacement)[name]
        if not isinstance(value, (classmethod, staticmethod)) and not callable(value):
            raise TypeError("Only selected authored method descriptors can be refreshed")
        setattr(original, name, value)
    return original


def reload_visible_automation():
    """Refresh fixed source definitions with no registration or scene reset."""
    if bpy.app.background or bpy.context.window is None:
        raise RuntimeError("Visible Blender desktop is required")
    records = bpy.app.driver_namespace.get("mimi_ai_jobs", {})
    if any(record["status"] not in {"succeeded", "failed", "cancelled", "interrupted"} for record in records.values()):
        raise RuntimeError("Finish active workflow jobs before refreshing their code")
    prefix = ROOT.name
    collaboration = sys.modules.get(prefix + ".automation.collaboration")
    if collaboration is not None:
        collaboration.unregister()
    module = importlib.import_module(prefix + ".common.global_config")
    config = patch_class(module, ROOT / "common" / "global_config.py", "GlobalConfig",
                         ("read_from_main_json", "get_workspace_name", "path_workspace_folder",
                          "path_import_selection_json", "path_generate_mod_folder", "path_mods_folder"))
    if not hasattr(config, "_automation_override"):
        config._automation_override = None
    workspace = importlib.import_module(prefix + ".workspace.mmt_workspace")
    patch_class(workspace, ROOT / "workspace" / "mmt_workspace.py", "MMTWorkSpace",
                ("check_and_get_submesh_json_path", "get_submesh_folder_path"))
    ui = importlib.import_module(prefix + ".ui.ui_func_import_mmt")
    path = ROOT / "ui" / "ui_func_import_mmt.py"
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    definitions = [node for node in parsed.body if isinstance(node, ast.FunctionDef)
                   and node.name in {"ImprotFromWorkSpaceFull", "ImprotFromWorkSpaceSelected"}]
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), ui.__dict__)
    for relative, module_name in (("common/texture_format_service.py", ".common.texture_format_service"),
                                  ("ui/ui_func_export.py", ".ui.ui_func_export"),
                                  ("blueprint/blueprint_node_face_mod.py", ".blueprint.blueprint_node_face_mod"),
                                  ("blueprint/blueprint_graph.py", ".blueprint.blueprint_graph")):
        target = importlib.import_module(prefix + module_name)
        source_path = ROOT / relative
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                       or isinstance(node, ast.ClassDef) and node.name == "_FaceObjectListSource"]
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source_path), "exec"), target.__dict__)
    export_ui = importlib.import_module(prefix + ".ui.ui_func_export")
    patch_class(export_ui, ROOT / "ui" / "ui_func_export.py", "MMTGenerateModBlueprint", ("invoke",))
    # Registered class objects remain valid; refresh only their implementation API.
    # Existing user data must not be reinitialized to obtain new helper functions.
    for suffix in ("contract", "registry", "paths", "context", "revisions", "inspection", "properties", "presentation",
                   "preservation", "audits", "jobs", "state", "blueprints", "workspaces", "binding", "exports", "meshes", "materials", "reverse", "collaboration", ""):
        name = prefix + ".automation" + ("." + suffix if suffix else "")
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    collaboration = importlib.import_module(prefix + ".automation.collaboration")
    collaboration.register()
    return {"visible": True, "legacy_class_identity_preserved": True, "scene": bpy.context.scene.name}
