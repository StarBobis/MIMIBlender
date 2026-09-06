# 01 - Bare Except Blocks

## Severity

🔴 **Fatal** - silently swallows every exception, including `KeyboardInterrupt`, `SystemExit`, and `MemoryError`, so Blender appears to run "normally" while actually crashing or becoming impossible to interrupt.

## Scope

There are **43 bare `except:` blocks** across the whole project, distributed in the following files:

| File | Count | Lines |
|------|:----:|------|
| `addon_updater.py` | 22 | 176, 223, 275, 292, 304, 327, 376, 403, 452, 463, 475, 486, 673, 754, 760, 817, 827, 838, 845, 890, 1105, 1545 |
| `utils/obj_utils.py` | 13 | 455, 463, 468, 501, 509, 514, 685, 693, 698, 788, 993, 1001, 1006 |
| `blueprint/blueprint_node_obj.py` | 1 | 174 |
| `blueprint/blueprint_node_menu.py` | 2 | 651, 740 |
| `addon_updater_ops.py` | 3 | 549, 629, 653 |

## Typical Problem Examples

### `addon_updater.py` (third-party vendored code)

```python
# line 176
except:
    pass

# line 223
except:
    pass

# line 292
except:
    pass
```

These are densely packed between lines 176-890, mostly in error handling around string parsing and network requests. Because this is third-party code, the fix should be conservative - switching to `except Exception:` is enough; semantics stay unchanged while system-level exceptions are no longer swallowed.

### `utils/obj_utils.py:455` (`apply_mirror_transform` method)

```python
# line 455
try:
    if original_mode == 'EDIT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    obj.scale[0] = -obj.scale[0]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    
finally:
    if original_mode == 'EDIT':
        try:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
        except:                          # <--- line 455
            pass
    
    bpy.ops.object.select_all(action='DESELECT')
    for sel_obj in original_selected:
        if sel_obj:
            try:
                sel_obj.select_set(True)
            except:                      # <--- line 463
                pass
    if original_active:
        try:
            bpy.context.view_layer.objects.active = original_active
        except:                          # <--- line 468
            pass
```

The same pattern recurs in `flip_face_normals` (lines 501/509/514), `_apply_all_modifiers` (lines 685/693/698), and `mesh_triangulate_beauty` (lines 993/1001/1006).

### `blueprint/blueprint_node_obj.py:174`

```python
# line 174
except:
    pass
```

Inside `SSMT_OT_PickObjectModal.modal()`, all errors are silently ignored while attempting to restore the original selection state.

## Fix Plan

### Principles

1. **Never use a bare `except:`**; at minimum use `except Exception:`
2. If a specific exception really is expected, catch it explicitly (e.g. `except ReferenceError:`)
3. If it is unclear what might be raised, at least use `except Exception:` and print the traceback to the log

### Fix Template

```python
# Before the fix
except:
    pass

# After the fix - Option A (the expected exception is known)
except ReferenceError:
    pass

# After the fix - Option B (exception type unknown, but silent failure must be avoided)
except Exception:
    import traceback
    traceback.print_exc()

# After the fix - Option C (confirmed that no exception handling is needed)
except Exception:
    pass
```

### Fix Strategy by File

#### `addon_updater.py` (third-party, conservative)

Full replacement: `except:` -> `except Exception:`

```bash
# Change all 22 bare except: blocks to except Exception:
# They are all inside try blocks for network requests / JSON parsing / file operations
# Switching to except Exception: keeps the semantics unchanged, it only stops
# swallowing KeyboardInterrupt/SystemExit
```

#### `utils/obj_utils.py` (core utilities, needs care)

The bare excepts in this file all sit inside `finally` blocks that restore Blender context state. The exception that may plausibly be raised is `ReferenceError` (the object has already been deleted):

```python
# Before the fix
finally:
    if original_mode == 'EDIT':
        try:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
        except:
            pass
    
    bpy.ops.object.select_all(action='DESELECT')
    for sel_obj in original_selected:
        if sel_obj:
            try:
                sel_obj.select_set(True)
            except:
                pass

# After the fix
finally:
    if original_mode == 'EDIT':
        try:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
        except Exception:
            pass
    
    bpy.ops.object.select_all(action='DESELECT')
    for sel_obj in original_selected:
        if sel_obj:
            try:
                sel_obj.select_set(True)
            except Exception:
                pass
```

Affected obj_utils.py methods (each contains the same finally-restore pattern):
- `apply_mirror_transform` (lines 455/463/468)
- `flip_face_normals` (lines 501/509/514)
- `_apply_all_modifiers` (lines 685/693/698)
- `mesh_triangulate_beauty` (lines 993/1001/1006)

#### `blueprint/blueprint_node_obj.py:174`

```python
# Before the fix
except:
    pass

# After the fix
except Exception:
    pass
```

## How to Verify

1. Search the whole project for `except:` and confirm zero remain:
   ```
   grep -rn "except:" --include="*.py" d:\Dev\MIMIBlender
   ```
2. In Blender, run the complete "one-click import" + "generate mod" flow and confirm there are no exceptions.
3. Manually delete an object, then trigger `apply_mirror_transform` and confirm `ReferenceError` is handled correctly.

## Risks

- `addon_updater.py` is third-party code; after these changes, they must be re-applied when upgrading to a newer upstream version.
- The changes to `obj_utils.py` affect all export flows and need a full regression test.
