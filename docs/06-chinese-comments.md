# 06 — 已知 BUG 的中文注释（非中文开发者无法理解）

## 严重程度

🟡 **中等** — 项目中有多处用中文标记的"已知 BUG"或"临时方案"，非中文开发者完全看不懂这些关键警告。

## 问题清单

### 致命：m_ini_helper.py:773 的已知 BUG 注释

```python
# XXX 这里由于有BUG，我们固定用$active0来检测激活
```

**影响**：这是 INI 生成逻辑的一个 workaround。如果未来这个 BUG 被"修复"但新人不知道有这个注释，可能引入新的问题。

**建议修复**：
```python
# FIXME: Due to a bug in 3Dmigoto key detection, we hardcode $active0 as the active
# detection key. The correct approach should read from GlobalConfig.active_key_name,
# but that variable is unreliable in certain game contexts. See: (link to issue if exists)
```

### obj_buffer_helper.py:229 的符号处理注释

```python
# XXX 将副切线符号乘以 -1
```

**影响**：这是 3D 图形学中的切线空间处理。注释说明了一个非直觉的操作（副切线符号翻转），但没有解释**为什么**。

**建议修复**：
```python
# FIXME: Binormal sign is flipped (multiplied by -1) to match DirectX convention.
# Blender uses OpenGL-style tangent space where binormal = cross(normal, tangent) * bitangent_sign,
# while DirectX expects binormal = cross(tangent, normal) * bitangent_sign.
# See: https://... (link to relevant documentation)
```

### obj_buffer_helper.py:382 的类型截断注释

```python
# TODO 这里类型截断错了吧
```

**影响**：注释说"类型截断错了吧"但没有给出更多信息——是 `int()` 截断了浮点数？还是 `float32` 精度不够？

**建议修复**：要么确认并修复这个 BUG，要么添加更详细的说明：

```python
# TODO: Float truncation here may lose precision. The current code uses int()
# which floors the value, but round() might be more appropriate. Need to verify
# against original game buffer behavior.
```

### 其他中文注释（信息性，非 BUG）

这些是正常的注释，但非中文开发者无法理解：

| 文件 | 行号 | 内容 |
|------|:----:|------|
| `blueprint/blueprint_node_obj.py` | 多处 | Nico 备注风格的中文注释 |
| `utils/obj_utils.py` | ~460 | `select_obj` 方法的 15 行中文注释说明 |
| `model/blueprint_model.py` | 多处 | 蓝图解析逻辑的中文注释 |
| `common/global_config.py` | 多处 | 路径配置的中文注释 |
| `ui/ui_func_import_ssmt.py` | 多处 | 导入流程的中文注释 |

## 修复方案

### 原则

1. 功能性注释（解释为什么这样做）→ 翻译为英文并补充技术细节
2. 个人风格注释（Nico 备注等）→ 翻译为英文或删除
3. TODO/FIXME 注释 → 必须用英文，这是国际开源项目惯例

### 优先级

| 优先级 | 内容 | 原因 |
|:------:|------|------|
| **高** | `# XXX 这里由于有BUG` → 翻译并加详细说明 | 这是 workaround 标记，不懂中文会踩坑 |
| **中** | `# XXX 将副切线符号乘以 -1` → 翻译并解释图形学原因 | 这是数学操作的业务逻辑解释 |
| **中** | `# TODO 这里类型截断错了吧` → 翻译并确认/修复 | 可能是实际的 BUG |
| **低** | 一般性中文注释 → 翻译为英文 | 不影响功能，但影响可维护性 |

### 批量翻译工具辅助

如果注释量大，可以借助 AI 批量翻译。关键是要确保**技术术语不翻译错**：
- `副切线` → `binormal`
- `切线` → `tangent`
- `法线` → `normal`
- `顶点组` → `vertex group`
- `形态键` → `shape key`

## 验证方法

```bash
# 搜索中文注释
grep -rn "[\u4e00-\u9fff]" --include="*.py" d:\Dev\TheHerta4 | grep "^.*#"
```
