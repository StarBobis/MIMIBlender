# 10 — 过长方法（Long Methods）

## 严重程度

🟢 **低** — 几个 100+ 行的方法可以拆分，提高可测试性和可读性。

## 问题清单

### blueprint_node_menu.py — SSMT_OT_BatchConnectNodes（~200 行）

**文件**：`blueprint/blueprint_node_menu.py`  
**行号**：约 550-750  
**内容**：批量连接节点的操作符，包含连接方向推断逻辑。

```python
class SSMT_OT_BatchConnectNodes(bpy.types.Operator):
    def execute(self, context):
        # 获取选中的节点...
        # 分离输入/输出节点...
        # 推断连接方向（7 个分支）...
        # 执行连接...
        # 刷新 UI...
```

**可拆分方向**：

```python
class SSMT_OT_BatchConnectNodes(bpy.types.Operator):
    def execute(self, context):
        nodes = self._get_selected_socket_nodes(context)
        if not nodes:
            return {'CANCELLED'}
        input_nodes, output_nodes = self._classify_nodes(nodes)
        direction = self._infer_connect_direction(input_nodes, output_nodes)
        self._perform_connection(input_nodes, output_nodes, direction)
        return {'FINISHED'}

    @staticmethod
    def _classify_nodes(nodes):
        """将节点分为有输入插槽的（输入节点）和有输出插槽的（输出节点）。"""
        ...

    @staticmethod
    def _infer_connect_direction(input_nodes, output_nodes):
        """根据节点数量推断连接方向（一对一、多对一、一对多）。"""
        ...
    
    @staticmethod
    def _perform_connection(input_nodes, output_nodes, direction):
        """根据方向执行实际连线操作。"""
        ...
```

### common/m_ini_helper.py — generate_hash_style_texture_ini（~100 行）

**文件**：`common/m_ini_helper.py`  
**内容**：生成"hash 风格"纹理 INI 段。与方法 `generate_shared_slot_style_texture_ini` 结构几乎相同。

**重构建议**：提取公共逻辑到辅助方法：

```python
@classmethod
def _iterate_drawib_textures(cls, draw_ib_model_list, texture_filter=None):
    """遍历所有 DrawIB 的贴图，生成 (submesh, texture_info, output_path) 三元组。"""
    for draw_ib_model in draw_ib_model_list:
        for submesh_model in draw_ib_model.submesh_model_list:
            for texture_info in draw_ib_model.get_submesh_texture_markup_info_list(submesh_model):
                if texture_filter and not texture_filter(texture_info):
                    continue
                ...yield submesh_model, texture_info, ...

@classmethod
def generate_hash_style_texture_ini(cls, ...):
    for submesh, tex_info, path in cls._iterate_drawib_textures(draw_ib_model_list):
        ...  # hash-style 特有逻辑

@classmethod
def generate_shared_slot_style_texture_ini(cls, ...):
    for submesh, tex_info, path in cls._iterate_drawib_textures(draw_ib_model_list):
        ...  # shared-slot 特有逻辑
```

### common/m_ini_helper.py — add_shapekey_ini_sections（~100+ 行）

**文件**：`common/m_ini_helper.py`  
**内容**：添加形态键相关的 INI 段，处理 constants、present、custom shader、resource、key sections 五种情况。

```python
@classmethod
def add_shapekey_ini_sections(cls, ...):
    # 1. 写入 [Constants] 段
    ...
    # 2. 写入 [Present] 段
    ...
    # 3. 写入自定义 Shader 段
    ...
    # 4. 写入 [Resource] 段
    ...
    # 5. 写入按键映射段
    ...
```

**重构建议**：每个段独立为一个私有方法：

```python
@classmethod
def add_shapekey_ini_sections(cls, ...):
    cls._write_shapekey_constants(builder, ...)
    cls._write_shapekey_present(builder, ...)
    cls._write_shapekey_custom_shader(builder, ...)
    cls._write_shapekey_resources(builder, ...)
    cls._write_shapekey_key_sections(builder, ...)
```

### common/obj_buffer_helper.py — 格式编码 if/elif 链（~80 行）

**文件**：`common/obj_buffer_helper.py`  
**行号**：约 200-280  
**内容**：一个很长的 `if/elif` 链处理不同 D3D11 格式的法线编码。

**重构建议**：使用字典映射代替 if/elif 链：

```python
# 修复前
if format == 'R8G8B8A8_SNORM':
    normal_x = int(x * 127 + 127.5)
    normal_y = int(y * 127 + 127.5)
    ...
elif format == 'R16G16_FLOAT':
    normal_x = struct.pack('<H', ...)
    ...

# 修复后
NORMAL_ENCODERS = {
    'R8G8B8A8_SNORM': lambda x, y, z: (...),
    'R16G16_FLOAT': lambda x, y, z: (...),
}

encoder = NORMAL_ENCODERS.get(format)
if encoder:
    data = encoder(normal_x, normal_y, normal_z)
else:
    raise ValueError(f"Unknown normal format: {format}")
```

## 修复优先级

| 优先级 | 方法 | 原因 |
|:------:|------|------|
| **中** | `generate_hash_style_texture_ini` 与 `generate_shared_slot_style_texture_ini` | 两个 100 行方法有 ~70% 代码重复 |
| **低** | `SSMT_OT_BatchConnectNodes.execute` | 200 行但有清晰的内部函数，拆分收益一般 |
| **低** | `add_shapekey_ini_sections` | 5 个独立段，拆分自然但当前可接受 |
| **低** | 格式编码 if/elif 链 | 80 行但逻辑简单，维护成本低 |

## 验证方法

1. 拆分后逐段运行，确认行为不变
2. 对比拆分前后的 INI 输出文件（diff）
