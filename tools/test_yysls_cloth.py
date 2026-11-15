"""Exercise native-cloth INI generation with the real exporter and serializer.

Blender dependencies are replaced by fixtures. The command model checks scope,
unknown-pass preservation, object conditions, map cleanup and packaging. Actual
GPU decoding and Blender vertex provenance have separate regression programs.
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
    for name in ("common", "games", "games.base", "blueprint"):
        install_module(name)
    # Skip Draw helpers are bpy-free and live in the real common folder.
    # Exposing the folder lets this synthetic package import them by path,
    # exactly like the production module does.
    sys.modules[PACKAGE + ".common"].__path__ = [str(ROOT / "common")]
    # Existing cloth fixtures have no shape keys; load the real optional path.
    # This keeps the regression test sensitive to accidental unguarded hooks.
    install_module("blueprint.blueprint_export_helper", BlueprintExportHelper=NS(
        get_current_shapekeyname_mkey_dict=lambda: {}))
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
                 "generate_hash_style_global_texture_ini",
                 "generate_hash_style_object_texture_ini", "move_slot_style_textures",
                 "move_object_texture_binding_files", "add_branch_key_sections",
                 "add_shapekey_ini_sections"):
        setattr(helper, name, lambda *args, **kwargs: None)
    install_module("common.m_ini_helper", M_IniHelper=helper)
    install_module("games.base.sections", add_resource_texture_sections=lambda **kwargs: None)
    builder = load_module("common.m_ini_builder", "common/m_ini_builder.py")
    load_module("games.base.standard_exporter", "games/base/standard_exporter.py")
    cloth = load_module("games.yysls_cloth_preserve", "games/yysls_cloth_preserve.py")
    load_module("games.yysls_shapekeys", "games/yysls_shapekeys.py")
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


def simulate(sections, section_name, shader=823116, enabled=1, variant=1, events=None):
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
    Only CustomShader models a documented shader save/restore boundary.
    Plain CommandList calls run inside the caller's existing shader scope.
    Optional events record the active shader at every resource binding.
    This distinguishes early shader selection from merely changing at draw.
    It does not prove that a particular loader version restores shader state.
    That remaining acceptance check belongs to an in-game frame capture.
    No simulated state is written into the actual game's files or process.
    """
    # Model CustomShader's documented VS save/restore behavior around run.
    # Log side effects so the disabled-mod case can require an empty trace.
    state = {"vs": shader, "$costume_mods": enabled, "$variant": variant}
    trace = []
    if events is None:
        events = []

    def condition(text):
        if " || " in text:
            return any(condition(term) for term in text.split(" || "))
        if " == " in text:
            key, value = text.split(" == ")
            return state[key] == int(value)
        return bool(state[text])

    def execute(name):
        # Shader declarations are setup metadata, applied before run commands.
        # A normal CommandList must not save or restore the caller's shader.
        # This is the important difference from the earlier draw-only model.
        custom = name.startswith("CustomShader")
        original_shader = state["vs"]
        if custom:
            declaration = next(line for line in sections[name] if line.startswith("vs = "))
            state["vs"] = declaration.split(" = ", 1)[1]
            events.append(("vs_enter", state["vs"], name))
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
                    execute(value)
                elif key == "vs":
                    # Already installed before command-list execution starts.
                    assert custom
                elif key == "drawindexed":
                    trace.append(("draw", state["vs"], value))
                    events.append(("draw", state["vs"], value))
                else:
                    trace.append((key, value))
                    # Log bindings separately without altering earlier assertions.
                    # Include both submesh and per-object texture assignments.
                    if key == "ib" or key.startswith(("vb", "ps-t", "vs-t")):
                        events.append(("bind", state["vs"], line))
        assert len(levels) == 1, "Unbalanced INI conditionals"
        if custom:
            state["vs"] = original_shader
            events.append(("vs_restore", state["vs"], name))

    execute(section_name)
    return trace, state["vs"]


class ClothTests(unittest.TestCase):
    # These checks exercise the real exporter and serializer. The small command
    # model verifies scope and side effects, not D3D driver execution.
    def test_native_cloth_resources_cover_both_passes(self):
        _, builder = build([make_model()])
        sections = parse_sections(builder)
        for _, shader_filter, filename, _ in CLOTH.CLOTH_SHADER_VARIANTS:
            events = []
            trace, restored = simulate(sections, "TextureOverride_LOD0.31e22cc3_0",
                                       shader=shader_filter, events=events)
            self.assertEqual(restored, shader_filter)
            self.assertIn(("draw", filename, "924,0,0"), trace)
            self.assertIn(("vs-t118", "ref Resource31e22cc3YYSLSClothMap"), trace)
            self.assertEqual(trace[-1], ("vs-t118", "null"))
            self.assertFalse(any(e[0] == "vs-t119" for e in trace))
            binds = [e for e in events if e[0] == "bind"]
            self.assertTrue(all(e[1] == filename for e in binds))
            self.assertTrue(binds[0][2].startswith("vs-t118 = ref"))

    def test_unknown_pass_keeps_original_draw_untouched(self):
        _, builder = build([make_model()])
        for shader in (0, 1, 123456, 823114):
            trace, restored = simulate(parse_sections(builder),
                                      "TextureOverride_LOD0.31e22cc3_0", shader=shader)
            self.assertEqual(trace, [])
            self.assertEqual(restored, shader)

    def test_disabled_mod_has_no_side_effects(self):
        for hidden in (True, False):
            _, builder = build([make_model(hidden=hidden)])
            for _, shader, _, _ in CLOTH.CLOTH_SHADER_VARIANTS:
                self.assertEqual(simulate(parse_sections(builder),
                    "TextureOverride_LOD0.31e22cc3_0", shader=shader, enabled=0)[0], [])

    def test_object_conditions_offsets_and_texture_cleanup_survive(self):
        draw = make_draw("300,17,-2", "$variant == 1")
        draw.texture_lines = ["ps-t0 = ResourceObject"]
        draw.restore_lines = ["ps-t0 = ResourceOriginal"]
        _, builder = build([make_model(draws=[draw])])
        sections = parse_sections(builder)
        for _, shader, filename, _ in CLOTH.CLOTH_SHADER_VARIANTS:
            trace, _ = simulate(sections, "TextureOverride_LOD0.31e22cc3_0", shader=shader)
            i = trace.index(("draw", filename, "300,17,-2"))
            self.assertEqual(trace[i-1], ("ps-t0", "ResourceObject"))
            self.assertEqual(trace[i+1], ("ps-t0", "ResourceOriginal"))
            off, _ = simulate(sections, "TextureOverride_LOD0.31e22cc3_0", shader=shader, variant=0)
            self.assertFalse(any(e[0] == "draw" for e in off))
            self.assertEqual(off[-1], ("vs-t118", "null"))

    def test_markers_only_identify_and_models_have_independent_maps(self):
        _, builder = build([make_model(), make_model("e92032c5")])
        sections = parse_sections(builder)
        for name, lines in sections.items():
            if name.startswith("ShaderOverride"):
                self.assertTrue(all(x.startswith(("hash =", "allow_duplicate_hash =", "filter_index =")) for x in lines))
        trace, _ = simulate(sections, "TextureOverride_LOD0.e92032c5_0")
        self.assertIn(("vs-t118", "ref Resourcee92032c5YYSLSClothMap"), trace)

    def test_full_export_packages_all_assets_and_map(self):
        # All output lives in the repository tmp directory, outside live Mods.
        output_root = ROOT / "tmp"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as directory:
            CONFIG.output = directory
            exporter, _ = build([make_model()])
            exporter.export()
            output = Path(directory)
            for _, _, filename, _ in CLOTH.CLOTH_SHADER_VARIANTS:
                self.assertEqual((output / filename).read_bytes(),
                                 (ROOT / "resources" / filename).read_bytes())
            text = (output / "fixture.ini").read_text()
            self.assertIn("[Resource31e22cc3YYSLSClothMap]", text)
            self.assertIn("format = R32_UINT", text)
            self.assertNotIn("vs-t119", text)
            self.assertNotIn("no_cloth.hlsl", text)


if __name__ == "__main__":
    unittest.main()
