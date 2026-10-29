"""Regression test: import-time texture lookup must accept marked names.

MMT names a copied mark texture "<SubMesh>-<MarkName>.dds" and appends
"-<8 hex texture hash>" only when one mark name points at several different
pictures. The one-click import used to accept only the plain spelling, so a
hash-suffixed DiffuseMap silently produced no material at all.

These tests build small file sets and check:
    - the plain spelling still wins,
    - the hash-suffixed spelling is accepted when it is the only candidate,
    - two different hashes are ambiguous and must not be guessed,
    - another mark name (NormalMap) is never mistaken for DiffuseMap.

Run from the repository root with a headless Blender:
    blender -b --python tools/test_import_marked_texture_lookup.py
"""
import os
import sys
import tempfile
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Load the package without running the add-on registration.
PKG = types.ModuleType("MIMIBlender")
PKG.__path__ = [REPO_ROOT]
sys.modules["MIMIBlender"] = PKG

from MIMIBlender.workspace.texture_metadata_helper import TextureMetadataResolver  # noqa: E402
from MIMIBlender.common.mesh_create_helper import MeshCreateHelper  # noqa: E402

PASSED = []
FAILED = []

PREFIX = "14a706ae-10446-"


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("[TEST] PASS |", name)
    else:
        FAILED.append(name)
        print("[TEST] FAIL |", name, "|", detail)


def write_file(folder, name):
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(b"DDS fixture")
    return path


def test_exact_name_still_wins():
    with tempfile.TemporaryDirectory() as folder:
        write_file(folder, "14a706ae-10446-0-DiffuseMap.dds")
        found = TextureMetadataResolver.find_texture(PREFIX, "-DiffuseMap.dds", folder)
        check("exact name is found by the plain lookup", found is not None)


def test_hash_suffixed_name_is_accepted():
    with tempfile.TemporaryDirectory() as folder:
        write_file(folder, "14a706ae-10446-0-DiffuseMap-143375a6.dds")
        plain = TextureMetadataResolver.find_texture(PREFIX, "-DiffuseMap.dds", folder)
        check("plain lookup misses the hash-suffixed name", plain is None)
        found = TextureMetadataResolver.find_texture_with_mark_hash(
            PREFIX, "-DiffuseMap", ".dds", folder)
        check("hash-suffixed name is found", found is not None and found.endswith(
            "14a706ae-10446-0-DiffuseMap-143375a6.dds"), str(found))


def test_mesh_helper_finds_hash_suffixed_diffuse():
    with tempfile.TemporaryDirectory() as folder:
        write_file(folder, "14a706ae-10446-0-DiffuseMap-143375a6.dds")
        found = MeshCreateHelper._find_gimi_texture(PREFIX, "-DiffuseMap", folder)
        check("one-click import resolves the hash-suffixed diffuse",
              found is not None and os.path.isfile(found), str(found))


def test_two_hashes_are_not_guessed():
    with tempfile.TemporaryDirectory() as folder:
        write_file(folder, "14a706ae-10446-0-DiffuseMap-143375a6.dds")
        write_file(folder, "14a706ae-10446-0-DiffuseMap-ed14910e.dds")
        found = TextureMetadataResolver.find_texture_with_mark_hash(
            PREFIX, "-DiffuseMap", ".dds", folder)
        check("two different DiffuseMaps stay ambiguous", found is None, str(found))


def test_other_mark_names_do_not_match():
    with tempfile.TemporaryDirectory() as folder:
        write_file(folder, "14a706ae-10446-0-NormalMap-143375a6.dds")
        found = TextureMetadataResolver.find_texture_with_mark_hash(
            PREFIX, "-DiffuseMap", ".dds", folder)
        check("NormalMap is not mistaken for DiffuseMap", found is None, str(found))


def test_other_extensions_are_supported():
    with tempfile.TemporaryDirectory() as folder:
        write_file(folder, "14a706ae-10446-0-DiffuseMap-143375a6.png")
        found = TextureMetadataResolver.find_texture_with_mark_hash(
            PREFIX, "-DiffuseMap", ".png", folder)
        check("PNG marked texture is found", found is not None, str(found))


def main():
    tests = [
        test_exact_name_still_wins,
        test_hash_suffixed_name_is_accepted,
        test_mesh_helper_finds_hash_suffixed_diffuse,
        test_two_hashes_are_not_guessed,
        test_other_mark_names_do_not_match,
        test_other_extensions_are_supported,
    ]
    for test in tests:
        try:
            test()
        except Exception:
            import traceback
            FAILED.append(test.__name__)
            print("[TEST] FAIL |", test.__name__, "| exception:")
            traceback.print_exc()
    print(f"[SUMMARY] {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("[SUMMARY] failed:", ", ".join(FAILED))


main()
