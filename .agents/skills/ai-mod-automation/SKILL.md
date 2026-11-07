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

## Native export and manual handoff

`workspace.bind` creates a recoverable source-bound version of an already edited user blueprint without another geometry import. `mod.export` requires a current graph revision and a new absolute output directory outside source assets. It resolves the bound native game/type record, plans the existing exact-format conversion service, runs native generation in the visible desktop, verifies preexisting scene data and audits actual INI/resource filenames plus file SHA256 evidence. `mod.audit` exposes that offline artifact layer; `in_game_verified` remains false.

The graph revision covers semantic `mimi_ai_workflow` data, but ignores unrelated observational job IDs. Automatic shrink-frame dimensions are not user graph edits; effective child layout is hashed so real frame movement still conflicts. Binding responses refresh both the top-level token and returned graph state.

Native Generate Mod/Face buttons on bound AI trees route through the same cooperative export jobs. Ordinary unbound trees retain their existing behavior. Manual output roots receive new version directories, preserving older generated files. Node drawing and named texture/blueprint refresh operators use lightweight configuration-only scopes through `automation.collaboration`: never assign scene RNA during Blender draw callbacks. Original callback class identities and authorization decisions remain unchanged.

Face export now reuses strict Object Info/List/custom-group source traversal and respects exact object-list output ports. Multi-channel texture traversal follows its matching input channel. AI Face node overrides cannot redirect writes outside the validated new artifact root.

A real no-LOD PGR export exposed an existing short-name texture lookup bug: `MMTWorkSpace.get_submesh_folder_path` incorrectly required a nonempty LOD key. Removing that requirement restored both marked DDS files in the generated Mod. Native Hash auto-fill intentionally deduplicates by mark name; two captured DiffuseMap hashes still produce one per-mark row, so do not mistake that original behavior for a lost source-context wrapper.

## Incremental model edits

`mesh.inspect` reports local-space vertices/weights, current signatures and checkpoint history. `mesh.patch` stages a private object/mesh copy, edits vertices, named sparse weight groups, UV loops, explicit Basis/named shape keys, transforms or acknowledged replacement topology, then swaps new data onto the same visible scene object. Shared original mesh users and existing blueprint/rig references stay intact. Invalid indices, locked groups, existing user Edit/Pose mode and stale observations fail rather than being silently coerced.

Independent fake-user meshes retain recoverable checkpoints; `mesh.restore` checkpoints current work before restoring an older version. Checkpoint markers prevent history records from selecting unrelated user meshes. A presentation/commit failure resets group definitions on rejected private data before reconnecting the untouched original shared mesh. Restoration keeps the original rotation mode and world matrix. Topology replacement requires explicit acknowledgement of shape/raw channel loss and new weights/UVs when those channels existed. Existing non-Euler objects cannot be silently reinterpreted by Euler transform requests.

## Reverse output imports

`reverse.inspect` discovers native ssmt_fmt DrawIB JSON candidates and source dependencies. `reverse.import` chooses one valid layout per DrawIB and uses the existing MMT buffer parser plus native component-map/skeleton helpers in cooperative visible steps. Source bytes stay read-only; partial imported models remain after cancellation. Reverse viewer success is explicitly not a normal extraction/export workspace: create a blueprint over reviewed objects and call `workspace.bind` with an original native workspace before Mod generation. The fixture handoff through binding/native export was verified without guessing a folder conversion.

The current data-edit milestone adds eight visible mesh transaction cases and five native reverse cases. Those verify linked shared-data preservation, current-object identity, independent checkpoint restore, weight/UV/shape-key commits, staging/UI failure rollback, explicit topology/raw-channel loss guards, native reverse component identities, candidate ambiguity, source-byte preservation and reverse-model binding to an original workspace before native export. All tests use the existing visible desktop; no background Blender is used.

## Dedicated MCP and collaboration state

`automation/mcp_bridge.py` is a dependency-free stdio MCP server. Configure a client explicitly with an ordinary Python executable and this script's absolute path, plus `--port 9877`. It connects only to the existing visible Blender MCP listener, never starts Blender or installs/enables an add-on. `tools/list` discovers the loaded `automation.tools()` registry and `tools/call` exposes dedicated action names/schemas. The generic execute-code transport is internal only: fixed authored templates decode base64 JSON data; clients cannot supply Python source. Protocol negotiation, notifications, strict action errors and actual stdio framing were exercised against the live desktop. A timeout has an unknown outcome and must never trigger automatic mutation replay; re-inspect the scene or exact returned job before retrying. This adapter is available for client configuration, not automatically installed into the user's DSH profile.

`state.inspect` and the **AI Collaboration** sidebars in both 3D and blueprint editors share bounded current-scene journal/job records. Native buttons provide cooperative cancellation, explicit mesh inspection and revision-bearing checkpoint restore, plus retained base-graph navigation. Drawing does not dispatch mutations or assign scene RNA. Inspect again after manual edits; old restore buttons intentionally reject stale revisions. Cancellation is accepted in user Edit mode without leaving it; generator cleanup errors retain terminal status plus warnings instead of keeping the scene busy. Worker-thread request errors must not publish bpy-backed journal data. Registration owns only the new UI classes and does not rerun native add-on registration. Long errors wrap in the narrow sidebar rather than eliding their codes/messages.

Run `python tools/test_automation_mcp.py` for the offline protocol/transport cases (now five, including an oversized complete socket response). The initial four visible collaboration cases plus all prior query/graph/workspace/export/mesh/reverse cases passed 54 tests; the final scope is recorded below. Recompute after any further implementation changes. The connected upstream MCP add-on still reports 1.8/protocol 13 against expected 15; successful basic/dedicated calls do not certify missing upstream protocol capabilities. Do not install or restart it implicitly. Chat image previews can report normalized JPEG even when the original screenshot's raw magic is PNG; preview metadata is not source encoding proof. Check raw bytes before choosing a filename extension. A screenshot requested with `.jpg` actually contained PNG here and was preserved by a verified non-overwriting move to `.png`.

## Native material edits and conversion safety

`material.inspect/patch/restore` address one explicit current-scene mesh material slot. Inspect native node types and socket identifiers; patch only existing unlinked numeric defaults or existing image-texture bindings. Copy the native shader graph and nested groups independently, then use an OBJECT-linked slot override so DATA-linked shared mesh users keep their original material. Each edit/restore retains a complete independent material/group checkpoint; current state, checkpoint identity and checkpoint content are protected. Real presentation failure restores the exact original slot link/material. Linked inputs, missing images, duplicate targets, numeric clamping and user Edit/Pose/Paint modes fail instead of silently coercing the request. Image pixels/files are not rewritten or certified (`pixel_content_verified=false`). Material recovery controls are also available in the collaboration sidebar. This is native shader preservation/adaptation, not a universal game shader or arbitrary native-operator executor.

Export scene signatures now include native shader/group/input/image-interpretation state. Recheck user scene state and source-stat revision after the exporting yield, before calling the native writer. Source/resource caches must not overlap original workspace roots in either ancestry direction, and conversion input files cannot belong to a mutable conversion cache. The native conversion service supports an internal exact-batch outcome observer; later user/global batches cannot supply success or errors to an earlier AI export. Stage initialization/finalization failures remain explicit errors. Cancellation stops only the owned still-current worker and retains partial user-visible artifacts; no current native step is advertised as interruptible. Native source hashing/stat claims and image pixel claims remain separate.

Six native material cases and seven added export/conversion/failure cases passed with the prior suites (67 visible cases total). Failure injection replaces only the targeted UI or file-conversion boundary; the actual native import/export and scene preservation paths stay active. A separate actual bundled texconv call produced verified 4x4 BC7_UNORM with three mips and unchanged PNG SHA256 under `tmp/ai-conversion-check`; all generated inputs/outputs were retained. The protocol suite now includes strict scalar/vector `oneOf` validation (seven cases). Reload `contract` before registry/handlers, and refresh authored conversion functions without resetting native service globals or registered class identities.

## Local packaging and dedicated-tool acceptance

`release.ps1` still packages committed HEAD with `git archive`; it now refuses a plugin ZIP missing any of the 23 automation runtime modules, including the dedicated MCP adapter, collaboration UI and materials. Existing local package ZIPs are verified as the exact repository tmp target, then moved into lowercase exclusive `tmp/archive-history/package-<id>.zip` backups instead of hard-deleted. No release, version bump, upload or installation is needed for local validation. `tools/check_automation_package.py <archive> --prefix <native-wrapper>` rejects missing/duplicate/escaping members and compiles/hashes actual shipped automation bytes without importing Blender. `tools/test_automation_package.py` covers those negative cases plus synchronization with the native PowerShell runtime list. PowerShell AST parsing validates release script syntax without executing it. A real committed-HEAD ZIP using the native `MIMIBlenderV1076/` wrapper passed all 23 runtime inclusion/compilation checks; no version was published.

`python tools/test_automation_mcp_live.py` is a fixture-only client using actual MCP stdio negotiation and dedicated tools against port 9877. It rejects saved/user scenes, tracks exact jobs, lets real visible Blender timers progress, imports native synthetic source, edits/rejects stale mesh work, recovers the earlier version, creates/presents a recoverable graph version and performs native export plus independent source-byte/artifact audits. The accepted first flow produced five real fixture files with unchanged source SHA256 and no in-game verification. This does not replace the separate cached two-component/two-DDS and reverse-original-workspace handoff cases. All source/work/output/report artifacts remain under exclusive tmp roots.

## Accepted local implementation scope

The completed local collaboration scope exposes 25 dedicated action tools and passed 68 real visible Blender cases: 4 query, 13 graph, 12 workspace, 15 export/conversion/failure, 8 mesh, 5 reverse, 5 collaboration and 6 native material cases. The additional collaboration case explicitly entered native Pose and Weight Paint modes and verified that rejected AI mesh writes left both modes and geometry unchanged. Cooperative cancellation was separately verified in Edit mode. Current ordinary-Python suites passed 22 cases: 7 contract, 5 MCP transport, 5 artifact audits and 5 packaging cases. Actual stdio cross-flow acceptance and real bundled texconv execution are separate from those unit counts. All ten newly authored Python files passed English-only, syntax and at least 30% comment-line coverage gates.

The existing unsaved `MIMIBlender MCP Capability Probe` desktop remained open with no active automation jobs. The visible blueprint/task sidebar was reviewed from raw PNG desktop captures. Opening the overlay sidebar can hide a Generate Mod node even after native view-all; the deferred focus helper now measures frame-aware projected node bounds and performs bounded native zoom steps until the right edge fits beside that sidebar. It does not change node locations/revisions or focus a graph the user has switched away from. The reviewed complete native graph's rightmost node was at pixel 1270 against a sidebar-safe limit of 1278. Preview JPEG normalization must not be confused with raw PNG screenshot bytes.

Completion covers these implemented collaboration, transport, recovery, native adaptation, packing and local artifact-validation contracts, not universal AI control of every native operator or game. The MCP adapter is ready for explicit client configuration; no DSH profile/add-on installation or upstream protocol upgrade was performed automatically. Original authorization decisions remain unchanged. No Mod was installed, no game was launched and no new version was released. Image pixel content, full arbitrary draw coverage and in-game rendering remain unverified. Add further native model/material operations only through explicit typed transaction adapters with tests; do not expose arbitrary operator execution as a shortcut. Existing native functions may log benign missing optional metadata or report partial success, so artifact and source coverage checks must stay independent.

Do not write `Import.json` into an original extraction workspace just to preserve an AI session's type selection. Isolate selection records and export artifacts in a managed working copy or explicit output directory. Restore transient global exporter state and scene settings even on exceptions. Do not make every operation asynchronous by running bpy in a background worker; timer-based jobs must retain main-thread ownership and bounded polling.

## Native UI callback signatures

Keep native drawing wrappers explicitly `(self, context, layout)` for both
`draw_buttons` and `draw_buttons_ext`, and operator execution wrappers explicitly
`(self, context)`. Blender's callback dispatch depends on concrete positional
slots; `*args` and `functools.wraps` metadata do not supply the missing layout.
The shared source-context helper may be variadic, but the registered callbacks
must not be. This applies to ordinary unbound user blueprints as well as AI trees.

Run `python -B tools/test_automation_ui_callbacks.py` before changing collaboration
wrappers. Its seven Blender-free cases model positional-slot dispatch, preserve
original callback identity, check error reporting/context restoration, and exercise
registration/unregistration for both draw callbacks. The old implementation failed
with the same missing-layout exception reported for cross-IB blueprint nodes.
This is offline signature regression coverage, not actual desktop drawing proof.
Recheck the native node editor and extended properties in a visible desktop before
claiming visual acceptance; do not reuse the historical visible-test counts above.

## Tests

Run the Blender-free protocol tests with `python tools/test_automation_contract.py`. For Blender regressions, use an already open visible MCP desktop with the designated unsaved scene name `MIMIBlender MCP Capability Probe`:

```python
from MIMIBlender.tools.run_automation_tests import run_visible_tests
result = run_visible_tests()
```

The live runner rejects headless mode, saved/ordinary user scenes and active user Edit/Pose mode. It reloads automation implementations, never the registered add-on chain, and returns diagnostics without exiting Blender. Refresh the authored legacy path methods with `MIMIBlender.tools.reload_automation_live.reload_visible_automation` when testing those source changes in an already loaded desktop; preserve existing class identities. Reload `paths` before consumers such as `workspaces`, otherwise new imports can still resolve stale cached helper definitions.

The native export/manual handoff milestone passed 37 real-desktop cases: four query, thirteen graph, twelve workspace and eight export/handoff cases. It includes real native Generate Mod clicks, GIMI Face/Object List export, user geometry/source preservation, bound Hash refresh and two marked DDS copies from a real cached no-LOD PGR workspace. Five separate Blender-free artifact parser/closure tests passed; six protocol, four legacy generation and seven retained Mods-root cases also passed. A separately queued real-timer PGR export produced eleven audited files (one INI, eight geometry buffers, two DDS textures) with scene preservation and no game-runtime verification. The earlier visible import milestone passed 29 cases: four query, thirteen graph and twelve workspace cases. Those include independent source/user-geometry hashes, cancellation, user rename/transform/mode handoff, source containment, stale observations and an optional real cached PGR workspace with two components. One separately started PGR import completed through actual automatic timers in the existing visible desktop. The earlier six-component cached beads workspace was correctly rejected because its declared source buffers were missing; do not inherit historical success from that incomplete cache. Six ordinary-Python protocol tests, four legacy generation-entry tests and seven legacy Mods-root tests passed. The legacy filesystem fixtures were retained under tmp rather than automatically deleted. Recompute every result after further changes.

## Desktop capture traps

A process can report `bpy.app.background == False` while its desktop window is minimized. This produced an all-black native screenshot. Restore only this Blender process's minimized Windows windows before collaborative operations; do not restart Blender or open a replacement user scene. The presentation helper performs that process-scoped restore.

The upstream Blender MCP `look` currently requires a 3D viewport and cannot capture a layout whose main area is a blueprint editor. Use the real desktop `bpy.ops.screen.screenshot` through an explicit window/area context when reviewing that editor. Verify actual image bytes and framing; never infer the original file encoding from a normalized chat preview. Native screenshot encoding must match the file extension. GUI binding and successful operators alone are not proof that the complete graph is on screen.

Game capture, source extraction and in-game validation are external acceptance layers. A syntactically generated INI or successful operator status is not proof of complete draw coverage, source preservation or correct game rendering. Keep those claims separate in both tool results and reports.
