"""Compile the shipped YYSLS no-cloth vertex shader.

This tool uses the Windows system HLSL compiler without installing the Windows
SDK. No game process, mod-loader DLL, graphics hook, or shader cache is
modified. Two optional comparisons are available:

--reference      another no-cloth asset from the same game build. Executable
                 DXBC and every signature chunk must match byte-for-byte, which
                 shows a rewrite did not change the compiled path.
--reference-abi  a dumped game shader for the same draw, cloth path included.
                 Semantic names, indices, component formats and input slots
                 must match, so the asset still binds where the game binds it.
                 Per-component read masks may differ: the cloth solver is what
                 makes the game shader read SV_VertexID, and this asset removes
                 it. Executables never match across builds by design.
"""

import argparse
import ctypes as ct
import os
from pathlib import Path
import struct


# Use fixed-width HRESULT/UINT types for the public COM ABI on Windows.
# Blob methods 3 and 4 expose bytecode; method 2 releases the owned reference.
PTR = ct.c_void_p
UINT = ct.c_uint32
HRESULT = ct.c_int32
ROOT = Path(__file__).resolve().parents[1]
SHADERS = (
    ROOT / "resources" / "yysls_no_cloth.hlsl",
)


def blob_call(blob, index, result):
    """Call a parameterless ID3DBlob method with its implicit this pointer."""
    table = ct.cast(blob, ct.POINTER(ct.POINTER(PTR))).contents
    method = ct.WINFUNCTYPE(result, PTR)(table[index])
    return method(blob)


def compile_shader(path):
    """Return compiled DXBC bytes and release every compiler-owned blob."""
    # Explicit System32 lookup avoids loading a DLL from the mod directory.
    # The compiler accepts the source's UTF-8 comments as well.
    system = Path(os.environ["SystemRoot"]) / "System32"
    compiler = ct.WinDLL(str(system / "d3dcompiler_47.dll"))
    compiler.D3DCompile.argtypes = [
        PTR, ct.c_size_t, ct.c_char_p, PTR, PTR, ct.c_char_p, ct.c_char_p,
        UINT, UINT, ct.POINTER(PTR), ct.POINTER(PTR),
    ]
    compiler.D3DCompile.restype = HRESULT
    source = path.read_bytes()
    code, errors = PTR(), PTR()
    try:
        # Use the normal optimization level for every shipped variant.
        # No include handler is needed: each asset is self-contained.
        hr = compiler.D3DCompile(
            source, len(source), path.name.encode("utf-8"), None, None,
            b"main", b"vs_5_0", 0, 0, ct.byref(code), ct.byref(errors),
        )
        if hr < 0:
            message = ct.string_at(blob_call(errors, 3, PTR)) if errors else b""
            raise AssertionError(message.decode("utf-8", errors="replace"))
        return ct.string_at(blob_call(code, 3, PTR), blob_call(code, 4, ct.c_size_t))
    finally:
        # Warnings may allocate a blob even when compilation succeeds.
        # Release both blobs after copying their contents into Python bytes.
        for blob in (errors, code):
            if blob:
                blob_call(blob, 2, UINT)


def dxbc_chunks(data):
    """Read the standard DXBC chunk table without third-party packages."""
    # The container header is magic, checksum, version, size, chunk count.
    # Every table entry then points to a four-character type and byte size.
    assert data[:4] == b"DXBC"
    count = struct.unpack_from("<I", data, 28)[0]
    result = {}
    for index in range(count):
        offset = struct.unpack_from("<I", data, 32 + index * 4)[0]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        result[data[offset:offset + 4]] = data[offset + 8:offset + 8 + size]
    return result


def signature_elements(data):
    """Decode one DXBC signature chunk into layout-relevant elements.

    The chunk is a count, a reserved dword, then one 24-byte element per
    semantic and a string table of absolute name offsets. The trailing
    read/write "used" byte is deliberately dropped: it records which
    components the shader body happens to read, so removing the cloth solver
    changes it for SV_VertexID without changing the input layout the game
    binds. D3D11 validates a layout against semantic, index, format and slot,
    never against that read mask.
    """
    assert data[:4] != b""
    count = struct.unpack_from("<I", data, 0)[0]
    elements = []
    for index in range(count):
        base = 8 + index * 24
        name_offset, semantic, system_value, component, register = struct.unpack_from("<5I", data, base)
        mask = data[base + 20]
        end = data.index(b"\0", name_offset)
        elements.append((data[name_offset:end].decode("ascii"), semantic,
                         system_value, component, register, mask))
    return elements


def compare_reference(shipped, reference):
    """Require executable and signature chunks to match a working reference."""
    # Reflection differs because unused declarations were intentionally removed.
    # Input/output signatures and executable DXBC must remain byte-identical.
    for key in (b"ISGN", b"OSGN", b"SHDR", b"SHEX"):
        assert shipped.get(key) == reference.get(key), "DXBC mismatch: " + str(key)


def compare_signatures(shipped, reference):
    """Require the bound input/output ABI, ignoring per-component read masks."""
    # A no-cloth variant must remove cloth execution while retaining the source
    # input layout and pixel-shader-facing output contract.
    for key in (b"ISGN", b"OSGN"):
        mine, theirs = signature_elements(shipped[key]), signature_elements(reference[key])
        assert mine == theirs, "%s ABI mismatch:\n  shipped=%r\n  reference=%r" % (key, mine, theirs)


def compare_read_masks(shipped, reference):
    """Report which elements the two sources read differently, if any."""
    report = []
    for key in (b"ISGN", b"OSGN"):
        mine, theirs = shipped[key], reference[key]
        for index, element in enumerate(signature_elements(mine)):
            base = 8 + index * 24
            used_mine, used_theirs = mine[base + 21], theirs[base + 21]
            if used_mine != used_theirs:
                report.append("%s[%d] %s used 0x%02x vs 0x%02x"
                              % (key.decode(), index, element[0], used_mine, used_theirs))
    return report


def assert_no_cloth_deformation(path, bytecode):
    """Reject accidental reintroduction of the t11 cloth solver path."""
    # The local asset may keep comments describing the removed path, but source
    # declarations and compiled bytecode must not contain its executable ABI.
    source = path.read_text(encoding="utf-8")
    for token in ("Texture2DArray", "cVertexDeformType", "cDeformationMisc", "register(t11)"):
        assert token not in source, "cloth declaration remains: " + token
    assert b"tPositionDeformTex" not in bytecode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path,
                        help="same-build asset whose executable DXBC must match exactly")
    parser.add_argument("--reference-abi", type=Path,
                        help="game dump whose input/output ABI this asset must still satisfy")
    args = parser.parse_args()

    compiled = []
    for shader in SHADERS:
        bytecode = compile_shader(shader)
        chunks = dxbc_chunks(bytecode)
        assert b"SHDR" in chunks or b"SHEX" in chunks
        assert_no_cloth_deformation(shader, bytecode)
        compiled.append(chunks)
        print("PASS: " + shader.name + " compiles as vs_5_0 and has no t11 cloth path")

    # The executable reference is only meaningful within one game build: a
    # recompiled build changes scheduled instructions without changing the ABI.
    if args.reference:
        reference = dxbc_chunks(compile_shader(args.reference))
        compare_reference(compiled[0], reference)
        print("PASS: variant matches its executable and signatures exactly")

    # The ABI reference is a dumped game shader, cloth path included. Element
    # names, indices, formats and slots must match; read masks may not, because
    # the cloth solver is what makes the game shader read SV_VertexID.
    if args.reference_abi:
        reference = dxbc_chunks(compile_shader(args.reference_abi))
        compare_signatures(compiled[0], reference)
        print("PASS: input/output ABI matches " + args.reference_abi.name)
        for line in compare_read_masks(compiled[0], reference):
            print("NOTE: read mask differs, cloth path removed: " + line)


if __name__ == "__main__":
    main()
