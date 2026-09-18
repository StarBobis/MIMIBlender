"""Compile the shipped YYSLS vertex shader variants.

This tool uses the Windows system HLSL compiler without installing the Windows
SDK. No game process, mod-loader DLL, graphics hook, or shader cache is
modified. The optional reference comparison ignores reflection/debug metadata
and compares executable DXBC plus the input/output signatures. Matching those
chunks demonstrates that the original supported shader's dead cloth branches
were removed without changing its compiled path. The second supplied variant
is compiled independently because it has a different input signature and UV
ABI; it has no no-cloth reference in the repository.
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
    ROOT / "resources" / "yysls_no_cloth_49bf02a13c364cd9.hlsl",
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


def compare_reference(shipped, reference):
    """Require executable and signature chunks to match a working reference."""
    # Reflection differs because unused declarations were intentionally removed.
    # Input/output signatures and executable DXBC must remain byte-identical.
    for key in (b"ISGN", b"OSGN", b"SHDR", b"SHEX"):
        assert shipped.get(key) == reference.get(key), "DXBC mismatch: " + str(key)


def compare_signatures(shipped, reference):
    """Require only input/output signatures to match a supplied source."""
    # A no-cloth variant must remove cloth execution while retaining the source
    # input layout and pixel-shader-facing output contract.
    for key in (b"ISGN", b"OSGN"):
        assert shipped.get(key) == reference.get(key), "Signature mismatch: " + str(key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reference-49bf-signature", type=Path)
    args = parser.parse_args()

    compiled = []
    for shader in SHADERS:
        chunks = dxbc_chunks(compile_shader(shader))
        assert b"SHDR" in chunks or b"SHEX" in chunks
        compiled.append(chunks)
        print("PASS: " + shader.name + " compiles as vs_5_0")

    # The optional reference is for the original ab148 no-cloth asset only.
    # The 49bf asset has a different input signature and is validated separately.
    if args.reference:
        reference = dxbc_chunks(compile_shader(args.reference))
        compare_reference(compiled[0], reference)
        print("PASS: first variant matches its executable and signatures exactly")

    if args.reference_49bf_signature:
        reference = dxbc_chunks(compile_shader(args.reference_49bf_signature))
        compare_signatures(compiled[1], reference)
        print("PASS: second variant matches the supplied input/output signatures")


if __name__ == "__main__":
    main()
