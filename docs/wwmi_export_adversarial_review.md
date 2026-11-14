# WWMI 导出对抗审查（2026-11-14）

用户明确同意后启动。每条结论单独审查，每条至少使用反证及边界／实际消费／独立复现
中的两个不同视角。审查者未改生产代码；主代理用可复现探针确认问题后修改，再逐条复审。
初始代码提交为 `08787a5`，上游固定版本见[原审查记录](wwmi_export_compatibility.md)。

## 逐条结论台账

“成立”只针对下表限定的代码与离线证据，不表示任意模型、游戏版本或未测输入都正确。
R1、R2、R3 是对应结论的审查轮次；最终轮承接未修改路径的已通过证据，并重新审查
修改涉及的结论。最后一轮没有遗留“不成立”或“证据不足”条目。

| ID | 单条结论及最终限定 | 轮次结果 | 两个视角与复现证据（仓库根目录起） |
|---|---|---|---|
| C01 | 足够的当前工作区信息允许跳过历史 sidecar，但必须验证实际消费的 unsigned 整数、count/offset 边界 | R1 不成立；R2 成立 | 坏历史信息反证、直接最终 INI 消费；`tmp/review_c01/probe_r2.py` |
| C02 | 零实际原生 shape 需求时，整个未消费 shape 元数据构建／校验被跳过，保留 geometry/skeleton | R1 不成立；R2 成立 | 坏 hash/batch/count 反证、真实 Xin 无 keys 与 Basis-only 完整导出；`tmp/review_c02/{builder_probe.py,full_probe.py}` |
| C03 | 原生 shape 的需求判断和实际稀疏缓存使用同一已求值临时顶点域 | R1 不成立；R2 成立 | MASK 原反例、空 MASK／SMOOTH／MIRROR／不同 key 顶点数失败；`tmp/review_c03/probe_r2.py` |
| C04 | 末批 offset 表能填至127槽，保持本地导入 ID 映射和原 checksum；不承诺公共 Setter ID API 对短中间批次兼容 | R1 不成立；收窄并限制运行时两批后 R2 成立 | PACK→IMPORT往返、Package Loader槽选择；`tmp/review_c04/probe_r2.py` |
| C05 | 未消费尾批次不形成 count/checksum/dispatch 校验依赖；真正消费的损坏记录仍拒绝 | R1 不成立；R2 成立 | 原非法尾 count 反例、builder→resolver→EXPORT全链；`tmp/review_c05/probe_r2.py` |
| C06 | native 基准读取用 reference 身份及首项回退，重建 modifier 后也不依赖显示名 | R1 成立；最终复核成立 | 基准名Custom900反证、relative key／旧结构／SMOOTH重建；`tmp/review_c06/{probe.py,probe_modifier.py}` |
| C07 | 同一批次先横向合并所有组件字段，再选择全局消费前缀；真冲突不被截取掩盖 | R1 成立；前缀改造后 R2 不成立；修复后 R3 成立 | 缺count/缺checksum互补反例、双枚举顺序与消费冲突；`tmp/review_c07/{prefix_final.py,tail_r3.py,probe.py}` |
| C08 | 有效8位 offsets/scale hash 大小写等价，不同身份仍拒绝且源记录不变 | R1 成立 | 原生组件合并、实际消耗sidecar补字段和第二批；`tmp/review_c08/probe.py` |
| C09 | 显式False占位不升级；显式batch缺base最终消费者拒绝；旧单批schema默认base0是明确兼容例外 | R1 宽泛表述不成立；修复消费者并明确例外后 R2 成立 | False/完整组件顺序、绕过resolver直调consumer；`tmp/review_c09/{probe.py,merge_r2.py}` |
| C10 | WWMI无权重行在最终Blend bytes仍为零，其他预设保持原行为 | R1 不成立；R2 成立 | 实际4/8通道字节、NaN/零/正常行与normalization边界；`tmp/review_c10/probe_r2.py` |
| C11 | 每对象一种骨身份规则：全数字保留显式身份；混合/显示名整体按index；不靠.001静默别名 | R1 不成立；R2 成立 | 混合名冲突、稀疏乱序／ignore／多对象join／补组开关；`tmp/review_c11/probe.py` |
| C12 | 与上游一致采集全部原生组件，隐藏组件无custom draw；就绪后才skip原draw | R1 绝对保证不成立；收窄后 R2 成立 | 模板反证、skip/empty/vg0和ready/null消费状态；`tmp/review_c12/probe.py` |
| C13 | 正常生产payload中，原生资源声明与生成文件对应；不承诺人工矛盾flag/offset自动修复 | R1 成立；最终复核成立 | no/native/Blueprint Smile条件、三个buffer独立解码；`tmp/review_c13/{probe_r2.py,bytes_r2.py}` |
| C14 | 1.10对应Tools的(1,1,0)，该Package版本确实具备动态remap stride，数字比较不误拒1.1/1.2 | R1 历史证据不足；补证后 R2 成立 | 上游Version运算、固定v1.1.0历史实现；`tmp/review_c14/{probe.py,history_probe.py}` |
| C15 | 全数字输入的R8/R16表示边界拒绝截断，合法宽骨身份通过forward/reverse往返 | R1 成立 | 255/256/257与65535/65536边界、Package实际shader索引；`tmp/review_c15/probe.py` |
| C16 | fresh输出的全部INI引用存在，测试覆盖字段前后相等，成功返回后无objects/meshes净增 | R1 原证据不足；加强测试后 R2 成立 | value/mute/custom数组修改反证、独立fresh完整导出；`tmp/review_c16/{snapshot_r2.py,full_r2.log}` |
| C17 | BI8/BW8即使只有1～4影响骨也保持声明宽度，top-K与零补位正确 | 发现额外缺陷并修复后成立 | 原真实Xin格式复现、0/1/4/5/8/11组与4/8通道实际bytes；`tmp/review_c17/{probe8.py,probe.py}` |

所有 Python 独立探针从插件仓库根目录运行。含 bpy 的探针使用：

```text
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python-exit-code 1 --python tmp/review_cXX/probe.py
```

## 修复与持久回归

独立探针保留在本机 tmp；关键反例已加入跟踪测试，不依赖旧临时产物：

- `tools/test_wwmi_reverse_metadata.py`：native快速路径的整数/range校验、边界矛盾、
  未消费坏尾、坏sidecar及零需求。
- `tools/test_wwmi_batches.py`：PACK无关坏尾、最终consumer缺base、两批Package范围、
  横向互补字段后再选择全局前缀。
- `tools/test_wwmi_components_blender.py`：混合组名不别名、MASK重编号后真实位移保留、
  实际4/8通道Blend字节与未加权行。
- `tools/test_wwmi_roundtrip_blender.py`：无shape场景在builder前注入损坏元数据；
  每次独立新目录；全部INI引用检查；递归序列化对象、mesh、shape datablock属性；
  shape value/mute/slider/relative_key等也纳入快照。

## 收窄而非伪装修复的结论

- Package公开 `SkapeKeySetter` 以固定127做全局ID→slot换算，不能对短中间批次直接沿用
  本地累计ID。当前MIMI不调用该Setter，蓝图自定义控制使用独立Position/Vector路径。
  填入末批槽不代表它自动获得非零权重或已通过游戏内激活验证。
- 固定Package只暴露batch0/batch1。本轮增加明确两批上限，避免生成不可消费的batch2。
  仅导入或分析更多批的缓冲与真正可运行的生成不是同一结论。
- legacy单批Metadata省略base时按上游旧schema默认0；显式batch省略base不适用此回退。
- merged资源未就绪时仍可能绘制原模型，与上游一致。冲突重叠VG范围仍可能后写覆盖，
  不宣称能自动识别或修复错误捕获范围。
- 逐key求值保证已测modifier的公共顶点域；任意shape-dependent Geometry Nodes在相同
  顶点数下重排顶点身份的语义未被证明。不同key得到不同顶点数时会明确失败。
- 自定义Blueprint Smile可能生成三个零字节native文件，但不在INI声明引用它们。
  正常payload链的资源正确性，不等于支持手工构造任意矛盾数据对象。

## 历史版本补证

另获取Package v1.1.0固定提交 `7b35c4c2478197361fbf9ccb92bb477440a9a4fe`，没有切换
当前v1.2.0副本。旧版 `WuWa-Model-Importer.ini:47/73/219/254` 以及
`Shaders/{BlendRemapper,SkeletonRemapper}.hlsl` 已声明并消费动态bone_count。
这证明最低版存在API，不声称该API恰在该版本首次引入。

## 验证边界

修复后常规回归：reverse metadata 30项、batch 32项（31通过／1可选fixture跳过）、
component 19项、多DrawIB INI 17项。最终Xin/MERGED、Xin/PER_COMPONENT均导出355434
indices；JinXi三个贴图节点再次通过格式及替换字节检查。日志为
`tmp/review-final-{merged,local,textures,multi}.log`、`tmp/review-components.log`。

这是代码、缓冲和生成INI的离线对抗审查。没有用户截图原工程，也没有游戏内渲染验证。
source快照只保证明确覆盖的字段，不扩展为任意UI、UV、normal或系统级全部文件写入监测。
审查通过不是不存在其他缺陷的证明，源代码、输入样本或游戏版本变化后需重新判断。
