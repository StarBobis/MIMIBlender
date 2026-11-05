"""Scoped legacy importer/exporter configuration for visible AI actions.

The user's host settings and active scene configuration remain authoritative
outside each short operation step. Explicit AI paths never become host defaults.
Source workspaces are read-only; selection records live in the session directory.
"""
# Context ownership:
# - Scope exists only while the current main-thread action step executes.
# - Between timer steps the user resumes normal manual editing settings.
# - Explicit workspace paths do not require changing host settings JSON.
# - Existing legacy path helpers consult the private scope when it is active.
# - No classmethod is monkeypatched or permanently replaced.
# - Global scalar/container fields are restored after success and failure.
# - Import settings can be frozen per request and applied only within a step.
# - Only typed writable settings are temporarily assigned.
# - UI selection and mode are separate from game/workspace configuration.
# - A context must not switch the active scene or open a blend file.
# - The current visible desktop remains the bpy execution target.
# - Every source path is explicit and resolved before scope creation.
# - A missing explicit output path cannot fall back to the user's Mods folder.
# - Import.json is redirected to the AI session, not the source workspace.
# - Shared exporter counters are scoped with the same legacy field snapshot.
# - Runtime blueprint/output selection is restored after the step.
# - Restoration failures are actionable errors, not silent UI reports.
# - Context data is ordinary JSON; no caller Python code is evaluated.
# - Source geometry and files are outside this configuration context.
# - An import/export adapter still owns its artifact and source validation.
from contextlib import contextmanager
from copy import deepcopy

from .contract import AutomationError


@contextmanager
def workflow_context(config, settings=None):
    """Temporarily bind explicit workspace and settings for one visible step."""
    import bpy
    from ..common.global_config import GlobalConfig
    from ..blueprint.blueprint_export_helper import BlueprintExportHelper
    from .presentation import desktop_window
    from .properties import prepared_value, scalar_snapshot, restore_scalars
    desktop_window()
    types = (str, int, float, bool, dict, list, tuple, type(None))
    snapshot = {name: deepcopy(value) for name, value in vars(GlobalConfig).items()
                if not name.startswith("_") and isinstance(value, types)}
    previous_scope = GlobalConfig._automation_override
    previous_tree = BlueprintExportHelper.runtime_blueprint_tree_name
    previous_output = BlueprintExportHelper.runtime_output_node
    owner = bpy.context.scene.mimi_global_properties
    settings_snapshot = scalar_snapshot(owner)
    try:
        # Legacy enum callbacks must not reread and replace the scoped host state.
        # Prepare all explicit assignments before changing the scene properties.
        GlobalConfig._automation_override = dict(config)
        GlobalConfig.logic_name = config["logic"]
        GlobalConfig.gamename = config.get("game_name", config["logic"])
        GlobalConfig.workspacename = config["workspace_name"]
        prepared = {name: prepared_value(owner, name, value) for name, value in (settings or {}).items()}
        for name, value in prepared.items():
            setattr(owner, name, value)
        yield
    finally:
        # Restore callback-owned sibling settings as well as requested fields.
        # Global configuration restoration still runs if a setting restore fails.
        try:
            restore_scalars(owner, settings_snapshot)
        finally:
            GlobalConfig._automation_override = previous_scope
            for name, value in snapshot.items():
                setattr(GlobalConfig, name, value)
            BlueprintExportHelper.runtime_blueprint_tree_name = previous_tree
            BlueprintExportHelper.runtime_output_node = previous_output


def require_session_config(tree):
    """Read persisted workflow metadata from a user-saveable blueprint tree."""
    import json
    data = tree.get("mimi_ai_workflow")
    if not isinstance(data, str):
        raise AutomationError("SESSION_REQUIRED", "Blueprint has no AI workspace metadata; bind an explicit workspace first")
    try:
        config = json.loads(data)
    except (TypeError, ValueError) as error:
        raise AutomationError("INVALID_SESSION", "Blueprint workflow metadata is invalid JSON") from error
    required = {"workspace", "workspace_name", "logic", "import_selection", "work_directory"}
    if not isinstance(config, dict) or not required.issubset(config):
        raise AutomationError("INVALID_SESSION", "Blueprint workflow metadata is incomplete")
    return config
