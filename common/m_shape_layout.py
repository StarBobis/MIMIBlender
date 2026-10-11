"""Match shape shaders to explicit Position layouts before dispatch.

A stride alone is insufficient: a packed NORMAL at offset 12 cannot be read
as float3. Keep the supported layouts small and explicit instead of silently
reinterpreting packed data. Other layouts require a format-aware shader.
"""


def shape_shader_for_layout(game_type):
    """Return the shader filename or fail before producing corrupt output.

    Both shaders operate on full-weight shape buffers, not delta files.
    The 12-byte variant intentionally animates only Position; vector data in
    separate categories is outside the shared shape pipeline's contract.
    """
    if game_type is None:
        raise ValueError("Shape keys require a Position data layout")
    elements = []
    for element in game_type.D3D11ElementList:
        if element.Category == "Position":
            elements.append((element.SemanticName, element.Format, int(element.ByteWidth)))
    # Compare ordered semantics and widths as well as the exported stride.
    # This rejects packed formats, extra fields and reordered declarations.
    position = [("POSITION", "R32G32B32_FLOAT", 12)]
    full = position + [("NORMAL", "R32G32B32_FLOAT", 12), ("TANGENT", "R32G32B32A32_FLOAT", 16)]
    stride = game_type.CategoryStrideDict.get("Position", 0)
    if elements == position and stride == 12:
        return "shapes_position.hlsl"
    if elements == full and stride == 40:
        return "Shapes.hlsl"
    raise ValueError("Unsupported shape key Position layout; use DrawIndexed animation or a supported float32 layout")
