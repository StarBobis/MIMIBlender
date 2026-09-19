# Blueprint audit and regression coverage — v1.0.23

## Scope

Audited the blueprint node/socket implementation, Object List references, custom grouping and navigation, node menus, file drops, preview/highlight behavior, shape-key refresh, animation rebaking, and graph export traversal. Validation uses the installed Blender 5.2.0 LTS build `fbe6228777e7`, disposable factory scenes, and the repository's existing export fixtures. No user scene or preferences are overwritten.

This records verified fixes and coverage, not a guarantee that every possible production scene or game/runtime combination is defect-free. Live in-game rendering and private production workspaces are outside the available regression fixtures.

## Confirmed fixes

### Drawing and references

- **Blank socket labels:** `MIMISocketObject.draw()` called a nonexistent superclass method. Draw labels directly; Blender still draws the cyan socket circles. Verified on the reported Object List → Master Mesh Group layout with connected and unconnected ports.
- **Renamed object identity:** Object Info refresh, selection, highlighting and export now prefer a matching saved UUID over a reused old object name.
- **Object List renames:** native object pointers retain identity; the safe timer updates row/socket names. Export reads the pointer even before that timer runs.
- **Persisted highlight colors:** restore `IDPropertyArray` colors after loading, discard stale pointer caches, and read selection from each visible 3D window's actual view layer. Disabled list rows do not highlight.
- **Preview and texture marks:** shared read-only traversal supports Object Lists, per-item ports, reroutes, muted nodes and nested custom groups. Texture-mark lookup no longer requires a standalone Object Info source.
- **Shape-key refresh:** bind the button to its own output node, collect only connected sources including lists/groups, and preserve the existing per-key settings.
- **Stale explicit targets:** deleted/renamed blueprint targets cancel instead of silently editing a different open blueprint. This applies to blueprint selection and list/texture row operators.
- **Drops inside groups:** use the actively edited child tree rather than always adding nodes to the outer blueprint.

### Grouping and graph evaluation

- **Collection loss on grouping:** explicitly copy PropertyGroup collections, dynamic enums and both input/output socket identifiers. Object Lists, shape options and texture settings survive cloning.
- **Native nodes:** keep Blender-owned Frame/Reroute ports rather than attempting to remove/recreate them.
- **Rollback crash:** snapshot link endpoint metadata before editing. Never dereference removed RNA links/sockets. Failed grouping/ungrouping restores the original graph and removes temporary clones.
- **Dynamic target ports:** wire replacements before removing source nodes, preventing auto-growing target nodes from deleting ports that are still needed.
- **Interface edits:** synchronize custom group ports in place, preserving unchanged wires through renames, additions and reordering. A persistent, change-detecting timer covers custom-tree edits without native notifications.
- **Group output isolation:** export only the caller's connected output instead of every child output; choose an explicit active Group Output or a legacy first-output fallback.
- **Nested/group-input traversal:** restore the parent instance context when crossing a Group Input, including inside switch/timeline branches.
- **Cycle handling:** report wire/group cycles without overflowing recursion; distinguish legitimate serial instances of the same shared group.
- **Reroute export:** retain upstream geometry through reroute nodes instead of silently omitting it.
- **Orphan list outputs:** reject a port with no corresponding item instead of silently expanding it to All.
- **Ungroup layout and pass-through:** preserve direct Group Input → Group Output links and moved-instance coordinates. New groups use schema 2 relative positions; schema 1 retains its historical absolute layout.
- **Navigation:** exiting works after the Python navigation stack is lost on load or breadcrumb navigation. A group's own Enter button no longer depends on a different active node.

### Menus and animation

- **Batch connection direction:** allow a pass-through Group to feed an input-only Generate Mod node.
- **Batch socket growth:** only known dynamic node contracts may gain ports; texture/custom-group interfaces cannot acquire arbitrary extra inputs.
- **Independent rebaking:** associate a baked Object List with its timeline instance, not just the mesh name. Rebaking the same object into a second timeline no longer clears the first timeline's wires. Shared lists are not destructively reused.

## Reproduce validation

```text
python tools/run_blueprint_checks.py "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

The runner launches eleven isolated suites and rejects both nonzero exits and unexpected Python tracebacks. It also normalizes the Python import path and argv for legacy standalone fixtures. Logs are written under `tmp/blueprint_checks/`.

- `test_blueprint_blender.py`: 22 real-Blender regression cases, including every registered custom node type plus native Frame/Reroute cloning, grouping roundtrips, rollback failure injection, nested/shared groups, serialization, references, output ownership and drawing.
- `test_dynamic_mod_titles.py`: English/Chinese titles, node sizing and legacy title migration.
- `test_dynamic_animation_blender.py`: graph conditions, aliases, evaluated-mesh baking, time/shape configuration, independent rebaking, RNA serialization and generated game-specific controls. The obsolete Object-Info-only rebake mock is replaced with real Object List RNA tests.
- Existing time-switch, position-switch, animation-toggle, slot-texture, hash-texture, material application, Naraka shape-key and YYSLS shape-key suites cover related export paths.

For actual GPU-drawn node UI screenshots, run a separate disposable GUI process:

```text
blender --factory-startup --python-exit-code 1 --python tools/test_blueprint_ui.py
```

It renders the reported socket layout and all registered blueprint nodes in English and Chinese, saves screenshots in `tmp/`, then exits. The startup splash is disabled only for that process. Headless tests are not presented as a substitute for this drawing check.

## Release

The release uses the repository's existing `release.ps1` flow after the fixes and version bump are committed. The manual-install archive and updater tag must refer to the same pushed commit. Release verification checks the public release, remote tag/branch commit, archive version, asset size and SHA-256 digest.
