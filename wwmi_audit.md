# WWMI 预设生成 Mod —— 对比 WWMI-Tools 的缺陷审查与修复方案

审查对象：`games/wwmi/`（exporter.py / model.py / blend_remap.py / shapekeys.py）与它调用的 `common/m_ini_helper.py`。
对照实现：`SpectrumQT/WWMI-Tools` v1.7.3（模板 `templates/merged.ini.j2`、`per_component.ini.j2`）与 `SpectrumQT/WWMI` 运行时 1.0.0（`WuWa-Model-Importer.ini`、`Shaders/*.hlsl`）。
另一份用于判定引擎语义的权威依据：本仓库 `tmp/3dmigoto-src/DirectX11/*.cpp`（IniHandler.cpp / CommandList.cpp）。

**结论先说**：WWMI 单 DrawIB 的常规角色替换场景，生成结果与 WWMI-Tools 在结构上是对得上的；但**多 DrawIB（一个 Mod 同时改本体 + 武器/配件/多套部件）这条路径存在会导致模型错乱的确定性缺陷**，且**骨骼合并缺少参考实现里的全部守卫**，属于「偶发炸裂」的隐性缺陷。

---

## 一、缺陷清单（按严重度排序）

### A1【致命】一个 Mod 内多个 DrawIB 的 INI 共用同名全局变量，只有第一个文件生效

**证据**

- `games/wwmi/exporter.py:62-80`（`add_constants_section`）对**每一个** DrawIB 都无条件写出：
  `global $object_guid` / `global $mesh_vertex_count` / `global $shapekey_vertex_count` / `global $shapekey_vertex_offset_batchN` / `global $shapekey_vertex_count_batchN` / `global $mod_id` / `global $state_id` / `global $mod_enabled` / `global $object_detected`。
- `games/wwmi/exporter.py:407-479`（`generate_unreal_vs_config_ini`）按 DrawIB 逐个写出 `<模组名>_<DrawIB>.ini`，同一个 Mod 目录里因此有 N 个 INI。
- 3Dmigoto 的 `[Constants]` 是**全局命名空间**，且同名全局变量**只接受第一次声明**：
  `IniHandler.cpp:2106-2110`
  ```cpp
  inserted = command_list_globals.emplace(name, CommandListVariable{name, fval, flags});
  if (!inserted.second) {
      IniWarning("WARNING: Redeclaration of %S\n", name.c_str());
      continue;                      // 后来的声明被整行丢弃
  }
  ```
- 实测（`tmp/verify_wwmi_multi_drawib_ini.py`，三个 DrawIB 跑真实导出代码）：三个 INI 里 `[Constants]`、`[ResourcePositionBuffer]`、`[CommandListOverrideSharedResources]` 等都各自出现一次，即**每个文件都独立声明了同一批全局变量**。
- 加载顺序：`IniHandler.cpp:773,810-815` 用 `std::set<wstring, WStringInsensitiveLess>` 按文件名**不区分大小写排序**后依次解析，所以是**文件名字典序最靠前的那个 DrawIB 说了算**。

**影响**

`$mesh_vertex_count` 决定三件事，全都只认第一个 DrawIB 的值：

| 使用点 | 位置 | 后果 |
|---|---|---|
| `override_vertex_count = $mesh_vertex_count` | `games/wwmi/shapekeys.py:118,127` | 形态键 UAV 尺寸按错的顶点数扩张 → 变形错位/花屏 |
| `$\WWMIv1\custom_vertex_count = $mesh_vertex_count` | `games/wwmi/shapekeys.py:168` | 形态键乘算 CS 的 dispatch 范围错 |
| `$\WWMIv1\custom_vertex_count = $mesh_vertex_count` | `games/wwmi/blend_remap.py:80` | BlendRemap 初始化按错长度拷贝 → 骨骼权重错乱 |

同理 `$object_guid`（WWMI 用它做对象登记标识）、`$shapekey_vertex_offset_batchN`（形态键批次偏移）也会被第一个 DrawIB 顶掉。

**这是一个确定性缺陷**：只要一个 Mod 里有两个顶点数不同的 DrawIB，第二个起就会错。

---

### A2【高】`[CommandListMergeSkeleton]` 无任何守卫，把非骨骼数据当骨骼合并

**证据**

我们的实现 `games/wwmi/blend_remap.py:136-149`（整段无条件执行）：
```ini
[CommandListMergeSkeleton]
$\WWMIv1\custom_mesh_scale = 1.00
cs-cb8 = ref vs-cb4
cs-u6 = ResourceMergedSkeletonRW
run = CustomShader\WWMIv1\SkeletonMerger
cs-cb8 = ref vs-cb3
cs-u6 = ResourceExtraMergedSkeletonRW
run = CustomShader\WWMIv1\SkeletonMerger
```

参考实现 `merged.ini.j2:298-335` 用三层守卫：
1. `if $merge_status_id == 0` + `if vs-cb4 == 3381.7777` → 才合并常规骨骼（`vs-cb4` 必须是骨骼 CB，`3381.7777` 是 `[TextureOverrideMarkBoneDataCB]` 打上的标记）；
2. `if $merge_status_id == 1` + `if vs-cb4 == 3381.7777 && vs-cb3 == 3381.7777` → 才合并附加骨骼。

WWMI 运行时文档 `WuWa-Model-Importer.ini:289-297` 明确指出 vs-cb3/vs-cb4 的三种槽位组合，只有组合 2/3 才能可靠取到骨骼。

**影响**：`SkeletonMerger.hlsl` 会把 `cs-cb8` 里的东西**无条件当成 256 根骨骼**写进 `ResourceMergedSkeletonRW` / `ResourceExtraMergedSkeletonRW`。当该 draw call 的 `vs-cb3`/`vs-cb4` 装的是别的东西时，合并结果被污染：

- `ResourceMergedSkeleton` 被污染 → 顶点错位、模型炸裂；
- `ResourceExtraMergedSkeleton` 被污染后还会经 `vs-cb3 = ref ResourceExtraMergedSkeleton`（`exporter.py:169`）**覆盖游戏自己的 vs-cb3** → 描边/抗锯齿等依赖 vs-cb3 的 pass 一起坏掉。

这是「大多数时候没事、换一套衣服/换个场景就炸」的典型隐性缺陷。

---

### A3【中】缺少 `$merge_status_id` 三态跟踪，每帧多做一次多余的骨骼合并

**证据**

- 我们的 `exporter.py:276-284`：靠 `$state_id`（`blend_remap.py:22-26` 每帧 0/1 翻转）+ 组件内 `local $state_id_N` 判断是否重复合并。
- **`local` 变量每次 command list 运行都是全新的**：`CommandList.cpp:184` 每次 `RunCommandListComplete` 都新建 `CommandListState state;`，`$state_id_N` 因此每次都是 0。所以判断退化成「每帧都合并」，而不是参考实现的「每组件每帧最多一次常规 + 一次附加」。

**影响**：功能上尚可工作（合并幂等），但每帧每个组件都白跑一次 `SkeletonMerger` CS，另外两处附带问题：

1. 参考实现在 `vs-cb4 == 3381.7777`（常规骨骼到手）后把状态推进到 1，下一帧才会去取 vs-cb3 的附加骨骼；我们一次调用里连跑两次，第二次的前提条件根本没被验证过（即 A2）。
2. `blend_remap.py:27-28` 每帧无条件拷贝 `ResourceExtraMergedSkeletonRW`，即使这次根本没有合并出附加骨骼。

---

### A4【中】蓝图里没有任何物体指定的组件，仍然参与骨骼合并

**证据**：`exporter.py:276-284` 对**所有**组件（含 `submesh_drawcall_groups[N]` 为空数组的组件）都执行 `$\WWMIv1\vg_offset/vg_count` + `run = CommandListMergeSkeleton`，而参考模板 `merged.ini.j2:448-456` 把整个合并块放在 `if objects|length > 0` 里面。

**影响**：该组件的 `vg_offset/vg_count` 取自 submesh JSON 的组件级信息（`common/dmg` → `workspace/wwmi_info.py:59-67`），在 MERGED 顶点组模式下语义与合并用的全局顶点组表并不一致。等于让 `SkeletonMerger` 在错误的顶点组区间上写一遍数据，可能覆盖掉别的组件已经合并好的骨骼。

我们的 `tools/test_wwmi_components_blender.py:123-124` 甚至把「空组件也写 vg_offset/vg_count」当成**期望行为**断言下来了，所以这个行为被测试锁死了，改动时要同步改测试。

---

### A5【低】`[CommandListTriggerResourceOverrides]` 少一个 `ps-t8`

**证据**

- 我们：`exporter.py:124-131` 只检查 `ps-t0` ~ `ps-t7`。
- 参考：`merged.ini.j2:340-348` 和 `per_component.ini.j2:163-171` 都是 `ps-t0` ~ `ps-t8`。

**影响**：贴着 `ps-t8` 的替换贴图在 WWMI 场景下不生效（表现为「换了图，游戏里没变」）。属于对齐问题，不是崩溃。

---

### A6【中】`required_wwmi_version` 仍写 `0.91`，WWMI-Tools 当前是 `1.00`

**证据**

- 我们：`exporter.py:65` → `global $required_wwmi_version = 0.91`。
- 参考：`wwmi-tools/__init__.py` → `"wwmi_version": (1, 0, 0)`，模板写出 `required_wwmi_version = 1.00`。
- 运行时校验：`WuWa-Model-Importer.ini:103,187-190`，`$wwmi_version = 1.00`；`if $wwmi_version < $required_wwmi_version` 则 `$mod_id = -1`，Mod 被整体禁用并弹窗。

**影响**：我们声明的是 0.91。**用户装的 WWMI 若在 [0.91, 1.00) 区间内**，我们会放心地启用，但此时生成的 INI 依赖的 `$\WWMIv1\*` 变量与 CS 插槽可能并不齐全；反之我们若把版本抬高到 1.00，则会把只装了 0.9x 的用户挡在门外。需要一次**明确的版本策略决定**，不能继续含糊地停在 0.91。

---

### A7【中】所有分支开关的 `[Key]` 都挂在 `$active0` 上，多 DrawIB 时快捷键失效

**证据**

- `common/m_ini_helper.py:1360-1361` 按 `GlobalConfig.generated_mod_number` 声明 `global $active0`、`global $active1`…；`exporter.py:272` 让每个组件的 `[TextureOverrideComponentN]` 置 `$active<N> = 1`。
- 但 `common/m_ini_helper.py:1419-1422` 把所有 `[KeySwap_N]` 的条件硬编码成 `condition = $active0 == 1`（代码里自己留了注释 `XXX: due to a BUG here, we always use $active0`）。

**影响**：一个 Mod 有多个 DrawIB 时，若屏幕上只有 DrawIB 1/2 的物体（`$active0 == 0`），所有形态键/开关快捷键**完全按不动**。

---

### A8【低】自动 Hash 贴图替换缺少 `if $object_detected` 守卫

**证据**：`common/m_ini_helper.py:676-689` 生成的 hash 覆盖段是
```ini
[TextureOverride_<hash>]
hash = <hash>
match_priority = 0
this = <resource>
```
参考 `merged.ini.j2:496-501` 是
```ini
[TextureOverrideTextureN]
hash = <hash>
match_priority = 0
if $object_detected
    this = ResourceTextureN
endif
```
**影响**：游戏里凡是使用该 Hash 的**其它**物件也会被一并替换（典型现象：改了主角衣服，路人的同款贴图也变了）。参考实现靠 `$object_detected`（只有我们的组件在屏幕上时才是 1）把替换限制在本 Mod 的对象上。

---

### B 类：功能缺口（非缺陷，但决定要不要补）

| 编号 | 缺口 | 参考实现位置 | 说明 |
|---|---|---|---|
| B1 | 没有「Per-Component Skeleton（无骨骼合并）」独立导出模式 | `per_component.ini.j2` 全文 | 该模式不跑 `CommandListMergeSkeleton`/BlendRemap，流程更短、更不容易炸，适合小改件。我们只有 merged 一条路。当前 `PER_COMPONENT` 顶点组模式仍走合并流程，与参考的 per-component 模式不是一回事。 |
| B2 | 无 `skeleton_scale` 用户参数 | `merged.ini.j2:311` `custom_mesh_scale = {skeleton_scale}` | 我们硬编码 `1.00`（`blend_remap.py:141,145`）。可用于整体放大/缩小模型。 |
| B3 | 无「Ini Toggles」逐物体开关 + 持久化 | `merged.ini.j2:7-21,57-68` | 参考会给每个子物体生成一个 `global persist` 开关和快捷键。我们有 `$activeN`，但没有逐物体持久开关。 |
| B4 | 无 `unrestricted_custom_shape_keys` | `merged.ini.j2:585-596,620-630` | 让本体没有形态键的组件也能用自定义形态键（需要 `ResourceShapeKeyedPosition`/`ResourcePositionRW`）。 |
| B5 | 无 `match_priority` 于组件段 | `merged.ini.j2:427-430`（同样没有） | 双方一致，**不是**问题，列在此仅为闭环。 |

---

## 二、修复方案

### 阶段 1：阻断性修复（必须做，直接对应 A1 / A2 / A4）

**S1.1 —— 让每个 DrawIB 的全局变量与资源名带上 DrawIB 作用域（修 A1）**

在 `games/wwmi/` 新增一个极小的命名助手（`games/wwmi/names.py`），只做一件事：给出该 DrawIB 的名称后缀。

```python
# names.py: one place that decides how WWMI symbols are scoped per DrawIB.
def draw_ib_suffix(draw_ib: str) -> str:
    """Return the suffix that makes a WWMI INI symbol unique per DrawIB."""
    return "_" + str(draw_ib)

def scoped(name: str, draw_ib: str) -> str:
    """Turn a bare WWMI symbol into its per-DrawIB scoped form."""
    return name + draw_ib_suffix(draw_ib)
```

改造点（全部集中在 WWMI 包内，不动其他游戏预设）：

| 文件 | 改什么 |
|---|---|
| `games/wwmi/exporter.py:62-80` | `global $object_guid_<IB>`、`$mesh_vertex_count_<IB>`、`$shapekey_vertex_count_<IB>`、`$shapekey_vertex_offset_batchN_<IB>`、`$shapekey_vertex_count_batchN_<IB>`、`$state_id_<IB>`。**`$mod_id`/`$mod_enabled`/`$object_detected` 保持全局唯一**（注册流程本来就该全 Mod 一次）。 |
| `games/wwmi/exporter.py:103-119` | `[CommandListRegisterMod<IB>]`；里面 `$\WWMIv1\object_guid` 仍写全局槽位，但读的是 `$object_guid_<IB>`。因为只有第一个文件会被解析，最终登记的是排序最前的 DrawIB —— **需要在 `[Present]` 里对每个 DrawIB 分别登记**，或明确「一个 Mod 只登记一个 object_guid」并把这个限制写进 README。**这一条要在动手前定方案**（见第三节问题 Q1）。 |
| `games/wwmi/exporter.py:232-239` | `[TextureOverrideMarkBoneDataCB<IB>]` |
| `games/wwmi/exporter.py:241-328` | `[TextureOverrideComponent<IB>_N]`、变量 `$state_id_<IB>_N`、`$\WWMIv1\vg_offset/vg_count` 的写入保持运行时槽位名不变（`$\WWMIv1\*` 是 WWMI 自己的命名空间，**不能改**），但引用的资源名全部改为 `<IB>` 作用域。 |
| `games/wwmi/exporter.py:330-405` | `[Resource<IB>IndexBuffer]`、`[Resource<IB>PositionBuffer]` … `[Resource<IB>ShapeKeyVertexOffsetBuffer]` |
| `games/wwmi/exporter.py:121-207` | `[CommandList<IB>TriggerResourceOverrides]`、`[Resource<IB>BypassVB0]`、`[CommandList<IB>OverrideSharedResources]`、`[CommandList<IB>CleanupSharedResources]` |
| `games/wwmi/blend_remap.py` 全文 | `[CommandList<IB>UpdateMergedSkeleton]`、`[CommandList<IB>MergeSkeleton]`、`[CommandList<IB>InitializeBlendRemaps]`、`[CommandList<IB>RemapMergedSkeleton]`、以及全部 `[Resource<IB>…Remapped…]` |
| `games/wwmi/shapekeys.py:104-377` | `[CommandList<IB>SetupShapeKeysBatch]`、`[CommandList<IB>LoadShapeKeysBatch]` 等；`ResourceShapeKeyCBRW` / `ResourceCustomShapeKeyValuesRW` 的 `array` 尺寸依赖根 DrawIB 的批次数，因此**也要加作用域**（它们是 RWBuffer，同名只留第一份会让后一个 DrawIB 的批次数不匹配）。 |
| `common/m_ini_helper.py` | `generate_hash_style_texture_ini` / `generate_shared_slot_style_texture_ini` 传入一个名称前缀，避免两个 DrawIB 生成重复的 `[TextureOverride_<hash>]`（3Dmigoto 会对同 hash 的 TextureOverride 报 `Possible Mod Conflict`）。 |

`$\WWMIv1\<变量>` 是 WWMI 运行时的命名空间，**一律不加后缀**，否则运行时不认。

**S1.2 —— 给 `[CommandListMergeSkeleton]` 补上参考实现的全部守卫（修 A2）**

改写 `games/wwmi/blend_remap.py:136-149` 为参考实现的三态结构：

```ini
[CommandList<IB>MergeSkeleton]
if $merge_status_id_<IB> == 0
  if vs-cb4 == 3381.7777
    cs-cb8 = ref vs-cb4
    cs-u6 = <IB>ResourceMergedSkeletonRW
    $\WWMIv1\custom_mesh_scale = 1.00
    run = CustomShader\WWMIv1\SkeletonMerger
    $merge_status_id_<IB> = 1
  endif
endif
if $merge_status_id_<IB> == 1
  if vs-cb4 == 3381.7777 && vs-cb3 == 3381.7777
    cs-cb8 = ref vs-cb3
    cs-u6 = <IB>ResourceExtraMergedSkeletonRW
    $\WWMIv1\custom_mesh_scale = 1.00
    run = CustomShader\WWMIv1\SkeletonMerger
    $merge_status_id_<IB> = 2
  endif
endif
```

配套改动：

1. `[Constants]` 增加 `global $merge_status_id_<IB> = 0` 与每组件一个 `global $merge_status_id_<IB>_N = 0`（参考 `merged.ini.j2:49-56`）。
2. `[CommandList<IB>UpdateMergedSkeleton]`（`blend_remap.py:19-31`）里把每个 `$merge_status_id_<IB>_N` 重置为 0（参考 `merged.ini.j2:125-127`），并保留 `$state_id` 的帧翻转（它现在只用来给 `ResourceMergedSkeleton` 的拷贝做节流，可以保留）。
3. `[TextureOverrideComponent<IB>_N]` 把 `$state_id_<IB>_N` 换成 `$merge_status_id_<IB>_N`，并在调用前把当前组件状态传进 `$merge_status_id_<IB>`、调用后取回（参考 `merged.ini.j2:434-445`）。

**S1.3 —— 空组件不再参与骨骼合并（修 A4）**

`games/wwmi/exporter.py:274-325` 拆成两条分支，对齐参考模板：

- **该组件有物体**：`handling = skip` → （blend remap 时）绑 Override 资源 → `Trigger/OverrideSharedResources` → `drawindexed` → `CleanupSharedResources`；
- **该组件无物体**：`handling = skip` + 注释 `; Draw skipped: No matching custom components found`，**不跑任何 CommandList、不写 vg_offset/vg_count、不跑 MergeSkeleton**；blend remap 的三段 Override 资源也不设置。

同步更新 `tools/test_wwmi_components_blender.py:123-124` 的断言。

---

### 阶段 2：一致性与行为修复（A3 / A5 / A8）

**S2.1（A3）** 由 S1.2 的三态结构自然解决：每组件每帧最多一次常规 + 一次附加合并；`blend_remap.py:27-28` 的 `ResourceExtraMergedSkeleton` 拷贝保留（每帧一次是参考实现的做法）。

**S2.2（A5）** `exporter.py:124-131` 在 `ps-t7` 后补 `CheckTextureOverride = ps-t8`。
—— 注意：全量搜索 WWMI 1.0.0 仓库后确认，运行时自己只检查过 `ps-t0`（`WWMI-Utilities.ini:43`），`ps-t8` 纯粹是参考工具的一致性问题。**修它等于对齐参考，收益不确定，可以放到最后一并做**。

**S2.3（A8）** `common/m_ini_helper.py:676-689` 的自动 Hash 覆盖段加 `if $object_detected` 包夹。因为该函数是所有预设共用的，建议加一个**按预设开关的参数**，只在 WWMI 下启用，避免影响 GIMI/SRMI/ZZZ 等已验收的预设。

---

### 阶段 3：版本与开关（A6 / A7）

**S3.1（A6）** 把 `exporter.py:65` 的 `required_wwmi_version` 从 `0.91` 提到 `1.00`，并把该常量抽成一个具名常量（`WWMI_REQUIRED_RUNTIME_VERSION`）便于以后单点修改；README 里补一句「需要 WWMI 1.0.0+」。**这一条需要你确认**（见 Q2）。

**S3.2（A7）** `common/m_ini_helper.py:1419-1422` 的 `condition = $active0 == 1` 改为 `condition = $mod_visible == 1`，并在 `[Present]`/`[Constants]` 里维护 `$mod_visible`：任意一个 `$activeN` 为 1 时置 1。这样快捷键与「哪个 DrawIB 在屏幕上」解耦。因该函数为全预设共用，需回归所有预设的键测试。

---

### 阶段 4：可选增强（B1 / B2 / B3 / B4）—— 建议单独排期，不进本次修复

按性价比排序：B2（`skeleton_scale` 参数，改动最小）→ B1（Per-Component 导出模式，工作量最大、收益也最大）→ B3 → B4。

---

## 三、需要你审核决策的问题

**Q1（影响 S1.1 的写法）** 一个 Mod 里多个 DrawIB 时，WWMI 的 `[CommandListRegisterMod]` 只能登记一个 `$object_guid`。参考工具直接不支持多对象（一个 Mod 一个 `mod.ini`），我们是支持的。请选：

- **(a) 每个 DrawIB 各自登记一次**：`[Present]` 里按 DrawIB 轮流 `run = CommandList<IB>RegisterMod`，每个 DrawIB 用自己的 `$object_guid_<IB>` 和自己的 `$mod_enabled_<IB>`。语义最正确，但改动面最大（`$mod_enabled` 要变成 per-DrawIB，1000+ 行 INI 生成代码都要跟着走）。
- **(b) 保留现在的单次登记**：只把**几何/形态键/骨骼相关**的全局变量加作用域（A1 的实际危害全部来自这几个），`$object_guid` 仍取第一个 DrawIB。改动小、风险低，但 WWMI 面板里只会显示一个对象 ID。
- **(c) 明确不支持多 DrawIB**：一个 Mod 只允许一个 DrawIB，超过就报错。最简单，但砍功能。

**我的建议是 (b)**：能消掉 A1 的全部实际危害，改动可控，且不砍功能。

**Q2（S3.1）** `required_wwmi_version` 提到 `1.00` 会把「装了 WWMI 0.9x 且我们目前能跑通」的用户挡掉。你更看重「不误伤老版本」还是「和参考实现对齐、不留隐患」？

**Q3（阶段 2 范围）** S2.2（`ps-t8`）与 S2.3（`$object_detected` 守卫）都涉及跨预设共用代码，前者收益不确定、后者需要按预设开关。是否放进本次修复？

---

## 四、验证方案

**V1 多 DrawIB 命名唯一性（新增固定测试 `tools/test_wwmi_multi_drawib_ini.py`）**
复用已经跑通的 `tmp/verify_wwmi_multi_drawib_ini.py` 采集方式，对 3 个「顶点数各不相同」的假 DrawIB 跑真实导出路径，断言：

- 三个 INI 的全局变量名集合**两两不相交**（`$mesh_vertex_count` 不再重复出现）；
- 每个文件的 `[CommandList*]` / `[Resource*]` 名称集合两两不相交；
- 每个文件恰好一个 `[TextureOverrideComponent<IB>_0]`；
- `$\WWMIv1\*` 的名字**没有**被加后缀。

**V2 骨骼合并守卫（扩展 `tools/test_wwmi_components_blender.py`）**
断言 `[CommandList*MergeSkeleton]` 的结果里：

- 恰好出现 2 次 `vs-cb4 == 3381.7777` / `vs-cb3 == 3381.7777` 守卫；
- 顺序为「先 vs-cb4 写 MergedSkeleton，后 vs-cb4+vs-cb3 写 ExtraMergedSkeleton」；
- 每一次 `run = CustomShader\WWMIv1\SkeletonMerger` 都在对应的 `if` 块内。

**V3 空组件不合并（改现有断言 + 新增）**
断言空组件段内既没有 `run =`，也没有 `$\WWMIv1\vg_offset`。

**V4 版本与守卫字符串**
断言 `global $required_wwmi_version = 1.00`、`[CommandList*TriggerResourceOverrides]` 含 `ps-t8`（若采纳 S2.2）。

**V5 回归**
`python tools/run_blueprint_checks.py "<Blender 5.2 路径>"` 全套 + `tools/test_*_ini.py` 里所有非 WWMI 的 INI 测试，确认共用代码改动没有波及 GIMI / SRMI / ZZMI / Naraka / YYSLS 等预设。

**V6 真机**（只有你能做）
一个角色替换 Mod，分两种：①单 DrawIB 换衣服；②多 DrawIB（本体 + 武器）。观察：模型是否炸裂、待机动作是否正常、描边/抗锯齿是否正常、换装菜单里模型是否正常、快捷键是否还能按。

---

## 五、涉及文件与工作量

| 阶段 | 文件 | 预估 |
|---|---|---|
| 1 | `games/wwmi/names.py`（新增）、`games/wwmi/exporter.py`、`games/wwmi/blend_remap.py`、`games/wwmi/shapekeys.py`、`common/m_ini_helper.py` | 主要工作量，约 4 处结构调整 + 1 个新助手 |
| 2 | `games/wwmi/exporter.py`、`common/m_ini_helper.py` | 小 |
| 3 | `games/wwmi/exporter.py`、`common/m_ini_helper.py`、`README.md` | 小 |
| 验证 | `tools/test_wwmi_multi_drawib_ini.py`（新增）、`tools/test_wwmi_components_blender.py`、`tools/run_blueprint_checks.py` | 中 |

**发布**：改动完成后按仓库流程 `.\release.ps1 -Bump -Push` 走一次补丁版本；因为本次修的是生成结果而非 UI，建议 release note 明确写「WWMI 多 DrawIB Mod 修复 + 骨骼合并守卫」。

---

## 六、本次审查没有做的事（边界声明）

- **没有真机验证**：所有结论来自源码对照、3Dmigoto 引擎源码语义和 Blender 无头实测，未在游戏内加载验证过任何一条。
- **只审了 WWMI 预设**：GIMI / SRMI / ZZMI / EFMI / NTEMI 等未做同类对照。
- **A6/Q2 的版本区间没有实证**：`required_wwmi_version` 从 0.91 到 1.00 之间具体哪个版本支持哪些 `$\WWMIv1\*` 变量，WWMI 运行时仓库没有历史标签可查，属于需要你按社区经验判断的项。
