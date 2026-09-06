# 06 - Known-BUG Comments Written in Chinese (Incomprehensible to Non-Chinese Developers)

## Severity

🟡 **Medium** - several places in the project mark "known bugs" or "temporary workarounds" in Chinese; developers who do not read Chinese completely miss these critical warnings.

## Issue List

### Critical: The Known-Bug Comment at m_ini_helper.py:773

```python
# XXX Because of a bug here, we hardcode $active0 for activation detection
```

**Impact**: This is a workaround in the INI generation logic. If the underlying bug ever gets "fixed" while a newcomer has no idea this comment exists, new problems may be introduced.

**Suggested fix**:
```python
# FIXME: Due to a bug in 3Dmigoto key detection, we hardcode $active0 as the active
# detection key. The correct approach should read from GlobalConfig.active_key_name,
# but that variable is unreliable in certain game contexts. See: (link to issue if exists)
```

### The Sign-Handling Comment at obj_buffer_helper.py:229

```python
# XXX Multiply the binormal sign by -1
```

**Impact**: This is tangent-space handling in 3D graphics. The comment describes a non-intuitive operation (flipping the binormal sign) but never explains **why**.

**Suggested fix**:
```python
# FIXME: Binormal sign is flipped (multiplied by -1) to match DirectX convention.
# Blender uses OpenGL-style tangent space where binormal = cross(normal, tangent) * bitangent_sign,
# while DirectX expects binormal = cross(tangent, normal) * bitangent_sign.
# See: https://... (link to relevant documentation)
```

### The Type-Truncation Comment at obj_buffer_helper.py:382

```python
# TODO This type truncation looks wrong
```

**Impact**: The comment says "the type truncation looks wrong" but gives no further detail - is `int()` truncating a float? Or is `float32` precision insufficient?

**Suggested fix**: either confirm and fix the bug, or add a more detailed explanation:

```python
# TODO: Float truncation here may lose precision. The current code uses int()
# which floors the value, but round() might be more appropriate. Need to verify
# against original game buffer behavior.
```

### Other Chinese Comments (Informational, Not Bugs)

These are ordinary comments, but developers who do not read Chinese cannot understand them:

| File | Location | Content |
|------|:----:|------|
| `blueprint/blueprint_node_obj.py` | several | Chinese comments in Nico's personal style |
| `utils/obj_utils.py` | ~460 | a 15-line Chinese explanatory comment block for the `select_obj` method |
| `model/blueprint_model.py` | several | Chinese comments on blueprint-parsing logic |
| `common/global_config.py` | several | Chinese comments on path configuration |
| `ui/ui_func_import_ssmt.py` | several | Chinese comments on the import flow |

## Fix Plan

### Principles

1. Functional comments (explaining why something is done this way) -> translate into English and add technical detail
2. Personal-style comments (Nico's remarks, etc.) -> translate into English or remove
3. TODO/FIXME comments -> must be in English; that is the convention for international open-source projects

### Priorities

| Priority | Item | Reason |
|:------:|------|------|
| **High** | `# XXX Because of a bug here, we hardcode $active0...` -> translate and expand with detail | it marks a workaround; anyone who cannot read Chinese will trip over it |
| **Medium** | `# XXX Multiply the binormal sign by -1` -> translate and explain the graphics rationale | it explains the business logic behind a mathematical operation |
| **Medium** | `# TODO This type truncation looks wrong` -> translate, then confirm/fix | it may be a real bug |
| **Low** | general Chinese comments -> translate into English | does not affect functionality, but affects maintainability |

### Machine-Assisted Bulk Translation

If the comment volume is large, AI-assisted bulk translation can help. The key is making sure **technical terms are not mistranslated**; use these canonical English terms:
- `binormal`
- `tangent`
- `normal`
- `vertex group`
- `shape key`

## How to Verify

```bash
# Search for Chinese comments
grep -rn "[\u4e00-\u9fff]" --include="*.py" d:\Dev\MIMIBlender | grep "^.*#"
```
