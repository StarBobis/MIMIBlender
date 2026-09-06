"""D3D11 vertex-buffer semantic name constants.

Centralizes all semantic-name strings used in D3D11 Input Layouts so they
are not scattered across obj_buffer_helper.py and the various game exporters.

Usage:
    from ..common.d3d11_semantics import D3D11Semantic
    if d3d11_element_name.startswith(D3D11Semantic.COLOR):
"""


class D3D11Semantic:
    """D3D11 HLSL semantic name constants"""

    POSITION = "POSITION"
    NORMAL = "NORMAL"
    TANGENT = "TANGENT"
    BINORMAL = "BINORMAL"
    BITANGENT = "BINORMAL"

    COLOR = "COLOR"
    TEXCOORD = "TEXCOORD"

    BLENDINDICES = "BLENDINDICES"
    BLENDWEIGHTS = "BLENDWEIGHTS"

    SV_POSITION = "SV_POSITION"
    SV_INSTANCEID = "SV_INSTANCEID"
    SV_VERTEXID = "SV_VERTEXID"

    POSITIONT = "POSITIONT"
    TESSFACTOR = "TESSFACTOR"


class D3D11Format:
    """D3D11 DXGI format name constants"""

    R32G32B32A32_FLOAT = "R32G32B32A32_FLOAT"
    R32G32B32_FLOAT = "R32G32B32_FLOAT"
    R32G32_FLOAT = "R32G32_FLOAT"
    R32_FLOAT = "R32_FLOAT"

    R16G16B16A16_FLOAT = "R16G16B16A16_FLOAT"
    R16G16B16A16_SNORM = "R16G16B16A16_SNORM"
    R16G16_FLOAT = "R16G16_FLOAT"
    R16G16_SNORM = "R16G16_SNORM"
    R16G16_UNORM = "R16G16_UNORM"

    R8G8B8A8_UNORM = "R8G8B8A8_UNORM"
    R8G8B8A8_SNORM = "R8G8B8A8_SNORM"
    R8G8B8A8_UINT = "R8G8B8A8_UINT"
    R8G8B8A8_SINT = "R8G8B8A8_SINT"

    R8G8_UNORM = "R8G8_UNORM"
    R8G8_SNORM = "R8G8_SNORM"
    R8G8_UINT = "R8G8_UINT"

    R8_UNORM = "R8_UNORM"
    R8_UINT = "R8_UINT"

    R32_UINT = "R32_UINT"
    R32G32_UINT = "R32G32_UINT"
    R16_UINT = "R16_UINT"

    B8G8R8A8_UNORM = "B8G8R8A8_UNORM"


class D3D11Category:
    """D3D11 buffer category name constants; identify buffer purposes in the WWMI/Unreal engine."""

    POSITION = "Position"
    NORMAL = "Normal"
    TANGENT = "Tangent"
    BINORMAL = "Binormal"
    BLEND = "Blend"
    COLOR = "Color"
    TEXCOORD = "Texcoord"
