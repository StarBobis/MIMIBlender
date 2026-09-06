# 05 - Commented-Out Code Blocks

## Severity

🟡 **Medium** - 90 lines of commented-out method code plus assorted scattered comment blocks leave newcomers puzzled: "Is this dead code or something temporarily disabled? Should I delete it or restore it?"

## Issue List

### Biggest Issue: The 90 Lines of Commented Code in vertexgroup_utils.py

**File**: `utils/vertexgroup_utils.py`  
**Lines**: roughly 55-140  
**Content**: the whole `merge_vertex_groups_with_same_number` method is commented out

```python
# def merge_vertex_groups_with_same_number(obj):
#     '''Merge vertex groups with the same name...'''
#     ...about 90 lines of implementation code...
```

**Recommended handling**:
- If the feature is deprecated -> delete it
- If it might be needed again in the future -> restore it from Git history; do not keep it in the code
- **Do not** keep commented-out code

### Other Commented-Out Debug Code

| File | Lines | Content |
|------|:----:|------|
| `utils/obj_utils.py` | 290 | `# print("Normalize All Weights For: " + obj.name)` |
| `workspace/ssmt_workspace.py` | 805 | `# print(used_component_count_list)` |
| `common/obj_buffer_helper.py` | 229 | `# XXX Multiply the binormal sign by -1` |
| `common/obj_buffer_helper.py` | 382 | `# TODO This type truncation looks wrong` |
| `addon_updater_ops.py` | 1185-1236 | several commented-out code blocks (beta-label check, platform detection, etc.) |

### Commented-Out Imports

| File | Lines | Content |
|------|:----:|------|
| `utils/collection_utils.py` | comment lines | `# import ...` - an unused import commented out instead of deleted |

### Commented-Out Legacy Code Paths Never Cleaned Up

| File | Lines | Content |
|------|:----:|------|
| `sword/ui_panel_sword.py` | comment lines | `# bpy.context.view_layer...` - a superseded old implementation kept as a comment |
| `common/m_ini_helper.py` | comment lines | several `# [old approach]...` style legacy-implementation comments |

## Fix Plan

### Principles

1. **Commented-out code has no value in the Git era** - Git history can recover it at any time
2. If you really need to flag "there is a known problem here", use `# TODO:` or `# FIXME:` and state the reason
3. Debug `# print(...)` statements: delete them outright or replace them with `logging.debug()`

### Item-by-Item Handling

#### The 90 Commented-Out Lines in vertexgroup_utils.py

**Approach**: delete outright. Git history keeps them forever.

```python
# Before the fix
# def merge_vertex_groups_with_same_number(obj):
#     '''Merge vertex groups with the same name...'''
#     ...about 90 lines...

# After the fix
# (delete all 90 lines of commented code)
```

After the deletion the file shrinks from ~230 lines to ~140, and readability improves substantially.

#### The Commented Blocks in addon_updater_ops.py

**Approach**: delete outright. These are default comments from the Blender updater template and are not actually used.

```python
# Before the fix (lines 1185-1236)
# Delete the following commented blocks:
#     # if not updater.update_ready:
#     #     ...
#     # if updater.invalid_updater:
#     #     ...

# After the fix
# (delete all commented-out code blocks)
```

#### Commented-Out Imports

```python
# Before the fix
# import os

# After the fix
# (delete that line)
```

#### The TODO Comment in obj_buffer_helper.py

```python
# Before the fix
# TODO This type truncation looks wrong

# After the fix - convert it to the proper format
# FIXME: Float truncation may cause precision loss; need to confirm whether it
# should be changed to round()
```

## How to Verify

1. Search the whole project for commented-out-code patterns:
```bash
grep -rn "^#\s*def " --include="*.py" d:\Dev\MIMIBlender
grep -rn "^#\s*if " --include="*.py" d:\Dev\MIMIBlender
grep -rn "^#\s*import " --include="*.py" d:\Dev\MIMIBlender
```
2. Search for commented-out debug output with `# print(`:
```bash
grep -rn "# print(" --include="*.py" d:\Dev\MIMIBlender
```

## Risks

- **Low**: deleting commented code does not affect runtime behavior
- The only risk: the commented-out code may be the draft of someone's ongoing development work - but that situation belongs on a Git branch, not in comments
