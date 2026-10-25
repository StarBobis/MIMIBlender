"""Exact original-format DDS replacement, independent of Blender.

All conversion happens in temporary or cache storage. Callers commit the
resulting files only after every configured replacement has passed validation.
Unknown formats are errors: a plausible BC7 fallback is not an exact match.

The module is split into four layers so both the export pipeline and the
node UI can use it without duplicating rules:

1. ``read_dds_metadata`` parses the DDS headers (format detection).
2. ``build_conversion_plan`` decides what the replacement needs, or returns
   None when the supplied DDS is already byte-compatible.
3. ``run_conversion_plan`` executes one texconv call and verifies the output.
4. ``DDSReplacementStage`` batches plans during one export and can persist
   results in a content-addressed cache.

No bpy import is allowed here; the Blender layer injects the cache and the
optional user-configured texconv path through the setters below.
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

# Formats whose pixels are sRGB-encoded: the hardware decodes them to linear
# when sampled. Every other entry is linear or vector/mask data. Keeping this
# as a derived set means a new DXGI_FORMATS row cannot forget its colour space.
SRGB_FORMATS = frozenset(name for name in DXGI_FORMATS.values() if name.endswith('_SRGB'))

# Mark roles that carry vectors or masks instead of colour. Gamma-converting
# these corrupts the values (a normal map is not a photograph), so their bytes
# are copied verbatim regardless of the target format. Tokens are deliberately
# specific: a bare "ao"/"rough"/"metal" would also match unrelated file names.
DATA_ROLE_TOKENS = (
    'normal', 'mask', 'roughness', 'metallic', 'occlusion',
    'specular', 'gloss', 'smoothness', 'height', 'displacement',
    'materialmap', 'aomap', 'ao_map',
)

# Per-row colour-space override. AUTO follows the source file's own format and
# the mark role; the other values let a user correct a mis-tagged DDS.
COLOR_MODE_AUTO = 'AUTO'
COLOR_MODE_SRGB = 'SRGB'
COLOR_MODE_LINEAR = 'LINEAR'
COLOR_MODE_DATA = 'DATA'
COLOR_MODES = (COLOR_MODE_AUTO, COLOR_MODE_SRGB, COLOR_MODE_LINEAR, COLOR_MODE_DATA)

# Resize filters accepted by texconv; the first entry is the pipeline default.
# POINT keeps hard pixel edges, which is usually wrong for painted textures.
# FANT is a good general-purpose choice for downscaling atlases.
RESIZE_FILTERS = ('FANT', 'LINEAR', 'CUBIC', 'BOX', 'TRIANGLE', 'POINT')
DEFAULT_RESIZE_FILTER = RESIZE_FILTERS[0]

# Defaults injected by the Blender layer. Keeping them in module state lets
# every helper stay importable (and testable) outside Blender.
_DEFAULT_CACHE = None
_DEFAULT_TEXCONV = ""


def set_default_cache(cache):
    """Install the disk cache used by stages that were given no explicit one."""
    global _DEFAULT_CACHE
    _DEFAULT_CACHE = cache


def get_default_cache():
    """Return the disk cache currently shared by the export pipeline."""
    return _DEFAULT_CACHE


def set_default_texconv_path(path):
    """Remember a user-configured texconv.exe path (empty means auto-detect)."""
    global _DEFAULT_TEXCONV
    _DEFAULT_TEXCONV = str(path or "")


def get_default_texconv_path():
    """Return the user-configured texconv.exe path, or an empty string."""
    return _DEFAULT_TEXCONV


def _texconv_path(explicit_path=""):
    """Resolve the texconv path without importing bpy or the scene."""
    return explicit_path or _DEFAULT_TEXCONV


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


def describe_format(metadata):
    """Return the human readable format name shown in the node panels."""
    # Unknown IDs stay explicit so a user can report them without guessing.
    name = DXGI_FORMATS.get(metadata.dxgi)
    if name is None:
        return 'DXGI_' + str(metadata.dxgi)
    # Legacy headers carry no sRGB tag, which is useful information in the UI.
    return name if metadata.dx10 else name + ' (legacy header)'


def describe_metadata(metadata):
    """Return one compact line describing format, size and mip count."""
    return '{} {}x{} {} mip(s)'.format(
        describe_format(metadata), metadata.width, metadata.height, metadata.mip_count,
    )


# Reverse lookup used by the manual format override in the node panels.
# Building it from DXGI_FORMATS keeps one single source of truth.
FORMAT_BY_NAME = {name: dxgi for dxgi, name in DXGI_FORMATS.items()}


def format_names():
    """Return every format name a user may pick manually (sorted for the UI)."""
    return sorted(FORMAT_BY_NAME)


def metadata_for_format(format_name, width, height):
    """Build a synthetic capture header for a manual format override.

    A manual override is used when no original DDS can be resolved at all.
    There is no captured header to copy, so the assumed layout is the most
    common game one: a DX10 2D texture with a full mip chain.
    """
    dxgi = FORMAT_BY_NAME.get(str(format_name or ''))
    if dxgi is None:
        raise ValueError('Unsupported replacement format: ' + str(format_name))
    width = max(1, int(width))
    height = max(1, int(height))
    return DDSMetadata(width, height, max(width, height).bit_length(), dxgi, True)


def agree_on_metadata(paths):
    """Return (metadata, conflict, agreed_path) for one texture's originals.

    Several marks can share one slot or hash. When every readable capture
    agrees, the format is unambiguous and its path is authoritative.
    Unreadable candidates are ignored so one broken capture cannot block a
    replacement that still has a valid one. ``metadata`` is None when nothing
    could be read, and ``conflict`` is True when the readable captures differ.
    """
    readable = []
    for path in paths or []:
        if not path or not os.path.isfile(path):
            continue
        try:
            readable.append((path, read_dds_metadata(path)))
        except Exception:
            # A truncated or non-DDS capture simply contributes no authority.
            continue
    if not readable:
        return None, False, ''
    first = readable[0][1]
    conflict = any(item != first for _path, item in readable[1:])
    if conflict:
        return first, True, ''
    return first, False, readable[0][0]



def _png_dimensions(path):
    """Read width and height from a PNG IHDR chunk."""
    with open(path, 'rb') as stream:
        header = stream.read(24)
    # Signature, IHDR length and chunk type together fill the first 16 bytes.
    if len(header) < 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Not a PNG file: ' + str(path))
    return struct.unpack('>II', header[16:24])


def _jpeg_dimensions(path):
    """Walk JPEG markers until the first start-of-frame segment."""
    # SOF markers carry the real image size; APPn segments must be skipped.
    # Marker payload lengths include their own two length bytes.
    start_of_frame = (
        0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
        0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf,
    )
    with open(path, 'rb') as stream:
        if stream.read(2) != b'\xff\xd8':
            raise ValueError('Not a JPEG file: ' + str(path))
        while True:
            marker_start = stream.read(1)
            if not marker_start:
                raise ValueError('JPEG has no size segment: ' + str(path))
            if marker_start != b'\xff':
                continue
            marker = stream.read(1)
            # Fill bytes and restart markers carry no length field.
            while marker == b'\xff':
                marker = stream.read(1)
            if not marker:
                raise ValueError('JPEG has no size segment: ' + str(path))
            code = marker[0]
            if code == 0xd8 or code == 0x01 or 0xd0 <= code <= 0xd7:
                continue
            length_bytes = stream.read(2)
            if len(length_bytes) < 2:
                raise ValueError('Truncated JPEG segment: ' + str(path))
            length = struct.unpack('>H', length_bytes)[0]
            if code in start_of_frame:
                payload = stream.read(5)
                if len(payload) < 5:
                    raise ValueError('Truncated JPEG frame header: ' + str(path))
                # The frame header starts with precision, then height and width.
                height, width = struct.unpack('>HH', payload[1:5])
                return (width, height)
            stream.seek(length - 2, 1)


def _bmp_dimensions(path):
    """Read both axes from a BMP info header (top-down rows use negatives)."""
    with open(path, 'rb') as stream:
        header = stream.read(26)
    if len(header) < 26 or header[:2] != b'BM':
        raise ValueError('Not a BMP file: ' + str(path))
    width, height = struct.unpack('<ii', header[18:26])
    return (abs(width), abs(height))


def _tga_dimensions(path):
    """Read the fixed 18-byte TGA header (width, height, bit depth)."""
    with open(path, 'rb') as stream:
        header = stream.read(18)
    if len(header) < 18:
        raise ValueError('Not a TGA file: ' + str(path))
    width, height, depth = struct.unpack('<HHB', header[12:17])
    # Color-mapped or invalid files would otherwise report a bogus size.
    if not width or not height or depth not in (8, 16, 24, 32):
        raise ValueError('Unsupported TGA layout: ' + str(path))
    return (width, height)


def image_dimensions(path):
    """Return (width, height) for one replacement image without Pillow.

    Texconv is the only heavy dependency of this module, and Pillow is an
    optional part of the addon, so header parsing keeps conversion available
    even when the user never installed Pillow.
    """
    suffix = os.path.splitext(path)[1].lower()
    if suffix == '.dds':
        metadata = read_dds_metadata(path)
        return (metadata.width, metadata.height)
    if suffix == '.png':
        return _png_dimensions(path)
    if suffix in ('.jpg', '.jpeg'):
        return _jpeg_dimensions(path)
    if suffix == '.bmp':
        return _bmp_dimensions(path)
    if suffix == '.tga':
        return _tga_dimensions(path)
    raise ValueError('Unsupported replacement image type: ' + str(path))


def format_is_srgb(format_name):
    """Return True when a DXGI format name stores sRGB-encoded pixels."""
    return str(format_name or '') in SRGB_FORMATS


def format_dxgi(format_name):
    """Return the numeric DXGI id of a format name, or 0 when unknown."""
    return FORMAT_BY_NAME.get(str(format_name or ''), 0)


def source_color_space(path):
    """Return 'srgb' or 'linear' from the file's own colour-space information.

    A DDS declares its colour space through the DXGI format. PNG/JPEG/BMP/TGA
    have no reliable tag of their own (WIC assumes sRGB), which is also how
    every paint program writes them.
    """
    suffix = os.path.splitext(str(path or ''))[1].lower()
    if suffix == '.dds':
        try:
            return 'srgb' if format_is_srgb(read_dds_metadata(path).format) else 'linear'
        except Exception:
            # An unreadable DDS is rejected by the caller's validation; for the
            # colour decision assume the artist's working space.
            return 'srgb'
    return 'srgb'


def is_data_role(text):
    """Return True when a mark or file role names vector or mask data."""
    lowered = str(text or '').lower()
    return any(token in lowered for token in DATA_ROLE_TOKENS)


def colour_flags(source, target_dxgi, color_mode=COLOR_MODE_AUTO, data_hint=''):
    """Return (srgb_in, srgb_out, ignore_srgb) for one replacement conversion.

    texconv only converts between colour spaces when the input and output
    declarations disagree. Passing both ``-srgbi`` and ``-srgbo``
    unconditionally (the historical behaviour) suppressed every conversion and
    merely re-tagged the bytes: an sRGB image written into BC6H came out about
    12x too bright in linear light and a linear DDS written into
    BC7_UNORM_SRGB came out correspondingly dark.

    - sRGB -> sRGB: both flags (declared equal, so the bytes pass through).
    - sRGB -> linear: ``-srgbi`` (decode before encoding).
    - linear -> sRGB: ``-srgbo`` (encode after filtering).
    - data textures: both flags (never convert the values).
    """
    mode = str(color_mode or COLOR_MODE_AUTO).upper()
    if mode not in COLOR_MODES:
        mode = COLOR_MODE_AUTO
    target_srgb = format_is_srgb(DXGI_FORMATS.get(int(target_dxgi or 0), ''))
    if mode == COLOR_MODE_DATA:
        return False, target_srgb, True
    if mode == COLOR_MODE_SRGB:
        source_srgb = True
    elif mode == COLOR_MODE_LINEAR:
        source_srgb = False
    else:
        source_srgb = source_color_space(source) == 'srgb'
        if is_data_role(data_hint):
            return source_srgb, target_srgb, True
    return source_srgb, target_srgb, False


def describe_colour_conversion(source, target_dxgi, color_mode=COLOR_MODE_AUTO, data_hint=''):
    """Return the short 'sRGB -> linear' note shown next to one row."""
    srgb_in, srgb_out, ignore = colour_flags(source, target_dxgi, color_mode, data_hint)
    if ignore:
        return 'data (bytes kept)'
    if srgb_in == srgb_out:
        return 'sRGB kept' if srgb_in else 'linear kept'
    return 'sRGB -> linear' if srgb_in else 'linear -> sRGB'


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


@dataclass(frozen=True)
class ConversionPlan:
    """Everything one texconv call needs, decided before any file is written.

    The UI uses the same object to preview the target format, so planning and
    execution can never disagree about dimensions, mips or the header style.
    """
    # The source bytes are never modified; only read and copied into staging.
    source: str
    # Format spelling is texconv's own DXGI identifier from DXGI_FORMATS.
    format: str
    # Output top-level size. With force_original_size it equals the capture.
    width: int
    height: int
    # Exact number of levels required by the original chain policy.
    mips: int
    # Legacy headers must stay legacy; BC formats need the DX10 extension.
    dx10: bool
    # Straight/opaque/unknown tags are preserved verbatim after conversion.
    alpha_mode: int
    # Used by the cache to distinguish conversion products of one source.
    storage_key: tuple
    # Resize filter is only meaningful when the output size differs.
    resize_filter: str = DEFAULT_RESIZE_FILTER
    # Colour-space decision; the texconv flags are derived from these fields.
    # ``ignore_srgb`` means vector/mask data whose values must not be gamma
    # converted (normal maps, masks).
    srgb_in: bool = False
    srgb_out: bool = False
    ignore_srgb: bool = False
    color_mode: str = COLOR_MODE_AUTO


def build_conversion_plan(source, original, force_original_size=False,
                          resize_filter=DEFAULT_RESIZE_FILTER,
                          color_mode=COLOR_MODE_AUTO, data_hint=''):
    """Return the plan for one replacement, or None for a byte-identical DDS.

    ``original`` is a parsed DDSMetadata, not a path, so callers can show the
    detected format first and reuse that header for every later decision.
    ``color_mode`` is the per-row override; AUTO follows the source file's own
    colour space and ``data_hint`` (mark name, slot, file stem).
    Raising ValueError is the contract for "this replacement cannot be made
    exact"; callers either surface the message or intentionally fall back.
    """
    candidate = None
    if os.path.splitext(source)[1].lower() == '.dds':
        # DDS input receives the same validation as the authoritative capture.
        # Matching storage avoids recompression, including unknown DXGI types.
        # A header match alone is insufficient when mip or dimensions differ.
        candidate = read_dds_metadata(source)
    # Topological DDS resources are byte-preserving only. Their depth and
    # face/array layout cannot be reconstructed from an ordinary image.
    # Require identical dimensions and mip topology before returning bytes.
    if not original.ordinary_2d:
        if candidate == original:
            return None
        raise ValueError('DDS arrays, cubes and volumes require an exactly matching DDS replacement')
    width, height = original.width, original.height
    if not force_original_size:
        # Replacement pixels keep their own size unless the row forces capture size.
        if candidate is not None:
            width, height = candidate.width, candidate.height
        else:
            width, height = image_dimensions(source)
    mips = matching_mip_count(original, width, height)
    if candidate is not None and candidate.storage_key == original.storage_key:
        if (candidate.width, candidate.height, candidate.mip_count) == (width, height, mips):
            return None
    # Unknown DXGI formats can only pass through as exactly matching DDS.
    # Conversion targets must have both a texconv spelling and alpha semantics.
    if original.dxgi not in DXGI_FORMATS:
        raise ValueError('Unsupported exact DDS conversion: ' + original.format)
    if original.alpha_mode not in (0, 1, 3):
        raise ValueError(
            'Unsupported exact DDS conversion: ' + original.format
            + ' / alpha mode ' + str(original.alpha_mode)
        )
    # An unknown filter falls back to the documented default instead of
    # reaching texconv, which would fail on a typo and abort the export.
    chosen_filter = resize_filter if resize_filter in RESIZE_FILTERS else DEFAULT_RESIZE_FILTER
    srgb_in, srgb_out, ignore_srgb = colour_flags(
        source, original.dxgi, color_mode=color_mode, data_hint=data_hint,
    )
    return ConversionPlan(
        source=source,
        format=original.format,
        width=width,
        height=height,
        mips=mips,
        dx10=original.dx10,
        alpha_mode=original.alpha_mode,
        storage_key=original.storage_key,
        resize_filter=chosen_filter,
        srgb_in=srgb_in,
        srgb_out=srgb_out,
        ignore_srgb=ignore_srgb,
        color_mode=str(color_mode or COLOR_MODE_AUTO).upper(),
    )


def run_conversion_plan(plan, output_dir, explicit_path=""):
    """Run one texconv call, verify the produced header and return its path."""
    os.makedirs(output_dir, exist_ok=True)
    # A private input basename makes texconv output discovery deterministic.
    # The source is copied so texconv can never touch the user's own file.
    input_path = os.path.join(output_dir, 'replacement' + os.path.splitext(plan.source)[1].lower())
    shutil.copy2(plan.source, input_path)
    args = [
        '-f', plan.format,
        # Explicit file type: -f already implies DDS, but being explicit keeps
        # the behaviour stable if texconv changes its default inference.
        '-ft', 'dds',
        # Explicit dimensions and mip count prevent texconv default policies.
        '-m', str(plan.mips), '-w', str(plan.width), '-h', str(plan.height),
        # Header style must match the capture, not the replacement extension.
        '-dx10' if plan.dx10 else '-dx9',
    ]
    # A conversion only happens when the two declarations disagree. Equal
    # spaces (and data textures) pass both flags so texconv cannot "fix" an
    # untagged PNG by guessing; differing spaces pass exactly one.
    if plan.ignore_srgb or plan.srgb_in == plan.srgb_out:
        args += ['-srgbi', '-srgbo']
    elif plan.srgb_in:
        args.append('-srgbi')
    else:
        args.append('-srgbo')
    args += ['-y', '-o', output_dir]
    # The resize filter only matters when the output size differs from the
    # source size, and texconv ignores it otherwise.
    if plan.resize_filter:
        args += ['-if', plan.resize_filter]
    args.append(input_path)
    # A failure stays inside this call and propagates to the caller.
    _run_texconv(args, _texconv_path(explicit_path))
    output = os.path.join(output_dir, 'replacement.dds')
    if not os.path.isfile(output):
        raise RuntimeError('texconv produced no DDS for ' + plan.source)
    if plan.dx10:
        # Straight/opaque/unknown flags describe interpretation, not a
        # requested premultiplication transform. Preserve the original tag.
        with open(output, 'r+b') as handle:
            handle.seek(144)
            handle.write(struct.pack('<I', plan.alpha_mode))
    # Verify the produced file instead of trusting a successful process exit.
    # Legacy output that cannot represent the target is an error, not a fallback.
    actual = read_dds_metadata(output)
    if actual.storage_key != plan.storage_key:
        raise ValueError(
            'texconv output metadata does not match original DDS requirements: '
            + plan.format
        )
    # Dimensions and mip count are verified separately from the header style:
    # a successful process exit alone never proves the requested shape.
    if (actual.width, actual.height, actual.mip_count) != (plan.width, plan.height, plan.mips):
        raise ValueError(
            'texconv output shape does not match the conversion plan: '
            + '{}x{} {} mip(s)'.format(actual.width, actual.height, actual.mip_count)
        )
    return output


# The stage owns only temporary conversion products, never final export files.
# Closing it releases those products after callers have copied validated bytes.
# Passthrough results remain caller-owned source paths and are not removed.
# One stage can validate a complete batch before any final copy is attempted.
# A shared disk cache makes repeated exports of unchanged sources free.
class DDSReplacementStage:
    """One export's temporary conversion/cache lifetime, never user output."""
    def __init__(self, cache=None):
        self.directory = tempfile.TemporaryDirectory(prefix='mimi_dds_')
        self.cache = cache
        self.counter = 0
        # One export often asks for the same image twice (preflight and copy).
        # A cheap file-stamp key avoids re-reading bytes or running texconv.
        self.memory = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.directory.cleanup()

    def _active_cache(self):
        # An explicitly injected cache always wins over the module default.
        return self.cache if self.cache is not None else _DEFAULT_CACHE

    def prepare(self, source, original_path="", force_original_size=False,
                resize_filter=DEFAULT_RESIZE_FILTER, original_metadata=None,
                color_mode=COLOR_MODE_AUTO, data_hint=""):
        """Return verified staged bytes, or the untouched matching DDS source.

        ``original_metadata`` lets callers that already resolved an agreed
        capture header (or a manual format) skip re-reading the file.
        """
        original = original_metadata
        if original is None:
            original = read_dds_metadata(original_path)
        plan = build_conversion_plan(
            source, original,
            force_original_size=force_original_size,
            resize_filter=resize_filter,
            color_mode=color_mode,
            data_hint=data_hint,
        )
        # None means the supplied DDS already satisfies the capture exactly.
        if plan is None:
            return source
        # A file stamp is enough inside one export: the source cannot change
        # underneath an operation that is already reading it.
        memory_key = (
            os.path.normcase(os.path.abspath(plan.source)),
            os.path.getmtime(plan.source),
            os.path.getsize(plan.source),
            plan.storage_key,
            plan.width, plan.height, plan.mips,
            plan.resize_filter,
            plan.srgb_in, plan.srgb_out, plan.ignore_srgb,
        )
        remembered = self.memory.get(memory_key)
        if remembered:
            return remembered
        cache = self._active_cache()
        cache_key = ''
        if cache is not None:
            # The key is content addressed, so an in-place edit misses the old
            # entry and a re-export of unchanged files stays instantaneous.
            cache_key = cache.key(plan)
            cached = cache.get(cache_key, plan)
            if cached:
                self.memory[memory_key] = cached
                return cached
        folder = os.path.join(self.directory.name, str(self.counter))
        self.counter += 1
        os.makedirs(folder)
        output = run_conversion_plan(plan, os.path.join(folder, 'output'))
        if cache is not None:
            # Persisting before returning keeps the copy step file-only.
            output = cache.put(cache_key, output, plan)
        self.memory[memory_key] = output
        return output


def prepare_replacement_job(stage, source, job):
    """Run one resolver job dict through a stage and return the exact file.

    Jobs are plain dicts so they can travel with the model layer:
    ``original_path`` (captured DDS), ``manual_format`` (no capture available),
    ``force_original_size``, ``resize_filter`` and the colour-space decision
    (``color_mode`` / ``data_hint``).
    """
    job = job or {}
    original_path = str(job.get('original_path', '') or '')
    manual_format = str(job.get('manual_format', '') or '')
    if original_path:
        metadata = read_dds_metadata(original_path)
    elif manual_format:
        # A manual override has no captured size, so the replacement's own
        # dimensions define the full mip chain that is generated.
        width, height = image_dimensions(source)
        metadata = metadata_for_format(manual_format, width, height)
    else:
        raise ValueError('Replacement job has no original DDS and no manual format')
    return stage.prepare(
        source,
        force_original_size=bool(job.get('force_original_size', False)),
        resize_filter=str(job.get('resize_filter', '') or DEFAULT_RESIZE_FILTER),
        original_metadata=metadata,
        color_mode=str(job.get('color_mode', '') or COLOR_MODE_AUTO),
        data_hint=str(job.get('data_hint', '') or ''),
    )
