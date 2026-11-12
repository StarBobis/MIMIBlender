"""Check the extraction contract without loading Blender or changing sources.

Run with plain Python and NumPy. Set NARAKA_POSTSKIN_EVIDENCE_JSON to the
opt-in local capture result for a complete source-data validation.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_postskin_data", ROOT / "games/naraka/native_postskin_data.py")
DATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA)


class NativeEvidenceTests(unittest.TestCase):
    """Reject changed files and incompatible contracts before export begins."""

    def test_legacy_workspace_is_optional(self):
        self.assertIsNone(DATA.load_native_postskin(ROOT / "unused.json", {}))

    def test_unknown_schema_is_not_guessed(self):
        with self.assertRaises(DATA.NativePostSkinError):
            DATA.load_native_postskin(ROOT / "unused.json", {"SchemaVersion": 2})

    def test_changed_file_and_path_escape_are_rejected(self):
        # All disposable fixtures stay under the repository's tmp directory.
        temporary = ROOT / "tmp"
        temporary.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as directory:
            folder = Path(directory).resolve()
            file = folder / "input.buf"
            file.write_bytes(b"abc")
            item = {"FileName": file.name, "ByteLength": 3, "Sha256": hashlib.sha256(b"abc").hexdigest()}
            self.assertEqual(DATA._read(folder, item), b"abc")
            # Same-size changes must fail; length checks alone are insufficient.
            file.write_bytes(b"xyz")
            with self.assertRaises(DATA.NativePostSkinError):
                DATA._read(folder, item)
            item["FileName"] = "../outside.buf"
            with self.assertRaises(DATA.NativePostSkinError):
                DATA._read(folder, item)

    @unittest.skipUnless(os.environ.get("NARAKA_POSTSKIN_EVIDENCE_JSON"), "requires local capture evidence")
    def test_real_capture_inputs(self):
        # The maintained Rust collector produces this JSON and its copied files.
        file = Path(os.environ["NARAKA_POSTSKIN_EVIDENCE_JSON"])
        loaded = DATA.load_native_postskin(file, json.loads(file.read_text()))
        self.assertEqual(len(loaded["source_vertices"]), 17087)
        self.assertEqual(len(loaded["position_records"]), 1545)
        self.assertEqual(loaded["frame_count"], 168)
        self.assertEqual(loaded["bone_count"], 89)


if __name__ == "__main__":
    unittest.main()
