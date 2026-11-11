"""Create the shared shape-key output descriptor on a D3D11 device.

The generic shape-key writer ends with a raw buffer:

    [Resource<DrawIB>PositionComputed]
    type = ByteAddressBuffer
    misc_flags = buffer_allow_raw_views
    bind_flags = vertex_buffer shader_resource

D3D11 only accepts ALLOW_RAW_VIEWS when the buffer can also be bound as an
SRV or UAV. A vertex-buffer-only descriptor fails CreateBuffer with
E_INVALIDARG; 3Dmigoto then leaves the resource null, and the assignment to
the game-facing Position resource nulls that binding.

This test renders that block with the real writer, turns its flags back into
D3D11 bits and asks a real device to create the buffer, copy a structured
accumulator into it and read the bytes back. It also re-creates the invalid
descriptor combination to show D3D11 still rejects it.

Scope: it proves the descriptor is creatable and copy-compatible on the
device that runs it (hardware if available, WARP fallback, skipped off
Windows). It does not prove in-game shape-key behaviour.

Run: python tools/test_shapekey_descriptor_gpu.py
"""

import ctypes
import os
import struct
import sys
import types

# Reuse the established blob-free harness from the INI test, so the flags come
# from production code rather than from a copy in this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_time_position_ini as harness  # noqa: E402

D3D11_USAGE_DEFAULT = 0
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_BIND_VERTEX_BUFFER = 0x1
D3D11_BIND_INDEX_BUFFER = 0x2
D3D11_BIND_SHADER_RESOURCE = 0x8
D3D11_BIND_UNORDERED_ACCESS = 0x80
D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS = 0x20
D3D11_RESOURCE_MISC_BUFFER_STRUCTURED = 0x40
D3D11_MAP_READ = 1
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


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [
        ("pData", ctypes.c_void_p),
        ("RowPitch", ctypes.c_uint),
        ("DepthPitch", ctypes.c_uint),
    ]


def position_elements(stride):
    """Position-category element list for the two layouts the writer accepts."""
    full = [
        types.SimpleNamespace(Category="Position", SemanticName="POSITION",
                              Format="R32G32B32_FLOAT", ByteWidth=12),
        types.SimpleNamespace(Category="Position", SemanticName="NORMAL",
                              Format="R32G32B32_FLOAT", ByteWidth=12),
        types.SimpleNamespace(Category="Position", SemanticName="TANGENT",
                              Format="R32G32B32A32_FLOAT", ByteWidth=16),
    ]
    if stride == 40:
        return full
    assert stride == 12
    return full[:1]


def make_gpu_model(modules, draw_ib, stride, shape_keys=None):
    """A GPU DrawIB whose Position category has the requested stride."""
    key_type = modules[harness.TEST_PKG + ".common.m_key"].M_Key
    game_type = types.SimpleNamespace(
        OrderedCategoryNameList=["Position", "Texcoord", "Blend"],
        CategoryStrideDict={"Position": stride, "Texcoord": 28, "Blend": 32},
        CategoryDrawCategoryDict={"Position": "Position", "Texcoord": "Texcoord",
                                  "Blend": "Position"},
        CategoryExtractSlotDict={"Position": "vb0", "Texcoord": "vb1", "Blend": "vb2"},
        D3D11ElementList=position_elements(stride),
        GPU_PreSkinning=True,
    )
    model = types.SimpleNamespace(
        draw_ib=draw_ib,
        d3d11_game_type=game_type,
        vertex_count=18343,
        draw_number=18343,
        shapekey_name_bytelist_dict=shape_keys or {},
        time_pos_frame_groups={},
        category_hash_dict={"Position": "27426557", "Texcoord": "1148cbd1",
                            "Blend": "b02b34e5"},
        draw_ib_alias=draw_ib,
    )
    model.get_category_buffer_filename = lambda category: "LOD0." + draw_ib + "-" + category + ".buf"
    return model


def install_shapekey_dict(modules, names):
    key_type = modules[harness.TEST_PKG + ".common.m_key"].M_Key
    harness.TEST_SHAPEKEY_DICT.clear()
    for index, name in enumerate(names):
        m_key = key_type()
        m_key.key_name = "$shapekey" + str(index)
        m_key.initialize_value = 0
        m_key.initialize_vk_str = ""
        m_key.key_type = "key"
        harness.TEST_SHAPEKEY_DICT[name] = m_key


def render_shapekey_ini(modules, models):
    builder_class = modules[harness.TEST_PKG + ".common.m_ini_builder"].M_IniBuilder
    helper = modules[harness.TEST_PKG + ".common.m_ini_helper"].M_IniHelper
    ini_builder = builder_class()
    helper.add_shapekey_ini_sections(
        ini_builder=ini_builder,
        drawib_drawibmodel_dict={model.draw_ib: model for model in models},
    )
    ini_path = os.path.join(harness.GlobalConfig.path_generate_mod_folder(),
                            "shapekey_descriptor_probe.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as handle:
        return handle.read()


def render_time_position_ini(modules, blueprint_model, model):
    """Same rule, different writer: Time Position frame buffers.

    A GPU-pre-skinning DrawIB declares its frame seed as
    type = ByteAddressBuffer. Those buffers are copy sources only, so no slot
    binding ever adds SRV capability for them. With shape keys the seed is a
    StructuredBuffer instead, which D3D11 accepts without SRV/UAV capacity.
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


def render_cs_vb_section(modules, model):
    """Text of the compute-path VB overrides (pins the cs-t0 destination)."""
    for package in (harness.TEST_PKG + ".games", harness.TEST_PKG + ".games.base"):
        if package not in sys.modules:
            sys.modules[package] = types.ModuleType(package)
    skip_draw_name = harness.TEST_PKG + ".common.skip_draw"
    if skip_draw_name not in sys.modules:
        harness.load_module_by_path(
            skip_draw_name, os.path.join(harness.ROOT, "common", "skip_draw.py"))
    sections = harness.load_module_by_path(
        harness.TEST_PKG + ".games.base.sections",
        os.path.join(harness.ROOT, "games", "base", "sections.py"),
    )
    builder_class = modules[harness.TEST_PKG + ".common.m_ini_builder"].M_IniBuilder
    ini_builder = builder_class()
    sections.add_unity_cs_texture_override_vb_sections(
        ini_builder=ini_builder,
        drawib_model=model,
        blueprint_model=types.SimpleNamespace(keyname_mkey_dict={}),
    )
    lines = []
    for section in ini_builder.ini_section_list:
        lines.extend(section.SectionLineList)
    return "\n".join(lines)


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
    return hr, device, context, feature_level.value


class Device:
    """Minimal ID3D11Device/Context wrapper for the few calls used here."""

    def __init__(self, device, context):
        self.device = device
        self.context = context
        device_vtable = ctypes.cast(device, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        context_vtable = ctypes.cast(context, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        self._create_buffer = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(D3D11_BUFFER_DESC),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(device_vtable.contents[3])
        self._update_subresource = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint)(
                context_vtable.contents[48])
        # CopyResource returns void, not HRESULT.
        self._copy_resource = ctypes.WINFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
                context_vtable.contents[47])
        self._map = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE))(
                context_vtable.contents[14])
        self._unmap = ctypes.WINFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)(
                context_vtable.contents[15])

    def create_buffer(self, desc):
        out = ctypes.c_void_p()
        hr = self._create_buffer(self.device, ctypes.byref(desc), None, ctypes.byref(out))
        return hr, out

    def copy(self, dst, src):
        self._copy_resource(self.context, dst, src)

    def upload(self, resource, payload):
        data = ctypes.create_string_buffer(payload, len(payload))
        return self._update_subresource(self.context, resource, 0, None, data, 0, 0)

    def read_back(self, resource, size):
        staging_desc = D3D11_BUFFER_DESC(size, D3D11_USAGE_STAGING, 0,
                                         D3D11_CPU_ACCESS_READ, 0, 0)
        hr, staging = self.create_buffer(staging_desc)
        assert hr == 0, "staging buffer creation failed: 0x%08x" % (hr & 0xFFFFFFFF)
        self.copy(staging, resource)
        mapped = D3D11_MAPPED_SUBRESOURCE()
        hr = self._map(self.context, staging, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped))
        assert hr == 0, "map failed: 0x%08x" % (hr & 0xFFFFFFFF)
        payload = ctypes.string_at(mapped.pData, size)
        self._unmap(self.context, staging, 0)
        return payload


def assert_creatable(device, block, draw_ib, expect_vertex_buffer=True):
    """Check one emitted resource block against a real device."""
    bind_flags = flags_from_names(block["bind_flags"], BIND_FLAG_BITS)
    misc_flags = flags_from_names(block["misc_flags"], MISC_FLAG_BITS)
    stride = int(block["stride"])
    assert block["type"] == "ByteAddressBuffer", block
    assert misc_flags & D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS, block
    # The rule this fix is about.
    assert bind_flags & (D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS), (
        draw_ib + ": the emitted descriptor cannot be created: "
        "ALLOW_RAW_VIEWS needs SRV/UAV")
    if expect_vertex_buffer:
        assert bind_flags & D3D11_BIND_VERTEX_BUFFER, (
            draw_ib + ": the result must stay bindable as a vertex buffer")
    desc = D3D11_BUFFER_DESC(
        ByteWidth=stride * 4,
        Usage=D3D11_USAGE_DEFAULT,
        BindFlags=bind_flags,
        CPUAccessFlags=0,
        MiscFlags=misc_flags,
        StructureByteStride=stride,
    )
    hr, _resource = device.create_buffer(desc)
    assert hr == 0, (draw_ib + ": emitted descriptor must be creatable, got 0x%08x"
                     % (hr & 0xFFFFFFFF))
    return bind_flags, misc_flags, stride


def main():
    harness.ensure_parent_packages()
    harness.install_stubs()
    modules = harness.load_real_modules()

    # --- shape-key writer: one DrawIB per supported Position layout ----------
    install_shapekey_dict(modules, ["Sculpt"])
    model_40 = make_gpu_model(modules, "f2d2eac3", 40, {"Sculpt": b"x" * 40})
    model_12 = make_gpu_model(modules, "65b9cf5a", 12, {"Sculpt": b"y" * 12})
    ini_text = render_shapekey_ini(modules, [model_40, model_12])

    blocks = {}
    for model in (model_40, model_12):
        header = "[Resource" + model.draw_ib + "PositionComputed]"
        blocks[model.draw_ib] = parse_resource_block(ini_text, header)
        assert ini_text.count(header) == 1, "one block per DrawIB: " + header
        assert ("Resource" + model.draw_ib + "Position = ref Resource"
                + model.draw_ib + "PositionComputed" in ini_text), (
            "each DrawIB must assign its own Position")

    # --- device -------------------------------------------------------------
    if sys.platform != "win32":
        print("SKIP: D3D11 is only available on Windows")
        print("test_shapekey_descriptor_gpu OK")
        return

    device = None
    for driver_type, label in ((D3D_DRIVER_TYPE_HARDWARE, "hardware"),
                               (D3D_DRIVER_TYPE_WARP, "warp")):
        hr, dev, ctx, level = create_device(driver_type)
        if hr == 0 and dev:
            device = Device(dev, ctx)
            print("using %s device, feature level 0x%x" % (label, level))
            break
    if not device:
        print("SKIP: no D3D11 device")
        return

    for model in (model_40, model_12):
        bind_flags, misc_flags, stride = assert_creatable(
            device, blocks[model.draw_ib], model.draw_ib)
        print("OK: %s descriptor (BindFlags=0x%02x MiscFlags=0x%02x stride=%d) created"
              % (model.draw_ib, bind_flags, misc_flags, stride))

    # The old combination must stay invalid, so the reason is pinned too.
    block = blocks[model_40.draw_ib]
    legacy = D3D11_BUFFER_DESC(
        ByteWidth=int(block["stride"]) * 4,
        Usage=D3D11_USAGE_DEFAULT,
        BindFlags=flags_from_names(block["bind_flags"], BIND_FLAG_BITS)
        & ~D3D11_BIND_SHADER_RESOURCE,
        CPUAccessFlags=0,
        MiscFlags=flags_from_names(block["misc_flags"], MISC_FLAG_BITS),
        StructureByteStride=int(block["stride"]),
    )
    hr, _ = device.create_buffer(legacy)
    assert hr == E_INVALIDARG, (
        "vertex-buffer-only raw descriptor must stay rejected, got 0x%08x"
        % (hr & 0xFFFFFFFF))
    print("OK: vertex-buffer-only raw descriptor still rejected (0x80070057)")

    # --- the copy the writer performs: structured accumulator -> raw buffer --
    stride = int(block["stride"])
    count = 8
    size = stride * count
    src_desc = D3D11_BUFFER_DESC(size, D3D11_USAGE_DEFAULT,
                                 D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS,
                                 0, D3D11_RESOURCE_MISC_BUFFER_STRUCTURED, stride)
    hr, src = device.create_buffer(src_desc)
    assert hr == 0, "structured accumulator must be creatable"
    payload = struct.pack("<" + "f" * (size // 4),
                          *[float(i) * 0.25 for i in range(size // 4)])
    assert device.upload(src, payload) == 0, "accumulator upload failed"
    dst_desc = D3D11_BUFFER_DESC(size, D3D11_USAGE_DEFAULT,
                                 flags_from_names(block["bind_flags"], BIND_FLAG_BITS),
                                 0, flags_from_names(block["misc_flags"], MISC_FLAG_BITS),
                                 stride)
    hr, dst = device.create_buffer(dst_desc)
    assert hr == 0, "emitted destination must be creatable"
    device.copy(dst, src)
    assert device.read_back(dst, size) == payload, (
        "the emitted descriptor must survive the same copy the writer performs")
    print("OK: structured accumulator copied into the emitted descriptor, bytes match")

    # --- Time Position writer: raw seed without shape keys -------------------
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
    timepos_desc = D3D11_BUFFER_DESC(timepos_stride * 4, D3D11_USAGE_DEFAULT,
                                     timepos_bind, 0,
                                     D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS,
                                     timepos_stride)
    hr, _ = device.create_buffer(timepos_desc)
    assert hr == 0, ("Time Position descriptor must be creatable, got 0x%08x"
                     % (hr & 0xFFFFFFFF))
    bare = D3D11_BUFFER_DESC(timepos_stride * 4, D3D11_USAGE_DEFAULT, 0, 0,
                             D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS, timepos_stride)
    hr, _ = device.create_buffer(bare)
    assert hr == E_INVALIDARG, (
        "bind-flag-less raw descriptor must stay rejected, got 0x%08x"
        % (hr & 0xFFFFFFFF))
    print("OK: Time Position raw descriptor (BindFlags=0x%02x) created" % timepos_bind)

    # --- Time Position writer: structured seed when shape keys exist ---------
    shaped_model = harness.make_fake_drawib_model()
    shaped_model.d3d11_game_type.GPU_PreSkinning = True
    shaped_model.shapekey_name_bytelist_dict = {"Sculpt": b"z" * 12}
    shaped_text = render_time_position_ini(
        modules, harness.make_fake_blueprint_model(modules), shaped_model)
    shaped_block = parse_resource_block(
        shaped_text, "[Resource" + shaped_model.draw_ib + "PositionTimeBase]")
    assert shaped_block["type"] == "StructuredBuffer", shaped_block
    assert "bind_flags" not in shaped_block, shaped_block
    structured_desc = D3D11_BUFFER_DESC(
        int(shaped_block["stride"]) * 4, D3D11_USAGE_DEFAULT, 0, 0,
        D3D11_RESOURCE_MISC_BUFFER_STRUCTURED, int(shaped_block["stride"]))
    hr, _ = device.create_buffer(structured_desc)
    assert hr == 0, ("structured seed must be creatable without SRV/UAV, got 0x%08x"
                     % (hr & 0xFFFFFFFF))
    print("OK: structured Time Position seed created without bind flags")

    # --- compute path: the game-facing Position is a cs-t0 reference ---------
    cs_model = make_gpu_model(modules, "abcd1234", 40, {"Sculpt": b"w" * 40})
    cs_model.d3d11_game_type.CategoryExtractSlotDict = {
        "Position": "cs-t0", "Texcoord": "vb1", "Blend": "cs-t1"}
    cs_text = render_cs_vb_section(modules, cs_model)
    assert "cs-t0 = Resourceabcd1234Position" in cs_text, cs_text
    print("OK: compute path keeps binding the game-facing Position as cs-t0")

    print("test_shapekey_descriptor_gpu OK")


if __name__ == "__main__":
    main()
