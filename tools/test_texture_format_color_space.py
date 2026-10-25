"""Real-texconv colour-space regression for replacement texture conversion.

Run with plain Python: ``python tools/test_texture_format_color_space.py``.

The historical bug was that every conversion passed both ``-srgbi`` and
``-srgbo``. texconv then treats input and output as the same colour space and
never converts, so:
- an sRGB image written into BC6H was about 12x too bright in linear light,
- a linear DDS written into BC7_UNORM_SRGB about 5x too dark.

The suite drives the real ``dds_match`` planning/execution code and the bundled
texconv, then reads the produced DDS pixels back through texconv itself.
"""
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from texcomb.core import dds_match, texconv  # noqa: E402

# 16-pixel wide grey steps: level = step * 16, repeated over 16 rows.
STEPS = tuple(range(16))
LEVELS = tuple(step * 16 for step in STEPS)
SIZE = 256


def _png_chunk(kind, payload):
    """Build one PNG chunk with its CRC."""
    return (
        struct.pack('>I', len(payload)) + kind + payload
        + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    )


def write_gray_ladder_png(path):
    """Write an 8-bit RGB PNG with 16 vertical grey steps and an sRGB tag."""
    row = b''
    for step in STEPS:
        row += bytes((step * 16, step * 16, step * 16)) * 16
    raw = b''.join(b'\x00' + row for _ in range(SIZE))
    header = struct.pack('>IIBBBBB', SIZE, SIZE, 8, 2, 0, 0, 0)
    # Editors tag their PNG as sRGB; texconv/WIC treats untagged files as
    # linear, so the fixture has to declare the same thing a real texture does.
    data = (
        b'\x89PNG\r\n\x1a\n'
        + _png_chunk(b'IHDR', header)
        + _png_chunk(b'sRGB', b'\x00')
        + _png_chunk(b'IDAT', zlib.compress(raw, 9))
        + _png_chunk(b'IEND', b'')
    )
    with open(path, 'wb') as stream:
        stream.write(data)
    return path


def _read_dds_payload(path, offset):
    with open(path, 'rb') as stream:
        stream.seek(offset)
        return stream.read()


def read_float_pixels(dds_path, width, height):
    """Return one RGBA float tuple per grey step, stored values unchanged."""
    with tempfile.TemporaryDirectory(prefix='mimi_colour_float_') as folder:
        texconv._run_texconv([
            '-f', 'R32G32B32A32_FLOAT', '-ft', 'dds', '-m', '1', '-dx10',
            '-y', '-o', folder, dds_path,
        ])
        produced = os.path.join(folder, os.path.splitext(os.path.basename(dds_path))[0] + '.dds')
        payload = _read_dds_payload(produced, 148)
    stride = width * 16
    return [
        struct.unpack_from('<4f', payload, (height // 2) * stride + (step * 16 + 8) * 16)
        for step in STEPS
    ]


def read_unorm8_pixels(dds_path, width, height, target_format):
    """Return one RGBA byte tuple per grey step, stored values unchanged."""
    with tempfile.TemporaryDirectory(prefix='mimi_colour_u8_') as folder:
        texconv._run_texconv([
            '-f', target_format, '-ft', 'dds', '-m', '1', '-dx10',
            '-y', '-o', folder, dds_path,
        ])
        produced = os.path.join(folder, os.path.splitext(os.path.basename(dds_path))[0] + '.dds')
        payload = _read_dds_payload(produced, 148)
    stride = width * 4
    return [
        tuple(payload[(height // 2) * stride + (step * 16 + 8) * 4:
                      (height // 2) * stride + (step * 16 + 8) * 4 + 4])
        for step in STEPS
    ]


def srgb_to_linear(value):
    """The sRGB transfer function of one 0..255 channel."""
    normalized = value / 255.0
    if normalized <= 0.04045:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


class ColorSpaceTests(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory(prefix='mimi_colour_case_')
        self.folder = self._folder.name
        self.png = write_gray_ladder_png(os.path.join(self.folder, 'ladder.png'))

    def tearDown(self):
        self._folder.cleanup()

    def _plan(self, source, dxgi, color_mode='AUTO', data_hint=''):
        original = dds_match.DDSMetadata(SIZE, SIZE, 1, dxgi, True)
        return dds_match.build_conversion_plan(
            source, original, color_mode=color_mode, data_hint=data_hint,
        )

    def test_srgb_image_into_bc6h_is_linearised(self):
        """A painted (sRGB) lightmap must become linear HDR, not raw bytes."""
        plan = self._plan(self.png, 95, data_hint='LightMap')
        self.assertTrue(plan.srgb_in)
        self.assertFalse(plan.srgb_out)
        self.assertFalse(plan.ignore_srgb)
        produced = dds_match.run_conversion_plan(plan, os.path.join(self.folder, 'bc6h'))
        pixels = read_float_pixels(produced, SIZE, SIZE)
        for level, pixel in zip(LEVELS, pixels):
            expected = srgb_to_linear(level)
            # BC6H is lossy, but a gamma shift is 10x larger than this window.
            self.assertAlmostEqual(
                pixel[0], expected, delta=max(0.008, expected * 0.08),
                msg='level %d stored %.4f, expected linear %.4f' % (level, pixel[0], expected),
            )

    def test_linear_dds_into_srgb_is_encoded(self):
        """A genuinely linear DDS must be gamma-encoded for an sRGB slot."""
        linear_source = os.path.join(self.folder, 'linear.dds')
        texconv._run_texconv([
            '-f', 'BC7_UNORM', '-ft', 'dds', '-m', '1', '-dx10',
            '-y', '-o', self.folder, self.png,
        ])
        produced_source = os.path.join(self.folder, 'ladder.dds')
        os.replace(produced_source, linear_source)
        plan = self._plan(linear_source, 99, data_hint='DiffuseMap')
        self.assertFalse(plan.srgb_in)
        self.assertTrue(plan.srgb_out)
        produced = dds_match.run_conversion_plan(plan, os.path.join(self.folder, 'encoded'))
        pixels = read_unorm8_pixels(produced, SIZE, SIZE, 'R8G8B8A8_UNORM_SRGB')
        for level, pixel in zip(LEVELS, pixels):
            self.assertAlmostEqual(
                pixel[0], level, delta=4,
                msg='level %d came back as %d' % (level, pixel[0]),
            )

    def test_srgb_image_into_srgb_is_passthrough(self):
        """The common diffuse case must keep the author's bytes."""
        plan = self._plan(self.png, 99, data_hint='DiffuseMap')
        self.assertTrue(plan.srgb_in)
        self.assertTrue(plan.srgb_out)
        self.assertFalse(plan.ignore_srgb)
        produced = dds_match.run_conversion_plan(plan, os.path.join(self.folder, 'passthrough'))
        pixels = read_unorm8_pixels(produced, SIZE, SIZE, 'R8G8B8A8_UNORM_SRGB')
        for level, pixel in zip(LEVELS, pixels):
            self.assertAlmostEqual(pixel[0], level, delta=2)

    def test_normal_map_is_never_gamma_converted(self):
        """Normal/mask roles keep their values whatever the target format is."""
        plan = self._plan(self.png, 28, data_hint='NormalMap')
        self.assertTrue(plan.ignore_srgb)
        produced = dds_match.run_conversion_plan(plan, os.path.join(self.folder, 'data'))
        pixels = read_unorm8_pixels(produced, SIZE, SIZE, 'R8G8B8A8_UNORM')
        for level, pixel in zip(LEVELS, pixels):
            self.assertEqual(pixel[0], level)

    def test_cache_key_separates_colour_modes(self):
        """Colour and data interpretations of one source need different keys."""
        from texcomb.core.conversion_cache import ConversionCache

        cache = ConversionCache(os.path.join(self.folder, 'cache'))
        original = dds_match.DDSMetadata(SIZE, SIZE, 1, 99, True)
        colour = dds_match.build_conversion_plan(self.png, original, color_mode='AUTO', data_hint='DiffuseMap')
        data = dds_match.build_conversion_plan(self.png, original, color_mode='DATA')
        self.assertNotEqual(cache.key(colour), cache.key(data))


if __name__ == '__main__':
    unittest.main(verbosity=2)
