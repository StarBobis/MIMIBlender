"""Create the shared shape-key output descriptor on a real D3D11 device.

The generic shape-key writer ends with a raw vertex buffer:

    [Resource<DrawIB>PositionComputed]
    type = ByteAddressBuffer
    misc_flags = buffer_allow_raw_views
    bind_flags = vertex_buffer shader_resource

D3D11 only accepts ALLOW_RAW_VIEWS when the buffer can also be bound as an
SRV or UAV. A vertex-buffer-only descriptor fails CreateBuffer with
E_INVALIDARG; 3Dmigoto then leaves the resource null, and the following
"Position = ref PositionComputed" line nulls the game's Position binding.

This test renders that exact INI block with the real writer, turns its flags
back into D3D11 bits, and asks a real device to create the buffer. It also
re-creates the old descriptor to prove the failure mode is still real.

Run: python tools/test_shapekey_descriptor_gpu.py
"""

import ctypes
import os
import sys
import types
from ctypes import wintypes

# Reuse the established blob-free harness from the INI test, so the flags come
# from production code rather than from a copy in this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_time_position_ini as harness  # noqa: E402

D3D11_USAGE_DEFAULT = 0
D3D11_BIND_VERTEX_BUFFER = 0x1
D3D11_BIND_INDEX_BUFFER = 0x2
D3D11_BIND_SHADER_RESOURCE = 0x8
D3D11_BIND_UNORDERED_ACCESS = 0x80
D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS = 0x20
D3D11_RESOURCE_MISC_BUFFER_STRUCTURED = 0x40
D3D_DRIVER_TYPE_HARDWARE = 1
D3D_DRIVER_TYPE_WARP = 5
E_INVALIDARG = -2147024809  # 0x80070057

BIND_FLAG_BITS = {
    "vertex_buffer": D3D11_BIND_VERTEX_BUFFER,
    "index_buffer": D3D11_BIND_INDEX_BUFFER,
    "shader_resource": D3D11_BIND_SHADER_RESOURCE,
    "unordered_access": D3D11_BIND_UNORDERED_ACCESS,
}
MISC_FLAG_BITS = {
    "buffer_allow_raw_views": D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS,
    "buffer_structured": D3D11_RESOURCE_MISC_BUFFER_STRUCTURED,
}


class D3D11_BUFFER_DESC(ctypes.Structure):
    _fields_ = [
        ("ByteWidth", ctypes.c_uint),
        ("Usage", ctypes.c_uint),
        ("BindFlags", ctypes.c_uint),
        ("CPUAccessFlags", ctypes.c_uint),
        ("MiscFlags", ctypes.c_uint),
        ("StructureByteStride", ctypes.c_uint),
    ]


def make_gf2_gpu_model(modules):
    """A GF2 GPU DrawIB: 40-byte Position (POSITION/NORMAL/TANGENT float32)."""
    m_key_type = modules[harness.TEST_PKG + ".common.m_key"].M_Key
    m_key = m_key_type()
    m_key.key_name = "$shapekey0"
    m_key.initialize_value = 0
    m_key.initialize_vk_str = ""
    m_key.key_type = "key"

    game_type = types.SimpleNamespace(
        OrderedCategoryNameList=["Position", "Texcoord", "Blend"],
        CategoryStrideDict={"Position": 40, "Texcoord": 28, "Blend": 32},
        CategoryDrawCategoryDict={"Position": "Position", "Texcoord": "Texcoord", "Blend": "Position"},
        CategoryExtractSlotDict={"Position": "vb0", "Texcoord": "vb1", "Blend": "vb2"},
        D3D11ElementList=[
            types.SimpleNamespace(Category="Position", SemanticName="POSITION",
                                  Format="R32G32B32_FLOAT", ByteWidth=12),
            types.SimpleNamespace(Category="Position", SemanticName="NORMAL",
                                  Format="R32G32B32_FLOAT", ByteWidth=12),
            types.SimpleNamespace(Category="Position", SemanticName="TANGENT",
                                  Format="R32G32B32A32_FLOAT", ByteWidth=16),
        ],
    )

    draw_ib = "f2d2eac3"
    model = types.SimpleNamespace(
        draw_ib=draw_ib,
        d3d11_game_type=game_type,
        vertex_count=18343,
        draw_number=18343,
        shapekey_name_bytelist_dict={"Sculpt": b"x" * 40},
        time_pos_frame_groups={},
    )
    model.get_category_buffer_filename = lambda category: "LOD0." + draw_ib + "-" + category + ".buf"

    harness.TEST_SHAPEKEY_DICT.clear()
    harness.TEST_SHAPEKEY_DICT["Sculpt"] = m_key
    return model


def render_ini(modules, model):
    builder_class = modules[harness.TEST_PKG + ".common.m_ini_builder"].M_IniBuilder
    helper = modules[harness.TEST_PKG + ".common.m_ini_helper"].M_IniHelper
    ini_builder = builder_class()
    helper.add_shapekey_ini_sections(
        ini_builder=ini_builder,
        drawib_drawibmodel_dict={model.draw_ib: model},
    )
    ini_path = os.path.join(harness.GlobalConfig.path_generate_mod_folder(),
                            "descriptor_probe.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as handle:
        return handle.read()


def parse_resource_block(ini_text, header):
    lines = ini_text.splitlines()
    start = lines.index(header)
    block = {}
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            break
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        block[key.strip()] = value.strip()
    return block


def render_time_position_ini(modules, blueprint_model, model):
    """Same rule, different writer: Time Position frame buffers.

    A GPU-pre-skinning DrawIB without shape keys declares its frame seed as
    type = ByteAddressBuffer. Those buffers are copy sources only, so no slot
    binding ever adds SRV capability for them.
    """
    builder_class = modules[harness.TEST_PKG + ".common.m_ini_builder"].M_IniBuilder
    m_time_position = modules[harness.TEST_PKG + ".common.m_time_position"]
    ini_builder = builder_class()
    m_time_position.append_time_position_sections(
        ini_builder=ini_builder,
        blueprint_model=blueprint_model,
        drawib_models=[model],
    )
    ini_path = os.path.join(harness.GlobalConfig.path_generate_mod_folder(),
                            "time_position_probe.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as handle:
        return handle.read()


def flags_from_names(text, table):
    bits = 0
    for name in text.split():
        assert name in table, "unknown flag emitted by the writer: " + name
        bits |= table[name]
    return bits


def create_device(driver_type):
    d3d11 = ctypes.WinDLL("d3d11")
    d3d11.D3D11CreateDevice.restype = ctypes.c_long
    d3d11.D3D11CreateDevice.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    device = ctypes.c_void_p()
    context = ctypes.c_void_p()
    feature_level = ctypes.c_uint()
    hr = d3d11.D3D11CreateDevice(
        None, driver_type, None, 0, None, 0, 7,
        ctypes.byref(device), ctypes.byref(feature_level), ctypes.byref(context),
    )
    return hr, device, feature_level.value


def create_buffer(device, desc):
    vtable = ctypes.cast(device, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    create = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p,
        ctypes.POINTER(D3D11_BUFFER_DESC), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )(vtable.contents[3])
    out = ctypes.c_void_p()
    hr = create(device, ctypes.byref(desc), None, ctypes.byref(out))
    return hr


def main():
    harness.ensure_parent_packages()
    harness.install_stubs()
    modules = harness.load_real_modules()

    model = make_gf2_gpu_model(modules)
    ini_text = render_ini(modules, model)
    block = parse_resource_block(
        ini_text, "[Resource" + model.draw_ib + "PositionComputed]")

    assert block["type"] == "ByteAddressBuffer", block
    assert block["misc_flags"] == "buffer_allow_raw_views", block
    bind_flags = flags_from_names(block["bind_flags"], BIND_FLAG_BITS)
    misc_flags = flags_from_names(block["misc_flags"], MISC_FLAG_BITS)
    stride = int(block["stride"])
    byte_width = stride * 4

    # Static rule first: RAW views require SRV or UAV capability.
    assert bind_flags & (D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS), (
        "the emitted descriptor cannot be created: ALLOW_RAW_VIEWS needs SRV/UAV")
    assert bind_flags & D3D11_BIND_VERTEX_BUFFER, (
        "the result must stay bindable as a vertex buffer")

    if sys.platform != "win32":
        print("SKIP: D3D11 is only available on Windows")
        print("test_shapekey_descriptor_gpu OK")
        return

    device = None
    for driver_type, label in ((D3D_DRIVER_TYPE_HARDWARE, "hardware"),
                               (D3D_DRIVER_TYPE_WARP, "warp")):
        hr, dev, level = create_device(driver_type)
        if hr == 0 and dev:
            device = dev
            print("using %s device, feature level 0x%x" % (label, level))
            break
    if not device:
        print("SKIP: no D3D11 device")
        return

    desc = D3D11_BUFFER_DESC(
        ByteWidth=byte_width,
        Usage=D3D11_USAGE_DEFAULT,
        BindFlags=bind_flags,
        CPUAccessFlags=0,
        MiscFlags=misc_flags,
        StructureByteStride=stride,
    )
    hr = create_buffer(device, desc)
    assert hr == 0, ("emitted descriptor must be creatable, got 0x%08x" % (hr & 0xFFFFFFFF))
    print("OK: emitted descriptor (BindFlags=0x%02x MiscFlags=0x%02x stride=%d) created"
          % (bind_flags, misc_flags, stride))

    # Prove the reason, not just the fix: the same descriptor without SRV
    # capability is exactly what used to be written.
    legacy = D3D11_BUFFER_DESC(
        ByteWidth=byte_width,
        Usage=D3D11_USAGE_DEFAULT,
        BindFlags=bind_flags & ~D3D11_BIND_SHADER_RESOURCE,
        CPUAccessFlags=0,
        MiscFlags=misc_flags,
        StructureByteStride=stride,
    )
    hr = create_buffer(device, legacy)
    assert hr == E_INVALIDARG, (
        "vertex-buffer-only raw descriptor must stay rejected, got 0x%08x" % (hr & 0xFFFFFFFF))
    print("OK: vertex-buffer-only raw descriptor still rejected (0x80070057)")

    # Second writer, same D3D11 rule: Time Position frame buffers are raw and
    # are only copy sources, so no slot ever adds SRV capability for them.
    timepos_model = harness.make_fake_drawib_model()
    timepos_model.d3d11_game_type.GPU_PreSkinning = True
    timepos_model.shapekey_name_bytelist_dict = {}
    timepos_text = render_time_position_ini(
        modules, harness.make_fake_blueprint_model(modules), timepos_model)
    timepos_block = parse_resource_block(
        timepos_text, "[Resource" + timepos_model.draw_ib + "PositionTimeOriginal]")
    assert timepos_block["type"] == "ByteAddressBuffer", timepos_block
    timepos_bind = flags_from_names(timepos_block["bind_flags"], BIND_FLAG_BITS)
    assert timepos_bind & (D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS), (
        "the Time Position raw buffer cannot be created: it needs SRV/UAV")
    timepos_stride = int(timepos_block["stride"])
    timepos_desc = D3D11_BUFFER_DESC(
        ByteWidth=timepos_stride * 4,
        Usage=D3D11_USAGE_DEFAULT,
        BindFlags=timepos_bind,
        CPUAccessFlags=0,
        MiscFlags=D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS,
        StructureByteStride=timepos_stride,
    )
    hr = create_buffer(device, timepos_desc)
    assert hr == 0, ("Time Position descriptor must be creatable, got 0x%08x"
                     % (hr & 0xFFFFFFFF))
    print("OK: Time Position raw descriptor (BindFlags=0x%02x) created" % timepos_bind)

    # Same reason as above: without SRV/UAV the raw frame buffer is rejected.
    bare_desc = D3D11_BUFFER_DESC(
        ByteWidth=timepos_stride * 4,
        Usage=D3D11_USAGE_DEFAULT,
        BindFlags=0,
        CPUAccessFlags=0,
        MiscFlags=D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS,
        StructureByteStride=timepos_stride,
    )
    hr = create_buffer(device, bare_desc)
    assert hr == E_INVALIDARG, (
        "bind-flag-less raw descriptor must stay rejected, got 0x%08x" % (hr & 0xFFFFFFFF))
    print("OK: bind-flag-less raw descriptor still rejected (0x80070057)")
    print("test_shapekey_descriptor_gpu OK")


if __name__ == "__main__":
    main()
