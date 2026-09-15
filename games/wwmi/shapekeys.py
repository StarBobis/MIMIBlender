"""
WWMI shape key INI sections.

Everything related to the WWMI shape key pipeline lives here:
- the shape key entries / batches derived from the blueprint and the
  WWMI metadata,
- the texture override + resource sections driving the WWMI shape key
  compute shaders,
- the optional custom apply-shapekeys command lists (with the HLSL
  shaders copied next to the generated INI).
"""

import os
import shutil

from ...common.global_config import GlobalConfig
from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...blueprint.blueprint_export_helper import BlueprintExportHelper
from .model import DrawIBModelWWMI


def get_safe_shapekey_name(shapekey_name: str) -> str:
    """Delegate to the model: resource names must be INI-safe."""
    return DrawIBModelWWMI.get_safe_shapekey_name(shapekey_name)


def get_wwmi_shapekey_entries(draw_ib_model: DrawIBModelWWMI | None = None):
    """Return (shapekey_name, safe_name, M_Key) entries for this export.

    When a DrawIB model is given, only the shape keys that actually have
    both a position and a vector buffer on that DrawIB are kept.
    """
    shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
    if draw_ib_model is not None:
        available_names = (
            set(draw_ib_model.obj_buffer_model_wwmi.shapekey_position_buffer_dict.keys())
            & set(draw_ib_model.obj_buffer_model_wwmi.shapekey_vector_buffer_dict.keys())
        )
        shapekeyname_mkey_dict = {
            shapekey_name: m_key
            for shapekey_name, m_key in shapekeyname_mkey_dict.items()
            if shapekey_name in available_names
        }
    return [
        (shapekey_name, get_safe_shapekey_name(shapekey_name), m_key)
        for shapekey_name, m_key in shapekeyname_mkey_dict.items()
    ]


def copy_wwmi_shapekey_shaders_to_mod_folder():
    # Flat layout: shaders are copied next to the generated INI, no res subfolder
    mod_path = GlobalConfig.path_generate_mod_folder()
    os.makedirs(mod_path, exist_ok=True)

    # This file lives in games/wwmi/, so the addon root is three levels up.
    addon_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for filename in ("ShapesWWMIPosition.hlsl", "ShapesWWMIVector.hlsl"):
        src = os.path.join(addon_root, "resources", filename)
        shutil.copy2(src, os.path.join(mod_path, filename))


def get_wwmi_shapekey_batches(draw_ib_model: DrawIBModelWWMI) -> list[dict]:
    """Return the 128-offset shape key batches of this DrawIB.

    Every batch carries the WWMI metadata (checksum, original vertex offset,
    dispatch size) plus the accumulated custom vertex offset used by the mod.
    """
    shapekey_offsets = draw_ib_model.obj_buffer_model_wwmi.shapekey_offsets
    if not shapekey_offsets:
        return []

    batch_count = len(shapekey_offsets) // 128
    metadata_batches = list(getattr(draw_ib_model.wwmi_info.shapekeys, "batches", []) or [])
    if not metadata_batches and getattr(draw_ib_model.wwmi_info.shapekeys, "checksum", 0):
        metadata_batches = [{
            "vertex_offset": 0,
            "dispatch_y": draw_ib_model.wwmi_info.shapekeys.dispatch_y,
            "checksum": draw_ib_model.wwmi_info.shapekeys.checksum,
        }]
    if len(metadata_batches) < batch_count:
        return []

    batches = []
    custom_vertex_offset = 0
    for batch_id in range(batch_count):
        batch_offsets = shapekey_offsets[batch_id * 128:(batch_id + 1) * 128]
        custom_vertex_count = batch_offsets[-1] if batch_offsets else 0
        metadata = metadata_batches[batch_id]
        if int(metadata.get("checksum", 0)) == 0:
            return []
        batches.append({
            "checksum": int(metadata.get("checksum", 0)),
            "original_vertex_offset": int(metadata.get("vertex_offset", 0)),
            "dispatch_y": int(metadata.get("dispatch_y", 0)),
            "custom_vertex_offset": custom_vertex_offset,
            "custom_vertex_count": custom_vertex_count,
        })
        custom_vertex_offset += custom_vertex_count
    return batches


def add_texture_override_shapekeys(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Texture overrides + command lists driving the WWMI shape key loader."""
    shapekey_batches = get_wwmi_shapekey_batches(draw_ib_model)
    if not shapekey_batches:
        return

    texture_override_shapekeys_section = M_IniSection(M_SectionType.TextureOverrideShapeKeys)

    shapekey_offsets_hash = draw_ib_model.wwmi_info.shapekeys.offsets_hash
    if shapekey_offsets_hash != "":
        texture_override_shapekeys_section.append("[TextureOverrideShapeKeyOffsets]")
        texture_override_shapekeys_section.append("hash = " + shapekey_offsets_hash)
        texture_override_shapekeys_section.append("match_priority = 0")
        texture_override_shapekeys_section.append("override_byte_stride = 24")
        texture_override_shapekeys_section.append("override_vertex_count = $mesh_vertex_count")
        texture_override_shapekeys_section.new_line()

    shapekey_scale_hash = draw_ib_model.wwmi_info.shapekeys.scale_hash
    if shapekey_scale_hash != "":
        texture_override_shapekeys_section.append("[TextureOverrideShapeKeyScale]")
        texture_override_shapekeys_section.append("hash = " + draw_ib_model.wwmi_info.shapekeys.scale_hash)
        texture_override_shapekeys_section.append("match_priority = 0")
        texture_override_shapekeys_section.append("override_byte_stride = 4")
        texture_override_shapekeys_section.append("override_vertex_count = $mesh_vertex_count")
        texture_override_shapekeys_section.new_line()

    texture_override_shapekeys_section.append("[CommandListSetupShapeKeysBatch]")
    for batch_id, batch in enumerate(shapekey_batches):
        texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_checksum_batch" + str(batch_id) + " = " + str(batch["checksum"]))
        texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_vertex_offset_original_batch" + str(batch_id) + " = " + str(batch["original_vertex_offset"]))
        texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_vertex_offset_custom_batch" + str(batch_id) + " = $shapekey_vertex_offset_batch" + str(batch_id))
    texture_override_shapekeys_section.append("cs-t33 = ResourceShapeKeyOffsetBuffer")
    texture_override_shapekeys_section.append("cs-u5 = ResourceCustomShapeKeyValuesRW")
    texture_override_shapekeys_section.append("cs-u6 = ResourceShapeKeyCBRW")
    texture_override_shapekeys_section.append("run = CustomShader\\WWMIv1\\ShapeKeyBatchOverrider")
    texture_override_shapekeys_section.new_line()

    texture_override_shapekeys_section.append("[CommandListLoadShapeKeysBatch]")
    for batch_id, batch in enumerate(shapekey_batches):
        texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_dispatch_size_y_original_batch" + str(batch_id) + " = " + str(batch["dispatch_y"]))
        texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_vertex_count_batch" + str(batch_id) + " = $shapekey_vertex_count_batch" + str(batch_id))
    texture_override_shapekeys_section.append("cs-t0 = ResourceShapeKeyVertexIdBuffer")
    texture_override_shapekeys_section.append("cs-t1 = ResourceShapeKeyVertexOffsetBuffer")
    texture_override_shapekeys_section.append("cs-u6 = ResourceShapeKeyCBRW")
    texture_override_shapekeys_section.append("run = CommandList\\WWMIv1\\LoadShapeKeysBatch")
    texture_override_shapekeys_section.new_line()

    if shapekey_offsets_hash != "":
        texture_override_shapekeys_section.append("[TextureOverrideShapeKeyLoaderCallback]")
        texture_override_shapekeys_section.append("hash = " + draw_ib_model.wwmi_info.shapekeys.offsets_hash)
        texture_override_shapekeys_section.append("match_priority = 0")
        texture_override_shapekeys_section.append("if $mod_enabled")
        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            texture_override_shapekeys_section.append("  if cs == 3381.3333 && ResourceMergedSkeleton !== null")
        else:
            texture_override_shapekeys_section.append("  if cs == 3381.3333")
        texture_override_shapekeys_section.append("    handling = skip")
        texture_override_shapekeys_section.append("    run = CommandListSetupShapeKeysBatch")
        texture_override_shapekeys_section.append("    run = CommandListLoadShapeKeysBatch")
        texture_override_shapekeys_section.append("  endif")
        texture_override_shapekeys_section.append("endif")
        texture_override_shapekeys_section.new_line()

    texture_override_shapekeys_section.append("[CommandListMultiplyShapeKeys]")
    texture_override_shapekeys_section.append("$\\WWMIv1\\custom_vertex_count = $mesh_vertex_count")
    texture_override_shapekeys_section.append("run = CustomShader\\WWMIv1\\ShapeKeyMultiplier")
    texture_override_shapekeys_section.new_line()

    if shapekey_offsets_hash != "":
        texture_override_shapekeys_section.append("[TextureOverrideShapeKeyMultiplierCallback]")
        texture_override_shapekeys_section.append("hash = " + draw_ib_model.wwmi_info.shapekeys.offsets_hash)
        texture_override_shapekeys_section.append("match_priority = 0")
        texture_override_shapekeys_section.append("if $mod_enabled")
        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            texture_override_shapekeys_section.append("  if cs == 3381.4444 && ResourceMergedSkeleton !== null")
        else:
            texture_override_shapekeys_section.append("  if cs == 3381.4444")
        texture_override_shapekeys_section.append("    handling = skip")
        texture_override_shapekeys_section.append("    run = CommandListMultiplyShapeKeys")
        texture_override_shapekeys_section.append("  endif")
        texture_override_shapekeys_section.append("endif")
        texture_override_shapekeys_section.new_line()

    ini_builder.append_section(texture_override_shapekeys_section)


def add_resource_shapekeys(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Resource declarations for the WWMI shape key override buffers."""
    shapekey_batches = get_wwmi_shapekey_batches(draw_ib_model)
    if not shapekey_batches:
        return

    resource_shapekeys_section = M_IniSection(M_SectionType.ResourceShapeKeysOverride)
    resource_shapekeys_section.append("; Resources: Shape Keys Override -------------------------")
    resource_shapekeys_section.append("[ResourceShapeKeyCBRW]")
    resource_shapekeys_section.append("type = RWBuffer")
    resource_shapekeys_section.append("format = R32G32B32A32_UINT")
    resource_shapekeys_section.append("array = 66")
    resource_shapekeys_section.append("[ResourceCustomShapeKeyValuesRW]")
    resource_shapekeys_section.append("type = RWBuffer")
    resource_shapekeys_section.append("format = R32G32B32A32_FLOAT")
    resource_shapekeys_section.append("array = " + str(32 * len(shapekey_batches)))
    ini_builder.append_section(resource_shapekeys_section)


def add_wwmi_shapekey_sections(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Custom apply-shapekeys command lists + resources (user hotkey driven).

    These sections apply the blueprint shape keys through the two WWMI HLSL
    shaders; they are only emitted when the blueprint defines shape keys
    that exist on this DrawIB.
    """
    shapekey_entries = get_wwmi_shapekey_entries(draw_ib_model)
    if not shapekey_entries:
        return

    copy_wwmi_shapekey_shaders_to_mod_folder()

    constants_section = M_IniSection(M_SectionType.Constants)
    constants_section.SectionName = "Constants"
    for shapekey_name, _safe_name, m_key in shapekey_entries:
        constants_section.append("; ShapeKey: " + shapekey_name)
        constants_section.append("global persist " + m_key.key_name + " = " + str(m_key.initialize_value))
        constants_section.new_line()
    ini_builder.append_section(constants_section)

    key_section = M_IniSection(M_SectionType.Key)
    for shapekey_name, _safe_name, m_key in shapekey_entries:
        if m_key.initialize_vk_str == "":
            continue

        key_section.append("[Key_ShapeKey_" + shapekey_name + "]")
        comment = getattr(m_key, 'comment', '')
        if comment:
            key_section.append("; " + comment)
        key_section.append("key = " + m_key.initialize_vk_str)
        key_section.append("type = cycle")
        key_section.append(m_key.key_name + " = 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1")
        key_section.new_line()
    ini_builder.append_section(key_section)

    commandlist_section = M_IniSection(M_SectionType.CommandList)
    commandlist_section.append("[CommandListApplyShapeKeysPosition]")
    commandlist_section.append("ResourcePositionBufferRW = copy ResourcePositionBufferFloat")
    commandlist_section.append("x89 = " + str(draw_ib_model.mesh_vertex_count * 3))
    commandlist_section.append("cs-t50 = ResourcePositionBufferFloat")
    commandlist_section.append("cs-u5 = ResourcePositionBufferRW")
    for shapekey_name, safe_name, m_key in shapekey_entries:
        commandlist_section.append("; ShapeKey: " + shapekey_name)
        commandlist_section.append("x88 = " + m_key.key_name)
        commandlist_section.append("cs-t51 = ResourceShapeKeyPosition_" + safe_name)
        commandlist_section.append("run = CustomShaderComputeWWMIShapeKeyPosition")
    commandlist_section.append("cs-t50 = null")
    commandlist_section.append("cs-t51 = null")
    commandlist_section.append("cs-u5 = null")
    commandlist_section.append("ResourcePositionBufferShapeKeyVB = copy ResourcePositionBufferRW")
    commandlist_section.new_line()

    commandlist_section.append("[CustomShaderComputeWWMIShapeKeyPosition]")
    commandlist_section.append("cs = ShapesWWMIPosition.hlsl")
    commandlist_section.append("vs = null")
    commandlist_section.append("ps = null")
    commandlist_section.append("hs = null")
    commandlist_section.append("ds = null")
    commandlist_section.append("gs = null")
    commandlist_section.append("dispatch = " + str((draw_ib_model.mesh_vertex_count * 3 + 63) // 64) + ", 1, 1")
    commandlist_section.new_line()

    commandlist_section.append("[CommandListApplyShapeKeysVector]")
    commandlist_section.append("ResourceVectorBufferRW = copy ResourceVectorBufferInt")
    commandlist_section.append("x89 = " + str(draw_ib_model.mesh_vertex_count * 2))
    commandlist_section.append("cs-t50 = ResourceVectorBufferInt")
    commandlist_section.append("cs-u5 = ResourceVectorBufferRW")
    for shapekey_name, safe_name, m_key in shapekey_entries:
        commandlist_section.append("; ShapeKey: " + shapekey_name)
        commandlist_section.append("x88 = " + m_key.key_name)
        commandlist_section.append("cs-t51 = ResourceShapeKeyVector_" + safe_name)
        commandlist_section.append("run = CustomShaderComputeWWMIShapeKeyVector")
    commandlist_section.append("cs-t50 = null")
    commandlist_section.append("cs-t51 = null")
    commandlist_section.append("cs-u5 = null")
    commandlist_section.append("ResourceVectorBufferShapeKeyVB = copy ResourceVectorBufferRW")
    commandlist_section.new_line()

    commandlist_section.append("[CustomShaderComputeWWMIShapeKeyVector]")
    commandlist_section.append("cs = ShapesWWMIVector.hlsl")
    commandlist_section.append("vs = null")
    commandlist_section.append("ps = null")
    commandlist_section.append("hs = null")
    commandlist_section.append("ds = null")
    commandlist_section.append("gs = null")
    commandlist_section.append("dispatch = " + str((draw_ib_model.mesh_vertex_count * 2 + 63) // 64) + ", 1, 1")
    commandlist_section.new_line()
    ini_builder.append_section(commandlist_section)

    resource_section = M_IniSection(M_SectionType.ResourceBuffer)
    resource_section.append("[ResourcePositionBufferRW]")
    resource_section.append("type = RWBuffer")
    resource_section.append("format = R32_FLOAT")
    resource_section.append("array = " + str(draw_ib_model.mesh_vertex_count * 3))
    resource_section.new_line()
    resource_section.append("[ResourcePositionBufferFloat]")
    resource_section.append("type = Buffer")
    resource_section.append("format = R32_FLOAT")
    resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-Position.buf"))
    resource_section.new_line()
    resource_section.append("[ResourcePositionBufferShapeKeyVB]")
    resource_section.append("type = Buffer")
    resource_section.append("stride = 12")
    resource_section.new_line()
    resource_section.append("[ResourceVectorBufferRW]")
    resource_section.append("type = RWBuffer")
    resource_section.append("format = R8_SINT")
    resource_section.append("array = " + str(draw_ib_model.mesh_vertex_count * 8))
    resource_section.new_line()
    resource_section.append("[ResourceVectorBufferInt]")
    resource_section.append("type = Buffer")
    resource_section.append("format = R8_SINT")
    resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-Vector.buf"))
    resource_section.new_line()
    resource_section.append("[ResourceVectorBufferShapeKeyVB]")
    resource_section.append("type = Buffer")
    resource_section.append("stride = 8")
    resource_section.new_line()
    for shapekey_name, safe_name, _m_key in shapekey_entries:
        resource_section.append("[ResourceShapeKeyPosition_" + safe_name + "]")
        resource_section.append("type = Buffer")
        resource_section.append("format = R32_FLOAT")
        resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-Position." + safe_name + ".buf"))
        resource_section.new_line()
        resource_section.append("[ResourceShapeKeyVector_" + safe_name + "]")
        resource_section.append("type = Buffer")
        resource_section.append("format = R8_SINT")
        resource_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-Vector." + safe_name + ".buf"))
        resource_section.new_line()
    ini_builder.append_section(resource_section)
