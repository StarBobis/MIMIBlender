# 05 — 被注释掉的代码块

## 严重程度

🟡 **中等** — 90 行被注释掉的方法和其他零散注释块让新人困惑："这是废弃代码还是临时禁用的？该删还是该恢复？"

## 问题清单

### 最大问题：vertexgroup_utils.py 中 90 行注释代码

**文件**：`utils/vertexgroup_utils.py`  
**行号**：约 55-140  
**内容**：`merge_vertex_groups_with_same_number` 方法整段被注释

```python
# def merge_vertex_groups_with_same_number(obj):
#     '''合并同名顶点组...'''
#     ...约 90 行实现代码...
```

**处理建议**：
- 如果功能已废弃 → 删除
- 如果将来可能恢复 → 从 Git 历史恢复，不保留在代码中
- **不要**保留注释掉的代码

### 其他注释掉的调试代码

| 文件 | 行号 | 内容 |
|------|:----:|------|
| `utils/obj_utils.py` | 290 | `# print("Normalize All Weights For: " + obj.name)` |
| `workspace/ssmt_workspace.py` | 805 | `# print(used_component_count_list)` |
| `common/obj_buffer_helper.py` | 229 | `# XXX 将副切线符号乘以 -1` |
| `common/obj_buffer_helper.py` | 382 | `# TODO 这里类型截断错了吧` |
| `addon_updater_ops.py` | 1185-1236 | 多个注释掉的代码块（beta 标签检查、平台检测等） |

### 注释掉的 import

| 文件 | 行号 | 内容 |
|------|:----:|------|
| `utils/collection_utils.py` | 注释行 | `# import ...` — 未使用的 import 被注释而非删除 |

### 注释掉但未清理的旧代码路径

| 文件 | 行号 | 内容 |
|------|:----:|------|
| `sword/ui_panel_sword.py` | 注释行 | `# bpy.context.view_layer...` — 被替代的旧实现保留为注释 |
| `common/m_ini_helper.py` | 注释行 | 多处 `# [old approach]...` 风格的旧实现注释 |

## 修复方案

### 原则

1. **注释掉的代码在 Git 时代没有保留价值** — Git 历史可以随时找回
2. 如果确实需要标记"这里有个已知问题"，用 `# TODO:` 或 `# FIXME:` 并说明原因
3. 调试用的 `# print(...)` 直接删除或用 `logging.debug()` 替代

### 逐项处理

#### vertexgroup_utils.py 的 90 行注释代码

**方案**：直接删除。Git 历史中永久保留。

```python
# 修复前
# def merge_vertex_groups_with_same_number(obj):
#     '''合并同名顶点组...'''
#     ...约 90 行...

# 修复后
# （删除全部 90 行注释代码）
```

删除后文件从 ~230 行缩减到 ~140 行，可读性大幅提升。

#### addon_updater_ops.py 的注释块

**方案**：直接删除。这些来自 Blender 更新器模板的默认注释，实际未被使用。

```python
# 修复前（1185-1236 行）
# 删除以下注释块：
#     # if not updater.update_ready:
#     #     ...
#     # if updater.invalid_updater:
#     #     ...

# 修复后
# （删除所有注释掉的代码块）
```

#### 注释掉的 import

```python
# 修复前
# import os

# 修复后
# （删除该行）
```

#### obj_buffer_helper.py 的 TODO 注释

```python
# 修复前
# TODO 这里类型截断错了吧

# 修复后 — 转为正确格式
# FIXME: 浮点数类型截断可能导致精度丢失，需要确认是否需要改为 round()
```

## 验证方法

1. 全局搜索注释掉的代码模式：
```bash
grep -rn "^#\s*def " --include="*.py" d:\Dev\TheHerta4
grep -rn "^#\s*if " --include="*.py" d:\Dev\TheHerta4
grep -rn "^#\s*import " --include="*.py" d:\Dev\TheHerta4
```
2. 搜索 `# print(` 注释掉的调试输出：
```bash
grep -rn "# print(" --include="*.py" d:\Dev\TheHerta4
```

## 风险

- **低**：删除注释代码不影响运行时行为
- 唯一风险：如果注释掉的代码是某人正在进行的开发工作的草稿——但这种情况应该用 Git branch，不应该用注释
