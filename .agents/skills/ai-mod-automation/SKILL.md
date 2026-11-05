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

## Workflows under implementation

Build import/export and mesh operations as dedicated actions rather than a blanket unrestricted `bpy.ops` endpoint. Use explicit source/output/tree/object identities; preserve user projects and original assets. Existing UI import/export functions can report success after partial failures, so action adapters must validate produced meshes, graph coverage and actual output artifacts independently.

Do not write `Import.json` into an original extraction workspace just to preserve an AI session's type selection. Isolate selection records and export artifacts in a managed working copy or explicit output directory. Restore transient global exporter state and scene settings even on exceptions. Do not make every operation asynchronous by running bpy in a background worker; timer-based jobs must retain main-thread ownership and bounded polling.

## Tests

Run the Blender-free protocol tests with `python tools/test_automation_contract.py`. For Blender regressions, use an already open visible MCP desktop with the designated unsaved scene name `MIMIBlender MCP Capability Probe`:

```python
from MIMIBlender.tools.run_automation_tests import run_visible_tests
result = run_visible_tests()
```

The live runner rejects headless mode and saved/ordinary user scenes. It reloads automation implementations, never the registered add-on chain, and returns diagnostics without exiting Blender. Query tests inventory every registered operator/node schema; graph tests cover typed edits, collection copying, rollback, stale user changes and actual editor/selection presentation. The initial collaborative editing milestone passed six ordinary-Python protocol tests plus four query and twelve graph tests in a visible Blender 5.2 desktop. Recompute these results after further changes. Place generated evidence under repository `tmp/`.

## Desktop capture traps

A process can report `bpy.app.background == False` while its desktop window is minimized. This produced an all-black native screenshot. Restore only this Blender process's minimized Windows windows before collaborative operations; do not restart Blender or open a replacement user scene. The presentation helper performs that process-scoped restore.

The upstream Blender MCP `look` currently requires a 3D viewport and cannot capture a layout whose main area is a blueprint editor. Use the real desktop `bpy.ops.screen.screenshot` through an explicit window/area context when reviewing that editor. Verify actual image bytes and framing; never infer the original file encoding from a normalized chat preview. Native screenshot encoding must match the file extension. GUI binding and successful operators alone are not proof that the complete graph is on screen.

Game capture, source extraction and in-game validation are external acceptance layers. A syntactically generated INI or successful operator status is not proof of complete draw coverage, source preservation or correct game rendering. Keep those claims separate in both tool results and reports.
