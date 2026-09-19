"""Exercise the actual YYSLS shape exporter without importing Blender.

Reuse existing Blender-free module loaders and the real shared timeline writer.
The fixtures contain real buffer lengths, layouts, and multiple submesh draws.
Assertions cover portable assets, resource flags, and the draw-local cache.
This checks generation, not the loader parser or in-game rendering behavior.
GPU arithmetic has a separate WARP test using the emitted shader sources.
"""

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS

import test_time_position_ini as support
from test_animation_toggle_ini import parse_sections, Runtime
import test_yysls_cloth as cloth_support


# Load the shared key/timeline implementation, keeping bpy dependencies stubbed.
support.ensure_parent_packages()
support.install_stubs()
MODULES = support.load_real_modules()
HELPER = MODULES[support.TEST_PKG + ".common.m_ini_helper"].M_IniHelper
KEY = MODULES[support.TEST_PKG + ".common.m_key"].M_Key
SHAPES = cloth_support.sys.modules[cloth_support.PACKAGE + ".games.yysls_shapekeys"]
SHAPES.M_IniHelper = HELPER
SHAPES.BlueprintExportHelper = support.BlueprintExportHelper


def make_model(draw_ib="b08e2121", count=65, compressed=False):
    # Reference layout: float3 position, opaque color, UNORM8 normal, float2 UV.
    # A compressed mesh substitutes UNORM16x4 position and has a 24-byte stride.
    model = cloth_support.make_model(draw_ib)
    position_format = "R16G16B16A16_UNORM" if compressed else "R32G32B32_FLOAT"
    position_size = 8 if compressed else 12
    fields = [("POSITION", position_format, position_size), ("COLOR", "R8G8B8A8_UNORM", 4),
              ("NORMAL", "R8G8B8A8_UNORM", 4), ("TEXCOORD", "R32G32_FLOAT", 8)]
    model.d3d11_game_type.D3D11ElementList = [
        NS(Category="Position", SemanticName=name, SemanticIndex=0, Format=fmt, ByteWidth=size)
        for name, fmt, size in fields]
    stride = position_size + 16
    model.d3d11_game_type.CategoryStrideDict["Position"] = stride
    model.vertex_count = count
    model.category_buffer_dict = {"Position": bytes(count * stride)}
    model.shapekey_name_bytelist_dict = {"blink": bytes(count * stride)}
    model.time_pos_frame_groups = {}
    return model


def render(models):
    # Exercise ExportYYSLS hooks, not an isolated copy of the section writer.
    # The production serializer merges Constants and Present into singletons.
    with tempfile.TemporaryDirectory() as directory:
        cloth_support.CONFIG.output = directory
        exporter, builder = cloth_support.build(models)
        exporter.generate_buffer_files()
        path = Path(directory) / "fixture.ini"
        builder.save_to_file(str(path))
        sections = parse_sections(path.read_text())
        shaders = {p.name: p.read_text() for p in Path(directory).glob("yysls_shapes_*.hlsl")}
    return sections, shaders


class ShapeTests(unittest.TestCase):
    def setUp(self):
        # One classic shape by default; individual tests add timed controls.
        support.TEST_SHAPEKEY_DICT.clear()
        support.TEST_SHAPEKEY_DICT["blink"] = KEY(key_name="$shapekey0", initialize_vk_str="F2")

    def tearDown(self):
        # The cloth harness shares this module in a single-process test suite.
        support.TEST_SHAPEKEY_DICT.clear()

    def test_draw_hook_and_safe_resource_contract(self):
        """Require the reference's allocation order with legal D3D11 flags.

        Both scoped cloth shaders and unknown shader passes use this draw body.
        Its first command must compute, before any category reaches a VB slot.
        Static SRVs are referenced directly instead of copied on every frame.
        The writable structured result is copied into an explicitly raw VB.
        Slot backups must restore the game's state after that final copy.
        Shader constants come from the actual exported category layout.
        """
        model = make_model()
        sections, shaders = render([model])
        root = "Resourceb08e2121"
        draw = sections["CommandList_YYSLS_Draw_LOD0.b08e2121_0"]
        self.assertEqual(draw[0], "run = " + SHAPES.command_name(model))
        compute = sections["CustomShader_YYSLS_Shape_b08e2121"]
        self.assertIn("cs-u5 = copy " + root + "YYSLSShapeBase", compute)
        self.assertIn("cs-t50 = ref " + root + "YYSLSShapeBase", compute)
        self.assertIn("Dispatch = 2,1,1", compute)
        self.assertIn(root + "YYSLSShapeComputed = copy cs-u5", compute)
        # Every borrowed UAV/SRV is restored after the output copy.
        # No compute-only resource is ever referenced directly by a VB slot.
        self.assertEqual(compute[-4:], [slot + " = ref " + root + "YYSLSShapeBackup_" + slot for slot in SHAPES.SLOTS])
        self.assertIn("misc_flags = buffer_allow_raw_views", sections[root + "YYSLSShapeComputed"])
        self.assertIn("bind_flags = vertex_buffer", sections[root + "YYSLSShapeComputed"])
        self.assertIn("type = StructuredBuffer", sections[root + "YYSLSShapeBase"])
        self.assertIn("stride = 32", sections[root + "YYSLSShapeScratch"])
        self.assertIn("array = 1", sections[root + "YYSLSShapeScratch"])
        self.assertIn("#define NORMAL_WORD 4", shaders[SHAPES.shader_filename(model)])
        self.assertIn("key = F2", sections["Key_ShapeKey_blink"])
        self.assertNotIn("CustomShaderComputeShapes1", sections)

    def test_cache_first_draw_reload_and_next_frame(self):
        """Model repeated draws, Present invalidation, and startup state.

        The first draw must compute even before Present has run once.
        Later submesh/pass draws reuse that result rather than dispatch again.
        The next Present invalidates the shared per-DrawIB cache.
        This state is never restored from persisted user settings on reload.
        The model records calls only; arithmetic belongs to the WARP tests.
        """
        model = make_model()
        sections, _ = render([model])
        # The shared interpreter records CustomShader calls rather than emulating
        # the GPU. Feed only the readiness declarations, not persistent hotkeys.
        runtime = Runtime({"Constants": ["global " + SHAPES.ready_name(model) + " = 0"]})
        runtime.sections = sections
        # Cache publication is a resource ref, outside the arithmetic interpreter.
        commands = [line for line in sections[SHAPES.command_name(model)] if not line.startswith("Resource")]
        for expected in (1, 1, 1):
            runtime.run(commands, 0)
            self.assertEqual(len(runtime.dispatches), expected)
        runtime.run([line.removeprefix("post ") for line in sections["Present"]], 1)
        runtime.run(commands, 1)
        self.assertEqual(len(runtime.dispatches), 2)
        # A fresh runtime starts from zero without a prior Present invocation.
        self.assertIn("global " + SHAPES.ready_name(model) + " = 0", sections["Constants"])

    def test_disabled_hidden_and_missing_shapes(self):
        """Separate missing shape data from an intentionally hidden submesh.

        Missing data creates neither a compute shader nor a dangling draw hook.
        A hidden submesh may share model resources but must issue no computation.
        A disabled costume gate must wrap every route to the common draw body.
        Offscreen models must not dispatch from Present just to refresh a cache.
        These constraints preserve the existing cloth and visibility behavior.
        """
        first = make_model()
        other = cloth_support.make_model("12345678")
        hidden = make_model("87654321")
        hidden.submesh_ib_dict[hidden.submesh_model_list[0].submesh_name] = []
        sections, shaders = render([first, other, hidden])
        # No hook is attached to DrawIBs without data or deliberately hidden parts.
        self.assertNotIn("CustomShader_YYSLS_Shape_12345678", sections)
        parent = sections["TextureOverride_LOD0.b08e2121_0"]
        self.assertLess(parent.index("if $costume_mods"), next(i for i, line in enumerate(parent) if line.startswith("run = ")))
        hidden_parent = sections["TextureOverride_LOD0.87654321_0"]
        self.assertFalse(any(line.startswith("run = ") for line in hidden_parent))
        self.assertEqual(len(shaders), 2)
        self.assertFalse(any("CustomShader" in line for line in sections["Present"]))

    def test_multiple_keys_and_time_animation(self):
        """Combine a weight hotkey with an independently toggled timeline.

        First/last flags bracket all keys contributing to this particular mesh.
        The final dispatch alone normalizes and writes the packed vertex.
        Multiple keys therefore allocate one float scratch record per vertex.
        Playback toggles must not accidentally create classic weight-cycle keys.
        Timeline state updates must precede geometry-cache invalidation.
        """
        model = make_model()
        model.shapekey_name_bytelist_dict["smile"] = model.category_buffer_dict["Position"]
        animated = KEY(key_name="$shapekey1", key_type="time_shapekey", fps=10,
                       value_list=[0, 1], weight_list=[0.0, 1.0])
        animated.configure_animation_toggle(NS(toggle_key="F3", start_enabled=False))
        support.TEST_SHAPEKEY_DICT["smile"] = animated
        sections, _ = render([model])
        compute = sections["CustomShader_YYSLS_Shape_b08e2121"]
        self.assertEqual([line for line in compute if line.startswith("y88")], ["y88 = 1", "y88 = 0"])
        self.assertEqual([line for line in compute if line.startswith("z88")], ["z88 = 0", "z88 = 1"])
        self.assertEqual(compute.count("Dispatch = 2,1,1"), 2)
        self.assertIn("array = 65", sections["Resourceb08e2121YYSLSShapeScratch"])
        self.assertIn("KeyMimiAnimation_shapekey1", sections)
        self.assertNotIn("Key_ShapeKey_smile", sections)
        # Update timeline controls before invalidating the cached geometry.
        present = sections["Present"]
        self.assertLess(present.index("post run = CommandListMimiAnimation_shapekey1"),
                        present.index("post " + SHAPES.ready_name(model) + " = 0"))

    def test_animated_seed_does_not_replace_delta_reference(self):
        model = make_model()
        model.time_pos_frame_groups = {"frame": {}}
        sections, _ = render([model])
        compute = sections["CustomShader_YYSLS_Shape_b08e2121"]
        self.assertIn("cs-u5 = copy Resourceb08e2121PositionTimeBase", compute)
        self.assertIn("cs-t50 = ref Resourceb08e2121YYSLSShapeBase", compute)

    def test_compressed_layout_and_dispatch_limit(self):
        model = make_model(count=65537, compressed=True)
        self.assertEqual(SHAPES.validate_model(model), (6, 0, 3, 1))
        sections, shaders = render([model])
        self.assertIn("Dispatch = 1025,1,1", sections["CustomShader_YYSLS_Shape_b08e2121"])
        self.assertIn("#define POSITION_UNORM16 1", shaders[SHAPES.shader_filename(model)])

    def test_invalid_layout_and_buffer_fail_before_assets(self):
        """Reject corrupt inputs before even the first shader file is emitted.

        A valid first model must not hide a malformed later model in preflight.
        Both base and full-weight targets must have exactly count times stride.
        Unsupported normal encodings cannot use the UNORM codec by accident.
        Compute-slot categories cannot silently reuse the direct VB draw path.
        Bounds use the 64-thread group limit, not the old one-vertex group limit.
        """
        # Test one invalid property at a time so every guard is exercised.
        # The source dictionaries are rebuilt rather than mutated across cases.
        mutations = [
            lambda m: setattr(m.d3d11_game_type.D3D11ElementList[2], "Format", "R8G8B8A8_SNORM"),
            lambda m: m.shapekey_name_bytelist_dict.update(blink=b"short"),
            lambda m: m.category_buffer_dict.update(Position=b"short"),
            lambda m: setattr(m, "vertex_count", 0),
            lambda m: setattr(m, "vertex_count", 65535 * 64 + 1),
            lambda m: m.d3d11_game_type.CategoryExtractSlotDict.update(Position="cs-u0"),
        ]
        for mutate in mutations:
            model = make_model()
            mutate(model)
            with tempfile.TemporaryDirectory() as directory:
                cloth_support.CONFIG.output = directory
                with self.assertRaises(ValueError):
                    SHAPES.write_shaders([make_model("11223344"), model])
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_no_keys_produces_no_shape_resources(self):
        support.TEST_SHAPEKEY_DICT.clear()
        sections, shaders = render([make_model()])
        self.assertFalse(shaders)
        self.assertFalse(any("YYSLSShape" in name for name in sections))
        draw = sections["CommandList_YYSLS_Draw_LOD0.b08e2121_0"]
        self.assertTrue(draw[0].startswith("vb2 = "))


if __name__ == "__main__":
    unittest.main()
