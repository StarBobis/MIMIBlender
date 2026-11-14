# WWMI 生成条件兼容性审查（2026-11-14）

按用户要求对照上游代码修改生成逻辑，不以删除全部校验为目标。
用户未提供截图中 `ce9c7f43` 的工程，该工程本身未复现。同类历史元数据冲突通过合成
样本覆盖，另用 Xin、JinXi 工作区在独立 Blender 中验证真实导出。
没有修改用户打开的场景、工作区文件或实际 Mods。

## 对照版本与范围

- [WWMI-Tools](https://github.com/SpectrumQT/WWMI-Tools/tree/5bd6fa4f16cf8e675a1d273ca2aa2f97a1d00ffb)
- [WWMI-Package](https://github.com/SpectrumQT/WWMI-Package/tree/8f5e5bc43df10adae094cbab5febb65bac9cb59f)
- 重点读取 Tools 的 `blender_export/object_merger.py`、
  `blender_export/data_models/data_model_wwmi.py`、`extract_frame_data/metadata_format.py`、
  `templates/merged.ini.j2`、`templates/per_component.ini.j2`、`addon/settings.py`、
  `migoto_io/data_model/data_extractor.py`，以及 Package 的
  `WWMI/Core/WWMI/ShapeKeys.ini`、`WuWa-Model-Importer.ini` 和相关计算着色器。
- 本地覆盖 WWMI model、形态键打包与运行时信息、component 匹配、骨骼 remap、
  INI 校验和资源声明、贴图节点以及导出后的文件引用。

## 已修复的差异

| 路径 | 原问题 | 修改与依据 |
|---|---|---|
| 逆向附加信息 | 源对象历史信息即使不参与输出，也必须与工作区相同；包括 `shapekey_count` 不一致时触发截图中的冲突 | 当前工作区已有所需运行时信息时直接采用它，不读取无用 sidecar；只有需要补充缺失信息时才验证来源。上游以选定 Metadata 为依据 |
| 无形态键模型 | 空批次数组被认定为错误，Basis-only 对象也可能触发历史来源检查 | 没有实际原生形态键变化时不要求批次、hash 或 sidecar，空数组保持为空 |
| 需求判定 | 仅从名字推算会把空 Custom 999 当成新增批次 | 在最终临时网格上检查非零位移和实际使用的顶点；无变化及 IB 未引用的松散顶点不形成依赖 |
| 末批次容量 | 将捕获到的已填充 key 数当成硬上限 | 保留中间批次的导入 ID 边界，允许最后一个原生批次使用剩余的 127-slot 空槽，不伪造新批次 checksum |
| 尾批次 | 只改第一批次也强制输出和校验所有后续批次 | 对齐上游按实际 key 生成的行为，只打包非空 key 使用的批次前缀 |
| Basis 名称 | 基础形态键改名后，按字面 `Basis` 索引失败 | 使用 Blender reference_key 身份取基准坐标，保留第一项回退 |
| 原生元数据 | 不同 component 的批次前缀和完整列表必须相等，新旧头字段也冲突 | 批次数组按索引合并互补字段，显式 batches 优先于弃用的单批次头；真正同一运行时字段冲突仍报告索引和字段 |
| hash 大小写 | 相同十六进制 hash 大小写不同会被当成不匹配 | 原生和逆向关联比较统一大小写 |
| incomplete 标志 | native 明确标为 incomplete 的残留数字可能被重新认定为 complete | native 占位信息也应用 incomplete 语义，不用默认数字伪造 checksum/dispatch |
| 无权重模型 | 额外要求至少一个顶点组，上游支持零 blend 数据 | 仅 WWMI 路径允许无组模型，由现有打包器写零值，其他预设规则保持 |
| 骨骼组名称 | 上游允许普通显示名称，本地却在后续打包时硬性要求数字名 | 在临时对象合并前，非数字组名按上游 group index 转为内部身份；显式数字名仍保留原身份，源对象组名不变 |
| 隐藏 component | 没有自定义 draw 的 component 被排除出 skeleton merger | 与 merged 模板一致，所有原生 component 仍按捕获的 VG 范围采集骨骼；自定义 draw 仍由蓝图决定 |
| 资源引用 | 无条件引用未生成的 ShapeKeyOffset/VertexId/VertexOffset 文件 | 只在实际打包原生形态键时声明这三个文件资源，控制键 Position/Vector 资源保持独立 |
| 运行时版本 | 使用较新 remap 能力却宣告最低 1.00 | 对齐 Tools 最低版本 1.1.0，INI 数值为 1.10；所查 Package 为 1.20 |

## 保留的校验及边界

- 额外运行时批次仍需要真实 checksum、原始 sparse base 和 dispatch_y。上游模板也
  从 extracted metadata 逐批读取它们；编辑后的稀疏顶点数量不能生成原始身份。
- 只有实际消费逆向补充信息时，才要求 component 范围和资源身份关联到目标。
  这不再是替换几何必须满足的前置条件。
- R8 索引最多表示 256 个单 draw palette 项，R16 remap 也有表示范围，不会截断。
  本地显式数字组名作为稳定骨骼身份的规则保留；非数字显示名称采用上游 index 语义。
  不把全部数字组按内部 index 重命名，否则会破坏稀疏组、重排组和骨骼绑定流程。
- 完全相同的运行时组件匹配、冲突 section/global、未定义本地资源等仍报告错误。
  上游单 Metadata 导出没有提供多 DrawIB 冲突的自动解决策略。
- 手工编辑的历史 INI 不自动覆盖或删除；该检查处理迁移文件冲突，与形态键无关。
- 保留本地已有的最高 key 批次数计算、zero checksum、buffer range 和全宽骨骼身份
  修复，不为模仿上游的潜在边界问题而回退。

## 验证与复现

从插件根目录运行：

```text
python tools/test_wwmi_reverse_metadata.py
python tools/test_wwmi_batches.py
blender --background --factory-startup --python-exit-code 1 --python tools/test_wwmi_components_blender.py
blender --background --factory-startup --python-exit-code 1 --python tools/test_wwmi_multi_drawib_ini.py
blender --background --factory-startup --python-exit-code 1 --python tools/test_wwmi_texture_nodes_blender.py
```

逆向元数据 27 项通过；batch/兼容测试 29 项中 28 项通过、1 项可选旧 fixture 缺失而跳过。
component 16 项、多 DrawIB INI 17 项通过。真实 JinXi 的三个贴图节点完成生成，并验证
DDS 格式与替换字节。

真实工作区测试：`tools/test_wwmi_roundtrip_blender.py`，设置环境变量：

- `MIMI_AUDIT_WORKSPACE=Xin`；`MIMI_AUDIT_IMPORT_MODE=MERGED` 或 `PER_COMPONENT`。
- `MIMI_AUDIT_CASE=default/no_shapes/stale_sidecar/renamed_basis/empty_high_key/named_groups`。
- 每个进程独立启动 Blender，输出限制在仓库 tmp。fixture 固定 WWMI 预设，避免当前
  MMT 选其他游戏时误测其他 exporter，不修改启动器配置。
- 普通两种模式均完成 355434 索引导出。五个兼容场景在 Merged 下也成功生成。
  对 source geometry、weights、shape coordinates、custom properties 做前后快照比较；
  没有遗留临时对象或 mesh；检查每个实际 INI filename 均存在。
- 日志：`tmp/wwmi-upstream-*.log`。只证明这些路径和 fixture 的离线导出，未验证截图
  原工程，没有游戏内渲染或对抗审查。不能据此声称不存在其他缺陷。
