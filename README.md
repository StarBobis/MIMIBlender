# MIMIBlender

MIMIBlender 是 **MIMITools 的 Blender 插件端**：一个配合 MMT 与 3Dmigoto 使用的游戏 Mod 制作工具。
它负责「建模 / 反向导入 / Mod 生成」这一段工作流，把 Blender 里的模型按游戏预设导出为 3Dmigoto 可直接加载的 Mod（缓冲区文件 + INI）。

- 仓库地址：https://github.com/StarBobis/MIMIBlender
- 运行环境：**Blender 5.2 及以上**，Windows（3Dmigoto 体系仅在 Windows 上可用）
- 界面语言：English / 简体中文（插件内一键切换）

---

## 这个工具能做什么

### 1. 从 MMT 工作空间一键反向导入模型
- **Import All From MMT Workspace**：一键导入当前 MMT 工作空间里的全部内容（3Dmigoto dump 出来的缓冲区数据），自动建立蓝图节点。
- **Import MMT Model**：手动导入单个 MMT 模型。
- 导入时自动处理：按 DrawIB 文件夹命名集合与网格、按 per-IB match identity 命名分段对象、拼接部件别名（INI draw 注释）、形态键（Shape Keys）导入。
- **镜像工作流**（Mirror Workflow）：3Dmigoto 模型历史上有镜像问题，插件提供配套的烘焙镜像导入/导出流程。
- **Fix DrawIB / Submesh Data Type**：修复选中对象的数据类型标记。
- GIMI / SRMI 预设走无损原始字节通道：Blender 无法原生表示的 NORMAL w 分量、完整 TANGENT 负载等会以 POINT 域属性保存，导出时原样写回。

### 2. 蓝图（Blueprint）节点化 Mod 逻辑编辑器
在节点编辑器中以可视化节点组织一个 Mod 的全部逻辑，节点类型包括：
- **对象节点 / 对象列表节点**：引用场景对象，对象列表支持折叠扇出与批量设置子网格。
- **贴图绑定 / Hash 贴图节点**：绑定贴图资源；Hash 贴图支持连接物体的条件替换，以及不连接任何节点的全局 Hash 外部贴图替换。
- **形态键节点**：按按键切换形态键数值。
- **时间开关系列节点**（Time Switch / Time Position Switch / Time Shape Key）：按时间轴驱动的动画切换，支持循环与按键触发单次播放模式，附带动画烘焙器。
- **面部 Mod 导出节点**：按面部分组导出。
- **分组节点 / 结果输出节点 / 高亮节点 / 文件拖放**：组织图结构并标记输出；支持把文件直接拖入蓝图。
- **Naraka 专属节点**：跨 IB 成对渲染等永劫无间特有逻辑。
- 蓝图可保存、重命名、删除，旧版本蓝图标题会自动迁移。

### 3. 一键生成 Mod（Generate Mod）
- 解析蓝图输出节点，按当前游戏预设调用对应导出器，把缓冲区与 INI 写入 MMT 的 Mod 输出目录（`Buffers/` 与 `Textures/` 子目录），可直接被 3Dmigoto 加载。
- 目前**已注册导出器、可以生成 Mod** 的游戏预设：

| 预设 | 游戏（常见叫法） | 预设 | 游戏（常见叫法） |
| --- | --- | --- | --- |
| GIMI | 原神 | EFMI | 明日方舟：终末地 |
| SRMI | 崩坏：星穹铁道 | YYSLS | 燕云十六声 |
| ZZMI / ZZMIDX12 | 绝区零（DX11 / DX12） | Naraka / NarakaM | 永劫无间（端游 / 手游模拟器） |
| WWMI | 鸣潮 | SnowBreak | 尘白禁区 |
| HIMI | 崩坏3 | IdentityV | 第五人格 |
| NTEMI | 异环（测试中） | GF2 / AILIMIT | 少女前线2 / 无限机兵 |

> 预设列表在代码中以 `LogicName` 为准；DOAV、APMI（蓝色星原）、NEMI 等为保留或暂未开放生成的槽位。

### 4. 模型处理面板（Model Processing）
按 UV 松散块 / 共享与孤立顶点组 / DrawIndexed 值拆分模型；顶点组批量管理（重命名加前缀、删除空组、按数字前缀合并、补齐数字空缺、按名称排序、按位置映射重命名）；由顶点组生成基础骨骼；TANGENT 向量求和归一化重算、COLOR 算术平均归一化重算；完美镜像网格；删除松散点、清除自定义拆边法线、带形态键应用修改器、位置旋转归零等。

### 5. 快速贴图面板（Fast Texture）
加载工作空间的 DedupedTextures、刷新 LOD 列表、把贴图应用到选中对象、快速预览贴图。

### 6. 贴图合并（texcomb，内置的 Material Combiner）
- 把多个材质合并成图集，减少 draw call；可指定图集尺寸与每个材质的尺寸，可混合纯色与贴图。
- Pillow 依赖可通过面板上的 **Install Pillow** 按钮一键安装到插件自带目录（无需管理员权限）。

### 7. 其他
- **自动更新**：插件内通过 GitHub Release（Atom feed，不占 API 配额）检查新版本并一键更新。
- **多语言**：English / 简体中文。

---

## 这个工具不能做什么（重要，请先读）

1. **它不是独立可用的 Mod 工具。** 它只覆盖工作流中「Blender 内的建模与导出」这一段：
   - 游戏配置与工作空间由 **MMT** 提供；
   - Mod 在游戏内生效依赖 **3Dmigoto**。没有这套环境，插件本身无法让任何 Mod 进游戏。
2. **它不解包游戏。** 插件不能从游戏客户端里提取模型或贴图；反向导入的数据来源是 3Dmigoto 帧分析 dump 出来、经 MMT 工作空间整理好的缓冲区文件。
3. **它只支持已注册导出器的游戏预设。** 未注册的预设（如 DOAV、APMI、NEMI）选择「生成 Mod」会直接报「当前游戏预设暂不支持生成 Mod」。支持范围以上表与代码中的 `LogicName -> exporter` 注册表为准。
4. **环境限制：**
   - 仅支持 **Blender 5.2+**，不保证旧版本 Blender 可用；
   - 实际 Mod 管线仅适用于 **Windows + DirectX 11/12**（3Dmigoto 的限制）；
   - texcomb 的 Pillow 一键安装目前主要覆盖 Windows / macOS 路径。
5. **它不是通用模型转换器。** 导出目标是 3Dmigoto 缓冲区格式（`.buf`/`.ib`/`.vb` 等 + INI），不是 FBX/OBJ/glTF 等通用交换格式。
6. **导入保真度有边界。** 无损原始字节往返通道只覆盖 GIMI / SRMI；其他预设中 Blender 无法原生表示的游戏私有顶点负载（如 NORMAL 的 w 分量、完整 TANGENT、游戏自有的 COLOR alpha）会在导出时按算法重算，可能与原文件存在差异。
7. **texcomb（贴图合并）的功能边界：**
   - 新版**未实现**多合一图集（Normal / Specular 等多层图集）与 UV 打包（UV Packing）——这两个功能只存在于上游旧版（2.0.3.3 / 1.1.6.3）；
   - 已共享同一材质与贴图的对象会被跳过（视为已优化）；
   - Blender 界面语言非英文导致节点名不同、材质使用不支持的 shader 时，合并可能失败（见 `texcomb/README.md` 的 Known Issues）。
8. **它不为账号安全背书。** 在带反作弊的线上游戏中使用 Mod 可能导致掉帧、临时封禁甚至永久封禁（永劫无间预设尤其明确存在该风险）。是否使用、如何使用由使用者自行判断与承担。
9. **它不替你理解游戏的数据格式。** 面板提供修复与重算工具，但选错数据类型、错误拆分方式等仍需使用者对 3Dmigoto 模型格式有基本了解。

---

## 安装

1. 在 [Releases](https://github.com/StarBobis/MIMIBlender/releases) 下载最新版的 `MIMIBlenderVxxxx.zip`。
2. Blender → 编辑（Edit）→ 偏好设置（Preferences）→ 插件（Add-ons）→ **从磁盘安装（Install from Disk）**，选择该 zip。
3. 勾选启用 **MIMIBlender**。
4. 如需使用贴图合并：在 3D 视图按 `N` 打开侧栏 → MIMITools → MatCombiner 面板 → 点击 **Install Pillow**。

> 已安装旧版时，可直接用插件内的「Version Update」面板一键更新，无需手动下载。

## 快速上手

1. 在 **MMT** 中选择游戏、创建并打开工作空间（插件从这里读取 `main.json` 全局配置：游戏名、预设、工作空间、缓存路径）。
2. Blender 3D 视图按 `N` → **MIMITools** 分类 → 基础信息面板：确认当前配置 / 游戏预设 / 工作空间无误。
3. 点 **Import All From MMT Workspace** 一键导入并自动建蓝图（或 **Import MMT Model** 手动导入单个模型）。
4. 在节点编辑器中打开 MIMITools 蓝图，按需调整对象、贴图、形态键、时间开关等节点逻辑。
5. 回到基础信息面板，选择蓝图后点 **Generate Mod**，生成的 Mod 会写入 MMT 的 Mod 输出目录。
6. 通过 MMT 与 3Dmigoto 在游戏中加载验证。

## 目录结构（源码）

```
__init__.py            插件入口与 bl_info（版本号唯一来源）
blueprint/             蓝图节点系统（节点定义、导出辅助、时间轴烘焙）
common/                全局配置、D3D11 语义、贴图命名、原始顶点属性
games/                 各游戏预设的导出器（wwmi/gimi/naraka/ntemi 为包，其余为单文件）
i18n/                  多语言（English / 简体中文）
model/                 蓝图数据模型（BluePrintModel 等）
resources/             内置资源（HLSL、DDS 预览图）
sword/                 3Dmigoto 二进制文件读写（MigotoBinaryFile）与面板
texcomb/               内置 Material Combiner（贴图合并，源自上游开源项目）
tools/                 开发辅助脚本
ui/                    Blender 侧栏面板与导入/导出操作符
utils/                 通用工具（网格、顶点组、形态键、日志、TBN 编解码等）
workspace/             MMT 工作空间信息读取
release.ps1            维护者用的一键发布脚本（见下）
```

## 发布流程（维护者）

```powershell
# 预检（不改任何东西）
.\release.ps1 -Bump -DryRun
# 补丁版本 +1，提交并推送版本提交，然后发布 GitHub Release 并上传 zip
.\release.ps1 -Bump -Push
```

脚本会：校验干净工作区与版本号 → 打包 `git archive`（zip 内含 `MIMIBlenderVxxxx/` 包裹目录）→ 创建/更新 GitHub Release → 上传 zip 资产 → 校验资产大小与远端 tag。插件内自动更新走的是 tag zipball，Release 一经发布即对用户可见。

## 致谢

- 贴图合并（texcomb）集成自 [material-combiner-addon](https://github.com/Grim-es/material-combiner-addon)（Grim-es）。
- 自动更新基于 [Blender Addon Updater](https://github.com/CGCookie/blender-addon-updater)。
- 3Dmigoto（bo3b / DarkStarSword）、XXMI 社区与 MMT 工具链。

---

# MIMIBlender (English)

MIMIBlender is the **Blender add-on half of MIMITools**: a game-mod authoring tool that works together with MMT and 3Dmigoto. It covers the "model / reverse-import / mod generation" part of the pipeline, exporting Blender scenes into 3Dmigoto-loadable mods (buffer files + INI) per game preset. **Blender 5.2+, Windows only.**

## What it can do

- **One-click reverse import** from an MMT workspace ("Import All From MMT Workspace" / "Import MMT Model"): DrawIB-based naming, part aliases, shape keys, paired baked-mirror workflow, and a lossless raw-byte round-trip channel for GIMI/SRMI vertex payloads Blender cannot natively represent.
- **Blueprint node editor**: visual node graphs for mod logic — object / object-list, per-object texture & conditional hash-texture bind, unconnected global hash-texture replacement, shape key, time-switch animation nodes (loop or key-triggered, with baking), face-mod export, groups, result outputs, file drag-and-drop, Naraka-specific nodes.
- **One-click Generate Mod**: exports buffers + INI into the MMT mod output folder for the registered presets (GIMI, SRMI, ZZMI/ZZMIDX12, WWMI, HIMI, EFMI, NTEMI, YYSLS, Naraka/NarakaM, SnowBreak, IdentityV, GF2, AILIMIT — see the table above).
- **Model processing panel**: split by UV loose parts / vertex groups / DrawIndexed, batch vertex-group management, basic bone generation, TANGENT/COLOR recomputation, perfect mesh mirroring, and more.
- **Fast texture panel**: DedupedTextures loading, LOD list, apply/preview textures.
- **texcomb (built-in Material Combiner)**: merge materials into atlases; one-click Pillow install.
- **Auto update** from GitHub Releases and **English / 简体中文** UI.

## What it cannot do

- **It is not standalone**: it requires MMT (game configs and workspaces) and 3Dmigoto (in-game loading). It cannot put a mod into any game by itself.
- **It does not unpack games**: imports come from 3Dmigoto frame-analysis dumps organized in an MMT workspace, never from the game client directly.
- **Only presets with a registered exporter** can generate mods; DOAV/APMI/NEMI are reserved/unsupported.
- **Blender 5.2+ only; Windows/DX11-12 only** for the actual mod pipeline.
- **It is not a general model converter**: output targets 3Dmigoto buffer formats, not FBX/OBJ/glTF.
- **Lossless raw-byte round-trip is GIMI/SRMI-only**; other presets recompute game-private vertex payload components on export.
- **texcomb limits**: multi-atlas (normal/specular layers) and UV packing are not implemented in the integrated version; non-English Blender UI or unsupported shaders can break merging.
- **No account-safety guarantee**: using mods in online games with anti-cheat can get you banned (the Naraka preset carries this risk explicitly). Use at your own risk.
- **It does not replace format knowledge**: fixing/recalculation tools help, but a basic understanding of 3Dmigoto model formats is still required.

## Install & quick start

1. Download `MIMIBlenderVxxxx.zip` from [Releases](https://github.com/StarBobis/MIMIBlender/releases) → Blender → Edit → Preferences → Add-ons → **Install from Disk** → enable **MIMIBlender** (older installs can use the in-addon updater instead).
2. In **MMT**, pick a game and open a workspace.
3. Blender 3D Viewport → `N` sidebar → **MIMITools** → confirm the config, then **Import All From MMT Workspace**.
4. Adjust the blueprint node graph, then **Generate Mod**; load it in game via MMT and 3Dmigoto.
5. For the texture combiner, click **Install Pillow** in the MatCombiner panel first.
