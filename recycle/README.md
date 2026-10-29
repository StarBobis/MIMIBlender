# Removed architectures

This folder keeps the removed source files for recovery. Nothing here is
imported by the add-on. Both architectures are gone from the UI and from the
export flow:

- **MergedComponent** (`component_routing.py`, `component_routing_blender.py`,
  `merged_component.py`, `wwmi_component_routing.md`): merged editing with
  per-component local export, the routing report, and the "Allow Component
  Draw-State Changes" consent switch.
- **UniComponent** (`split_merged_object_by_submesh_vg_ranges` in
  `utils/vertexgroup_utils.py`, `_unico_split_object` in
  `model/blueprint_model.py`): merged import with automatic object splitting.

The only vertex group modes are now **Merged** and **PerComponent**.
A project saved with a removed mode falls back to PerComponent, so its
objects must already be one object per Submesh.

To restore a file, move it back to its original path and re-register the UI
entries. The git history keeps every version as well:

```
git log -- games/wwmi/component_routing.py
git show <commit>:games/wwmi/component_routing.py
```
