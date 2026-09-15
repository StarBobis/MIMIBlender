"""
Naraka shape key support (GPU pre-skinning compatible).

Why Naraka cannot reuse the generic shape key pipeline
(common/m_ini_helper.py + resources/Shapes.hlsl) as-is:

- The generic pipeline finishes its compute work with
  "Resource<DrawIB>Position = ref cs-u5", re-pointing the position
  resource at a *structured* buffer copy. CPU pre-skinning games bind that
  resource as a vertex buffer, where the underlying view type does not
  matter, so the generic pipeline works for them.
- Naraka skins its meshes on the GPU: Resource<DrawIB>Position is fed
  into the game's own skinning compute shader, which reads it as a raw
  ByteAddressBuffer. Re-pointing it at a structured copy is incompatible
  with that raw view, so the shape keys never reach the rendered mesh.

The Naraka variant keeps using the exact same Shapes.hlsl compute shader
and the exact same structured working buffers; only the final step
changes: instead of re-pointing the resource ("ref"), the accumulated
result is *copied* ("copy") back into the original raw position buffer.
CopyResource moves raw bytes between buffers of equal size regardless of
their view types, so:

- Resource<DrawIB>Position keeps its identity and its raw views forever,
  and the game's skinning compute shader always reads the layout it
  expects.
- Resource<DrawIB>Position.1 is a second resource declaration that points
  at the same Position buffer file but with "type = buffer" (structured),
  which is valid INI syntax; it acts as the pristine base the compute
  shader starts from every frame, so hotkey driven weights apply
  immediately and errors never accumulate across frames.
"""

import os
import shutil

from ...common.global_config import GlobalConfig
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...blueprint.blueprint_export_helper import BlueprintExportHelper


# Shapes.hlsl reads every vertex as a fixed 40-byte struct
# (float3 position + float3 normal + float4 tangent), so the Position
# category of the game type must match that exact layout. Naraka
# extractions always do (GPU_P12_N12_TA16_* types); anything else is
# reported and skipped instead of producing a broken mod.
EXPECTED_LAYOUT_DICT = {
    # semantic name -> (expected byte offset inside the vertex, format)
    "POSITION": (0, "R32G32B32_FLOAT"),
    "NORMAL": (12, "R32G32B32_FLOAT"),
    "TANGENT": (24, "R32G32B32A32_FLOAT"),
}
EXPECTED_POSITION_STRIDE = 40


def is_supported_position_layout(d3d11_game_type) -> bool:
    """Return True when the Position category matches the Shapes.hlsl layout.

    The compute shader views the buffer as a fixed struct, so POSITION,
    NORMAL and TANGENT must sit at their exact byte offsets in float32
    format and the vertex stride must be exactly 40 bytes.
    """
    if d3d11_game_type is None:
        return False

    # Walk the Position category elements in declaration order; every
    # element's byte offset is the running total of the previous widths.
    stride = 0
    semantic_offset_dict = {}
    semantic_format_dict = {}
    for d3d11_element in d3d11_game_type.D3D11ElementList:
        if d3d11_element.Category != "Position":
            continue
        semantic_offset_dict[d3d11_element.SemanticName] = stride
        semantic_format_dict[d3d11_element.SemanticName] = d3d11_element.Format
        stride += int(d3d11_element.ByteWidth)

    # The whole vertex must be exactly the 40-byte struct the shader reads.
    if stride != EXPECTED_POSITION_STRIDE:
        return False

    # Every expected semantic must sit at its hard-coded offset and format.
    for semantic_name, (expected_offset, expected_format) in EXPECTED_LAYOUT_DICT.items():
        if semantic_offset_dict.get(semantic_name) != expected_offset:
            return False
        if semantic_format_dict.get(semantic_name) != expected_format:
            return False

    return True


def collect_usable_drawib_list(drawib_drawibmodel_dict: dict) -> list:
    """Collect the DrawIBs whose shape keys can run on the Naraka pipeline.

    Returns the list of DrawIB models that actually carry shape key buffers
    and have a Position layout the compute shader understands. Other
    DrawIBs are reported and skipped so the base mod keeps working.
    """
    usable_drawib_list = []

    for drawib, drawib_model in drawib_drawibmodel_dict.items():
        shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
        if not shapekey_buffer_dict:
            continue

        if not is_supported_position_layout(getattr(drawib_model, "d3d11_game_type", None)):
            print("Naraka shape keys: DrawIB " + drawib
                  + " has an unsupported Position category layout, its shape keys are skipped")
            continue

        usable_drawib_list.append(drawib_model)

    return usable_drawib_list


def copy_shapes_hlsl_to_mod_folder():
    """Copy the shared Shapes.hlsl next to the generated mod INI."""
    # This file lives in games/naraka/, so the addon root is three levels up.
    addon_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = os.path.join(addon_root, "resources", "Shapes.hlsl")
    # Flat layout: shaders are copied next to the generated INI, no res subfolder.
    dst_dir = GlobalConfig.path_generate_mod_folder()
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copy2(src, os.path.join(dst_dir, "Shapes.hlsl"))


def add_naraka_shapekey_ini_sections(ini_builder: M_IniBuilder, drawib_drawibmodel_dict: dict):
    """Append every shape key section of a Naraka mod to the INI builder."""
    shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
    if len(shapekeyname_mkey_dict.keys()) == 0:
        return

    usable_drawib_list = collect_usable_drawib_list(drawib_drawibmodel_dict)
    if not usable_drawib_list:
        return

    copy_shapes_hlsl_to_mod_folder()

    # [Constants]: one persisted weight variable per configured shape key.
    constants_section = M_IniSection(M_SectionType.Constants)
    constants_section.append("[Constants]")
    for shapekey_name, m_key in shapekeyname_mkey_dict.items():
        constants_section.append("; ShapeKey: " + shapekey_name)
        constants_section.append("global persist " + m_key.key_name + " = " + str(m_key.initialize_value))
        constants_section.new_line()
    ini_builder.append_section(constants_section)

    # [Present]: re-run the compute command lists every frame, so hotkey
    # weight changes take effect at once. Each command list starts from the
    # pristine base copy, so no explicit restore step is needed here.
    present_section = M_IniSection(M_SectionType.Present)
    present_section.append("[Present]")
    for drawib_index, drawib_model in enumerate(usable_drawib_list):
        present_section.append("run = CustomShaderComputeShapesNaraka" + str(drawib_index + 1))
    ini_builder.append_section(present_section)

    # [CustomShaderComputeShapesNarakaN]: one command list per DrawIB.
    customshader_section = M_IniSection(M_SectionType.CommandList)
    for drawib_index, drawib_model in enumerate(usable_drawib_list):
        drawib = drawib_model.draw_ib
        shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
        draw_number = getattr(drawib_model, "draw_number", getattr(drawib_model, "vertex_count", 0))

        customshader_section.append("[CustomShaderComputeShapesNaraka" + str(drawib_index + 1) + "]")
        customshader_section.append("cs = Shapes.hlsl")
        # u5 is a fresh structured copy of the pristine base buffer; every
        # shape key dispatch accumulates its weighted difference onto it.
        customshader_section.append("cs-u5 = copy Resource" + drawib + "Position.1")
        customshader_section.new_line()

        # One dispatch per shape key that actually exists on this DrawIB.
        for shapekey_name, m_key in shapekeyname_mkey_dict.items():
            # A DrawIB that lacks this shape key must not reference its
            # resource, otherwise models without the key would malfunction.
            if shapekey_buffer_dict.get(shapekey_name, None) is None:
                continue

            customshader_section.append("; ShapeKey: " + shapekey_name)
            customshader_section.append("x88 = " + m_key.key_name)
            customshader_section.append("cs-t50 = Resource" + drawib + "Position.1")
            customshader_section.append("cs-t51 = Resource" + drawib + "Position." + shapekey_name)
            customshader_section.append("dispatch = " + str(draw_number) + ",1,1")
            customshader_section.new_line()

        # The crucial difference from the generic pipeline: copy the result
        # back into the original raw position buffer instead of re-pointing
        # the resource at the structured copy, so the game's skinning
        # compute shader keeps reading the ByteAddressBuffer it expects.
        customshader_section.append("Resource" + drawib + "Position = copy cs-u5")

        # Unbind everything so later game work never sees our buffers; the
        # temporary copy behind cs-u5 is released, its bytes already live
        # in the game-facing position buffer.
        customshader_section.append("cs-u5 = null")
        customshader_section.append("cs-t50 = null")
        customshader_section.append("cs-t51 = null")
        customshader_section.new_line()
    ini_builder.append_section(customshader_section)

    # [Resource...]: the pristine base copy plus one buffer per shape key.
    # Both are declared with "type = buffer" (structured, stride 40), which
    # is what the compute shader's StructuredBuffer views require; the raw
    # game-facing buffer keeps its own separate ByteAddressBuffer
    # declaration from the base pipeline.
    resource_section = M_IniSection(M_SectionType.ResourceBuffer)
    for drawib_model in usable_drawib_list:
        drawib = drawib_model.draw_ib
        shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
        position_stride = drawib_model.d3d11_game_type.CategoryStrideDict["Position"]

        # The pristine base copy: same Position file as the game-facing
        # buffer, just declared as a structured buffer.
        resource_section.append("[Resource" + drawib + "Position.1]")
        resource_section.append("type = buffer")
        resource_section.append("stride = " + str(position_stride))
        resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(
            drawib_model.get_category_buffer_filename("Position")))
        resource_section.new_line()

        # One buffer per shape key, holding the Position-category bytes of
        # the mesh with that key at full weight.
        for shapekey_name, m_key in shapekeyname_mkey_dict.items():
            if shapekey_buffer_dict.get(shapekey_name, None) is None:
                continue
            resource_section.append("[Resource" + drawib + "Position." + shapekey_name + "]")
            resource_section.append("type = buffer")
            resource_section.append("stride = " + str(position_stride))
            resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(
                drawib + "-Position." + shapekey_name + ".buf"))
            resource_section.new_line()
    ini_builder.append_section(resource_section)

    # [Key_ShapeKey_...]: press-to-cycle hotkeys, one per configured key;
    # also useful for quick testing when no toggle panel exists.
    key_section = M_IniSection(M_SectionType.Key)
    for shapekey_name, m_key in shapekeyname_mkey_dict.items():
        if m_key.initialize_vk_str == "":
            continue

        key_section.append("[Key_ShapeKey_" + shapekey_name + "]")
        comment = getattr(m_key, "comment", "")
        if comment:
            key_section.append("; " + comment)
        key_section.append("key = " + m_key.initialize_vk_str)
        key_section.append("type = cycle")
        key_section.append(m_key.key_name + " = 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1")
        key_section.new_line()
    ini_builder.append_section(key_section)
