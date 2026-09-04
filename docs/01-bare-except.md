# 01 — 裸 except: 块（Bare Except）

## 严重程度

🔴 **致命** — 会静默吞掉所有异常，包括 `KeyboardInterrupt`、`SystemExit`、`MemoryError`，导致 Blender 表面"正常"但实际崩溃或无法中断。

## 影响范围

全项目共 **43 个裸 `except:` 块**，分布在以下文件：

| 文件 | 数量 | 行号 |
|------|:----:|------|
| `addon_updater.py` | 22 | 176, 223, 275, 292, 304, 327, 376, 403, 452, 463, 475, 486, 673, 754, 760, 817, 827, 838, 845, 890, 1105, 1545 |
| `utils/obj_utils.py` | 13 | 455, 463, 468, 501, 509, 514, 685, 693, 698, 788, 993, 1001, 1006 |
| `blueprint/blueprint_node_obj.py` | 1 | 174 |
| `blueprint/blueprint_node_menu.py` | 2 | 651, 740 |
| `addon_updater_ops.py` | 3 | 549, 629, 653 |

## 典型问题示例

### `addon_updater.py`（第三方 vendored 代码）

```python
# 行 176
except:
    pass

# 行 223
except:
    pass

# 行 292
except:
    pass
```

这些在第 176-890 行之间密集分布，大多在字符串解析/网络请求的错误处理中。由于是第三方代码，修复策略应保守——改为 `except Exception:` 即可，不改变语义但避免吞掉系统级异常。

### `utils/obj_utils.py:455`（`apply_mirror_transform` 方法）

```python
# 行 455
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
        except:                          # <--- 行 455
            pass
    
    bpy.ops.object.select_all(action='DESELECT')
    for sel_obj in original_selected:
        if sel_obj:
            try:
                sel_obj.select_set(True)
            except:                      # <--- 行 463
                pass
    if original_active:
        try:
            bpy.context.view_layer.objects.active = original_active
        except:                          # <--- 行 468
            pass
```

同样的模式在 `flip_face_normals`（行 501/509/514）、`_apply_all_modifiers`（行 685/693/698）、`mesh_triangulate_beauty`（行 993/1001/1006）中重复出现。

### `blueprint/blueprint_node_obj.py:174`

```python
# 行 174
except:
    pass
```

在 `SSMT_OT_PickObjectModal.modal()` 中，尝试恢复原始选中状态时静默忽略所有错误。

## 修复方案

### 原则

1. **永远不要用裸 `except:`**，最低用 `except Exception:`
2. 如果确实预期某个特定异常，显式捕获它（如 `except ReferenceError:`）
3. 如果无法确定可能抛什么异常，至少用 `except Exception:` 并打印 traceback 到日志

### 修复模板

```python
# 修复前
except:
    pass

# 修复后 — 方案 A（知道预期异常）
except ReferenceError:
    pass

# 修复后 — 方案 B（不确定异常类型，但要避免静默失败）
except Exception:
    import traceback
    traceback.print_exc()

# 修复后 — 方案 C（确定无需处理任何异常）
except Exception:
    pass
```

### 分文件修复策略

#### `addon_updater.py`（第三方，保守）

全量替换：`except:` → `except Exception:`

```bash
# 22 处裸 except: 全部改为 except Exception:
# 这些都在网络请求/JSON解析/文件操作的 try 块中
# 改为 except Exception: 语义不变，只是不再吞 KeyboardInterrupt/SystemExit
```

#### `utils/obj_utils.py`（核心工具，需仔细）

该文件中的裸 except 都在 `finally` 块中，用于恢复 Blender 上下文状态。预期可能抛 `ReferenceError`（对象已被删除）：

```python
# 修复前
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

# 修复后
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

受影响的 obj_utils.py 方法（每个都包含相同的 finally 恢复模式）：
- `apply_mirror_transform`（行 455/463/468）
- `flip_face_normals`（行 501/509/514）
- `_apply_all_modifiers`（行 685/693/698）
- `mesh_triangulate_beauty`（行 993/1001/1006）

#### `blueprint/blueprint_node_obj.py:174`

```python
# 修复前
except:
    pass

# 修复后
except Exception:
    pass
```

## 验证方法

1. 全局搜索 `except:` 确保零残留：
   ```
   grep -rn "except:" --include="*.py" d:\Dev\TheHerta4
   ```
2. 在 Blender 中执行「一键导入」+「生成 Mod」完整流程，确认无异常
3. 手动删除一个物体后触发 `apply_mirror_transform`，确认 `ReferenceError` 被正确处理

## 风险

- `addon_updater.py` 是第三方代码，改动后升级上游版本时需要重新应用
- `obj_utils.py` 的修改影响所有导出流程，需要全量回归测试
