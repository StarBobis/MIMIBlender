# 10 - Long Methods

## Severity

🟢 **Low** - A few methods over 100 lines could be split up to improve testability and readability.

## Issue List

### blueprint/blueprint_node_menu.py - SSMT_OT_BatchConnectNodes (~200 lines)

**File**: `blueprint/blueprint_node_menu.py`  
**Lines**: approximately 550-750  
**Content**: an operator that batch-connects nodes, including the connection direction inference logic.

```python
class SSMT_OT_BatchConnectNodes(bpy.types.Operator):
    def execute(self, context):
        # gather the selected nodes...
        # separate input/output nodes...
        # infer the connection direction (7 branches)...
        # perform the connections...
        # refresh the UI...
```

**How to split it**:

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
        """Split the nodes into those with input sockets (input nodes) and those with output sockets (output nodes)."""
        ...

    @staticmethod
    def _infer_connect_direction(input_nodes, output_nodes):
        """Infer the connection direction from the node counts (one-to-one, many-to-one, one-to-many)."""
        ...

    @staticmethod
    def _perform_connection(input_nodes, output_nodes, direction):
        """Perform the actual link operation according to the direction."""
        ...
```

### common/m_ini_helper.py - generate_hash_style_texture_ini (~100 lines)

**File**: `common/m_ini_helper.py`  
**Content**: generates the "hash style" texture INI section. Its structure is almost identical to the method `generate_shared_slot_style_texture_ini`.

**Refactoring suggestion**: extract the shared logic into a helper method:

```python
@classmethod
def _iterate_drawib_textures(cls, draw_ib_model_list, texture_filter=None):
    """Iterate over the textures of all DrawIBs, yielding (submesh, texture_info, output_path) triples."""
    for draw_ib_model in draw_ib_model_list:
        for submesh_model in draw_ib_model.submesh_model_list:
            for texture_info in draw_ib_model.get_submesh_texture_markup_info_list(submesh_model):
                if texture_filter and not texture_filter(texture_info):
                    continue
                ...yield submesh_model, texture_info, ...

@classmethod
def generate_hash_style_texture_ini(cls, ...):
    for submesh, tex_info, path in cls._iterate_drawib_textures(draw_ib_model_list):
        ...  # hash-style specific logic

@classmethod
def generate_shared_slot_style_texture_ini(cls, ...):
    for submesh, tex_info, path in cls._iterate_drawib_textures(draw_ib_model_list):
        ...  # shared-slot specific logic
```

### common/m_ini_helper.py - add_shapekey_ini_sections (~100+ lines)

**File**: `common/m_ini_helper.py`  
**Content**: adds the shape-key-related INI sections, covering five cases: constants, present, custom shader, resource and key sections.

```python
@classmethod
def add_shapekey_ini_sections(cls, ...):
    # 1. write the [Constants] section
    ...
    # 2. write the [Present] section
    ...
    # 3. write the custom Shader section
    ...
    # 4. write the [Resource] section
    ...
    # 5. write the key mapping sections
    ...
```

**Refactoring suggestion**: give each section its own private method:

```python
@classmethod
def add_shapekey_ini_sections(cls, ...):
    cls._write_shapekey_constants(builder, ...)
    cls._write_shapekey_present(builder, ...)
    cls._write_shapekey_custom_shader(builder, ...)
    cls._write_shapekey_resources(builder, ...)
    cls._write_shapekey_key_sections(builder, ...)
```

### common/obj_buffer_helper.py - format-encoding if/elif chain (~80 lines)

**File**: `common/obj_buffer_helper.py`  
**Lines**: approximately 200-280  
**Content**: a very long `if/elif` chain handles the normal encoding for the different D3D11 formats.

**Refactoring suggestion**: replace the if/elif chain with a dictionary mapping:

```python
# Before
if format == 'R8G8B8A8_SNORM':
    normal_x = int(x * 127 + 127.5)
    normal_y = int(y * 127 + 127.5)
    ...
elif format == 'R16G16_FLOAT':
    normal_x = struct.pack('<H', ...)
    ...

# After
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

## Fix Priority

| Priority | Method | Reason |
|:------:|------|------|
| **Medium** | `generate_hash_style_texture_ini` and `generate_shared_slot_style_texture_ini` | The two 100-line methods share ~70% duplicated code |
| **Low** | `SSMT_OT_BatchConnectNodes.execute` | 200 lines but with clear internal functions; splitting yields limited benefit |
| **Low** | `add_shapekey_ini_sections` | 5 independent sections; splitting is natural but the current state is acceptable |
| **Low** | Format-encoding if/elif chain | 80 lines but the logic is simple; low maintenance cost |

## Verification

1. After splitting, run each part to confirm behavior is unchanged
2. Compare the INI output files before and after the split (diff)
