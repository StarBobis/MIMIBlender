"""Compile the shipped YYSLS VS and optionally compare a working reference.

Uses the Windows system HLSL compiler without installing the Windows SDK.
No game process, mod-loader DLL, graphics hook, or shader cache is modified.
The comparison ignores reflection/debug metadata and compares executable
DXBC plus the input/output signatures. Matching these chunks demonstrates
that removing dead cloth branches has not changed the compiled shader.
This does not replace testing the generated INI in the user's game build.
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


def blob_call(blob, index, result):
    """Call a parameterless ID3DBlob method with its implicit this pointer."""
    table = ct.cast(blob, ct.POINTER(ct.POINTER(PTR))).contents
    method = ct.WINFUNCTYPE(result, PTR)(table[index])
    return method(blob)


def compile_shader(path):
    """Return compiled DXBC bytes and release every compiler-owned blob."""
    # Explicit System32 lookup avoids loading a DLL from the mod directory.
    # The compiler accepts the original source's UTF-8 comments as well.
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
        # Use the normal optimization level for both reference and shipped VS.
        # No include handler is needed: the asset must be self-contained.
        hr = compiler.D3DCompile(
            source, len(source), path.name.encode("utf-8"), None, None,
            b"main", b"vs_5_0", 0, 0, ct.byref(code), ct.byref(errors),
        )
        if hr < 0:
            message = ct.string_at(blob_call(errors, 3, PTR)) if errors else b""
            raise AssertionError(message.decode("utf-8", errors="replace"))
        return ct.string_at(blob_call(code, 3, PTR), blob_call(code, 4, ct.c_size_t))
    finally:
        # Warnings may allocate a blob even when compilation succeeded.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    shader = ROOT / "resources" / "yysls_no_cloth.hlsl"
    chunks = dxbc_chunks(compile_shader(shader))
    assert b"SHDR" in chunks or b"SHEX" in chunks
    print("PASS: shipped no-cloth shader compiles as vs_5_0")

    # An optional original ShaderFixes file allows exact executable comparison.
    # Reflection differs because unused declarations have intentionally gone.
    # Input and output signatures must not differ from the working replacement.
    # Byte-for-byte executable comparison also catches subtle swizzle mistakes.
    # Merely compiling successfully would not detect those rendering changes.
    if args.reference:
        reference = dxbc_chunks(compile_shader(args.reference))
        for key in (b"ISGN", b"OSGN", b"SHDR", b"SHEX"):
            assert chunks.get(key) == reference.get(key), "DXBC mismatch: " + str(key)
        print("PASS: executable and input/output signatures match the reference exactly")


if __name__ == "__main__":
    main()
