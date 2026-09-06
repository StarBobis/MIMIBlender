# 02 - Wildcard Imports (from module import *)

## Severity

🔴 **Fatal** - pollutes the module namespace and pulls in 50+ unexpected symbols; IDEs cannot trace their origin, and a newcomer who defines a same-named function will hit baffling errors.

## Scope

| File | Line | Wildcard import | Source module |
|------|:----:|-----------|----------|
| `utils/obj_utils.py` | 7 | `from mathutils import *` | Blender math utilities |
| `utils/obj_utils.py` | 8 | `from math import *` | Python standard library math |
| `utils/algorithm_utils.py` | 4 | `from mathutils import *` | Blender math utilities |
| `common/m_ini_helper.py` | 4 | `from .m_ini_builder import *` | Project-internal module |
| `common/m_ini_helper_gui.py` | 5 | `from .m_ini_builder import *` | Project-internal module |

## Problem Detail

### `from math import *` (obj_utils.py:8)

Imports **50+ symbols** from Python's `math` module: `sin`, `cos`, `tan`, `sqrt`, `pi`, `e`, `floor`, `ceil`, `log`, `exp`, `pow`, `degrees`, `radians` and so on.

**Consequences**:
- If someone defines `def degrees(x)` or a variable `pi = 3.14` inside `obj_utils.py`, it will collide with the imported `math.degrees` / `math.pi`
- IDEs cannot trace where these symbols come from (`Go to Definition` breaks)
- The symbols brought in by `import *` can grow or shrink between Python versions

### `from mathutils import *` (obj_utils.py:7, algorithm_utils.py:4)

Imports every symbol of Blender's `mathutils` module: `Vector`, `Matrix`, `Quaternion`, `Euler`, `Color`, the `geometry` submodule, and so on.

**Consequences**:
- `Vector` gets pulled into the module namespace - if the project ever defines a `class Vector`, they will collide
- In practice the project never uses `mathutils.Vector` (it uses Blender's bpy types), so these imports are redundant

### `from .m_ini_builder import *` (m_ini_helper.py:4, m_ini_helper_gui.py:5)

Imports every public symbol of the project-internal module `m_ini_builder`.

**Consequences**:
- It is unclear which functions/classes `m_ini_builder` provides
- If someone adds a new function to `m_ini_builder`, it will silently pollute every importer
- If the `__all__` list is not maintained, the import behavior becomes unpredictable

## Fix Plan

### Principles

1. List each symbol that is actually needed and import it explicitly
2. If a large number of symbols is genuinely required, `import module` and access them as `module.symbol`

### Before/After Comparison

#### `utils/obj_utils.py`

First determine which math/mathutils symbols obj_utils.py actually uses:
- `bmesh` (already imported separately, unaffected)
- `itemgetter` (already imported via its own `from operator import`, unaffected)
- It may indirectly use `math.radians`, `math.pi`, etc. - this needs a code review to confirm

```python
# Before the fix (lines 7-8)
from mathutils import *
from math import *

# After the fix - Option A (import only what is actually used)
# Drop the wildcard imports and audit every math.xxx / mathutils.xxx usage in the code
# If only radians and pi are used:
from math import radians, pi

# After the fix - Option B (call through the module prefix)
import math
# In code: math.radians(x), math.pi, math.sin(x), etc.
```

**How to confirm actual usage**:
```bash
# Search obj_utils.py for uses with the math. and mathutils. prefixes
grep -n "math\." d:\Dev\MIMIBlender\utils\obj_utils.py
grep -n "mathutils\." d:\Dev\MIMIBlender\utils\obj_utils.py
# Search for prefix-less calls (meaning they come from the wildcard imports)
grep -n "\bradians\b\|\bdegrees\b\|\bpi\b\|\bsin\b\|\bcos\b\|\bsqrt\b" d:\Dev\MIMIBlender\utils\obj_utils.py
```

#### `utils/algorithm_utils.py`

```python
# Before the fix (line 4)
from mathutils import *

# After the fix
# Remove the line - algorithm_utils.py may not use mathutils at all
```

#### `common/m_ini_helper.py` and `common/m_ini_helper_gui.py`

```python
# Before the fix
from .m_ini_builder import *

# After the fix - check m_ini_builder's __all__ or explicitly list the symbols used
from .m_ini_builder import (
    M_IniBuilder,
    M_SectionType,
    M_IniSection,
)
```

## How to Verify

1. Comment out the wildcard imports and run Blender import/export.
2. If a `NameError: name 'xxx' is not defined` appears, add the matching explicit import.
3. Detect these automatically with flake8's F403/F405 rules:
```bash
pip install flake8
flake8 --select F403,F405 d:\Dev\MIMIBlender
```

## Risks

- Each file's actual use of wildcard-imported symbols must be carefully confirmed, otherwise `NameError`s will be introduced.
- Recommended to modify and test one file at a time instead of changing everything at once.
