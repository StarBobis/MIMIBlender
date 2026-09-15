"""
Naraka shape key support (GPU pre-skinning compatible).

Why Naraka cannot reuse the generic shape key pipeline
(common/m_ini_helper.py + resources/Shapes.hlsl) as-is:

- The generic pipeline finishes its compute work with
  "Resource<DrawIB>Position = ref cs-u5", re-pointing the position
  resource at a *structured* buffer copy, and it runs at [Present] time.
  CPU pre-skinning games bind that resource as a vertex buffer, where the
  underlying view type does not matter, so the generic pipeline works
  there.
- Naraka skins its meshes on the GPU: Resource<DrawIB>Position is fed
  into the game's own skinning compute shader, which reads it as a raw
  ByteAddressBuffer. Re-pointing it at a structured copy is incompatible
  with that raw view, so the shape keys never reach the rendered mesh.

The Naraka variant instead hooks the shape key compute into the Position
VB override itself, so the whole sequence happens in one place, right
 before the game re-dispatches its skinning compute shader:

    [TextureOverride_VB_<DrawIB>_<Alias>_Position]
    hash = ...
    run = CustomShaderComputeShapesNarakaN   ; shape keys applied here
    cs-cb0 = Resource_<DrawIB>_VertexLimit
    cs-t0 = Resource<DrawIB>Position         ; already holds the result
    cs-t1 = Resource<DrawIB>Blend
    handling = skip
    dispatch = ...

Inside the command list, the compute uses the shared Shapes.hlsl and
explicit StructuredBuffer inputs. "Buffer" is a different 3Dmigoto type;
adding a stride does not make a referenced SRV a structured buffer.

1. "Resource<DrawIB>PositionComputed = copy cs-u5" copies the result into
   a ByteAddressBuffer with "misc_flags = buffer_allow_raw_views".
   3Dmigoto rebuilds copy destinations from the source descriptor, so the
   explicit misc_flags override is essential: type alone only ADDS the
   raw flag and would leave the incompatible structured flag inherited.
2. "Resource<DrawIB>Position = ref Resource<DrawIB>PositionComputed"
   binds that raw result for the game's skinning shader. A reference is
   safe here because the intermediate resource already has raw views.

The pristine Resource<DrawIB>Position.1 is explicitly a StructuredBuffer
loaded from the same Position file. Every run starts from it so weights
never accumulate across repeated overrides. Scratch compute resource slots
are saved and restored because CustomShader only restores shaders and OM
output state, not CS SRVs or CS UAVs.
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


def collect_usable_drawib_model_list(drawib_model_list: list) -> list:
    """Collect the DrawIB models whose shape keys can run on Naraka.

    Returns the DrawIB models that actually carry shape key buffers and
    have a Position layout the compute shader understands. Other DrawIBs
    are reported and skipped so the base mod keeps working.
    """
    usable_drawib_model_list = []

    for drawib_model in drawib_model_list:
        drawib = drawib_model.draw_ib
        shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
        if not shapekey_buffer_dict:
            continue

        if not is_supported_position_layout(getattr(drawib_model, "d3d11_game_type", None)):
            print("Naraka shape keys: DrawIB " + drawib
                  + " has an unsupported Position category layout, its shape keys are skipped")
            continue

        usable_drawib_model_list.append(drawib_model)

    return usable_drawib_model_list


def get_compute_command_list_name(drawib_index: int) -> str:
    """Return the command list name of one usable DrawIB (0-based index).

    The exporter injects "run = <name>" into the Position VB override, so
    this name must stay in sync with the sections generated below.
    """
    return "CustomShaderComputeShapesNaraka" + str(drawib_index + 1)


def get_computed_resource_name(drawib: str) -> str:
    """Return the raw staging resource that receives the compute result."""
    return "Resource" + drawib + "PositionComputed"


def copy_shapes_hlsl_to_mod_folder():
    """Copy the shared Shapes.hlsl next to the generated mod INI."""
    # This file lives in games/naraka/, so the addon root is three levels up.
    addon_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = os.path.join(addon_root, "resources", "Shapes.hlsl")
    # Flat layout: shaders are copied next to the generated INI, no res subfolder.
    dst_dir = GlobalConfig.path_generate_mod_folder()
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copy2(src, os.path.join(dst_dir, "Shapes.hlsl"))


def add_naraka_shapekey_ini_sections(
    ini_builder: M_IniBuilder,
    drawib_drawibmodel_dict: dict,
    usable_drawib_model_list: list = None,
):
    """Append every shape key section of a Naraka mod to the INI builder.

    usable_drawib_model_list: precomputed result of
    collect_usable_drawib_model_list from the exporter, so the command
    list names match the "run = ..." lines injected into the Position VB
    overrides. When omitted, it is computed from drawib_drawibmodel_dict.
    """
    shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
    if len(shapekeyname_mkey_dict.keys()) == 0:
        return

    if usable_drawib_model_list is None:
        usable_drawib_model_list = collect_usable_drawib_model_list(drawib_drawibmodel_dict.values())
    if not usable_drawib_model_list:
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

    # [CustomShaderComputeShapesNarakaN]: one command list per DrawIB. It
    # is run from the top of the Position VB override, right before the
    # game's skinning compute shader is re-dispatched there.
    customshader_section = M_IniSection(M_SectionType.CommandList)
    for drawib_index, drawib_model in enumerate(usable_drawib_model_list):
        drawib = drawib_model.draw_ib
        shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
        draw_number = getattr(drawib_model, "draw_number", getattr(drawib_model, "vertex_count", 0))

        customshader_section.append("[" + get_compute_command_list_name(drawib_index) + "]")
        customshader_section.append("cs = Shapes.hlsl")
        # CustomShader restores shaders and OM state, not CS SRVs or UAVs.
        # Preserve borrowed slots instead of leaving the game's bindings null.
        for slot in ("cs-u5", "cs-t50", "cs-t51"):
            customshader_section.append("Resource" + drawib + "ShapeBackup_" + slot + " = ref " + slot)
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

        # A 3Dmigoto copy recreates its destination from the source descriptor.
        # PositionComputed explicitly replaces the structured misc flag with
        # the raw flag before the copy; the final reference is therefore raw.
        customshader_section.append(get_computed_resource_name(drawib) + " = copy cs-u5")
        customshader_section.append("Resource" + drawib + "Position = ref " + get_computed_resource_name(drawib))

        # Restore every borrowed slot before the game dispatch resumes.
        # Restoring u5 also unbinds the temporary shape accumulation buffer.
        for slot in ("cs-u5", "cs-t50", "cs-t51"):
            customshader_section.append(slot + " = ref Resource" + drawib + "ShapeBackup_" + slot)
        customshader_section.new_line()
    ini_builder.append_section(customshader_section)

    # [Resource...]: structured inputs, a raw result, and scratch backups.
    # Explicit StructuredBuffer types make reference-bound SRVs valid.
    # The raw intermediate overrides all misc flags, not just the type:
    # D3D11 forbids combining structured and raw flags on the same buffer.
    resource_section = M_IniSection(M_SectionType.ResourceBuffer)
    for drawib_model in usable_drawib_model_list:
        drawib = drawib_model.draw_ib
        shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
        position_stride = drawib_model.d3d11_game_type.CategoryStrideDict["Position"]

        # The pristine base copy: same Position file as the game-facing
        # buffer, just declared as a structured buffer.
        resource_section.append("[Resource" + drawib + "Position.1]")
        resource_section.append("type = StructuredBuffer")
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
            resource_section.append("type = StructuredBuffer")
            resource_section.append("stride = " + str(position_stride))
            resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(
                drawib + "-Position." + shapekey_name + ".buf"))
            resource_section.new_line()

        # CopyResource can move bytes between equal-sized buffer types.
        # 3Dmigoto first recreates the destination, so discard the inherited
        # structured flag explicitly instead of merely adding the raw flag.
        resource_section.append("[" + get_computed_resource_name(drawib) + "]")
        resource_section.append("type = ByteAddressBuffer")
        resource_section.append("misc_flags = buffer_allow_raw_views")
        # Do not depend on parse-order propagation through Position = ref.
        # The raw result is only consumed through the game's shader SRV.
        resource_section.append("bind_flags = shader_resource")
        resource_section.append("stride = " + str(position_stride))
        resource_section.new_line()

        # Empty resources hold references to the game's original CS bindings.
        # Keep backups per DrawIB so separate compute lists cannot collide.
        for slot in ("cs-u5", "cs-t50", "cs-t51"):
            resource_section.append("[Resource" + drawib + "ShapeBackup_" + slot + "]")
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
