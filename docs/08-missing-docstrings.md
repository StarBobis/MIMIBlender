# 08 — 游戏导出器基类缺少文档

## 严重程度

🟡 **中等** — 5 个游戏导出器类完全没有 docstring，新人想添加新游戏时不知道协议是什么。

## 问题清单

### 缺少 docstring 的类

| 文件 | 类名 | 行号 | 说明 |
|------|------|:----:|------|
| `games/unity.py` | `ExportUnity` | 14 | **基类**，被 GIMI/HIMI/SRMI/ZZMI 继承 |
| `games/gimi.py` | `ExportGIMI` | 18 | Genshin Impact（原神） |
| `games/himi.py` | `ExportHIMI` | 4 | Honkai Impact 3rd（崩坏3），`pass` 空类 |
| `games/wwmi.py` | `ExportWWMI` | 15 | Wuthering Waves（鸣潮），最复杂的导出器 |
| `games/ntemi.py` | `ExportNTEMI` | 39 | Neverness to Everness（异环） |
| `games/snowbreak.py` | `ExportSnowBreak` | 12 | Snowbreak（尘白禁区） |
| `games/identityv.py` | `ExportIdentityV` | 12 | Identity V（第五人格） |
| `games/yysls.py` | `ExportYYSLS` | 12 | Where Winds Meet（燕云十六声） |

### 已添加文档的类（良好示例）

| 文件 | 类名 | 说明 |
|------|------|------|
| `games/efmi.py` | `ExportEFMI` | ✅ 已有 docstring |
| `games/zzmi.py` | `ExportZZMI` | ✅ 已有 docstring |
| `games/srmi.py` | `ExportSRMI` | ✅ 已有 docstring |

## 为什么这很重要

一个新开发者想为项目添加新游戏支持。他们会：

1. 打开 `games/` 目录
2. 随机选一个导出器看代码
3. 发现 `ExportUnity.__init__` 接受一个 `blueprint_model` 参数
4. **困惑**：这个参数应该包含什么？`__init__` 里做了什么？必须重写哪些方法？

无文档的基类意味着新人必须**通读整个 200 行实现**才能理解协议。

## 修复方案

### ExportUnity 基类需要说明的内容

```python
@dataclass
class ExportUnity:
    '''
    Unity 引擎游戏导出器基类。

    职责：
    1. 从 BluePrintModel 解析所有 DrawIBModel 列表
    2. 为每个 DrawIB 生成 .buf 文件和 .ini 纹理覆盖段
    3. 应用 Submesh 别名到文件名

    子类需要重写的方法：
    - _get_drawib_submesh_entries(drawib_model)  — 返回每个 DrawIB 的子网格条目列表
    - _get_submesh_ib_resource_name(submesh_model) — 返回 IB 资源名（用于 INI）
    - _build_texture_override_ini(...)              — 构建纹理覆盖 INI 段

    子类可选重写：
    - _get_extra_ini_sections(...)  — 添加游戏特定的 INI 段

    生命周期：
    1. __post_init__()  → 调用 blueprint_model.parse_drawib_model_list()
    2. generate_mod_files() → 遍历每个 DrawIB，生成资源文件 + INI

    典型使用：
        exporter = ExportGIMI(blueprint_model)
        exporter.generate_mod_files()
    '''

    blueprint_model: BluePrintModel
    drawib_model_list: list[DrawIBModel] = field(default_factory=list, init=False)

    def __post_init__(self):
        ...
```

### 各子类需要的最小文档

```python
@dataclass
class ExportGIMI(ExportUnity):
    '''Genshin Impact（原神）Unity 引擎 3Dmigoto Mod 导出器。'''
    # 实现细节...

@dataclass
class ExportHIMI(ExportUnity):
    '''Honkai Impact 3rd（崩坏3）导出器。继承 ExportUnity，行为与 GIMI 相同。'''
    pass

@dataclass
class ExportWWMI:
    '''Wuthering Waves（鸣潮）Unreal 引擎导出器。

    与 Unity 引擎导出器的关键区别：
    - 使用 DrawIBModelWWMI 而非 DrawIBModel
    - 需要 WWMIInfoObject 来处理 VertexOffset/IndexOffset
    - 支持 MergedObject 的顶点组合并和 BlendRemap
    '''
    ...
```

### 文档模板

每个导出器类至少应包含：

```python
'''
{游戏中文名}（{游戏英文名}）{引擎名} 引擎 3Dmigoto Mod 导出器。

引擎类型: {Unity / Unreal / NeoX / Custom}
特殊处理:
  - {列出与基类的差异}
  - {列出游戏特有的 INI 格式差异}
  - {列出已知限制或 workaround}

关联 Issue: {GitHub issue 链接，如有}
'''
```

## 验证方法

1. 打开每个 `games/*.py`，确认类定义后紧跟 docstring
2. 让一个不熟悉项目的人阅读 `ExportUnity` 的 docstring，确认能否理解协议

## 风险

- **零风险**：纯文档添加，不影响运行时行为
