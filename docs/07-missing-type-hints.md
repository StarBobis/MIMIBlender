# 07 - Missing Type Annotations

## Severity

🟡 **Medium** - Parameters and return values in some files lack type annotations: the IDE cannot autocomplete, and newcomers do not know which types to pass.

## Scope of Impact

### Files completely missing type annotations

| File | Lines | Description |
|------|:----:|------|
| `utils/vertexgroup_utils.py` | 230 | Almost no type annotations |
| `utils/mesh_utils.py` | 200+ | Some methods annotated, some not |
| `games/unity.py` | 200+ | `__init__` and several methods have no types |
| `games/wwmi.py` | 700+ | `__init__` untyped; some internal methods annotated |

### Key methods only partially annotated

| File | Method | Problem |
|------|------|------|
| `utils/obj_utils.py` | `merge_objects(obj_list, target_collection=None)` | Is `obj_list` a `list[bpy.types.Object]` or a `list[str]`? |
| `utils/obj_utils.py` | `copy_object(context, obj, name=None, collection=None)` | What type is `context`? Is `obj` an Object or a str? |
| `utils/collection_utils.py` | `create_new_collection(collection_name, color_tag, link_to_parent_collection_name="")` | What values can `color_tag` take? |
| `common/m_ini_helper.py` | `_get_slot_texture_source_path(draw_ib_model, part_name, texture_markup_info)` | What type is `texture_markup_info`? |
| `games/wwmi.py` | `__init__(self, blueprint_model)` | What type is `blueprint_model`? |

### Missing return types

Many methods do not annotate their return value, including key export methods:

| File | Method | Return type |
|------|------|----------|
| `model/drawib_model_wwmi.py` | `build_merged_object()` | Returns `MergedObject` but is unannotated |
| `common/buffer_export_helper.py` | `write_buf_ib_r32_uint()` | No return type |
| `model/submesh_model.py` | `calc_buffer()` | Returns None but is unannotated |

## Proposed Fix

### Principles

1. All public methods must annotate parameter types and return types.
2. Private methods (`_method_name`) must at minimum annotate parameter types.
3. Use the standard types from the `typing` module: `List`, `Dict`, `Optional`, `Union`.
4. Use Blender types such as `bpy.types.Object`, `bpy.types.Mesh`.

### Fix template

```python
# Before
def merge_objects(obj_list, target_collection=None):
    """Merge the given list of objects."""
    ...

# After
def merge_objects(
    obj_list: list[bpy.types.Object],
    target_collection: bpy.types.Collection | None = None
) -> None:
    """Merge the given list of objects."""
    ...
```

### Quick reference of common Blender types

| Python annotation | Blender type | Description |
|-------------|-------------|------|
| `bpy.types.Object` | 3D object | Any object in the scene |
| `bpy.types.Mesh` | Mesh data | `.data` attribute |
| `bpy.types.Collection` | Collection | Container for objects |
| `bpy.types.Material` | Material | Object material |
| `bpy.types.NodeTree` | Node tree | A tree in the Blueprint editor |
| `bpy.types.Node` | Node | A single node in the Blueprint editor |
| `bpy.types.Context` | Context | Blender's Context object |
| `bpy.types.VertexGroup` | Vertex group | A vertex group on an object |
| `bpy.types.ShapeKey` | Shape key | shape key |
| `bmesh.types.BMesh` | BMesh | Low-level mesh editing |

### Project-specific custom types

| Python annotation | Type | Defined in |
|-------------|------|----------|
| `DrawCallModel` | Draw call model | `model/draw_call_model.py` |
| `SubMeshModel` | Submesh model | `model/submesh_model.py` |
| `DrawIBModel` | DrawIB model | `model/drawib_model.py` |
| `BluePrintModel` | Blueprint model | `model/blueprint_model.py` |
| `WorkSpaceModel` | Workspace model | `workspace/ssmt_workspace.py` |
| `D3D11GameType` | D3D11 game type | `common/d3d11_gametype.py` |

### Priorities

| Priority | File | Reason |
|:------:|------|------|
| **High** | `utils/obj_utils.py` | Referenced across the whole project; annotations yield the biggest benefit |
| **High** | `games/unity.py` | Base class that affects all game exporters |
| **Medium** | `common/m_ini_helper.py` | Complex INI generation logic |
| **Medium** | `utils/collection_utils.py` | Utility class used project-wide |
| **Low** | `utils/vertexgroup_utils.py` | Used less frequently |

## Verification

```bash
# Check types with mypy (requires installing mypy)
pip install mypy
mypy d:\Dev\MIMIBlender --ignore-missing-imports
```

## Risks

- **Low**: adding type annotations does not change runtime behavior
- The only risk: incorrect annotations mislead developers. Confirm the actual types carefully before annotating
