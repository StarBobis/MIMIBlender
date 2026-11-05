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

## Workflows under implementation

Build noninteractive imports, blueprint mutations and export as dedicated actions rather than a blanket unrestricted `bpy.ops` endpoint. Use explicit source/output/tree/object identities; preserve user projects and original assets. Existing UI import/export functions can report success after partial failures, so action adapters must validate produced meshes, graph coverage and actual output artifacts independently.

Do not write `Import.json` into an original extraction workspace just to preserve an AI session's type selection. Isolate selection records and export artifacts in a managed working copy or explicit output directory. Restore transient global exporter state and scene settings even on exceptions. Do not make every operation asynchronous by running bpy in a background worker; timer-based jobs must retain main-thread ownership and bounded polling.

## Tests

```text
python tools/test_automation_contract.py
blender --background --factory-startup --python-exit-code 1 --python tools/test_automation_blender.py
```

Contract tests load the exact automation package without importing the add-on root or bpy. Stub only the implementation boundary. Blender tests inventory all registered operator/node schemas and use named fixture objects/graphs. Run in factory-startup isolation, never an existing user scene. Place generated evidence under repository `tmp/`.

Game capture, source extraction and in-game validation are external acceptance layers. A syntactically generated INI or successful operator status is not proof of complete draw coverage, source preservation or correct game rendering. Keep those claims separate in both tool results and reports.
