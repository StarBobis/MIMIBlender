# Fix: Textures Not Read Correctly

## Problem Description

While using the add-on, if the user modifies a material in the Shader Editor, for example:
- Replaces a texture node.
- Previews an intermediate node with Node Wrangler (Ctrl+Shift+Click).
- Disconnects some node links.

After clicking "Update Material List", the following anomalies may appear:
1. **Wrong texture size**: the detected texture size becomes 32x32 pixels (the size of Blender's default empty texture or a Viewer node placeholder).
2. **Merge failure**: these materials are ignored during merging, or the merge produces incorrect colors.

## Root Cause

### 1. Blender's material output mechanism
A material can have several output nodes.
- **Normal output**: `Material Output`, used for final rendering.
- **Preview output**: when you preview with Node Wrangler, it creates a temporary `Viewer Output` node.

### 2. Flaw in the old code
The old code's logic for finding "which node is the final output" was too naive:

```python
# old logic
for node in nodes:
    if node.bl_idname == "ShaderNodeOutputMaterial":
        return node  # returns the first one it finds!
```

It simply iterated over all nodes and returned the **first** output node it found.
- If you used Node Wrangler, the material has two output nodes.
- The code may wrongly pick the `Viewer Output` (preview node) or a stale node whose links were disconnected.
- If it picks a disconnected node, the add-on cannot trace back to the textures feeding it, so reading fails (falling back to the default 32x32 placeholder).

## The Fix

We changed the `_find_output_node` function in `utils/materials.py` to be smarter. It now looks for the correct node by priority:

### New lookup priority

1. **Priority 1 (best)**: an output node that is both **Active** and **Connected**.
    * *This is the ideal case: the output the user currently has selected and that is actually in effect.*

2. **Priority 2 (second best)**: any output node that is **connected**.
    * *If the active node is not connected (for example, the user accidentally disconnected it), we take another connected node so data can still be read.*

3. **Priority 3 (fallback)**: the **currently active** output node (even if not connected).
    * *If no node is connected, at least return the one the user selected.*

4. **Priority 4 (last resort)**: any output node at all.

### Code comparison

**Before:**

```python
def _find_output_node(nodes):
    for node in nodes:
        if node.bl_idname == "ShaderNodeOutputMaterial":
            return node  # returns any output node, connected or not
    return None
```

**After:**

```python
def _find_output_node(nodes):
    # 1. First look for a node that is both active and connected
    for node in nodes:
        if (node.bl_idname == "ShaderNodeOutputMaterial" and
            node.is_active_output and
            node.inputs[0].is_linked):
            return node

    # 2. Then look for any node that is connected
    for node in nodes:
        if (node.bl_idname == "ShaderNodeOutputMaterial" and
            node.inputs[0].is_linked):
            return node

    # ... (further fallback logic below)
```

## Summary

This fix ensures the add-on always finds the material output node that is **actually in effect**, so it can follow the chain to the correct texture files, resolving textures being detected as 32x32 or being dropped during merging.
