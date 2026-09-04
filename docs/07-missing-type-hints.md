# 07 — 类型标注缺失

## 严重程度

🟡 **中等** — 部分文件的函数参数和返回值缺少类型标注，IDE 无法补全，新人不知道传什么类型。

## 影响范围

### 完全缺失类型标注的文件

| 文件 | 行数 | 说明 |
|------|:----:|------|
| `utils/vertexgroup_utils.py` | 230 | 几乎零类型标注 |
| `utils/mesh_utils.py` | 200+ | 部分方法有，部分没有 |
| `games/unity.py` | 200+ | `__init__` 和多个方法无类型 |
| `games/wwmi.py` | 700+ | `__init__` 无类型，内部方法部分有 |

### 部分缺失的关键方法

| 文件 | 方法 | 问题 |
|------|------|------|
| `utils/obj_utils.py` | `merge_objects(obj_list, target_collection=None)` | `obj_list` 是 `list[bpy.types.Object]` 还是 `list[str]`？ |
| `utils/obj_utils.py` | `copy_object(context, obj, name=None, collection=None)` | `context` 是什么类型？`obj` 是 Object 还是 str？ |
| `utils/collection_utils.py` | `create_new_collection(collection_name, color_tag, link_to_parent_collection_name="")` | `color_tag` 的取值是什么？ |
| `common/m_ini_helper.py` | `_get_slot_texture_source_path(draw_ib_model, part_name, texture_markup_info)` | `texture_markup_info` 的类型？ |
| `games/wwmi.py` | `__init__(self, blueprint_model)` | `blueprint_model` 的类型？ |

### 返回类型缺失

很多方法没有标注返回值类型，包括关键的导出方法：

| 文件 | 方法 | 返回类型 |
|------|------|----------|
| `model/drawib_model_wwmi.py` | `build_merged_object()` | 返回 `MergedObject` 但未标注 |
| `common/buffer_export_helper.py` | `write_buf_ib_r32_uint()` | 无返回类型 |
| `model/submesh_model.py` | `calc_buffer()` | 返回 None 但未标注 |

## 修复方案

### 原则

1. 所有公共方法必须标注参数类型和返回类型
2. 私有方法（`_method_name`）最低标注参数类型
3. 使用 `typing` 模块的标准类型：`List`, `Dict`, `Optional`, `Union`
4. Blender 类型使用 `bpy.types.Object`, `bpy.types.Mesh` 等

### 修复模板

```python
# 修复前
def merge_objects(obj_list, target_collection=None):
    """合并给定的对象列表。"""
    ...

# 修复后
def merge_objects(
    obj_list: list[bpy.types.Object],
    target_collection: bpy.types.Collection | None = None
) -> None:
    """合并给定的对象列表。"""
    ...
```

### 常见 Blender 类型速查

| Python 标注 | Blender 类型 | 说明 |
|-------------|-------------|------|
| `bpy.types.Object` | 3D 物体 | 场景中的任何物体 |
| `bpy.types.Mesh` | 网格数据 | `.data` 属性 |
| `bpy.types.Collection` | 集合 | 物体容器 |
| `bpy.types.Material` | 材质 | 物体材质 |
| `bpy.types.NodeTree` | 节点树 | 蓝图编辑器中的树 |
| `bpy.types.Node` | 节点 | 蓝图编辑器中的单个节点 |
| `bpy.types.Context` | 上下文 | Blender 的 Context 对象 |
| `bpy.types.VertexGroup` | 顶点组 | 物体上的顶点组 |
| `bpy.types.ShapeKey` | 形态键 | shape key |
| `bmesh.types.BMesh` | BMesh | 底层网格编辑 |

### 项目自定义类型

| Python 标注 | 类型 | 定义位置 |
|-------------|------|----------|
| `DrawCallModel` | 绘制调用模型 | `model/draw_call_model.py` |
| `SubMeshModel` | 子网格模型 | `model/submesh_model.py` |
| `DrawIBModel` | DrawIB 模型 | `model/drawib_model.py` |
| `BluePrintModel` | 蓝图模型 | `model/blueprint_model.py` |
| `WorkSpaceModel` | 工作空间模型 | `workspace/ssmt_workspace.py` |
| `D3D11GameType` | D3D11 游戏类型 | `common/d3d11_gametype.py` |

### 优先级

| 优先级 | 文件 | 原因 |
|:------:|------|------|
| **高** | `utils/obj_utils.py` | 被全项目引用，类型标注收益最大 |
| **高** | `games/unity.py` | 基类，影响所有游戏导出器 |
| **中** | `common/m_ini_helper.py` | 复杂的 INI 生成逻辑 |
| **中** | `utils/collection_utils.py` | 全项目使用的工具类 |
| **低** | `utils/vertexgroup_utils.py` | 使用频率较低 |

## 验证方法

```bash
# 使用 mypy 检查类型（需要安装 mypy）
pip install mypy
mypy d:\Dev\TheHerta4 --ignore-missing-imports
```

## 风险

- **低**：添加类型标注不改变运行时行为
- 唯一风险：错误的类型标注会误导开发者。标注前需仔细确认实际类型
