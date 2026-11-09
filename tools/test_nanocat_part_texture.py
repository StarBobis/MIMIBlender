"""Regression tests for the NanoCat (MMT) preview-texture lookup.

A WWMI mod keeps every component of one DrawIB inside a single index buffer,
so the MMT host records the per-component base-color assignment on the
draw-call segment instead of the IndexBufferList entry. The importer must
prefer the segment's own texture and fall back to the IndexBufferList entry
when the segment carries none.

Run from the repository root with a headless Blender, for example:
    blender -b --python tools/test_nanocat_part_texture.py
"""
import os
import sys
import tempfile
import types
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Import the add-on modules as the "MIMIBlender" package without executing
# the add-on's own __init__.py (which would register everything else).
PKG = types.ModuleType("MIMIBlender")
PKG.__path__ = [REPO_ROOT]
sys.modules["MIMIBlender"] = PKG

import bpy  # noqa: E402,F401
from MIMIBlender.common.mmt_import_helper import MMTImportHelper  # noqa: E402
from MIMIBlender.workspace.submesh_json import SubmeshJson  # noqa: E402


class NanoCatPartTextureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="mmt_nanocat_texture_")
        self.variant_dir = os.path.join(self.temp_dir, "243b7e59")
        os.makedirs(self.variant_dir, exist_ok=True)
        self.segment_texture = "Components-0 t=4296f0e8.png"
        self.entry_texture = "Components-all.png"
        for name in (self.segment_texture, self.entry_texture):
            with open(os.path.join(self.temp_dir, name), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n")
        self.json_path = os.path.join(self.variant_dir, "GPU_Test.json")
        with open(self.json_path, "w", encoding="utf-8") as handle:
            handle.write(
                "{\n"
                '  "GamePreset": "WWMI",\n'
                '  "IndexBufferList": [{"FileName": "243b7e59.ib",'
                ' "DXGI_FORMAT": "DXGI_FORMAT_R32_UINT",'
                ' "NanoCatPartTexture": "%s"}],\n'
                '  "DrawCallSegmentList": [{"IBIndex": 0, "IndexOffset": 0,'
                ' "IndexCount": 3, "Alias": "Draw Component 0",'
                ' "MatchFirstIndex": 0, "MatchIndexCount": 5790,'
                ' "NanoCatPartTexture": "%s"}]\n'
                "}\n" % (self.entry_texture, self.segment_texture)
            )

    def test_segment_texture_wins_over_index_buffer_entry(self):
        submesh_json = SubmeshJson(self.json_path)
        self.assertEqual(
            submesh_json.DrawCallSegmentList[0].NanoCatPartTexture, self.segment_texture
        )
        resolved = MMTImportHelper.resolve_nanocat_part_texture_path(
            submesh_json=submesh_json,
            ib_entry_index=0,
            segment_texture_name=submesh_json.DrawCallSegmentList[0].NanoCatPartTexture,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(os.path.basename(resolved), self.segment_texture)

    def test_index_buffer_entry_is_the_fallback(self):
        submesh_json = SubmeshJson(self.json_path)
        resolved = MMTImportHelper.resolve_nanocat_part_texture_path(
            submesh_json=submesh_json,
            ib_entry_index=0,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(os.path.basename(resolved), self.entry_texture)

    def test_whole_import_finds_a_segment_texture(self):
        submesh_json = SubmeshJson(self.json_path)
        # A whole import merges every index buffer into one mesh: the segment
        # texture must still be reachable.
        resolved = MMTImportHelper.resolve_nanocat_part_texture_path_for_whole_import(
            submesh_json
        )
        self.assertIsNotNone(resolved)


if __name__ == "__main__":
    unittest.main()
