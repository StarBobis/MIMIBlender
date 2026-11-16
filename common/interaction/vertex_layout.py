"""The position layout the interaction shader can read.

The runtime compute shader views the position buffer as a fixed struct of
position, normal and tangent.  A preset may only use the interaction
deformation when its position category has exactly that layout, because a
packed normal or a different field order cannot be reinterpreted safely.

The check mirrors the one the shared shape key pipeline performs: the
semantics are compared by their byte offset and their format, and the
whole vertex must add up to the expected stride.
"""

# The semantic name mapped to its byte offset inside the vertex and to the
# format the shader expects at that offset.
DEFORM_SEMANTIC_DICT = {
    "POSITION": (0, "R32G32B32_FLOAT"),
    "NORMAL": (12, "R32G32B32_FLOAT"),
    "TANGENT": (24, "R32G32B32A32_FLOAT"),
}

# The vertex size the runtime shader reads: three float3 plus one float4.
DEFORM_VERTEX_STRIDE = 40


def collect_position_semantic_dict(game_type):
    """Return the semantic name mapped to its offset and format.

    The offsets are the running total of the byte widths of the elements
    that come before it, so the order of the declaration matters.
    """
    semantic_dict = {}
    if game_type is None:
        return semantic_dict

    stride = 0
    for element in game_type.D3D11ElementList:
        if element.Category != "Position":
            continue
        semantic_dict[element.SemanticName] = (stride, element.Format)
        stride += int(element.ByteWidth)

    return semantic_dict


def is_supported_deform_layout(game_type):
    """Return True when the position category matches the shader layout.

    The compute shader reads the vertex as a fixed struct, so every
    semantic has to sit at its exact byte offset in the expected format
    and the vertex stride has to be exactly the expected size.
    """
    if game_type is None:
        return False

    semantic_dict = collect_position_semantic_dict(game_type)
    stride = game_type.CategoryStrideDict.get("Position", 0)
    if stride != DEFORM_VERTEX_STRIDE:
        return False

    for semantic_name, expected_pair in DEFORM_SEMANTIC_DICT.items():
        if semantic_dict.get(semantic_name) != expected_pair:
            return False

    return True


def describe_unsupported_layout(game_type):
    """Return a short human readable reason for a rejected layout.

    The message names the layout that was found, so the user can tell a
    missing tangent from a differently packed normal.
    """
    if game_type is None:
        return "no position data layout"
    semantic_dict = collect_position_semantic_dict(game_type)
    found = []
    for semantic_name, pair in semantic_dict.items():
        found.append(semantic_name + "@" + str(pair[0]) + " " + str(pair[1]))
    stride = game_type.CategoryStrideDict.get("Position", 0)
    return "position stride " + str(stride) + " [" + ", ".join(found) + "]"
