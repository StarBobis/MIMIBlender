"""Regression tests for YYSLS draw-local cloth bypass, without Blender.

Load the actual exporter, section builder, and shared draw-line helper.
Only Blender-facing dependencies and mesh objects are replaced by fixtures.
A small command-list model checks control-flow outcomes, not the 3Dmigoto
parser or GPU state restoration implementation. The separate shader test
compiles the real asset and can compare it with the working ShaderFixes VS.

Coverage is intentionally separated into generation and shader validation:
- Identification metadata must not contain a run or handling command.
- A matching shader uses the custom VS for exactly one indexed draw.
- Other shaders keep the same draw arguments and their own shader object.
- Disabling costume mods prevents skip, resource binding, and custom draws.
- A hidden submesh produces no custom shader invocation at all.
- Existing object conditions remain outside each wrapped draw.
- Per-object texture replacement remains immediately before its draw.
- Per-object texture restoration remains immediately after its draw.
- Index offsets and base-vertex values are never reconstructed or guessed.
- Multiple DrawIBs produce one shared marker and distinct custom sections.
- Packaging copies a portable asset beside the generated INI.
- No exported path depends on the developer's game directory.

The command-list model implements only the emitted conditional subset.
It deliberately does not pretend to validate 3Dmigoto's parser or driver.
In particular, VS restoration is a documented CustomShader contract here.
Real-game acceptance should check an unrelated mesh immediately afterwards.
The actual ShaderOverride only identifies a hash; it never suppresses a draw.
The actual TextureOverride still requires its original index-buffer match.
Therefore the simulation starts only after selecting the tested override.
"""

import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace as NS


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "yysls_cloth_test"


def install_module(name, **values):
    # Synthetic packages avoid executing the addon's bpy-dependent __init__.
    module = types.ModuleType(PACKAGE + "." + name)
    module.__dict__.update(values)
    sys.modules[module.__name__] = module
    return module


def load_module(name, filename):
    # Load production modules by path while preserving their relative imports.
    spec = importlib.util.spec_from_file_location(PACKAGE + "." + name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def setup_modules():
    """Install small dependency stubs and import the real export path."""
    sys.modules[PACKAGE] = types.ModuleType(PACKAGE)
    for name in ("common", "games", "games.base"):
        install_module(name)
    config = NS(generated_mod_number=0, output="")
    config.path_generate_mod_folder = lambda: config.output
    config.path_generatemod_buffer_folder = lambda: config.output
    config.get_generated_mod_name = lambda: "fixture"
    config.ini_buffer_filename = lambda name: "Buffers\\" + name
    install_module("common.global_config", GlobalConfig=config)
    properties = NS(forbid_auto_texture_ini=lambda: False)
    install_module("common.mimi_global_properties", MIMIGlobalProperties=properties)

    # Extract the real draw helper rather than implementing its behavior twice.
    # Deferred annotations avoid importing Blender's DrawCallModel type.
    # Object texture commands remain fixture inputs in their original order.
    tree = ast.parse((ROOT / "common/m_ini_helper.py").read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "M_IniHelper")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "get_drawindexed_str_list")
    method.decorator_list = []
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module_ast = ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[]))
    control = NS(
        get_object_texture_slot_lines=lambda obj: obj.texture_lines,
        get_object_texture_slot_restore_lines=lambda obj: obj.restore_lines,
    )
    scope = {"M_ControlFlow": control}
    exec(compile(module_ast, "shared_draw_helper", "exec"), scope)
    helper = NS(get_drawindexed_str_list=scope[method.name])
    # Shared finalization is not replaced, only its unrelated Blender helpers.
    # This exercises the actual once-per-export shader marker insertion hook.
    for name in ("generate_hash_style_texture_ini", "generate_shared_slot_style_texture_ini",
                 "generate_hash_style_object_texture_ini", "move_slot_style_textures",
                 "move_object_texture_binding_files", "add_branch_key_sections",
                 "add_shapekey_ini_sections"):
        setattr(helper, name, lambda *args, **kwargs: None)
    install_module("common.m_ini_helper", M_IniHelper=helper)
    install_module("games.base.sections", add_resource_texture_sections=lambda **kwargs: None)
    builder = load_module("common.m_ini_builder", "common/m_ini_builder.py")
    load_module("games.base.standard_exporter", "games/base/standard_exporter.py")
    cloth = load_module("games.yysls_cloth", "games/yysls_cloth.py")
    exporter = load_module("games.yysls", "games/yysls.py")
    return config, builder, cloth, exporter.ExportYYSLS


CONFIG, BUILDER, CLOTH, EXPORTER = setup_modules()


def make_draw(arguments="924,0,0", condition=""):
    # Nonzero offsets in dedicated tests must survive the wrapper unchanged.
    return NS(obj_name="cloth", vertex_count=226, texture_lines=[], restore_lines=[],
              get_condition_str=lambda: condition,
              get_drawindexed_str=lambda offsets: "drawindexed = " + arguments)


def make_model(draw_ib="31e22cc3", hidden=False, draws=None):
    # The slots and strides match the supplied RuiHeXian configuration.
    # A second model uses a different hash to test unique command names.
    submesh = NS(submesh_name="LOD0." + draw_ib + "-0", match_first_index=0,
                 match_index_count=924, drawcall_model_list=draws or [make_draw()])
    game_type = NS(
        CategoryDrawCategoryDict={"Blend": "Blend", "Position": "Position", "Texcoord": "Texcoord"},
        CategoryExtractSlotDict={"Blend": "vb2", "Position": "vb0", "Texcoord": "vb1"},
        OrderedCategoryNameList=["Position", "Texcoord", "Blend"],
        CategoryStrideDict={"Position": 24, "Texcoord": 16, "Blend": 8}, GPU_PreSkinning=True,
    )
    return NS(draw_ib=draw_ib, d3d11_game_type=game_type, submesh_model_list=[submesh],
              submesh_ib_dict={submesh.submesh_name: [] if hidden else [0, 1, 2]},
              obj_name_draw_offset={}, get_submesh_texture_markup_info_list=lambda sub: [],
              get_category_buffer_filename=lambda category: "LOD0." + draw_ib + "-" + category + ".buf",
              apply_drawib_alias=lambda: None, generate_buffer_files=lambda path: None)


def build(models, keys=False):
    # The real constructor still parses the supplied blueprint and aliases.
    blueprint = NS(keyname_mkey_dict={"key": 1} if keys else {},
                   parse_drawib_model_list=lambda combine_ib: models)
    exporter = EXPORTER(blueprint)
    builder = BUILDER.M_IniBuilder()
    for model in models:
        exporter.add_drawib_sections(builder, model)
    exporter.add_final_sections(builder, {model.draw_ib: model for model in models})
    return exporter, builder


def parse_sections(builder):
    # Preserve repeated keys and commands: ConfigParser would discard them.
    result = {}
    current = None
    for section in builder.ini_section_list:
        for raw in section.SectionLineList:
            line = raw.strip()
            if line.startswith("["):
                current = line[1:-1]
                assert current not in result, "Duplicate section: " + current
                result[current] = []
            elif line and not line.startswith(";"):
                result[current].append(line)
    return result


def simulate(sections, section_name, shader=823114, enabled=1, variant=1):
    """Model the emitted subset; this is explicitly not a game integration test.

    Conditions are evaluated as the generated draw list executes.
    The model supports only boolean variables and equality with an integer.
    Nested branches inherit the enabled state of their parent branch.
    A disabled parent prevents either child branch from executing commands.
    Each section must finish with a balanced conditional stack.
    Hash and draw-range metadata are not executable command-list effects.
    Their matching role is assumed by the caller selecting a section.
    Resource and handling commands are logged rather than sent to a driver.
    Their presence in a disabled trace therefore indicates a regression.
    Indexed draws record the shader that is active at the instant of drawing.
    The run command models CustomShader's documented save/restore boundary.
    This lets consecutive draws detect a missing shader-selection branch.
    It does not prove that a particular loader version restores shader state.
    That remaining acceptance check belongs to an in-game frame capture.
    No simulated state is written into the actual game's files or process.
    """
    # Model CustomShader's documented VS save/restore behavior around run.
    # Log side effects so the disabled-mod case can require an empty trace.
    state = {"vs": shader, "$costume_mods": enabled, "$variant": variant}
    trace = []

    def condition(text):
        if " == " in text:
            key, value = text.split(" == ")
            return state[key] == int(value)
        return bool(state[text])

    def execute(name):
        levels = [True]
        for line in sections[name]:
            if line.startswith("if "):
                levels.append(levels[-1] and condition(line[3:]))
            elif line == "else":
                levels[-1] = levels[-2] and not levels[-1]
            elif line == "endif":
                levels.pop()
            elif levels[-1]:
                key, value = line.split(" = ", 1)
                if key in ("hash", "match_first_index", "match_index_count", "filter_index", "allow_duplicate_hash"):
                    continue
                if key == "run":
                    before = state["vs"]
                    execute(value)
                    state["vs"] = before
                elif key == "vs":
                    state["vs"] = value
                elif key == "drawindexed":
                    trace.append(("draw", state["vs"], value))
                else:
                    trace.append((key, value))
        assert len(levels) == 1, "Unbalanced INI conditionals"

    execute(section_name)
    return trace, state["vs"]


class ClothTests(unittest.TestCase):
    def test_exact_hash_marker_has_no_render_commands(self):
        # Merely encountering the shader on another mesh must do nothing.
        _, builder = build([make_model()])
        sections = parse_sections(builder)
        marker = sections["ShaderOverride_YYSLS_ClothVS"]
        self.assertEqual(marker, ["hash = ab148fe238420411", "allow_duplicate_hash = true", "filter_index = 823114"])
        self.assertEqual(simulate(sections, "ShaderOverride_YYSLS_ClothVS")[0], [])

    def test_matching_shader_is_scoped_to_one_draw(self):
        # After the custom draw, a subsequent mesh still sees the original VS.
        _, builder = build([make_model()])
        trace, restored = simulate(parse_sections(builder), "TextureOverride_LOD0.31e22cc3_0")
        self.assertEqual([x for x in trace if x[0] == "draw"], [("draw", CLOTH.CLOTH_SHADER_FILENAME, "924,0,0")])
        self.assertEqual(restored, CLOTH.CLOTH_VS_FILTER)

    def test_other_shader_and_unbound_shader_never_use_custom_vs(self):
        # Other passes retain their original Mod draw, not the original mesh.
        _, builder = build([make_model()])
        for shader in (0, 1, 123456):
            trace, restored = simulate(parse_sections(builder), "TextureOverride_LOD0.31e22cc3_0", shader=shader)
            self.assertIn(("draw", shader, "924,0,0"), trace)
            self.assertEqual(restored, shader)

    def test_disabled_mod_has_no_skip_bind_or_draw(self):
        """Require a genuinely empty command trace when the mod is disabled.

        Testing only draw counts would miss a stray handling=skip command.
        Resource assignments could also alter later game draws without drawing.
        Both populated and intentionally hidden parts must pass this check.
        """
        # This includes disabling an intentionally hidden submesh via F6.
        for hidden in (False, True):
            _, builder = build([make_model(hidden=hidden)], keys=True)
            trace, _ = simulate(parse_sections(builder), "TextureOverride_LOD0.31e22cc3_0", enabled=0)
            self.assertEqual(trace, [])

    def test_hidden_mesh_never_invokes_custom_shader(self):
        # Hiding a part skips it but does not need to replace a shader object.
        _, builder = build([make_model(hidden=True)])
        sections = parse_sections(builder)
        self.assertFalse(any(name.startswith("CustomShader") for name in sections))
        trace, _ = simulate(sections, "TextureOverride_LOD0.31e22cc3_0")
        self.assertEqual(trace, [("handling", "skip"), ("ib", "null")])

    def test_object_conditions_offsets_and_texture_restore_survive(self):
        """Exercise the shared helper's most order-sensitive command sequence.

        The wrapper must not lift an object's draw outside its condition.
        Texture setup/cleanup surrounds both shader-selection branches alike.
        A negative base vertex is deliberately retained as a literal argument.
        """
        # Both draw arguments and surrounding texture commands are significant.
        draw = make_draw("300,17,-2", "$variant == 1")
        draw.texture_lines = ["ps-t0 = ResourceObject"]
        draw.restore_lines = ["ps-t0 = ResourceOriginal"]
        _, builder = build([make_model(draws=[draw])])
        sections = parse_sections(builder)
        name = "TextureOverride_LOD0.31e22cc3_0"
        trace, _ = simulate(sections, name, variant=1)
        index = trace.index(("draw", CLOTH.CLOTH_SHADER_FILENAME, "300,17,-2"))
        self.assertEqual(trace[index - 1], ("ps-t0", "ResourceObject"))
        self.assertEqual(trace[index + 1], ("ps-t0", "ResourceOriginal"))
        trace, _ = simulate(sections, name, variant=0)
        self.assertFalse(any(x[0] in ("draw", "ps-t0") for x in trace))

    def test_multiple_draws_and_drawibs_share_only_the_hash_marker(self):
        """Check both intra-submesh and inter-DrawIB command naming.

        A single mod can contain several original index-buffer hashes.
        Identification is emitted by finalization, not by each DrawIB hook.
        The second draw must also see the restored original shader marker.
        """
        # No duplicate section names, no global parameter slot, no stale flag.
        first = make_model(draws=[make_draw(), make_draw("6,924,5")])
        _, builder = build([first, make_model("12345678")])
        sections = parse_sections(builder)
        self.assertEqual(sum(n.startswith("ShaderOverride") for n in sections), 1)
        self.assertEqual(sum(n.startswith("CustomShader") for n in sections), 3)
        trace, restored = simulate(sections, "TextureOverride_LOD0.31e22cc3_0")
        self.assertEqual(sum(x[0] == "draw" for x in trace), 2)
        self.assertEqual(restored, CLOTH.CLOTH_VS_FILTER)

    def test_full_export_packages_shader_and_serializes_marker(self):
        """Check the production serializer as well as in-memory sections.

        Section types omitted by serialization would silently break filtering.
        Exported shader bytes must match the version shipped with the addon.
        Temporary files stay outside the real game and are removed afterwards.
        """
        # Exercise the actual StandardExporter.export flow in a temporary mod.
        # No buffer fixture writes are required for checking INI serialization.
        with tempfile.TemporaryDirectory() as directory:
            CONFIG.output = directory
            exporter, _ = build([make_model()])
            exporter.export()
            output = Path(directory)
            self.assertEqual((output / CLOTH.CLOTH_SHADER_FILENAME).read_bytes(),
                             (ROOT / "resources" / CLOTH.CLOTH_SHADER_FILENAME).read_bytes())
            text = (output / "fixture.ini").read_text()
            self.assertEqual(text.count("[ShaderOverride_YYSLS_ClothVS]"), 1)
            self.assertIn("if $costume_mods", text)
            self.assertIn("if vs == 823114", text)
            self.assertNotIn("ShaderFixes\\", text)


if __name__ == "__main__":
    unittest.main()
