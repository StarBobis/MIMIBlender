---
name: ai-mod-automation
description: Extend and validate MIMIBlender's structured AI Mod workflow API without UI-only results, implicit targets, source mutation or fake in-game acceptance.
---

# AI Mod Automation

## Current public entry point

```python
from MIMIBlender import automation
result = automation.dispatch({
    "api_version": 1,
    "request_id": "inspect-1",
    "action": "system.capabilities",
    "params": {},
})
```

`automation.tools()` returns implemented actions and strict MCP-compatible input schemas. `dispatch_json()` serializes the same response for transport adapters. The package is Blender-independent until an action handler is needed. All bpy handlers run on Blender's main thread; concurrent/reentrant calls return `BUSY` rather than racing shared exporter state.

Every response has `api_version`, `request_id`, `ok`, `result`, `error` and `warnings`. Errors have a stable `code`, English `message` and JSON `details`. Validate types, unknown keys, finite numbers, size and depth before touching Blender. Never evaluate caller-provided Python source or interpolate it into a transport command.

## Implemented query layer

- `system.capabilities`: actual loaded build, registered concrete types, exporter registry and implemented actions.
- `scene.inspect`: exact object targets or paginated active-scene state; missing names are errors.
- `settings.inspect`: current scene settings values and RNA constraints; legacy enum getters may refresh configuration data, so the read-only handler restores GlobalConfig fields and never persists host settings.
- `rna.describe`: registered add-on operator/node and scene settings metadata; arbitrary bpy operators are not exposed.
- `blueprint.inspect`: explicit tree, paginated nodes, properties, socket identifiers and links.

Read source modules under `automation/` before extending them. Add an action only when its handler and tests exist; capability discovery must never advertise planned work as supported. Inspect current `tools()` rather than assuming this list remains complete.

## Collaborative editing

All production actions and Blender validation must use a visible interactive desktop. Background/headless Blender is forbidden for this workflow. Operate in the user's current scene so manual work can be handed to AI and then resumed by the user. Do not replace the user scene or save its files implicitly.

- `settings.update` preflights typed scalar edits and restores callback-owned sibling values on assignment failure. It redraws the actual desktop and does not persist preferences.
- `blueprint.build` creates a recoverable new graph version from explicit node/property/collection/socket/link data. An optional `base_tree` is never overwritten; its current `base_revision` token is required. A stale token returns `STALE_REVISION` before staging.
- `blueprint.validate` checks direct cycles, recursive custom groups, output presence and mesh references without changing binding metadata.
- `scene.present` shows an explicit tree or named object set in the real current-window editor. Graph builds present by default. `present=false` can defer presentation for a multi-step operation but never enables headless execution.

Presentation is transactional: a mid-operation GUI failure restores the previous editor, blueprint selection and object selection before a failed graph stage is discarded. Native Object Info callbacks may create object UUIDs; failed graph staging restores those metadata side effects. Successful graph builds do not change source mesh geometry.

Frame a newly bound graph with a short main-thread Blender timer, not an immediate view-all call before editor initialization. Mark that framing as pending in the initial result. Do not focus a graph if the user has switched the target editor before the callback runs. Never sleep or run bpy in a worker thread.

## Native workspace imports

`workspace.inspect` discovers explicit native workspace LOD/component/type candidates, buffer dependencies and source-stat revision tokens. Missing buffers remain invalid candidates; ambiguity requires explicit `types` choices or an existing valid source selection record. `workspace.import` validates that observation and starts a visible cooperative job. Poll its exact ID with `job.inspect`; `queued` or `running` is not success. `job.cancel` retains already yielded partial work.

Each component uses the real `MMTImportHelper`, including native UV/weight/shape-key/material behavior. Capture all newly created segment objects rather than trusting only the first object return. Every timer step exits `workflow_context` before yielding so manual settings/selection remain normal between steps. File stats are checked before each component read; these tokens are observations, not cryptographic authenticity or byte-level integrity claims.

The scope adds a private `GlobalConfig._automation_override` dictionary and one `path_import_selection_json` helper. Outside that scope, existing host configuration and paths behave unchanged. Inside it, workspace and output paths are explicit and source `Import.json` is never rewritten. AI-owned type records use lowercase `import.json` in new session directories. Native external source folder conventions such as `LOD0`/`TYPE_` remain unchanged in fixtures and source data; code filenames stay lowercase.

The blueprint and imported collection persist `mimi_ai_workflow` JSON plus a stable session marker. Object/source mappings use native object identities so user renames remain valid. User scene changes, Edit/Pose/Paint mode entry and changed imported transforms/ownership interrupt final binding instead of forcing the user back or overwriting their work. This ownership check does not claim to detect every possible arbitrary Python buffer edit.

The final graph reuses native Object List and Face Mod helpers, preserving per-segment source bindings. Scope restoration and final graph validation run even when the native importer otherwise reports partial success. Captured native errors are failures; warnings remain explicit.

## Workflows still under implementation

Implement explicit workspace binding for user-created/partially completed graphs, safe mesh operations, validated native export and manual UI handoff, reverse-output imports, dedicated MCP tool exposure and packaging checks. Do not mark the full objective complete from the currently implemented normal-workspace import milestone.

Manual Generate Mod and marked-texture UI/API operations must resolve a tree's persisted AI workspace metadata, not the unrelated host-selected game/workspace restored between steps. This handoff is a required next integration step, not yet an accepted workflow. Existing UI import/export functions can report success after partial failures, so adapters must independently validate meshes, graph coverage and actual output artifacts.

Do not write `Import.json` into an original extraction workspace just to preserve an AI session's type selection. Isolate selection records and export artifacts in a managed working copy or explicit output directory. Restore transient global exporter state and scene settings even on exceptions. Do not make every operation asynchronous by running bpy in a background worker; timer-based jobs must retain main-thread ownership and bounded polling.

## Tests

Run the Blender-free protocol tests with `python tools/test_automation_contract.py`. For Blender regressions, use an already open visible MCP desktop with the designated unsaved scene name `MIMIBlender MCP Capability Probe`:

```python
from MIMIBlender.tools.run_automation_tests import run_visible_tests
result = run_visible_tests()
```

The live runner rejects headless mode, saved/ordinary user scenes and active user Edit/Pose mode. It reloads automation implementations, never the registered add-on chain, and returns diagnostics without exiting Blender. Refresh the authored legacy path methods with `MIMIBlender.tools.reload_automation_live.reload_visible_automation` when testing those source changes in an already loaded desktop; preserve existing class identities. Reload `paths` before consumers such as `workspaces`, otherwise new imports can still resolve stale cached helper definitions.

The visible import milestone passed 29 real-desktop cases: four query, thirteen graph and twelve workspace cases. Those include independent source/user-geometry hashes, cancellation, user rename/transform/mode handoff, source containment, stale observations and an optional real cached PGR workspace with two components. One separately started PGR import completed through actual automatic timers in the existing visible desktop. The earlier six-component cached beads workspace was correctly rejected because its declared source buffers were missing; do not inherit historical success from that incomplete cache. Six ordinary-Python protocol tests, four legacy generation-entry tests and seven legacy Mods-root tests passed. The legacy filesystem fixtures were retained under tmp rather than automatically deleted. Recompute every result after further changes.

## Desktop capture traps

A process can report `bpy.app.background == False` while its desktop window is minimized. This produced an all-black native screenshot. Restore only this Blender process's minimized Windows windows before collaborative operations; do not restart Blender or open a replacement user scene. The presentation helper performs that process-scoped restore.

The upstream Blender MCP `look` currently requires a 3D viewport and cannot capture a layout whose main area is a blueprint editor. Use the real desktop `bpy.ops.screen.screenshot` through an explicit window/area context when reviewing that editor. Verify actual image bytes and framing; never infer the original file encoding from a normalized chat preview. Native screenshot encoding must match the file extension. GUI binding and successful operators alone are not proof that the complete graph is on screen.

Game capture, source extraction and in-game validation are external acceptance layers. A syntactically generated INI or successful operator status is not proof of complete draw coverage, source preservation or correct game rendering. Keep those claims separate in both tool results and reports.
