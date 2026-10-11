"""Exact original-format DDS replacement, independent of Blender.

All conversion happens in temporary storage. Callers commit the resulting
files only after every configured replacement has passed validation.
Unknown formats are errors: a plausible BC7 fallback is not an exact match.
"""
import os
import shutil
import struct
import tempfile
from dataclasses import dataclass

from .texconv import _run_texconv

# Only typed color formats with an unambiguous texconv spelling are supported.
# Typeless, depth/stencil, video and packed YUV formats deliberately stay out.
# Legacy headers have no stored sRGB semantics; their typed mapping is linear.
# Numeric IDs come from the DDS DX10 header, not the replacement extension.
# sRGB variants remain separate IDs even when their block layouts are equal.
# Single-channel textures must not grow an RGBA channel layout on conversion.
# Signed BC4/BC5 formats must not become their unsigned counterparts.
# Float formats retain their storage type instead of being normalized to bytes.
# BC6H signed and unsigned variants are intentionally distinct targets.
# This table is a conversion allowlist, not a claim to support every DDS type.
# A new entry needs both a texconv spelling and a payload-size test.
DXGI_FORMATS = {
    2: 'R32G32B32A32_FLOAT', 6: 'R32G32B32_FLOAT',
    10: 'R16G16B16A16_FLOAT', 11: 'R16G16B16A16_UNORM',
    13: 'R16G16B16A16_SNORM', 16: 'R32G32_FLOAT',
    24: 'R10G10B10A2_UNORM', 26: 'R11G11B10_FLOAT',
    28: 'R8G8B8A8_UNORM', 29: 'R8G8B8A8_UNORM_SRGB',
    31: 'R8G8B8A8_SNORM', 34: 'R16G16_FLOAT', 35: 'R16G16_UNORM',
    37: 'R16G16_SNORM', 41: 'R32_FLOAT', 49: 'R8G8_UNORM',
    51: 'R8G8_SNORM', 54: 'R16_FLOAT', 56: 'R16_UNORM',
    58: 'R16_SNORM', 61: 'R8_UNORM', 63: 'R8_SNORM', 65: 'A8_UNORM',
    67: 'R9G9B9E5_SHAREDEXP', 71: 'BC1_UNORM', 72: 'BC1_UNORM_SRGB',
    74: 'BC2_UNORM', 75: 'BC2_UNORM_SRGB',
    77: 'BC3_UNORM', 78: 'BC3_UNORM_SRGB',
    80: 'BC4_UNORM', 81: 'BC4_SNORM', 83: 'BC5_UNORM', 84: 'BC5_SNORM',
    85: 'B5G6R5_UNORM', 86: 'B5G5R5A1_UNORM',
    87: 'B8G8R8A8_UNORM', 88: 'B8G8R8X8_UNORM',
    91: 'B8G8R8A8_UNORM_SRGB', 93: 'B8G8R8X8_UNORM_SRGB',
    95: 'BC6H_UF16', 96: 'BC6H_SF16',
    98: 'BC7_UNORM', 99: 'BC7_UNORM_SRGB', 115: 'B4G4R4A4_UNORM',
}

# FourCC aliases map to the actual storage format, not a guessed color space.
# DXT2/4 encode premultiplied alpha and are rejected rather than transformed.
# Legacy FourCC values can include old numeric D3DFORMAT identifiers.
# Those values are read as four bytes so integer aliases remain little-endian.
# ATI and BC aliases describe the same channel and compression layouts.
# Do not add DXT2 or DXT4 without preserving premultiplied-alpha semantics.
# Conversion never guesses those semantics from opaque replacement pixels.
LEGACY_FOURCC = {
    b'DXT1': 71, b'DXT3': 74, b'DXT5': 77,
    b'ATI1': 80, b'BC4U': 80, b'BC4S': 81,
    b'ATI2': 83, b'BC5U': 83, b'BC5S': 84,
    struct.pack('<I', 36): 11, struct.pack('<I', 110): 13,
    struct.pack('<I', 111): 54, struct.pack('<I', 112): 34,
    struct.pack('<I', 113): 10, struct.pack('<I', 114): 41,
    struct.pack('<I', 115): 16, struct.pack('<I', 116): 2,
}

# These exact bit masks are the common legacy RGB and luminance encodings.
# Unsupported masks must not be mislabeled as RGBA during image conversion.
# Mask order is bit count, red, green, blue, then alpha.
# Luminance formats share this representation but keep their typed channel count.
# An absent alpha mask differs from an alpha channel filled with opaque values.
# The BGRX entry therefore remains distinct from BGRA.
# Legacy luminance-alpha is not RG storage: the shader-visible channel meaning differs.
# Reject it rather than silently replacing its alpha channel with green.
# Arbitrary masks are unsupported rather than heuristically reordered.
LEGACY_MASKS = {
    (32, 0xff, 0xff00, 0xff0000, 0xff000000): 28,
    (32, 0xff0000, 0xff00, 0xff, 0xff000000): 87,
    (32, 0xff0000, 0xff00, 0xff, 0): 88,
    (16, 0xf800, 0x7e0, 0x1f, 0): 85,
    (16, 0x7c00, 0x3e0, 0x1f, 0x8000): 86,
    (16, 0xf00, 0xf0, 0xf, 0xf000): 115,
    (8, 0xff, 0, 0, 0): 61,
    (16, 0xffff, 0, 0, 0): 56,
    (8, 0, 0, 0, 0xff): 65,
}


@dataclass(frozen=True)
class DDSMetadata:
    """Stored metadata; no attempt is made to infer shader-view semantics."""
    # Dimensions refer to the top mip, not the sum of the mip chain.
    # Depth participates in volume topology and in full-chain detection.
    # Array size counts cubes, while the payload check counts their six faces.
    # Frozen metadata makes equality safe for same-hash ambiguity detection.
    # The default dimension value is the DX10 enum for a 2D texture.
    width: int
    height: int
    mip_count: int
    dxgi: int
    dx10: bool
    dimension: int = 3
    array_size: int = 1
    cube: bool = False
    depth: int = 1
    alpha_mode: int = 0

    @property
    def format(self):
        # Unknown IDs remain identifiable for exact DDS passthrough checks.
        return DXGI_FORMATS.get(self.dxgi, 'DXGI_' + str(self.dxgi))

    @property
    def full_mips(self):
        return max(self.width, self.height, self.depth).bit_length()

    @property
    def ordinary_2d(self):
        return self.dimension == 3 and self.array_size == 1 and not self.cube and self.depth == 1

    @property
    def storage_key(self):
        # Header style and alpha mode matter as well as the DXGI format.
        return (self.dxgi, self.dx10, self.dimension, self.array_size,
                self.cube, self.depth, self.alpha_mode)


def read_dds_metadata(path):
    """Parse DDS/DX10 headers without invoking image decoders or Blender."""
    # Read only the fixed header; texture payloads can be very large.
    # Seeking to the end obtains a size without decoding or allocating pixels.
    # DDS magic and both structure sizes are validated before field access.
    # File errors propagate so missing originals cannot silently disappear.
    # Stored zero mip/depth counts use the DDS single-level conventions.
    with open(path, 'rb') as stream:
        header = stream.read(148)
        stream.seek(0, 2)
        length = stream.tell()
    if len(header) < 128 or header[:4] != b'DDS ':
        raise ValueError('Original texture is not a valid DDS: ' + str(path))
    if struct.unpack_from('<I', header, 4)[0] != 124 or struct.unpack_from('<I', header, 76)[0] != 32:
        raise ValueError('Invalid DDS header sizes: ' + str(path))
    height, width = struct.unpack_from('<II', header, 12)
    depth = max(1, struct.unpack_from('<I', header, 24)[0])
    mips = max(1, struct.unpack_from('<I', header, 28)[0])
    fourcc = header[84:88]
    caps2 = struct.unpack_from('<I', header, 112)[0]
    dx10 = fourcc == b'DX10'
    dimension, array_size, cube, alpha = 3, 1, bool(caps2 & 0x200), 0
    # The optional extension determines topology, format and alpha interpretation.
    # Legacy caps remain authoritative only when the extension is absent.
    # The extension must be complete and accompanied by image payload.
    # Unknown DXGI IDs can still be compared for exact byte passthrough.
    if dx10:
        if length <= 148 or len(header) < 148:
            raise ValueError('Truncated DX10 DDS: ' + str(path))
        dxgi, dimension, misc, array_size, alpha = struct.unpack_from('<IIIII', header, 128)
        cube = bool(misc & 4)
    else:
        if length <= 128:
            raise ValueError('DDS has no image payload: ' + str(path))
        flags = struct.unpack_from('<I', header, 80)[0]
        if flags & 4:
            dxgi = LEGACY_FOURCC.get(fourcc)
        else:
            masks = struct.unpack_from('<IIIII', header, 88)
            dxgi = LEGACY_MASKS.get(masks)
        if dxgi is None:
            raise ValueError('Unsupported exact legacy DDS format: ' + str(path))
        if caps2 & 0x200000:
            dimension = 4
    # Reject zero dimensions before computing any mip or payload bounds.
    # Impossible mip counts indicate a malformed capture, not a partial chain.
    # The minimum payload deliberately tolerates legal row-padding overhead.
    # Unknown typed sizes cannot receive this lower-bound check.
    if not width or not height or not array_size:
        raise ValueError('Invalid DDS dimensions: ' + str(path))
    # Invalid topology must not qualify for the exact-passthrough exception.
    # Only volume textures carry depth, and volumes cannot be arrays or cubes.
    # A cube is a square 2D resource; 1D resources have exactly one row.
    if dimension not in (2, 3, 4) or (dimension == 2 and height != 1):
        raise ValueError('Invalid DDS resource dimension: ' + str(path))
    if (dimension != 4 and depth != 1) or (dimension == 4 and (array_size != 1 or cube)):
        raise ValueError('Invalid DDS resource topology: ' + str(path))
    if cube and (dimension != 3 or width != height):
        raise ValueError('Invalid DDS cube topology: ' + str(path))
    metadata = DDSMetadata(width, height, mips, dxgi, dx10, dimension, array_size, cube, depth, alpha)
    if mips > metadata.full_mips:
        raise ValueError('Invalid DDS mip count: ' + str(path))
    # Known typed formats have a computable lower bound on payload size.
    # Header-only or truncated DDS files must never pass through unchanged.
    bits = {2: 128, 6: 96, 10: 64, 11: 64, 13: 64, 16: 64,
            24: 32, 26: 32, 28: 32, 29: 32, 31: 32, 34: 32, 35: 32,
            37: 32, 41: 32, 49: 16, 51: 16, 54: 16, 56: 16, 58: 16,
            61: 8, 63: 8, 65: 8, 67: 32, 85: 16, 86: 16, 87: 32,
            88: 32, 91: 32, 93: 32, 115: 16}
    block_size = 8 if dxgi in (71, 72, 80, 81) else 16 if dxgi in (74, 75, 77, 78, 83, 84, 95, 96, 98, 99) else 0
    # BC formats round each mip up to whole 4-by-4 compression blocks.
    # Typed uncompressed formats count bytes from their channel storage width.
    # Every level shrinks independently, including volume depth.
    # Array and cube multipliers apply to the complete per-surface chain.
    # One missing byte is enough to reject an otherwise valid typed header.
    if block_size or dxgi in bits:
        required = 0
        w, h, d = width, height, depth
        for level in range(mips):
            required += ((w + 3) // 4) * ((h + 3) // 4) * block_size * d if block_size else w * h * d * bits[dxgi] // 8
            w, h, d = max(1, w // 2), max(1, h // 2), max(1, d // 2)
        required *= array_size * (6 if cube else 1)
        if length < (148 if dx10 else 128) + required:
            raise ValueError('Truncated DDS image payload: ' + str(path))
    return metadata


def matching_mip_count(original, width, height):
    """Keep one mip, regenerate full chains, or retain an exact partial count."""
    # Replacement size is retained unless the caller explicitly forces capture size.
    # A full original chain describes a policy, not a fixed number of levels.
    # A partial original chain describes a fixed number instead.
    # Clamping a partial chain would hide an incompatible user replacement.
    maximum = max(width, height).bit_length()
    if original.mip_count == 1:
        return 1
    if original.mip_count == original.full_mips:
        return maximum
    if original.mip_count > maximum:
        raise ValueError('Replacement is too small to retain original partial mip count')
    return original.mip_count


# The stage owns only temporary conversion products, never final export files.
# Closing it releases those products after callers have copied validated bytes.
# Passthrough results remain caller-owned source paths and are not removed.
# One stage can validate a complete batch before any final copy is attempted.
class DDSReplacementStage:
    """One export's temporary conversion/cache lifetime, never user output."""
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='mimi_dds_')
        self.cache = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.directory.cleanup()

    def prepare(self, source, original_path, force_original_size=False):
        """Return verified staged bytes, or the untouched matching DDS source."""
        import hashlib
        original = read_dds_metadata(original_path)
        candidate = None
        if os.path.splitext(source)[1].lower() == '.dds':
            # DDS input receives the same validation as the authoritative capture.
            # Matching storage avoids recompression, including unknown DXGI types.
            # A header match alone is insufficient when mip or dimensions differ.
            candidate = read_dds_metadata(source)
        # Unknown DXGI formats can only pass through as exactly matching DDS.
        # Non-2D resources are never synthesized from an ordinary image.
        width, height = original.width, original.height
        if not force_original_size:
            if candidate:
                width, height = candidate.width, candidate.height
            else:
                from PIL import Image
                with Image.open(source) as image:
                    width, height = image.size
        # Topological DDS resources are byte-preserving only. Their depth and
        # face/array layout cannot be reconstructed from an ordinary image.
        # Require identical dimensions and mip topology before returning bytes.
        if not original.ordinary_2d:
            if candidate == original:
                return source
            raise ValueError('DDS arrays, cubes and volumes require an exactly matching DDS replacement')
        mips = matching_mip_count(original, width, height)
        if candidate and candidate.storage_key == original.storage_key:
            if candidate.width == width and candidate.height == height and candidate.mip_count == mips:
                return source
        if not original.ordinary_2d or (candidate and not candidate.ordinary_2d):
            raise ValueError('DDS arrays, cubes and volumes require an exactly matching DDS replacement')
        if original.dxgi not in DXGI_FORMATS or original.alpha_mode not in (0, 1, 3):
            raise ValueError('Unsupported exact DDS conversion: ' + original.format + ' / alpha mode ' + str(original.alpha_mode))
        # Content hashing prevents stale conversions after an in-place edit.
        # The cache also separates format, header, mip and size requirements.
        with open(source, 'rb') as stream:
            digest = hashlib.sha256(stream.read()).hexdigest()
        key = (digest, original.storage_key, width, height, mips)
        if key in self.cache:
            return self.cache[key]
        folder = os.path.join(self.directory.name, str(len(self.cache)))
        os.makedirs(folder)
        # A private input basename makes texconv output discovery deterministic.
        # No gamma, normal, swizzle or premultiplied-alpha conversion is requested.
        input_path = os.path.join(folder, 'replacement' + os.path.splitext(source)[1].lower())
        shutil.copy2(source, input_path)
        output_folder = os.path.join(folder, 'output')
        os.makedirs(output_folder)
        args = ['-f', original.format, '-m', str(mips), '-w', str(width), '-h', str(height),
                '-dx10' if original.dx10 else '-dx9', '--ignore-srgb', '-y', '-o', output_folder, input_path]
        # No normal-map, channel-swizzle or premultiply option is requested.
        # Ignore embedded source sRGB flags rather than introducing gamma edits.
        # Output sRGB interpretation comes solely from the requested DXGI ID.
        # Explicit dimensions and mip count prevent texconv default policies.
        # A failure stays inside the stage and propagates to the exporter.
        _run_texconv(args)
        output = os.path.join(output_folder, 'replacement.dds')
        if original.dx10:
            # Straight/opaque/unknown flags describe interpretation, not a
            # requested premultiplication transform. Preserve the original tag.
            with open(output, 'r+b') as handle:
                handle.seek(144)
                handle.write(struct.pack('<I', original.alpha_mode))
        # Verify the produced file instead of trusting a successful process exit.
        # Legacy output that cannot represent the target is an error, not a fallback.
        # Alpha-tag patching changes interpretation metadata, not pixel channels.
        # Cache only after both topology and output-size policy have passed.
        actual = read_dds_metadata(output)
        if actual.storage_key != original.storage_key or (actual.width, actual.height, actual.mip_count) != (width, height, mips):
            raise ValueError('texconv output metadata does not match original DDS requirements: ' + original.format)
        self.cache[key] = output
        return output
