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
import sys
import types
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_postskin_data", ROOT / "games/naraka/native_postskin_data.py")
DATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA)

# Load the pure binding module without importing the Blender addon entry point.
# This uses the same relative-import layout as production while keeping tests
# independent of bpy and any running interactive Blender instance.
PACKAGE = types.ModuleType("naraka_test")
PACKAGE.__path__ = [str(ROOT / "games/naraka")]
sys.modules["naraka_test"] = PACKAGE
sys.modules["naraka_test.native_postskin_data"] = DATA
BIND_SPEC = importlib.util.spec_from_file_location("naraka_test.native_postskin_binding", ROOT / "games/naraka/native_postskin_binding.py")
BIND = importlib.util.module_from_spec(BIND_SPEC)
BIND_SPEC.loader.exec_module(BIND)
BUFFER_SPEC = importlib.util.spec_from_file_location("naraka_test.native_postskin_buffers", ROOT / "games/naraka/native_postskin_buffers.py")
BUFFERS = importlib.util.module_from_spec(BUFFER_SPEC)
BUFFER_SPEC.loader.exec_module(BUFFERS)
sys.modules["naraka_test.native_postskin_binding"] = BIND
sys.modules["naraka_test.native_postskin_buffers"] = BUFFERS
EXPORT_SPEC = importlib.util.spec_from_file_location("naraka_test.native_postskin_export", ROOT / "games/naraka/native_postskin_export.py")
EXPORT = importlib.util.module_from_spec(EXPORT_SPEC)
EXPORT_SPEC.loader.exec_module(EXPORT)


class NativeEvidenceTests(unittest.TestCase):
    """Reject changed files and incompatible contracts before export begins."""

    def test_legacy_workspace_is_optional(self):
        self.assertIsNone(DATA.load_native_postskin(ROOT / "unused.json", {}))

    def test_unknown_schema_is_not_guessed(self):
        with self.assertRaises(DATA.NativePostSkinError):
            DATA.load_native_postskin(ROOT / "unused.json", {"SchemaVersion": 2})

    def test_displaced_unbound_vertex_is_rejected(self):
        # A newly moved vertex is not silently snapped to the old surface.
        # Such edits require a different binding method, outside this recipe.
        vertices = np.zeros((3, 10), dtype=np.float32)
        vertices[:, :3] = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        vertices[:, 5] = 1
        uv = vertices[:, :2].copy()
        triangles = np.array([[0, 1, 2]], dtype=np.uint32)
        evidence = {"source_vertices": vertices, "source_uv": uv, "source_triangles": triangles,
                    "members": np.arange(3), "offsets": np.arange(4)}
        edited = vertices.copy()
        edited[0, 2] = 0.01
        with self.assertRaises(DATA.NativePostSkinError):
            BIND.bind_subdivision_sources(evidence, edited, uv, triangles)

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

    @unittest.skipUnless(os.environ.get("NARAKA_POSTSKIN_MOD_BUFFERS"), "requires local subdivision fixture")
    def test_real_subdivision_correspondence(self):
        # Validate all exported vertices and triangle ownership using data from
        # the maintained collector, rather than the old hardcoded probe loader.
        file = Path(os.environ["NARAKA_POSTSKIN_EVIDENCE_JSON"])
        evidence = DATA.load_native_postskin(file, json.loads(file.read_text()))
        folder = Path(os.environ["NARAKA_POSTSKIN_MOD_BUFFERS"])
        vertices = np.fromfile(folder / "LOD0.c00f48ca-Position.buf", "<f4").reshape(-1, 10)
        uv = np.fromfile(folder / "LOD0.c00f48ca-Texcoord.buf", "<f4").reshape(-1, 2)
        triangles = np.fromfile(folder / "LOD0.c00f48ca-0-Index.buf", "<u4").reshape(-1, 3)
        parents = BIND.bind_subdivision_sources(evidence, vertices, uv, triangles)
        self.assertEqual(parents.shape, (53092, 2))
        reference = os.environ.get("NARAKA_POSTSKIN_REFERENCE_PARENTS")
        if reference:
            # This independent probe baseline produced the visually tested Mod.
            self.assertTrue(np.array_equal(parents, np.load(reference)))
        generated = BUFFERS.build_native_buffers(evidence, parents, triangles)
        self.assertEqual(generated["vertex_dispatch"], 830)
        self.assertEqual(generated["frame_dispatch"], 6)
        self.assertEqual(generated["normal_dispatch"], 95)
        baseline = os.environ.get("NARAKA_POSTSKIN_REFERENCE_BUFFERS")
        if baseline:
            # Check every binary input against the installed, visually tested
            # experiment. This includes signed influences and both CSR tables.
            for name, array in generated["arrays"].items():
                expected = (Path(baseline) / (name + ".buf")).read_bytes()
                self.assertEqual(array.tobytes(), expected, name)
        plan = EXPORT.prepare_native_export(file, evidence["metadata"], "c00f48ca", "caa1c4c4",
            {"Position": vertices.view(np.uint8).ravel(), "Texcoord": uv.view(np.uint8).ravel()}, [triangles.ravel()])
        lines, files, capture = EXPORT.emit_native_ini(plan)
        text = "\n".join(lines)
        self.assertEqual(len(files), 16)
        self.assertIn("run = CommandList\\NBPv1\\DeformNative", text)
        self.assertIn("run = CommandList\\NBPv1\\RecalculateNormals", text)
        self.assertNotIn("[CustomShader", text)
        self.assertIn("[" + capture + "]", text)
        self.assertIn("ResourceNative_c00f48ca_Bones = ref cs-t2", text)
        for name, array in generated["arrays"].items():
            self.assertEqual(files["native_c00f48ca_" + name + ".buf"], array.tobytes())
        # A second DrawIB gets distinct symbols and filenames even when its
        # generated array shapes happen to match this model exactly.
        second = dict(plan, draw_ib="01234567")
        other_lines, other_files, _ = EXPORT.emit_native_ini(second)
        self.assertFalse(set(files) & set(other_files))
        sections = {line for line in lines if line.startswith("[")}
        self.assertFalse(sections & {line for line in other_lines if line.startswith("[")})
        runtime = os.environ.get("NARAKA_POSTSKIN_RUNTIME_FOLDER")
        if runtime:
            EXPORT.check_package_runtime(runtime)


if __name__ == "__main__":
    unittest.main()
