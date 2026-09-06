# 08 - Game Exporter Base Classes Missing Docstrings

## Severity

🟡 **Medium** - Five game exporter classes have no docstrings at all, so a newcomer who wants to add a new game does not know what the protocol is.

## Issue List

### Classes missing docstrings

| File | Class | Line | Description |
|------|------|:----:|------|
| `games/unity.py` | `ExportUnity` | 14 | **Base class**, inherited by GIMI/HIMI/SRMI/ZZMI |
| `games/gimi.py` | `ExportGIMI` | 18 | Genshin Impact |
| `games/himi.py` | `ExportHIMI` | 4 | Honkai Impact 3rd; an empty `pass` class |
| `games/wwmi.py` | `ExportWWMI` | 15 | Wuthering Waves; the most complex exporter |
| `games/ntemi.py` | `ExportNTEMI` | 39 | Neverness to Everness |
| `games/snowbreak.py` | `ExportSnowBreak` | 12 | Snowbreak |
| `games/identityv.py` | `ExportIdentityV` | 12 | Identity V |
| `games/yysls.py` | `ExportYYSLS` | 12 | Where Winds Meet |

### Classes that already have docstrings (good examples)

| File | Class | Description |
|------|------|------|
| `games/efmi.py` | `ExportEFMI` | ✅ Already has a docstring |
| `games/zzmi.py` | `ExportZZMI` | ✅ Already has a docstring |
| `games/srmi.py` | `ExportSRMI` | ✅ Already has a docstring |

## Why This Matters

A new developer wants to add support for a new game to the project. They will:

1. Open the `games/` directory
2. Pick an exporter at random and read its code
3. Find that `ExportUnity.__init__` accepts a `blueprint_model` parameter
4. **Get confused**: what should this parameter contain? What does `__init__` do? Which methods must be overridden?

An undocumented base class means newcomers must **read through the entire 200-line implementation** to understand the protocol.

## Proposed Fix

### What the ExportUnity base class docstring should cover

```python
@dataclass
class ExportUnity:
    '''
    Base class for Unity engine game exporters.

    Responsibilities:
    1. Parse the list of all DrawIBModels from the BluePrintModel
    2. Generate a .buf file and an .ini texture override section for each DrawIB
    3. Apply Submesh aliases to file names

    Methods subclasses must override:
    - _get_drawib_submesh_entries(drawib_model)   - return the submesh entry list for each DrawIB
    - _get_submesh_ib_resource_name(submesh_model) - return the IB resource name (used in the INI)
    - _build_texture_override_ini(...)             - build the texture override INI section

    Optional subclass overrides:
    - _get_extra_ini_sections(...)   - add game-specific INI sections

    Lifecycle:
    1. __post_init__()  -> calls blueprint_model.parse_drawib_model_list()
    2. generate_mod_files() -> iterates over each DrawIB, generating resource files + INI

    Typical usage:
        exporter = ExportGIMI(blueprint_model)
        exporter.generate_mod_files()
    '''

    blueprint_model: BluePrintModel
    drawib_model_list: list[DrawIBModel] = field(default_factory=list, init=False)

    def __post_init__(self):
        ...
```

### Minimal docstring for each subclass

```python
@dataclass
class ExportGIMI(ExportUnity):
    '''Genshin Impact Unity engine 3Dmigoto Mod exporter.'''
    # implementation details...

@dataclass
class ExportHIMI(ExportUnity):
    '''Honkai Impact 3rd exporter. Inherits ExportUnity, behaves the same as GIMI.'''
    pass

@dataclass
class ExportWWMI:
    '''Wuthering Waves Unreal engine exporter.

    Key differences from the Unity engine exporters:
    - Uses DrawIBModelWWMI instead of DrawIBModel
    - Needs WWMIInfoObject to handle VertexOffset/IndexOffset
    - Supports MergedObject vertex merging and BlendRemap
    '''
    ...
```

### Docstring template

Every exporter class should at least include:

```python
'''
{Chinese game name} ({English game name}) {engine name} engine 3Dmigoto Mod exporter.

Engine type: {Unity / Unreal / NeoX / Custom}
Special handling:
  - {list the differences from the base class}
  - {list game-specific INI format differences}
  - {list known limitations or workarounds}

Related Issue: {GitHub issue link, if any}
'''
```

## Verification

1. Open each `games/*.py` file and confirm that a docstring immediately follows the class definition
2. Have someone unfamiliar with the project read the `ExportUnity` docstring and confirm they can understand the protocol

## Risks

- **Zero risk**: docstring-only addition, runtime behavior is unaffected
