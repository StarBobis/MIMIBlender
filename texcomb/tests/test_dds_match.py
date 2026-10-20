"""Real bundled-texconv coverage for exact format and mip policies.

Use tiny images so these tests exercise actual headers without large fixtures.
Matching DDS must stay byte-identical rather than undergoing recompression.
Pixel value preservation is asserted separately for sRGB and linear targets,
because the flag choice is what decides whether bytes are copied or gamma
converted. The disk cache is covered with a real conversion as well.
"""
# Texconv runs on generated images so fixtures cannot hide a format mismatch.
# Header policy is asserted separately from dimensions and mip count.
# The parameter list spans compressed, signed, float and single-channel storage.
# sRGB targets are distinct from linear variants with equal block sizes.
# Legacy BC1 ensures the converter does not silently require a DX10 extension.
# Volume topology is constructed from a valid typed image payload.
# The byte-short case checks payload validation independently of header validity.
# Exact passthrough never modifies the supplied replacement file.
# Round trips read the produced DDS back through texconv, not a guessed parser.
# Cache tests use a temporary root so no user cache is ever touched.
import os
import struct
import pytest
from PIL import Image
from texcomb.core.dds_match import (
    DDSReplacementStage,
    build_conversion_plan,
    read_dds_metadata,
    matching_mip_count,
    DDSMetadata,
)
from texcomb.core.conversion_cache import ConversionCache
from texcomb.core.texconv import _run_texconv


@pytest.mark.parametrize('format,dxgi,header', [
    ('BC1_UNORM', 71, '-dx9'), ('BC3_UNORM_SRGB', 78, '-dx10'),
    ('BC7_UNORM_SRGB', 99, '-dx10'), ('R8_UNORM', 61, '-dx10'),
    ('R16G16B16A16_FLOAT', 10, '-dx10'), ('BC5_SNORM', 84, '-dx10')])
def test_exact_conversion(tmp_path, format, dxgi, header):
    # The original and replacement deliberately have different resolutions.
    # Full mip chains follow the replacement, not the capture's dimensions.
    source = tmp_path / 'original.png'
    Image.new('RGBA', (16, 16), (40, 80, 120, 255)).save(source)
    _run_texconv(['-f', format, header, '-m', '0', '-y', '-o', str(tmp_path), str(source)])
    original = tmp_path / 'original.dds'
    replacement = tmp_path / 'replacement.png'
    Image.new('RGBA', (32, 8), (70, 20, 90, 255)).save(replacement)
    with DDSReplacementStage() as stage:
        converted = stage.prepare(str(replacement), str(original))
        metadata = read_dds_metadata(converted)
        assert metadata.dxgi == dxgi
        assert (metadata.width, metadata.height, metadata.mip_count) == (32, 8, 6)
        assert metadata.dx10 == (header == '-dx10')
        # Content-addressed cache reuses the same staged result.
        # The exact DDS result itself must be accepted without re-encoding.
        assert stage.prepare(str(replacement), str(original)) == converted
        assert stage.prepare(converted, str(original)) == converted
        forced = read_dds_metadata(stage.prepare(str(replacement), str(original), True))
        assert (forced.width, forced.height) == (16, 16)


def test_partial_and_one_mip():
    # Partial chains retain count, and reject dimensions too small to hold it.
    # A single original mip never silently generates a full replacement chain.
    partial = DDSMetadata(64, 64, 4, 28, True)
    assert matching_mip_count(partial, 32, 16) == 4
    with pytest.raises(ValueError, match='too small'):
        matching_mip_count(partial, 4, 4)
    assert matching_mip_count(DDSMetadata(64, 64, 1, 28, True), 128, 128) == 1


def test_invalid_header(tmp_path):
    # Invalid bytes are rejected before texconv or generated-output writes.
    # A renamed PNG therefore cannot masquerade as an original DDS texture.
    path = tmp_path / 'invalid.dds'
    path.write_bytes(b'not a DDS')
    with pytest.raises(ValueError, match='valid DDS'):
        read_dds_metadata(path)


def test_payload_and_volume_passthrough(tmp_path):
    # Build a real typed DDS before changing only its resource topology.
    # Two full slices are required for a two-deep volume, including mip data.
    # The exact volume must pass through without texconv rebuilding the slices.
    image = tmp_path / 'volume.png'
    Image.new('RGBA', (4, 4), (50, 70, 90, 255)).save(image)
    _run_texconv(['-f', 'R8G8B8A8_UNORM', '-dx10', '-m', '1', '-y', '-o', str(tmp_path), str(image)])
    path = tmp_path / 'volume.dds'
    data = bytearray(path.read_bytes())
    struct.pack_into('<I', data, 24, 2)
    struct.pack_into('<I', data, 132, 4)
    data.extend(data[148:])
    path.write_bytes(data)
    with DDSReplacementStage() as stage:
        assert stage.prepare(str(path), str(path)) == str(path)
        # An ordinary image cannot supply the missing volume layout.
        # Failure happens in staging and never creates a final replacement.
        with pytest.raises(ValueError, match='arrays, cubes and volumes'):
            stage.prepare(str(image), str(path))
    # A valid header with an incomplete second slice is still corrupt.
    # Payload validation must reject it even on the byte-preserving path.
    path.write_bytes(data[:-1])
    with pytest.raises(ValueError, match='Truncated DDS image payload'):
        read_dds_metadata(path)
    # An array of volumes is invalid even when enough bytes are present.
    # Malformed topology cannot evade validation via exact DDS passthrough.
    struct.pack_into('<I', data, 140, 2)
    path.write_bytes(data)
    with pytest.raises(ValueError, match='Invalid DDS resource topology'):
        read_dds_metadata(path)


def _round_trip_pixel(tmp_path, target_format):
    """Convert one 8x8 image to a target and read the first pixel back.

    The original DDS is produced first so the plan follows the same path as
    a real replacement (format detection, then conversion, then verification).
    """
    source = tmp_path / 'pixel.png'
    Image.new('RGBA', (8, 8), (128, 64, 32, 200)).save(source)
    original = tmp_path / 'pixel_original.png'
    Image.new('RGBA', (8, 8), (128, 64, 32, 200)).save(original)
    _run_texconv(['-f', target_format, '-dx10', '-m', '1', '-y', '-o',
                  str(tmp_path), str(original)])
    original_dds = tmp_path / 'pixel_original.dds'
    metadata = read_dds_metadata(str(original_dds))
    plan = build_conversion_plan(str(source), metadata)
    produced_dir = tmp_path / 'produced'
    # run_conversion_plan is imported lazily to keep the module list short.
    from texcomb.core.dds_match import run_conversion_plan
    produced = run_conversion_plan(plan, str(produced_dir))
    back_dir = tmp_path / 'back'
    os.makedirs(back_dir, exist_ok=True)
    _run_texconv(['-ft', 'PNG', '-y', '-o', str(back_dir), produced])
    with Image.open(back_dir / 'replacement.png') as image:
        return image.convert('RGBA').getpixel((3, 3))


def test_srgb_target_keeps_pixel_bytes(tmp_path):
    # The bug this guards against was --ignore-srgb on an _SRGB target, which
    # turned 128 into 187 by applying the gamma transform twice.
    pixel = _round_trip_pixel(tmp_path, 'R8G8B8A8_UNORM_SRGB')
    assert pixel[:3] == (128, 64, 32), pixel


def test_linear_target_keeps_raw_bytes(tmp_path):
    # Data textures rely on the ASCII bytes being copied unchanged; a color
    # space conversion here would corrupt masks, normals and lookups.
    pixel = _round_trip_pixel(tmp_path, 'R8G8B8A8_UNORM')
    assert pixel[:3] == (128, 64, 32), pixel


def test_disk_cache_reuses_and_revalidates(tmp_path):
    # A cached entry must be returned as-is, and a shape mismatch must miss.
    # The replacement is deliberately larger than the capture, so the forced
    # original size produces a different output shape and therefore a new key.
    source = tmp_path / 'cache_source.png'
    Image.new('RGBA', (32, 32), (10, 20, 30, 255)).save(source)
    original_png = tmp_path / 'cache_original.png'
    Image.new('RGBA', (16, 16), (10, 20, 30, 255)).save(original_png)
    _run_texconv(['-f', 'BC7_UNORM_SRGB', '-dx10', '-m', '0', '-y', '-o',
                  str(tmp_path), str(original_png)])
    original_dds = str(tmp_path / 'cache_original.dds')
    cache = ConversionCache(str(tmp_path / 'cache'))

    with DDSReplacementStage(cache=cache) as stage:
        first = stage.prepare(str(source), original_dds)
    assert os.path.isfile(first)
    assert cache.lookup(str(source)) is not None
    # A second stage must hit the same content-addressed file.
    with DDSReplacementStage(cache=cache) as stage:
        second = stage.prepare(str(source), original_dds)
    assert first == second
    # A forced size produces a different key and therefore a different file.
    with DDSReplacementStage(cache=cache) as stage:
        forced = stage.prepare(str(source), original_dds, force_original_size=True)
    assert forced != first
    # The index is display-only; an unrelated key must never return a file.
    metadata = read_dds_metadata(original_dds)
    plan = build_conversion_plan(str(source), metadata)
    assert cache.get('0' * 64, plan) == ''
    # Clearing removes products but keeps the folder usable.
    cache.clear()
    assert not os.path.isfile(first)
    remaining = [
        name for _folder, _dirs, files in os.walk(cache.root)
        for name in files if name.lower().endswith('.dds')
    ]
    assert remaining == []
