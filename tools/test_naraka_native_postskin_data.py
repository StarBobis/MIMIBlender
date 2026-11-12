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

    def test_multiple_batches_and_depth_modes_preserve_native_positions(self):
        """Preserve the full native blend, not only frame-index selection.

        The reference first skins each original point with one identity bone,
        then applies its own active row and selected simulation-frame base.
        The expected source result is skin*(1-alpha*g)+simulation*alpha*g*scale.
        A midpoint must equal the mean of those complete source results.

        The generated path evaluates the emitted signed influences against
        extended live frames: simulation*g*scale, bone, and bone*g families.
        It must match the reference even with unequal source alpha values.
        Mode one leaves depth y out, mode two divides by it, and other modes
        multiply by it; synthetic bone frames keep both depth factors at one.
        Every simulation matrix has a different translation and depth factor.
        This prevents an accidental zero-base or identity-depth shortcut from
        passing merely because all frame transforms happen to be identical.
        """
        # Compare generated affine terms with an independent direct evaluation
        # of the original shader. Use two frame bases and live depth factors,
        # not just multiple batches that happen to share a zero frame offset.
        count = 3
        source = np.zeros((count, 10), "<f4")
        source[:, :3] = [[0.2, 0.3, 0.4], [0.6, -0.2, 0.8], [-0.3, 0.5, 0.9]]
        blend = np.zeros(count, dtype=np.dtype([("w", "<f4", 4), ("i", "<i4", 4)]))
        blend["w"][:, 0] = 1
        records = np.zeros((count, 8), "<f4")
        records.view("<u4")[:, :3] = [[0, 0, 1], [1, 1, 2], [2, 2, 3]]
        records[:, 4] = [0.2, 0.5, 0.8]
        influences = np.zeros((count, 8), "<f4")
        influences[:, 0] = 1
        influences[:, 1:4] = source[:, :3] * 0.7
        influences.view("<u4")[:, 4] = [0, 1, 0]
        parents = np.array([[0, -1], [1, -1], [2, -1], [0, 2]], "<i4")
        triangles = np.array([[0, 1, 3], [1, 2, 3]], "<u4")
        # Nonidentity frames and nonunit depth factors distinguish each mode.
        frames = np.tile(np.eye(4, dtype=np.float32), (4, 1, 1))
        frames[:, :3, 3] = [[0.1, 0.2, 0.3], [0.4, -0.2, 0.1],
                               [-0.2, 0.3, 0.5], [0.7, 0.1, -0.4]]
        depth = np.array([[0.7, 1.3], [1.2, 0.8], [0.9, 1.4], [1.1, 0.6]])
        g, scale = 0.65, 0.8
        for mode in [0, 1, 2, 3]:
            for inactive in [False, True]:
                cb = np.array([2, 2, 99, count, 0, 0, mode, 0, 0, 0, 0, 0], "<u4")
                batches = np.array([[0, 2, 0, 0], [2, 3, 1, 0]], "<u4")
                if inactive:
                    batches[1, 2] = 0xffffffff
                bases = np.array([1, 2], "<u4")
                evidence = {"source_vertices": source, "source_blend_bytes": blend.tobytes(),
                    "members": np.arange(count), "offsets": np.arange(count + 1),
                    "position_records": records, "position_influences": influences,
                    "frame_count": 4, "bone_count": 1, "normal_targets": np.arange(count),
                    "position_inputs": {"cs-cb0": cb.tobytes(), "cs-t0": batches.tobytes(),
                                        "cs-t1": bases.tobytes()}}
                generated = BUFFERS.build_native_buffers(evidence, parents, triangles)["arrays"]
                self.assertEqual(generated["position-cb"][6], mode)
                expected = source[:, :3].astype(float).copy()
                for index, row in enumerate(records):
                    # Linear native batch search, independent of the generator's
                    # searchsorted/normalization implementation and term copies.
                    selected_batch = batches[0]
                    for candidate in batches:
                        if index >= int(candidate[0]):
                            selected_batch = candidate
                    selector = int(selected_batch[2])
                    if selector >= len(bases):
                        continue
                    term = influences[index]
                    frame_id = int(term.view("<u4")[4]) + int(bases[selector])
                    local = np.append(term[1:4].astype(float), 1)
                    local[2] *= depth[frame_id, 0]
                    if mode == 2:
                        local[2] /= depth[frame_id, 1]
                    elif mode != 1:
                        local[2] *= depth[frame_id, 1]
                    alpha = float(row[4]) * g
                    expected[index] = expected[index] * (1 - alpha) + (frames[frame_id] @ local)[:3] * alpha * scale
                result = []
                for row in generated["position-mapping"]:
                    left, right = map(int, row.view("<u4")[1:3])
                    total = np.zeros(3)
                    for term in generated["position-influences"][left:right]:
                        frame_id = int(term.view("<u4")[4])
                        local = np.append(term[1:4].astype(float), 1)
                        if frame_id < 4:
                            local[2] *= depth[frame_id, 0]
                            if mode == 2:
                                local[2] /= depth[frame_id, 1]
                            elif mode != 1:
                                local[2] *= depth[frame_id, 1]
                            transformed = (frames[frame_id] @ local)[:3] * g * scale
                        else:
                            # Synthetic bone depth factors are both one, so all
                            # native depth selectors preserve their local xyz.
                            transformed = local[:3] * (1 if frame_id == 4 else g)
                        total += float(term[0]) * transformed
                    result.append(total)
                wanted = np.vstack((expected, (expected[0] + expected[2]) / 2))
                with self.subTest(mode=mode, inactive=inactive):
                    np.testing.assert_allclose(result, wanted, atol=2e-7, rtol=2e-7)
                # Source evidence stays immutable; another export may reuse it.
                self.assertEqual(evidence["position_influences"].tobytes(), influences.tobytes())

    def test_native_active_ranges_and_invalid_batch_bounds(self):
        # The native shader can omit a trailing mapping range and one complete
        # dispatch group. Preserve these masks before looking up source alpha.
        records = np.zeros((128, 8), "<f4")
        records.view("<u4")[:, 0] = np.arange(128)
        cb = np.array([1, 1, 1, 128, 16, 0, 2, 0, 0, 0, 0, 0], "<u4")
        batches = np.array([[0, 128, 0, 0]], "<u4")
        evidence = {"position_records": records, "position_influences": np.empty((0, 8), "<f4"),
            "frame_count": 1, "position_inputs": {"cs-cb0": cb.tobytes(),
            "cs-t0": batches.tobytes(), "cs-t1": np.array([0], "<u4").tobytes()}}
        active, _, mode = BUFFERS._active_position_records(evidence)
        np.testing.assert_array_equal(active.view("<u4")[:, 0], np.arange(64))
        self.assertEqual(mode, 2)
        # The count must be bounded by captured records, not trusted as a loop
        # limit that could allocate unbounded data or read another model's rows.
        cb[3] = 145
        evidence["position_inputs"]["cs-cb0"] = cb.tobytes()
        with self.assertRaisesRegex(DATA.NativePostSkinError, "active mapping count"):
            BUFFERS._active_position_records(evidence)

    def test_legacy_workspace_is_optional(self):
        self.assertIsNone(DATA.load_native_postskin(ROOT / "unused.json", {}))

    def test_unknown_schema_is_not_guessed(self):
        with self.assertRaises(DATA.NativePostSkinError):
            DATA.load_native_postskin(ROOT / "unused.json", {"SchemaVersion": 2})

    def test_native_export_requires_exact_drawib_association(self):
        # A known shader in a dump does not establish ownership by this model.
        # Export must reject old unproven records or another DrawIB's record
        # before reading any native file or touching the output directory.
        metadata = {"SchemaVersion": 1, "OutputHash": "caa1c4c4", "Stages": [
            {"ShaderHash": "ade59729c33f1db5"}, {"ShaderHash": "3e301419231eeeff"}]}
        with self.assertRaisesRegex(DATA.NativePostSkinError, "re-extract and re-import"):
            EXPORT.prepare_native_export(ROOT / "missing.json", metadata, "c00f48ca", "caa1c4c4", {}, [])
        metadata["Association"] = {"Status": "VerifiedDrawBinding", "DrawIB": "11111111"}
        with self.assertRaisesRegex(DATA.NativePostSkinError, "does not match this indexed draw"):
            EXPORT.prepare_native_export(ROOT / "missing.json", metadata, "c00f48ca", "caa1c4c4", {}, [])

    def test_unrelated_compute_evidence_keeps_legacy_export(self):
        # The collector is allowed to retain zero, one or many unrelated CS
        # writers. None of them opts a model into the two-stage native recipe.
        # Deliberately omit paths, output hashes and geometry to ensure that
        # legacy selection happens before native-only resource validation.
        for hashes in [[], ["1111111111111111"], ["1111111111111111"] * 3]:
            metadata = {"SchemaVersion": 1, "Stages": [{"ShaderHash": shader} for shader in hashes]}
            with self.subTest(hashes=hashes):
                self.assertFalse(DATA.requires_native_postskin(metadata))
                self.assertIsNone(DATA.load_native_postskin(ROOT / "missing.json", metadata))
                self.assertIsNone(EXPORT.prepare_native_export(ROOT / "missing.json", metadata,
                                                              "", "", {}, []))

    def test_known_native_chain_selection_is_explicit(self):
        # Editable Role strings must not substitute for the actual shader IDs.
        # Preserve errors for partial, reversed, repeated or mixed known chains;
        # silently using legacy output there could reintroduce mesh tearing.
        position, normal = "ade59729c33f1db5", "3e301419231eeeff"
        pair = {"SchemaVersion": 1, "Stages": [{"ShaderHash": shader} for shader in [position, normal]]}
        self.assertTrue(DATA.requires_native_postskin(pair))
        for hashes in [[position], [normal], [normal, position], [position, normal, normal],
                       [position, "1111111111111111", normal]]:
            metadata = dict(pair, Stages=[{"ShaderHash": shader} for shader in hashes])
            with self.subTest(hashes=hashes):
                with self.assertRaisesRegex(DATA.NativePostSkinError, "found " + hashes[0]):
                    DATA.load_native_postskin(ROOT / "missing.json", metadata)
        # Invalid stage shapes remain metadata errors, not unrelated-CS cases.
        for stages in [None, {}, [None]]:
            with self.assertRaisesRegex(DATA.NativePostSkinError, "list of stage objects"):
                DATA.requires_native_postskin(dict(pair, Stages=stages))
        # Incomplete identity must never be interpreted as an unknown writer.
        for stage in [{}, {"ShaderHash": None}, {"ShaderHash": "invalid"}]:
            with self.assertRaisesRegex(DATA.NativePostSkinError, "ShaderHash must"):
                DATA.requires_native_postskin(dict(pair, Stages=[stage]))

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

    @unittest.skipUnless(os.environ.get("NARAKA_POSTSKIN_MIXED_WORKSPACE"), "requires mixed MMT workspace fixture")
    def test_real_mixed_workspace_keeps_drawib_ownership(self):
        # Both documents come from one capture containing the native shaders.
        # The ordinary DrawIB must have no native metadata or export dependency;
        # the affected DrawIB exercises an actual two-batch native input table.
        root = Path(os.environ["NARAKA_POSTSKIN_MIXED_WORKSPACE"])
        checked = set()
        for path in root.rglob("*.json"):
            document = json.loads(path.read_text())
            draw_ib = path.name[:8]
            if draw_ib not in ["051ea211", "8305a460"]:
                continue
            categories = {item["D3D11ElementList"][0]["Category"]:
                          np.fromfile(path.parent / item["FileName"], np.uint8)
                          for item in document["CategoryBufferList"]}
            indices = [np.fromfile(path.parent / item["FileName"], "<u4")
                       for item in document["IndexBufferList"]]
            metadata = document.get("NarakaPostSkin")
            plan = EXPORT.prepare_native_export(path, metadata, draw_ib,
                                                document["VertexLimitVB"], categories, indices)
            self.assertEqual(plan is not None, draw_ib == "8305a460")
            if plan:
                evidence = DATA.load_native_postskin(path, metadata)
                self.assertEqual(np.frombuffer(evidence["position_inputs"]["cs-cb0"], "<u4")[1], 2)
            else:
                self.assertNotIn("NarakaPostSkin", document)
            checked.add(draw_ib)
        self.assertEqual(checked, {"051ea211", "8305a460"})

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
        # Flattened frame IDs must not inherit an additional nonzero game base.
        self.assertIn("cs-t1 = ref ResourceNative_c00f48ca_PositionOffsets", text)
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
