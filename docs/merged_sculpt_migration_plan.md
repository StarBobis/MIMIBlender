# 多物体合并雕刻 · 通用化迁移方案

> 来源功能：WWMI-Tools（https://github.com/SpectrumQT/WWMI-Tools）的
> "Create Merged Object / Apply Merged Object Sculpt"。
> 目标：把它迁移为 MIMIBlender 的通用功能 —— 任意 N 个网格物体，无命名要求、
> 无集合要求、无变换要求，一键合并雕刻、一键写回。

---

## 实现安全修订（以本节为准）

以下修订覆盖后文初始方案中的对应策略：

- 来源身份仅使用完整会话 UID，名字只用于错误提示。删除来源后创建同名对象，或手动清除 UID，都必须中止应用，不能自动按名字回退。
- 一个来源只能参与一个未结束的会话；独立来源组仍支持多会话并存。
- 创建和应用均拒绝共享网格，请先在 Blender 中将网格设为单用户。不会自动改变关联副本关系，也不会修改未选中实例。
- 使用 `shape_keys.reference_key` 读写基础形态键，支持基础键重命名。开启增量传播时更新每个来源的全部形态键。
- 应用前准备全部写入数据和备份，检查可编辑性与共享数据。发生意外写入错误时恢复已尝试写入的坐标，保留会话。
- 无选中目标时，会话查找仅扫描当前场景。丢弃时清除所有精确匹配当前会话的 UID，包括重复来源，不清除其他会话标记。
- 回归测试新增以上边界与模拟写入失败回滚；真实 GUI 笔刷与撤销仍需交互验收。

## 0. 结论速览

**可行，且迁移成本低于预期。** 原因：

1. WWMI-Tools 的核心机制只有两个函数（约 100 行），原理清晰，不依赖其导出管线。
2. MIMIBlender 的 [ObjUtils](../utils/obj_utils.py) 已经具备全部基础设施
   （`copy_object`、`join_objects` 逐个 join、`OpenObject` 上下文管理器、
   `set_custom_property`），这些代码当年就是从 WWMI 移植并加固过的。
3. UI / 注册 / i18n 都有现成模式（[ui_panel_model.py](../ui/ui_panel_model.py)、
   `I18nOperator`、`@translatable`、`tr()`），照抄结构即可。

**工作量估算**（含测试）：核心模块约 250 行，UI 模块约 150 行，测试约 150 行，
分 3 个阶段提交，单人 1~2 天可完成。

---

## 1. WWMI-Tools 原实现解析

### 1.1 功能与入口

位置：`wwmi-tools/migoto_io/blender_tools/meshes.py`，由
`addon/modules/toolbox/ui.py` 中两个操作符触发：

| 按钮 | 函数 | 作用 |
|---|---|---|
| Create Merged Object | `create_merged_object(context)` | 把选中的多个物体复制并 join 成一个可雕刻物体 |
| Apply Merged Object Sculpt | `transfer_position_data(context, apply_deltas_to_shapekeys)` | 把雕刻后的顶点位置按记录切回各原始物体 |

### 1.2 合并（create_merged_object）的机制

```
选中物体 A(100v) B(50v) C(30v)
  │  逐个 copy_object() → TEMP_A, TEMP_B, TEMP_C
  │  逐个 bpy.ops.object.join()（每次只 join 一个，保证顶点追加顺序 = 列表顺序）
  ▼
MERGED_OBJECT（180 个顶点，[0:100]=A, [100:150]=B, [150:180]=C）
  └─ 自定义属性 "WWMI:MergedObjectComponents" = {"A":100, "B":50, "C":30}（JSON）
```

关键点：**顶点顺序即映射关系**。不需要顶点匹配、不需要最近点搜索，
合并时记录每个来源物体的顶点数，写回时按顺序切片即可，O(N) 且零误差。

### 1.3 写回（transfer_position_data）的机制

1. 找到合并物体（雕刻模式下的活动物体，或选中物体）。
2. 读取 JSON，逐个校验来源物体当前顶点数与记录一致（防止用户改了拓扑）。
3. 读取合并物体的顶点坐标：
   - 无形态键 → 读 `mesh.vertices` 的 `undeformed_co`（不受修改器影响的原始坐标）；
   - 有形态键 → 读 Basis 形态键的 `co`（雕刻写入的位置）。
4. 按记录的顶点数切片，逐个写回来源物体的 mesh 顶点或 Basis 形态键。
5. 可选：把 (新Basis − 旧Basis) 的差值叠加到来源物体的每一个形态键上。

### 1.4 为什么顶点顺序不会乱

WWMI（以及 MIMIBlender 的 `ObjUtils.join_objects`）用的是
**循环内逐个 `bpy.ops.object.join()`**：每轮只选中一个待并入物体执行 join，
Blender 会把它的顶点追加到当前活动物体末尾。因此顺序严格等于列表顺序，
与场景中物体的内部存储顺序无关。这是整个方案成立的地基，迁移时必须保留。

---

## 2. 原实现的限制清单（本次要打破的）

| # | 限制 | 影响 | 通用化处理 |
|---|---|---|---|
| 1 | 以**物体名**作为映射键 | 雕刻中途重命名来源物体 → 写回失败或写错物体 | 改用**会话 UID** 作为主键，名字只做回退 |
| 2 | 只支持**一个** `MERGED_OBJECT` | 场景里同时只能有一组在雕刻 | 合并物体带会话 ID，**多组并存** |
| 3 | 隐含要求**变换一致** | join 会把网格烘进第一个物体的局部空间；若来源物体各自有位移/旋转/缩放，写回位置会错 | 合并时记录每个来源的**相对矩阵**，写回时逆变换 |
| 4 | 形态键处理粗糙 | join 时各物体形态键不一致会丢键；写回只处理 Basis | 逐物体记录形态键清单，不一致时明确警告，差值只传播到共有键 |
| 5 | 顶点数变化直接报错 | 用户开了 Dyntopo / Remesh 后白雕 | 保留硬性限制（原理决定），但提供**预检操作符**+ 更友好的报错文案 |
| 6 | 无**取消/丢弃**入口 | 不想写了只能手动删物体、手动清理属性 | 新增 Discard 操作符，自动清理痕迹 |
| 7 | 来源被删除 → 未捕获的 KeyError | 直接抛栈 | 预检列出缺失物体，由用户选择跳过或中止 |
| 8 | 修改器行为不明确 | 带修改器的物体 join 后行为依赖活动物体 | 合并时可选"清空副本修改器"（默认开） |
| 9 | 依赖 WWMI 的 Toolbox 面板 | 无法独立使用 | 独立面板 + 右键菜单入口 |

> 说明：WWMI 的 `object_merger.py` 里那套 `component` 命名正则、
> `TEMP_` 前缀约定、集合扫描规则属于**导出管线**，与雕刻功能无关，
> 本次不迁移，从根源上消灭"命名限制"。

---

## 3. 通用化设计

### 3.1 数据 Schema v2（存在合并物体的自定义属性里）

属性名：`MIMI:MergedSculptSources`（JSON 字符串）

```json
{
  "version": 2,
  "session": "9f2c1e7a4b8d4f6e9a0c1d2e3f4a5b6c",
  "sources": [
    {
      "uid": "a1b2c3d4",
      "name": "Body",
      "vertex_count": 10234,
      "inv_rel_matrix": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
      "world_matrix":  [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
      "shape_keys": ["Basis", "deform_001"]
    }
  ]
}
```

- `session`：本组合并的全局唯一 ID，支持多组并存。
- `uid`：来源物体身份（重命名不丢）。合并时把 `"<session>:<uid>"` 写进
  来源物体的 `MIMI:MergedSculptUID` 自定义属性；写回/丢弃后清除。
- `inv_rel_matrix`：`M_source⁻¹ @ M_merged`（合并时刻），
  用于把合并空间的坐标变换回来源局部空间。
- `world_matrix`：来源物体合并时刻的世界矩阵，仅用于写回前校验
  "来源物体是否被移动过"（动了就警告，不阻断）。

### 3.2 身份解析顺序（写回时）

```
1. 按 uid 扫描 bpy.data.objects，匹配 MIMI:MergedSculptUID == "<session>:<uid>"
2. 找不到 → 按记录的 name 回退查找（兼容手动清了属性的情况）
3. 还找不到 → 记入 missing 列表，交由用户决定 skip / abort
4. 找到多个（用户复制过来源物体）→ 报错并指出名字，要求人工处理
```

### 3.3 变换矩阵处理

- 合并：记录 `inv_rel = M_src_world.inverted() @ M_merged_world`。
  join 后合并空间 = 第一个副本的局部空间，因此对每个来源有
  `v_merged = inv_rel⁻¹ @ v_src`，写回时 `v_src = inv_rel @ v_merged`。
- 全部变换都是单位矩阵时（3Dmigoto 导入物的常态），`inv_rel` 为单位阵，
  零开销，行为与 WWMI 完全一致 —— **向后兼容 WWMI 的工作流**。
- 写回前用 `world_matrix` 做 epsilon 校验，不一致给出
  "物体在雕刻期间被移动过"的警告（可由用户选择继续）。

### 3.4 形态键策略

| 场景 | 行为 |
|---|---|
| 合并物体无形态键 | 读 mesh 顶点 `undeformed_co`，写回各来源 mesh 顶点 |
| 合并物体有形态键 | 读 Basis `co`，写回各来源 Basis |
| `apply_deltas_to_shapekeys=True` | 差值 = 新Basis − 旧Basis，只叠加到**该来源与合并物体共有的**形态键 |
| 各来源形态键清单不一致 | 合并时 join 会丢键 → 立即弹警告列出差异，由用户决定是否继续 |

### 3.5 操作符清单

| bl_idname | 功能 |
|---|---|
| `mimi.merged_sculpt_create` | 选中 N(≥2) 个网格物体 → 生成合并物体并进入雕刻模式 |
| `mimi.merged_sculpt_apply` | 把雕刻结果写回所有来源物体（可选：传播到形态键） |
| `mimi.merged_sculpt_discard` | 丢弃合并物体，清理来源物体上的 UID 痕迹 |
| `mimi.merged_sculpt_validate` | 预检：顶点数、来源存在性、变换一致性，输出报告 |

合并物体命名：`MSCU_<session前8位>`（小写前缀，符合项目命名习惯）。

### 3.6 硬性限制（原理决定，无法消除，需文档化）

1. **禁止改变顶点数**：不能开 Dyntopo、不能 Remesh、不能用雕刻版
   "按距离合并"。写回前会校验 `sum(vertex_count) == len(merged.vertices)`。
2. **只迁移顶点位置**：遮罩、面组(Face Sets)、颜色不会写回。
3. 跨物体接缝不会被焊接（各物体仍是独立网格，法线在接缝处可能不连续）。

---

## 4. MIMIBlender 集成方案

### 4.1 文件改动清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `utils/merged_sculpt_utils.py` | 新增 | 核心逻辑类 `MergedSculptUtils`（约 250 行） |
| `ui/ui_panel_merged_sculpt.py` | 新增 | 4 个操作符 + 面板区段 + 右键菜单挂载（约 150 行） |
| `__init__.py` | 修改 | `_register_steps()` 增加一步 `yield ui_panel_merged_sculpt.register`；`unregister()` 逆序加一步 |
| `i18n/zh_cn.json`（或对应语言表） | 修改 | 新增按钮/报错文案的中文翻译 |
| `tools/test_merged_sculpt_blender.py` | 新增 | Blender 内自动化测试（参考现有 `tools/test_merged_component_blender.py` 的运行方式） |
| `docs/merged_sculpt_migration_plan.md` | 新增 | 本文档 |

零改动复用：`ObjUtils`（copy_object / join_objects / OpenObject /
set_custom_property）、`ShapeKeyUtils`。

### 4.2 核心模块骨架（`utils/merged_sculpt_utils.py`）

```python
"""
Generic N-object merged sculpting.

Merge any number of mesh objects into one temporary sculpt target, then
write the sculpted vertex positions back to each source object. No naming
convention, no collection requirement, no transform requirement.

Idea ported from WWMI-Tools (GPL-3.0) create_merged_object /
transfer_position_data, re-implemented with session UIDs, per-source
relative transforms and multi-session support.
"""

import json
import uuid

import numpy

import bpy

from .obj_utils import ObjUtils, OpenObject


# Custom property keys. Keep them namespaced to avoid collisions with
# 3Dmigoto metadata ("3DMigoto:*") or WWMI properties ("WWMI:*").
PROP_SOURCES = "MIMI:MergedSculptSources"   # on the merged object
PROP_SOURCE_UID = "MIMI:MergedSculptUID"    # on each source object

# Name prefix of generated merged objects, e.g. "MSCU_9f2c1e7a".
MERGED_NAME_PREFIX = "mscu_"


class MergedSculptUtils:

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    @classmethod
    def create_merged_object(cls, context, clear_modifiers=True):
        """Duplicate the selected mesh objects and join the copies into
        one sculpt target. Returns the merged object."""
        sources = [obj for obj in context.selected_objects
                   if obj.type == 'MESH']
        if len(sources) < 2:
            raise ValueError("Select at least 2 mesh objects to merge.")

        session = uuid.uuid4().hex

        # Record everything needed to slice and transform the data back.
        records = []
        for obj in sources:
            # The inverse of (merged_world^-1 @ source_world) converts
            # merged-space coordinates back to the source's local space.
            # Recorded before the join because the join bakes transforms.
            m_merged_world = sources[0].matrix_world.copy()
            inv_rel = obj.matrix_world.inverted() @ m_merged_world
            records.append({
                "uid": uuid.uuid4().hex[:8],
                "name": obj.name,
                "vertex_count": len(obj.data.vertices),
                "inv_rel_matrix": cls._matrix_to_list(inv_rel),
                "world_matrix": cls._matrix_to_list(obj.matrix_world),
                "shape_keys": cls._shape_key_names(obj),
            })

        # Warn (do not block) when shape key sets differ: Blender's join
        # drops keys that are missing on the active object.
        cls._warn_on_shape_key_mismatch(sources)

        # Stamp each source so renames during sculpting stay harmless.
        for obj, record in zip(sources, records):
            obj[PROP_SOURCE_UID] = session + ":" + record["uid"]

        # Duplicate into the same collection, then join one-by-one so the
        # vertex append order strictly matches `records` (the foundation
        # of the whole slice-back mechanism).
        target_collection = sources[0].users_collection[0]
        copies = []
        for obj in sources:
            copy_obj = ObjUtils.copy_object(
                context, obj, name="temp_mscu_" + obj.name,
                collection=target_collection)
            if clear_modifiers:
                for modifier in list(copy_obj.modifiers):
                    copy_obj.modifiers.remove(modifier)
            copies.append(copy_obj)
        ObjUtils.join_objects(context, copies)

        merged_obj = copies[0]
        merged_obj.name = MERGED_NAME_PREFIX + session[:8]
        merged_obj[PROP_SOURCES] = json.dumps({
            "version": 2, "session": session, "sources": records,
        })

        # Sculpt strokes write into the active shape key; make sure Basis
        # is active, otherwise positions silently land in mesh.vertices.
        cls._activate_basis_key(merged_obj)

        ObjUtils.select_obj(merged_obj)
        return merged_obj

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    @classmethod
    def apply_merged_sculpt(cls, context, apply_deltas_to_shapekeys=False):
        """Slice the merged object's positions back into every source."""
        merged_obj = cls._find_merged_object(context)
        payload = json.loads(merged_obj[PROP_SOURCES])

        # Pre-flight: abort early with a readable message instead of a
        # half-written scene. Returns (resolved, missing).
        resolved, missing = cls._resolve_sources(payload)
        if missing:
            raise ValueError("Missing source objects: " + ", ".join(missing))

        expected = sum(rec["vertex_count"] for rec in payload["sources"])
        actual = len(merged_obj.data.vertices)
        if actual != expected:
            raise ValueError(
                "Vertex count changed (merged: %d, expected: %d). "
                "Dyntopo/remesh is not supported." % (actual, expected))

        # Read sculpted positions: Basis key when present, else the
        # undeformed mesh coordinates (immune to leftover modifiers).
        merged_positions, old_basis = cls._read_merged_positions(
            context, merged_obj)

        offset = 0
        for obj, record in resolved:
            count = record["vertex_count"]
            chunk = merged_positions[offset:offset + count]

            # Convert merged-space positions into the source's local
            # space. Identity matrix (the common 3Dmigoto case) is a no-op.
            inv_rel = cls._list_to_matrix(record["inv_rel_matrix"])
            local_positions = cls._transform_positions(chunk, inv_rel)

            cls._write_source_positions(
                obj, local_positions,
                old_basis[offset:offset + count],
                apply_deltas_to_shapekeys, record["shape_keys"])
            offset += count

        cls._cleanup_sources(resolved)
        return len(resolved)

    # ------------------------------------------------------------------
    # Discard / validate helpers
    # ------------------------------------------------------------------
    @classmethod
    def discard_merged_sculpt(cls, context):
        """Delete the merged object and remove UID stamps from sources."""
        merged_obj = cls._find_merged_object(context)
        payload = json.loads(merged_obj[PROP_SOURCES])
        resolved, _ = cls._resolve_sources(payload)
        cls._cleanup_sources(resolved)
        mesh = merged_obj.data
        bpy.data.objects.remove(merged_obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    @classmethod
    def validate_merged_sculpt(cls, context):
        """Read-only health check. Returns a list of human-readable issues."""
        issues = []
        merged_obj = cls._find_merged_object(context)
        payload = json.loads(merged_obj[PROP_SOURCES])
        resolved, missing = cls._resolve_sources(payload)
        for name in missing:
            issues.append("missing source: " + name)
        for obj, record in resolved:
            if len(obj.data.vertices) != record["vertex_count"]:
                issues.append("vertex count changed: " + record["name"])
            if not cls._matrix_close(obj.matrix_world,
                                     record["world_matrix"]):
                issues.append("moved during sculpting: " + record["name"])
        expected = sum(r["vertex_count"] for r in payload["sources"])
        if len(merged_obj.data.vertices) != expected:
            issues.append("merged object was remeshed")
        return issues
```

私有辅助（`_read_merged_positions` / `_write_source_positions` /
`_transform_positions` / `_matrix_to_list` / `_list_to_matrix` /
`_matrix_close` / `_resolve_sources` / `_find_merged_object` /
`_activate_basis_key` / `_shape_key_names` / `_warn_on_shape_key_mismatch` /
`_cleanup_sources`）全部用 `foreach_get`/`foreach_set` + numpy 批量读写，
单个 1 万顶点的物体写回耗时在毫秒级。

### 4.3 UI 与注册（`ui/ui_panel_merged_sculpt.py`）

- 面板挂在 `MIMITools` 分类下，紧跟现有 "Model Processing Panel" 之后，
  `bl_options = {'DEFAULT_CLOSED'}` 保持一致风格。
- 同时把 4 个操作符挂进现有右键菜单 `MIMI_MT_object_3dmigoto`。
- 操作符继承 `I18nOperator`，面板类加 `@translatable`，文案走 `tr()`。
- **Blender 5.2 注意**：`Panel.draw()` 里禁止写 ID 属性
  （`ui_panel_basic.py` 已有教训），合并参数（如"传播到形态键"开关）
  放在 `bpy.types.Scene` 上、由操作符读取；面板上只 `layout.prop` 展示。
- 注册方式完全复刻 `__init__.py` 现有的容错注册链（单模块失败不拖垮全局）。

### 4.4 面板草图

```
Merged Sculpt Panel
├─ [ Create Merged Sculpt Object ]   ← 选中 N 个网格物体时可用
├─ [ Validate ]  状态: 3 sources, 18234 verts, OK
├─ (x) Also apply deltas to shape keys
├─ [ Apply Sculpt To Sources ]
└─ [ Discard Merged Object ]
```

---

## 5. 边界情况与风险矩阵

| 场景 | 检测时机 | 行为 |
|---|---|---|
| 来源物体被重命名 | Apply | UID 命中，正常写回（WWMI 会失败，我们修复） |
| 来源物体被删除 | Validate/Apply | 报错并列出名字，不写半个场景 |
| 来源物体被复制（UID 撞车） | Apply | 报错指出冲突，要求先清理 |
| 雕刻时开了 Dyntopo/Remesh | Validate/Apply | 顶点总数校验失败，明确报错 |
| 单个来源物体顶点数变了（编辑模式增删） | Apply | 记录值与现值不符，报错 |
| 雕刻期间移动了来源物体 | Validate | 警告（矩阵 epsilon 比对），可继续 |
| 合并物体带残留修改器 | Apply | 读 `undeformed_co`，天然免疫 |
| 各来源形态键不一致 | Create | 警告列出差异 |
| 多组合并物同时在场 | 全程 | 按 session 区分，互不影响 |
| 未保存崩溃后场景残留 | 下次 Apply/Discard | UID 属性随 .blend 保存，可继续或丢弃 |

## 6. 测试计划（`tools/test_merged_sculpt_blender.py`）

在 Blender 内跑（与 `tools/test_merged_component_blender.py` 同方式）：

1. **基础回环**：建 3 个随机命名 cube → merge → 程序化平移若干顶点 →
   apply → 断言每个来源顶点位置正确、UID 痕迹已清理。
2. **任意 N**：N = 2 / 7 / 20 分别回环。
3. **变换安全**：来源各自带位移/旋转/缩放 → 回环后断言位置正确。
4. **重命名安全**：merge 后重命名全部来源 → apply 成功。
5. **形态键**：带形态键来源 + `apply_deltas_to_shapekeys=True` →
   断言 Basis 与目标键都被正确更新。
6. **负例**：删一个来源 → 报错且不写任何数据；开 Dyntopo 改变顶点数 →
   报错；复制一个来源 → UID 冲突报错。
7. **多组并存**：两组 merge → 各自 apply 互不串数据。

## 7. 实施步骤与验收标准

**阶段 1 — 核心回环**（无 UI）
- 实现 `utils/merged_sculpt_utils.py` 的 create/apply/discard；
- 测试 1、2、4 通过。
- 验收：脚本层面任意 N 个物体合并-雕刻-写回无损。

**阶段 2 — 通用化加固**
- 相对矩阵、形态键策略、validate、多 session；
- 测试 3、5、6、7 通过。
- 验收：风险矩阵每一行都有对应行为与测试。

**阶段 3 — UI / i18n / 注册**
- `ui/ui_panel_merged_sculpt.py` + `__init__.py` 注册 + 中文翻译；
- 手动验收：Blender 5.2 中面板可用、右键菜单可用、报错文案友好。

## 8. 许可证与署名

- WWMI-Tools 为 **GPL-3.0**。本次是**思想移植 + 重新实现**
  （数据 schema、变换处理、session 机制均为新设计），但
  `ObjUtils.join_objects` 等既有代码本就源自 WWMI 一脉，MIMIBlender
  作为整体继续按 GPL-3.0 兼容方式分发即可。
- 在新模块 docstring 中保留来源说明（"Idea ported from WWMI-Tools
  (GPL-3.0)"），与现有 `obj_utils.py` 的注释习惯一致。
