"""Exercise the Naraka shape shader with real D3D11 buffers on Windows WARP.

This is not an INI parser or an in-game test. It verifies the D3D11 resource
contract used by the exporter: explicit structured inputs, structured UAV,
then a byte copy to a raw buffer whose misc flags do not include STRUCTURED.
The shader is compiled directly from the plugin's shared Shapes.hlsl.

Run without arguments for synthetic data, or pass base and shape .buf paths
to validate an exported mesh. Only Python's standard library is required.
WARP is Microsoft's software D3D11 driver, so no game injection is needed.

COM method indices used here (including the three IUnknown methods):
  Device 3: CreateBuffer; 4: CreateTexture1D.
  Device 7: CreateShaderResourceView; 8: CreateUnorderedAccessView.
  Device 18: CreateComputeShader.
  Context 14/15: Map/Unmap a CPU-readable staging resource.
  Context 41: Dispatch the active compute shader.
  Context 47: CopyResource without changing either resource descriptor.
  Context 67/68/69: CSSetShaderResources/UnorderedAccessViews/Shader.
  Context 110: ClearState before releasing resources.
  Blob 3/4: GetBufferPointer/GetBufferSize for compiled shader bytecode.
  All objects 2: Release the caller's COM reference.

D3D11 numeric constants are kept next to the operations they configure.
Each vertex is ten float32 values: position(3), normal(3), tangent(4).
The raw SRV counts 32-bit words rather than 40-byte vertex structures.
The final CPU comparison includes every component, not only positions.
These calls deliberately bypass 3Dmigoto; INI syntax/order is covered by
test_naraka_shapekeys.py, while this test validates the resource contract.
"""

import argparse
import ctypes as ct
import math
from pathlib import Path
import struct
import sys


# All COM calls below use the public ID3D11Device/DeviceContext vtable ABI.
# Fixed-width integers matter: Python runs on both 32-bit and 64-bit Windows.
UINT = ct.c_uint32
HRESULT = ct.c_int32
PTR = ct.c_void_p


class BufferDesc(ct.Structure):
    # Field order follows D3D11_BUFFER_DESC from the Windows SDK.
    _fields_ = [(name, UINT) for name in (
        "ByteWidth", "Usage", "BindFlags", "CPUAccessFlags", "MiscFlags", "StructureByteStride")]


class TextureDesc(ct.Structure):
    # The IniParams texture uses one float4 per entry, including entry 88.
    _fields_ = [(name, UINT) for name in (
        "Width", "MipLevels", "ArraySize", "Format", "Usage", "BindFlags", "CPUAccessFlags", "MiscFlags")]


class InitialData(ct.Structure):
    # Buffer initialization is synchronous; callers retain the byte storage.
    _fields_ = [("data", PTR), ("row_pitch", UINT), ("slice_pitch", UINT)]


class MappedData(ct.Structure):
    # Staging buffers are read back only after the dispatch and raw copy.
    _fields_ = [("data", PTR), ("row_pitch", UINT), ("depth_pitch", UINT)]


def method(obj, index, result, *argtypes):
    """Bind a COM method without third-party Python or graphics packages."""
    table = ct.cast(obj, ct.POINTER(ct.POINTER(PTR))).contents
    return ct.WINFUNCTYPE(result, PTR, *argtypes)(table[index])


def call(obj, index, result, argtypes, *args):
    # Keep the implicit COM this pointer in exactly one place.
    return method(obj, index, result, *argtypes)(obj, *args)


def succeeded(hr, label):
    # HRESULT errors carry the failed operation, not only a numeric code.
    if hr < 0:
        raise RuntimeError(label + " failed: 0x" + format(hr & 0xffffffff, "08x"))


def run(base, shape, stride=40, animated_seed=False):
    """Compile real shaders and check base + deltas, including animated seeds.

    The position-only and full-vertex shaders share the same slot contract.
    Test partial work groups and meshes larger than the old Dispatch limit.
    """
    if len(base) != len(shape) or not base or len(base) % stride:
        raise ValueError("Base and shape must have equal nonzero sizes aligned to stride")
    count = len(base) // stride
    if count > 65535 * 64:
        raise ValueError("Vertex count exceeds the 64-thread Dispatch limit")

    # Load system DLLs, not the mod loader's injected replacement d3d11.dll.
    # Explicit System32 paths avoid accidentally using a local proxy DLL.
    import os
    system = Path(os.environ["SystemRoot"]) / "System32"
    d3d = ct.WinDLL(str(system / "d3d11.dll"))
    compiler = ct.WinDLL(str(system / "d3dcompiler_47.dll"))
    owned = []
    device, context = PTR(), PTR()

    def create(index, argtypes, *args):
        # Register every created COM object for cleanup even on later failure.
        out = PTR()
        hr = call(device, index, HRESULT, [*argtypes, ct.POINTER(PTR)], *args, ct.byref(out))
        succeeded(hr, "ID3D11Device method " + str(index))
        owned.append(out)
        return out

    def buffer(data=None, bind=8, misc=64, staging=False):
        # STRUCTURED=0x40, ALLOW_RAW_VIEWS=0x20: never combine these flags.
        # The raw output retains the exported 40-byte vertex stride.
        desc = BufferDesc(len(base), 3 if staging else 0, bind,
                          0x20000 if staging else 0, misc, 0 if staging else stride)
        storage = ct.create_string_buffer(data) if data is not None else None
        initial = InitialData(ct.cast(storage, PTR), 0, 0) if storage is not None else None
        return create(3, [ct.POINTER(BufferDesc), ct.POINTER(InitialData)],
                      ct.byref(desc), ct.byref(initial) if initial is not None else None)

    def view(resource, unordered=False):
        # Null descriptors infer views for structured buffers and typed textures.
        # Raw SRVs below use an explicit BUFFEREX descriptor instead.
        return create(8 if unordered else 7, [PTR, PTR], resource, None)

    def srv(slot, resource_view):
        # CSSetShaderResources only touches the requested single slot.
        views = (PTR * 1)(resource_view.value if resource_view else None)
        call(context, 67, None, [UINT, UINT, ct.POINTER(PTR)], slot, 1, views)

    try:
        # D3D_DRIVER_TYPE_WARP=5, D3D11_SDK_VERSION=7.
        # Feature level 11.0 guarantees compute shader 5.0 support.
        levels = (UINT * 1)(0xb000)
        d3d.D3D11CreateDevice.argtypes = [PTR, UINT, PTR, UINT, ct.POINTER(UINT), UINT,
                                         UINT, ct.POINTER(PTR), ct.POINTER(UINT), ct.POINTER(PTR)]
        d3d.D3D11CreateDevice.restype = HRESULT
        succeeded(d3d.D3D11CreateDevice(None, 5, None, 0, levels, 1, 7,
                                       ct.byref(device), None, ct.byref(context)), "Create WARP device")
        owned.extend([device, context])

        # Compile the actual shipped shader, not a simplified stand-in.
        shader_file = "Shapes.hlsl" if stride == 40 else "shapes_position.hlsl"
        source = (Path(__file__).resolve().parents[1] / "resources" / shader_file).read_bytes()
        code, errors = PTR(), PTR()
        compiler.D3DCompile.argtypes = [PTR, ct.c_size_t, ct.c_char_p, PTR, PTR,
                                        ct.c_char_p, ct.c_char_p, UINT, UINT,
                                        ct.POINTER(PTR), ct.POINTER(PTR)]
        compiler.D3DCompile.restype = HRESULT
        hr = compiler.D3DCompile(source, len(source), b"Shapes.hlsl", None, None,
                                 b"main", b"cs_5_0", 0, 0, ct.byref(code), ct.byref(errors))
        for blob in (code, errors):
            if blob:
                owned.append(blob)
        if hr < 0 and errors:
            message = call(errors, 3, PTR, [])
            print(ct.string_at(message).decode("utf-8", errors="replace"))
        succeeded(hr, "Compile Shapes.hlsl")
        shader = create(18, [PTR, ct.c_size_t, PTR],
                        call(code, 3, PTR, []), call(code, 4, ct.c_size_t, []), None)
        call(context, 69, None, [PTR, PTR, UINT], shader, None, 0)

        # Reproduce the old declarations before validating the fixed path.
        # Buffer+stride has no structured flag, so its UNKNOWN-format SRV fails.
        # Merely adding RAW to a structured copy also makes CreateBuffer fail.
        plain = buffer(base, misc=0)
        invalid_view = PTR()
        hr = call(device, 7, HRESULT, [PTR, PTR, ct.POINTER(PTR)], plain, None, ct.byref(invalid_view))
        if invalid_view:
            owned.append(invalid_view)
        if hr >= 0:
            raise AssertionError("Plain Buffer unexpectedly accepted an inferred structured SRV")
        bad_desc = BufferDesc(len(base), 0, 8, 0, 32 | 64, 40)
        invalid_buffer = PTR()
        hr = call(device, 3, HRESULT, [ct.POINTER(BufferDesc), PTR, ct.POINTER(PTR)],
                  ct.byref(bad_desc), None, ct.byref(invalid_buffer))
        if invalid_buffer:
            owned.append(invalid_buffer)
        if hr >= 0:
            raise AssertionError("D3D11 unexpectedly accepted RAW and STRUCTURED together")
        # Reproduce the shared pipeline's former structured-to-VB failure as
        # well. A ref cannot turn a compute descriptor into a vertex buffer.
        bad_desc = BufferDesc(len(base), 0, 128 | 1, 0, 64, stride)
        invalid_vertex_buffer = PTR()
        hr = call(device, 3, HRESULT, [ct.POINTER(BufferDesc), PTR, ct.POINTER(PTR)],
                  ct.byref(bad_desc), None, ct.byref(invalid_vertex_buffer))
        if invalid_vertex_buffer:
            owned.append(invalid_vertex_buffer)
        assert hr < 0, "Structured buffers must reject VERTEX_BUFFER bindings"
        print("OK: all three legacy resource descriptor failures reproduced")

        # Inputs are explicitly structured; the accumulator has a UAV binding.
        # This mirrors type=StructuredBuffer plus cs-u5=copy base in the INI.
        base_buffer, shape_buffer = buffer(base), buffer(shape)
        # Structured buffers cannot carry VERTEX_BUFFER bindings in D3D11.
        # Keep the accumulator compute-only and copy into the raw result below.
        working = buffer(bind=128)
        base_view, shape_view = view(base_buffer), view(shape_buffer)
        working_view = view(working, unordered=True)
        srv(50, base_view)
        srv(51, shape_view)
        uavs = (PTR * 1)(working_view.value)
        call(context, 68, None, [UINT, UINT, ct.POINTER(PTR), PTR], 5, 1, uavs, None)

        # The intermediate result has RAW only, not RAW|STRUCTURED.
        # Validate the exact R32_TYPELESS BUFFEREX SRV used by raw reads.
        # Validate both consumers: raw SRV for skinning and VB for the shared
        # CPU-skinned path. Neither may inherit the accumulator's STRUCTURED bit.
        raw = buffer(bind=8 | 1, misc=32)
        raw_desc = (UINT * 6)(39, 11, 0, len(base) // 4, 1, 0)
        create(7, [PTR, PTR], raw, ct.byref(raw_desc))
        readback = buffer(bind=0, misc=0, staging=True)
        original = struct.unpack("<" + "f" * (len(base) // 4), base)
        target = struct.unpack("<" + "f" * (len(shape) // 4), shape)

        # Include a reset after weight 1, then multiple keys/dispatches.
        # Re-copying the pristine base each run prevents frame accumulation.
        # A nontrivial animated seed catches the old cancellation bug at
        # weight=1: subtracting the seed instead of base would erase animation.
        seed_values = [value + (2.0 if animated_seed else 0.0) for value in original]
        seed_buffer = buffer(struct.pack("<" + "f" * len(seed_values), *seed_values))
        for weights in ((0.0,), (0.3,), (1.0,), (0.0,), (0.2, 0.5)):
            call(context, 47, None, [PTR, PTR], working, seed_buffer)
            for weight in weights:
                # IniParams[88].x carries the weight exactly as x88 does.
                params = (ct.c_float * (89 * 4))()
                params[88 * 4] = weight
                initial = InitialData(ct.cast(params, PTR), 0, 0)
                desc = TextureDesc(89, 1, 1, 2, 0, 8, 0, 0)
                texture = create(4, [ct.POINTER(TextureDesc), ct.POINTER(InitialData)],
                                 ct.byref(desc), ct.byref(initial))
                srv(120, view(texture))
                call(context, 41, None, [UINT, UINT, UINT], (count + 63) // 64, 1, 1)

            # Copy structured bytes into raw, then into a CPU-readable buffer.
            # These are real D3D11 operations, not a CPU-only interpolation test.
            call(context, 47, None, [PTR, PTR], raw, working)
            call(context, 47, None, [PTR, PTR], readback, raw)
            mapped = MappedData()
            succeeded(call(context, 14, HRESULT, [PTR, UINT, UINT, UINT, ct.POINTER(MappedData)],
                           readback, 0, 1, 0, ct.byref(mapped)), "Map readback")
            result = ct.string_at(mapped.data, len(base))
            call(context, 15, None, [PTR, UINT], readback, 0)
            actual = struct.unpack("<" + "f" * len(original), result)
            expected = [seed + (b - a) * sum(weights) for seed, a, b in zip(seed_values, original, target)]
            for index, (a, b) in enumerate(zip(actual, expected)):
                if not math.isclose(a, b, rel_tol=2e-5, abs_tol=2e-6):
                    raise AssertionError("GPU mismatch at component " + str(index) + ": " + str((a, b)))
            print("OK: WARP structured -> raw, weights=" + str(weights) + ", vertices=" + str(count))
    finally:
        # ClearState releases the context's references before our COM cleanup.
        # Reverse creation order keeps the device alive until all children exit.
        if context:
            call(context, 110, None, [])
        for obj in reversed(owned):
            call(obj, 2, UINT, [])


def main():
    # The smoke test remains cross-platform; this integration test needs Windows.
    if sys.platform != "win32":
        print("SKIP: D3D11 WARP is only available on Windows")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("buffers", nargs="*", type=Path)
    args = parser.parse_args()
    if args.buffers:
        if len(args.buffers) != 2:
            parser.error("Pass both base and shape buffer paths, or neither")
        base, shape = [path.read_bytes() for path in args.buffers]
    else:
        # Synthetic values cover positions, normals, and all tangent components.
        # An odd vertex count also catches accidental hard-coded draw sizes.
        values = [float(i % 13) / 13 for i in range(70)]
        base = struct.pack("<70f", *values)
        shape = struct.pack("<70f", *[value + 0.25 for value in values])
    run(base, shape)
    if not args.buffers:
        # Cover the new layout, partial final groups, animated-seed composition,
        # and a 65537-vertex mesh that failed with one group per vertex.
        for stride, count in ((12, 65), (40, 65), (12, 65537)):
            values = [float(i % 13) / 13 for i in range(count * stride // 4)]
            fmt = "<" + "f" * len(values)
            run(struct.pack(fmt, *values), struct.pack(fmt, *[v + 0.25 for v in values]), stride, True)
    print("ALL NARAKA GPU CHECKS PASSED")


if __name__ == "__main__":
    main()
