# 02 — 通配符 import（from module import *）

## 严重程度

🔴 **致命** — 污染模块命名空间，导入 50+ 个未预期的符号，IDE 无法追踪来源，新手定义同名函数会诡异报错。

## 影响范围

| 文件 | 行号 | 通配符导入 | 来源模块 |
|------|:----:|-----------|----------|
| `utils/obj_utils.py` | 7 | `from mathutils import *` | Blender 数学工具 |
| `utils/obj_utils.py` | 8 | `from math import *` | Python 标准库 math |
| `utils/algorithm_utils.py` | 4 | `from mathutils import *` | Blender 数学工具 |
| `common/m_ini_helper.py` | 4 | `from .m_ini_builder import *` | 项目内部模块 |
| `common/m_ini_helper_gui.py` | 5 | `from .m_ini_builder import *` | 项目内部模块 |

## 问题详解

### `from math import *`（obj_utils.py:8）

导入了 Python `math` 模块的 **50+ 个符号**：`sin`, `cos`, `tan`, `sqrt`, `pi`, `e`, `floor`, `ceil`, `log`, `exp`, `pow`, `degrees`, `radians` 等等。

**后果**：
- 如果有人在 `obj_utils.py` 中定义 `def degrees(x)` 或变量 `pi = 3.14`，会和导入的 `math.degrees` / `math.pi` 冲突
- IDE 无法追踪这些符号的来源（`Go to Definition` 失效）
- `import *` 的符号可能随 Python 版本变化而增减

### `from mathutils import *`（obj_utils.py:7, algorithm_utils.py:4）

导入了 Blender 的 `mathutils` 模块的全部符号：`Vector`, `Matrix`, `Quaternion`, `Euler`, `Color`, `geometry` 子模块等。

**后果**：
- `Vector` 被导入到模块命名空间——如果项目中定义了 `class Vector`，会冲突
- 实际上项目从不使用 `mathutils.Vector`（用的是 bpy Blender 类型），这些导入是冗余的

### `from .m_ini_builder import *`（m_ini_helper.py:4, m_ini_helper_gui.py:5）

导入了项目内部模块 `m_ini_builder` 的所有公开符号。

**后果**：
- 不知道 m_ini_builder 提供了哪些函数/类
- 如果有人往 m_ini_builder 加了一个新函数，会自动污染所有导入者
- `__all__` 列表如果不维护，导入行为不确定

## 修复方案

### 原则

1. 逐个列出实际需要的符号，显式 import
2. 如果确实需要大量符号，`import module` 然后用 `module.symbol` 调用

### 修复前后对比

#### `utils/obj_utils.py`

首先确定 obj_utils.py 实际使用了哪些 math/mathutils 符号：
- `bmesh`（已单独 import，不受影响）
- `itemgetter`（已单独 `from operator import`，不受影响）
- 可能间接使用了 `math.radians`、`math.pi` 等——需要代码审查确认

```python
# 修复前（行 7-8）
from mathutils import *
from math import *

# 修复后 — 方案 A（只导入实际使用的）
# 去掉通配符导入，检查代码中所有使用 math.xxx / mathutils.xxx 的地方
# 如果只用到了 radians 和 pi：
from math import radians, pi

# 修复后 — 方案 B（用模块前缀调用）
import math
# 代码中 math.radians(x), math.pi, math.sin(x) 等
```

**确认使用情况的方法**：
```bash
# 在 obj_utils.py 中搜索 math. 和 mathutils. 前缀的使用
grep -n "math\." d:\Dev\TheHerta4\utils\obj_utils.py
grep -n "mathutils\." d:\Dev\TheHerta4\utils\obj_utils.py
# 搜索不带前缀的调用（说明来自通配符导入）
grep -n "\bradians\b\|\bdegrees\b\|\bpi\b\|\bsin\b\|\bcos\b\|\bsqrt\b" d:\Dev\TheHerta4\utils\obj_utils.py
```

#### `utils/algorithm_utils.py`

```python
# 修复前（行 4）
from mathutils import *

# 修复后
# 移除该行——algorithm_utils.py 可能根本不使用 mathutils
```

#### `common/m_ini_helper.py` 和 `common/m_ini_helper_gui.py`

```python
# 修复前
from .m_ini_builder import *

# 修复后 — 检查 m_ini_builder 的 __all__ 或显式列出使用的符号
from .m_ini_builder import (
    M_IniBuilder,
    M_SectionType,
    M_IniSection,
)
```

## 验证方法

1. 注释掉通配符 import，运行 Blender 导入/导出
2. 如果出现 `NameError: name 'xxx' is not defined`，添加对应的显式 import
3. 用 flake8 的 F403/F405 规则自动检测：
```bash
pip install flake8
flake8 --select F403,F405 d:\Dev\TheHerta4
```

## 风险

- 需要仔细确认每个文件实际使用了哪些通配符导入的符号，否则会引入 `NameError`
- 建议逐个文件修改+测试，不要一次性全部改
