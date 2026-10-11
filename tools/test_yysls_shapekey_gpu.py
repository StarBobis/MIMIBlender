"""Compile emitted YYSLS shaders and execute them on the D3D11 WARP driver.

This uses the real export template and real Direct3D buffers, not shader mocks.
An independent CPU oracle checks float/UNORM positions and packed normals.
Color, UV, padding, and normal/position W must remain byte-identical to the seed.
Zero weights must preserve the entire seed exactly, including unusual words.
Multiple key dispatches must normalize/quantize only after the final delta.
The same run resets to the base after a full-weight dispatch to catch drift.
An animated seed must not be substituted for the immutable delta reference.
Odd counts exercise tail guards, and a large count exceeds the old group limit.
The command-line mode accepts the supplied reference base and target buffers.
No game installation, injection, or external Python package is needed.
WARP cannot establish compatibility with a particular game's loader fork.
That final acceptance step still requires an in-game test of the generated INI.
"""

import argparse
import math
from pathlib import Path
import struct
import sys
import tempfile

import test_yysls_shapekeys as support
from test_naraka_shapekey_gpu import run


def normalize(values, fallback=(0.0, 0.0, 1.0)):
    # Match the reference convention but use Python doubles for the oracle.
    # A finite fallback is required when opposite directions cancel exactly.
    squared = sum(value * value for value in values)
    if squared < 1e-12:
        return fallback
    return tuple(value / math.sqrt(squared) for value in values)


def read_normal(vertex, normal_offset):
    # Only XYZ are directional data; W is never included in normalization.
    return normalize([byte * 2.0 / 255.0 - 1.0 for byte in vertex[normal_offset:normal_offset + 3]])


def read_position(vertex, compressed):
    # Normalized coordinates suffice because base/shape share one bounding box.
    if compressed:
        return tuple(value / 65535.0 for value in struct.unpack_from("<3H", vertex))
    return struct.unpack_from("<3f", vertex)


def check_result(base, shape, seed, result, weights, compressed=False):
    """Check every output vertex and every field, not only a sample position.

    GPU float arithmetic may differ slightly from Python's double precision.
    Permit one integer quantization unit for packed positions and normal XYZ.
    W and all unrelated words have no arithmetic and must be exactly equal.
    A zero-weight run bypasses normalization, allowing an exact whole-file check.
    Negative weights and cancellation share the same additive delta contract.
    """
    stride = 24 if compressed else 28
    normal_offset = 12 if compressed else 16
    if all(weight == 0 for weight in weights):
        assert result == seed, "Zero weights changed the seed"
        return
    for offset in range(0, len(base), stride):
        original = base[offset:offset + stride]
        target = shape[offset:offset + stride]
        start = seed[offset:offset + stride]
        actual = result[offset:offset + stride]
        positions = zip(read_position(start, compressed), read_position(original, compressed), read_position(target, compressed))
        expected_position = [s + (b - a) * sum(weights) for s, a, b in positions]
        if compressed:
            expected_position = [max(0.0, min(1.0, value)) for value in expected_position]
        tolerance = 1.1 / 65535.0 if compressed else 2e-6
        for observed, expected in zip(read_position(actual, compressed), expected_position):
            assert math.isclose(observed, expected, abs_tol=tolerance, rel_tol=2e-5), (offset, observed, expected)
        # Reproduce final normalization once, not repeated per-key lerps.
        start_normal = read_normal(start, normal_offset)
        normals = zip(start_normal, read_normal(original, normal_offset), read_normal(target, normal_offset))
        direction = normalize([s + (b - a) * sum(weights) for s, a, b in normals], start_normal)
        expected_normal = [int(max(0.0, min(1.0, value * 0.5 + 0.5)) * 255.0 + 0.5) for value in direction]
        for observed, expected in zip(actual[normal_offset:normal_offset + 3], expected_normal):
            assert abs(observed - expected) <= 1, (offset, observed, expected)
        # Exclude only position XYZ and normal XYZ from the exact-byte check.
        # This includes unusual color words and all UV/padding payloads.
        changed = set(range(6 if compressed else 12)) | set(range(normal_offset, normal_offset + 3))
        assert all(actual[index] == start[index] for index in range(stride) if index not in changed)


def synthetic(count, compressed=False, opposing=False):
    # Opaque words include NaN bit patterns to catch accidental float conversion.
    # Normal W intentionally differs between base and target; only seed W wins.
    base, shape, seed = bytearray(), bytearray(), bytearray()
    for index in range(count):
        for output, delta, normal, w in ((base, 0, (240, 100, 155), 0x63),
                                         (shape, 0.2, (150, 230, 120), 0x19),
                                         (seed, 0.05, (240, 100, 155), 0x87)):
            position = [0.2 + (index % 7) * 0.02 + delta, 0.3 + delta, 0.4 + delta]
            if compressed:
                output.extend(struct.pack("<4H", *[int(value * 65535 + 0.5) for value in position], 0x4567))
            else:
                output.extend(struct.pack("<3f", *position))
            output.extend(struct.pack("<I", 0x7fc01234))
            if opposing:
                # Complementary byte triplets decode to exact opposite vectors.
                normal = (0, 127, 127) if output is shape else (255, 128, 128)
            output.extend(bytes((*normal, w)))
            output.extend(struct.pack("<2I", 0xdeadbeef, index))
    return bytes(base), bytes(shape), bytes(seed)


def exercise(base, shape, compressed=False, seed=None):
    """Build the shader through the production writer, then run actual D3D11.

    The output directory is temporary, with no edits to the supplied reference.
    Length validation is exercised before the Direct3D resource is allocated.
    Generated layout constants are therefore exactly those used by real exports.
    The GPU harness also reproduces the invalid legacy resource flag failures.
    """
    stride = 24 if compressed else 28
    model = support.make_model(count=len(base) // stride, compressed=compressed)
    model.category_buffer_dict["Position"] = base
    model.shapekey_name_bytelist_dict["blink"] = shape
    support.support.TEST_SHAPEKEY_DICT["blink"] = support.KEY(key_name="$shapekey0")
    with tempfile.TemporaryDirectory() as directory:
        support.cloth_support.CONFIG.output = directory
        support.SHAPES.write_shaders([model])
        source = (Path(directory) / support.SHAPES.shader_filename(model)).read_bytes()
    # Preserve a clean boundary between shader output and the CPU oracle.
    # The callback sees read-back bytes, never a simulated GPU result.
    checker = lambda a, b, s, result, weights: check_result(a, b, s, result, weights, compressed)
    run(base, shape, stride=stride, shader_source=source, result_checker=checker, seed_data=seed)


def main():
    # The test is explicit about Windows rather than silently faking a GPU.
    if sys.platform != "win32":
        print("SKIP: D3D11 WARP is only available on Windows")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("buffers", nargs="*", type=Path)
    args = parser.parse_args()
    if args.buffers:
        if len(args.buffers) != 2:
            parser.error("Pass the reference base and shape buffer paths together")
        exercise(*[path.read_bytes() for path in args.buffers])
    else:
        # Test both layouts, odd tails, opposing normals, and seed composition.
        for compressed, count, opposing in ((False, 65, False), (True, 65, False),
                                             (False, 65, True), (False, 65537, False)):
            base, shape, seed = synthetic(count, compressed, opposing)
            exercise(base, shape, compressed, seed)
    print("ALL YYSLS GPU CHECKS PASSED")


if __name__ == "__main__":
    main()
