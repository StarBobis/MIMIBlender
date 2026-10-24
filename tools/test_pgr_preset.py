"""Blender-free regression checks for the PGR game preset.

Two things must stay true and are cheap to break with a later edit:

1. PGR owns the mod generation logic.  Its exporter is an independent copy
   of the Naraka exporter (own file, own class, own shape key pipeline), so
   the registry must never point PGR back at Naraka's class.
2. Nothing Naraka-branded leaks into a PGR mod.  The copied pipeline is
   allowed to be byte-identical, but every generated name (command lists,
   the "run = ..." lines) must belong to PGR, and the Naraka pipeline must
   keep producing its own names.

The test never imports Blender: the bpy-dependent imports are replaced with
the same light stubs the Naraka shape key test uses, and the registry is
read straight from the source with ast, so only pure Python runs here.
"""

import ast
import importlib.util
import os
import sys
import tempfile
import types

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The Naraka shape key test ships the stub harness for exactly this kind of
# pipeline (global config paths, texture settings, ini helper).  Reusing it
# keeps one set of fakes for both presets: if a stub starts lying about the
# real contract, both suites fail together instead of drifting apart.
SUPPORT_PATH = os.path.join(ROOT, "tools", "test_naraka_shapekeys.py")
SUPPORT_MODULE_NAME = "naraka_shapekey_test_support"

# Synthetic package name used to load addon modules by file path, so the
# real addon package (which imports bpy) is never touched.  The name comes
# from the shared stub harness; the PGR test only adds a games.pgr entry.
TEST_PKG = "naraka_shapekey_test_pkg"


def load_file_module(module_name: str, file_path: str):
    """Load one python file as a module with the given dotted name."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_stub_support():
    """Load the shared stub harness shipped with the Naraka shape key test."""
    return load_file_module(SUPPORT_MODULE_NAME, SUPPORT_PATH)


def read_python_source(relative_path: str) -> str:
    """Read one addon source file as text (used for keyword guards)."""
    with open(os.path.join(ROOT, relative_path), "r", encoding="utf-8") as source_file:
        return source_file.read()


def parse_python_source(relative_path: str) -> ast.Module:
    """Parse one addon source file without importing it."""
    return ast.parse(read_python_source(relative_path))


def exec_logic_name_class():
    """Execute the real LogicName class body from common/global_config.py.

    The module itself imports bpy, so only the class definition is taken
    from the module body and executed on its own.  The class contains plain
    strings and classmethods, so it needs no Blender namespace.
    """
    module = parse_python_source(os.path.join("common", "global_config.py"))
    logic_name_class = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "LogicName"
    )
    namespace = {}
    exec(compile(ast.Module(body=[logic_name_class], type_ignores=[]), "global_config.py", "exec"), namespace)
    return namespace["LogicName"]


def exec_exporter_registry(logic_name_class):
    """Execute the real exporter mapping and lookup from games/__init__.py.

    Every exporter class value is replaced by a uniquely named mock so the
    test can prove which class PGR resolves to without importing bpy.
    """
    module = parse_python_source(os.path.join("games", "__init__.py"))
    mapping = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_LOGIC_EXPORTER_DICT"
                for target in node.targets)
    )
    lookup = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_exporter_class"
    )
    # LogicName is the real class, so a typo in a mapping key breaks here.
    namespace = {"LogicName": logic_name_class}
    for value in mapping.value.values:
        namespace.setdefault(value.id, type(value.id, (), {}))
    exec(compile(ast.Module(body=[mapping, lookup], type_ignores=[]), "games/__init__.py", "exec"), namespace)
    return namespace


def find_pgr_exporter_class():
    """Return the single class definition of games/pgr/exporter.py."""
    module = parse_python_source(os.path.join("games", "pgr", "exporter.py"))
    class_nodes = [node for node in module.body if isinstance(node, ast.ClassDef)]
    return module, class_nodes


def imported_module_names(module: ast.Module) -> list:
    """Collect every dotted module name imported by one parsed file."""
    imported = []
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    return imported


def build_shapekey_dict():
    """One hotkey shape key plus one key without a hotkey."""
    from types import SimpleNamespace
    return {
        "Smile": SimpleNamespace(key_name="$shapekey0", initialize_value=0, initialize_vk_str="F1", comment=""),
        "Blink": SimpleNamespace(key_name="$shapekey1", initialize_value=0, initialize_vk_str="", comment=""),
    }


def build_section_draw_call(first_index: int, cross_render_at_submesh: str = ""):
    """One fake draw call that renders itself with a stable drawindexed line.

    The shared drawindexed helper calls get_drawindexed_str() on every draw
    call, so the fake implements exactly that contract and the emitted line
    stays easy to look for in the generated INI.
    """
    from types import SimpleNamespace
    return SimpleNamespace(
        cross_render_at_submesh=cross_render_at_submesh,
        get_drawindexed_str=lambda offsets=None: "drawindexed = 3," + str(first_index) + ",0",
    )


def build_section_submesh(submesh_name: str, match_first_index: int, draw_call_list: list):
    """One fake Submesh with the identity fields the IB sections read."""
    from types import SimpleNamespace
    return SimpleNamespace(
        submesh_name=submesh_name,
        display_str=submesh_name,
        match_first_index=match_first_index,
        drawcall_model_list=draw_call_list,
    )


def build_section_drawib_model(support, draw_ib: str, alias: str, submesh_list: list, shapekey_names=None):
    """One fake DrawIB carrying everything the copied section builders read.

    The real Naraka/PGR models expose a lot of small accessors; the fake
    implements the same names so the production code runs unmodified.
    """
    model = support.build_fake_drawib_model(draw_ib, 1000, shapekey_names or [])
    model.draw_ib_alias = alias
    # The shared shape key fake only needs the Position stride; the resource
    # builders write one buffer per category, so the other strides are set
    # to the values a real PGR capture carries (40 / 8 / 32 bytes).
    model.d3d11_game_type.CategoryStrideDict["Texcoord"] = 8
    model.d3d11_game_type.CategoryStrideDict["Blend"] = 32
    model.submesh_model_list = submesh_list
    model.submesh_ib_dict = {submesh.submesh_name: b"ib" for submesh in submesh_list}
    model.obj_name_draw_offset = {}
    model.vertex_limit_hash = "4ccff098"
    model.get_category_buffer_filename = lambda category: "LOD0." + draw_ib + "-" + category + ".buf"
    model.get_submesh_ib_resource_name = lambda submesh: "Resource" + draw_ib + "_" + submesh.submesh_name + "_IB"
    model.get_submesh_texture_override_suffix = lambda submesh: draw_ib + "_" + submesh.submesh_name
    # No texture marks: the resource texture section stays empty here.
    model.get_submesh_texture_markup_info_list = lambda submesh: []
    # The real key is the Submesh identity; normalizing the dashes keeps the
    # backup resource names readable in the assertions below.
    model.get_submesh_unique_key = lambda submesh: submesh.submesh_name.replace("-", "_")
    model.apply_drawib_alias = lambda: None
    return model


class FakeBlueprintModel:
    """Minimal blueprint: only the two hooks the exporter constructor calls."""

    def __init__(self, drawib_model_list: list):
        self.drawib_model_list = drawib_model_list
        # No branch keys, so the closing key sections stay out of this check.
        self.keyname_mkey_dict = {}

    def parse_drawib_model_list(self, combine_ib=False):
        # The exporter always asks for one model per DrawIB.
        return list(self.drawib_model_list)


def extract_ini_block(ini_text: str, section_header: str) -> str:
    """Return the text of one INI section (from its header to the next one)."""
    start_index = ini_text.find(section_header)
    if start_index < 0:
        return ""
    next_index = ini_text.find("\n[", start_index + len(section_header))
    if next_index < 0:
        return ini_text[start_index:]
    return ini_text[start_index:next_index]


def main():
    failures = []

    def check(condition, message):
        # Report every failure so one regression never hides the next one.
        if not condition:
            failures.append(message)
            print("FAIL: " + message)
        else:
            print("OK:   " + message)

    # ------------------------------------------------------------------
    # 1. Preset constant and exporter registry
    # ------------------------------------------------------------------
    logic_name_class = exec_logic_name_class()
    check(getattr(logic_name_class, "PGR", "") == "PGR", "LogicName.PGR is the PGR preset code")
    check(getattr(logic_name_class, "Naraka", "") == "Naraka", "LogicName.Naraka still exists")
    check(logic_name_class.PGR != logic_name_class.Naraka, "PGR and Naraka stay separate presets")

    registry = exec_exporter_registry(logic_name_class)
    pgr_exporter = registry["get_exporter_class"](logic_name_class.PGR)
    naraka_exporter = registry["get_exporter_class"](logic_name_class.Naraka)
    check(pgr_exporter is not None, "PGR resolves to a registered exporter")
    check(naraka_exporter is not None, "Naraka still resolves to its own exporter")
    check(pgr_exporter is not naraka_exporter, "PGR does not reuse the Naraka exporter class")
    check(getattr(pgr_exporter, "__name__", "") == "PGRExporter", "PGR resolves to PGRExporter")

    # ------------------------------------------------------------------
    # 2. The PGR exporter is an independent copy, not an alias
    # ------------------------------------------------------------------
    pgr_module, pgr_class_nodes = find_pgr_exporter_class()
    check(len(pgr_class_nodes) == 1, "games/pgr/exporter.py defines exactly one exporter class")
    if pgr_class_nodes:
        pgr_class = pgr_class_nodes[0]
        base_names = [getattr(base, "id", "") for base in pgr_class.bases]
        check(pgr_class.name == "PGRExporter", "the class is named PGRExporter")
        # Subclassing the shared skeleton is fine; inheriting Naraka's
        # exporter would defeat the whole point of the copy.
        check(base_names == ["StandardExporter"], "the only base class is the shared StandardExporter")
        fanout_methods = [node.name for node in pgr_class.body
                          if isinstance(node, ast.FunctionDef) and node.name.startswith("add_")]
        check("add_pgr_cs_texture_override_ib_sections" in fanout_methods,
              "the IB override section builder is PGR-branded")

    # No import may reach into the Naraka package: a later change here would
    # silently reintroduce inheritance through the back door.
    imports = imported_module_names(pgr_module)
    check(not [name for name in imports if "naraka" in name.lower()],
          "games/pgr/exporter.py never imports the Naraka package")
    check("COPY" in ast.get_docstring(pgr_module, clean=False),
          "the module docstring records that this file is a copy")

    # The copied source must not keep Naraka-branded identifiers or user
    # visible strings either.  The docstring and the inline provenance
    # comments are allowed to name the original file, but no runtime name
    # may stay Naraka-branded (that would leak into errors and the INI).
    pgr_source = read_python_source(os.path.join("games", "pgr", "exporter.py"))
    module_docstring = ast.get_docstring(pgr_module, clean=False) or ""
    pgr_code_text = pgr_source.replace(module_docstring, "", 1)
    check("add_naraka" not in pgr_code_text, "no add_naraka_* section builder is left behind")
    check('"Naraka' not in pgr_code_text, "no Naraka-branded runtime string is left behind")

    # The Naraka exporter keeps its own class, so both can diverge freely.
    naraka_class_nodes = [node for node in parse_python_source(os.path.join("games", "naraka", "exporter.py")).body
                          if isinstance(node, ast.ClassDef)]
    check([node.name for node in naraka_class_nodes] == ["Exporter"],
          "the Naraka exporter keeps its unchanged class name")

    # ------------------------------------------------------------------
    # 3. Preset plumbing: the places a Z-up GPU-pre-skinning preset needs
    # ------------------------------------------------------------------
    # Without these three entries PGR would export unrotated or be rejected
    # before any INI is written, so they are cheap guards against a merge
    # that only takes part of the preset.
    for relative_path, reason in (
        (os.path.join("model", "drawib_model.py"), "position frame exports are allowed"),
        (os.path.join("model", "submesh_model.py"), "the export keeps game space"),
        (os.path.join("common", "mesh_create_helper.py"), "the import cancels the axis conversion"),
    ):
        check("LogicName.PGR" in read_python_source(relative_path),
              relative_path + " knows the PGR preset (" + reason + ")")

    # ------------------------------------------------------------------
    # 4. Generated INI: PGR names only, no Naraka leakage
    # ------------------------------------------------------------------
    support = load_stub_support()
    temp_dir = tempfile.mkdtemp(prefix="pgr_preset_test_")
    mod_folder_path = os.path.join(temp_dir, "mod", "")
    os.makedirs(mod_folder_path, exist_ok=True)

    support.ensure_parent_packages()
    # The harness only registered the packages its own test needed; the PGR
    # package must exist before the relative imports of shapekeys.py resolve.
    sys.modules[TEST_PKG + ".games.pgr"] = types.ModuleType(TEST_PKG + ".games.pgr")
    support.install_global_config_stub(mod_folder_path)
    support.install_sections_module_stubs()

    shapekeyname_mkey_dict = build_shapekey_dict()
    support.install_blueprint_export_helper_stub(shapekeyname_mkey_dict)

    # The ini builder is pure python, load the real one.
    m_ini_builder = support.load_module_by_path(
        TEST_PKG + ".common.m_ini_builder",
        os.path.join(ROOT, "common", "m_ini_builder.py"),
    )
    pgr_shapekeys = support.load_module_by_path(
        TEST_PKG + ".games.pgr.shapekeys",
        os.path.join(ROOT, "games", "pgr", "shapekeys.py"),
    )
    naraka_shapekeys = support.load_module_by_path(
        TEST_PKG + ".games.naraka.shapekeys",
        os.path.join(ROOT, "games", "naraka", "shapekeys.py"),
    )
    sections = support.load_module_by_path(
        TEST_PKG + ".games.base.sections",
        os.path.join(ROOT, "games", "base", "sections.py"),
    )

    # The two presets must own distinct compute command list names, even
    # though the pipelines are copies today.
    pgr_command_name = pgr_shapekeys.get_compute_command_list_name(0)
    naraka_command_name = naraka_shapekeys.get_compute_command_list_name(0)
    check(pgr_command_name == "CustomShaderComputeShapesPGR1",
          "the PGR command list is numbered with its own game name")
    check(naraka_command_name == "CustomShaderComputeShapesNaraka1",
          "the Naraka command list keeps its historic name")
    check(pgr_command_name != naraka_command_name, "the two presets never share command list names")

    # The real PGR capture uses a 40-byte Position category
    # (GPU_P12_N12_TA16_*), which is exactly what Shapes.hlsl reads.
    cloth_model = support.build_fake_drawib_model("65b9cf5a", 8168, ["Smile", "Blink"])
    body_model = support.build_fake_drawib_model("d58050d1", 5517, ["Smile"])
    drawib_model_list = [cloth_model, body_model]
    drawib_dict = {model.draw_ib: model for model in drawib_model_list}

    usable_list = pgr_shapekeys.collect_usable_drawib_model_list(drawib_model_list)
    check(len(usable_list) == 2, "both DrawIBs accept the 40-byte Position layout")

    ini_builder = m_ini_builder.M_IniBuilder()
    for drawib_model in drawib_model_list:
        run_name = ""
        if drawib_model in usable_list:
            run_name = pgr_shapekeys.get_compute_command_list_name(usable_list.index(drawib_model))
        sections.add_unity_cs_texture_override_vb_sections(
            ini_builder=ini_builder,
            drawib_model=drawib_model,
            blueprint_model=types.SimpleNamespace(keyname_mkey_dict={}),
            position_pre_dispatch_run=run_name,
        )

    pgr_shapekeys.add_pgr_shapekey_ini_sections(
        ini_builder,
        drawib_dict,
        usable_drawib_model_list=usable_list,
    )

    ini_path = os.path.join(temp_dir, "test_mod.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as ini_file:
        ini_text = ini_file.read()

    # The shape key compute is hooked into the Position VB override, before
    # the skinning re-dispatch, and the Texcoord override stays untouched.
    cloth_position_block = extract_ini_block(ini_text, "[TextureOverride_VB_65b9cf5a_Cloth_Position]")
    check("run = " + pgr_command_name in cloth_position_block,
          "the Position override runs the PGR shape key command list")
    check(cloth_position_block.find("run = " + pgr_command_name) < cloth_position_block.find("dispatch = "),
          "the run line comes before the skinning dispatch")
    check("run = " not in extract_ini_block(ini_text, "[TextureOverride_VB_65b9cf5a_Cloth_Texcoord]"),
          "the Texcoord override stays untouched")

    # Raw staging: a copy recreates the destination from the source
    # descriptor, so the raw flags must REPLACE the structured ones.
    for model in usable_list:
        prefix = "Resource" + model.draw_ib
        raw_block = extract_ini_block(ini_text, "[" + prefix + "PositionComputed]")
        check("type = ByteAddressBuffer" in raw_block, model.draw_ib + " declares raw staging")
        check("misc_flags = buffer_allow_raw_views" in raw_block,
              model.draw_ib + " drops the inherited structured flag")
        check(prefix + "Position = ref " + prefix + "PositionComputed" in ini_text,
              model.draw_ib + " binds the raw result by reference")

    # Hotkeys follow the configured keys, not the DrawIBs.
    check("[Key_ShapeKey_Smile]" in ini_text, "Smile keeps its cycle key section")
    check("[Key_ShapeKey_Blink]" not in ini_text, "Blink has no hotkey and no key section")

    # The one leak that matters: a PGR mod must not mention Naraka at all.
    check("Naraka" not in ini_text, "no Naraka name leaks into the generated PGR INI")

    # The shared compute shader is copied next to the generated INI.
    check(os.path.exists(os.path.join(mod_folder_path, "Shapes.hlsl")),
          "Shapes.hlsl is copied into the mod folder")

    # ------------------------------------------------------------------
    # 5. The copied section builders run end to end
    # ------------------------------------------------------------------
    # A copy is only worth its own file if it still assembles a complete
    # DrawIB section set.  The fake blueprint below drives the real
    # PGRExporter, so a dropped or mistyped section shows up here instead of
    # in a broken mod.
    helper_class = sys.modules[TEST_PKG + ".common.m_ini_helper"].M_IniHelper
    # The shared stub only provides what the shape key test needed; these two
    # helpers are what the IB/resource section builders call.
    helper_class.get_drawindexed_str_list = staticmethod(
        lambda draw_call_list, obj_name_draw_offset_dict=None: [
            draw_call.get_drawindexed_str(obj_name_draw_offset_dict)
            for draw_call in draw_call_list
        ]
    )
    helper_class.add_object_texture_binding_resource_sections = staticmethod(lambda **kwargs: None)

    standard_exporter = support.load_module_by_path(
        TEST_PKG + ".games.base.standard_exporter",
        os.path.join(ROOT, "games", "base", "standard_exporter.py"),
    )
    pgr_exporter_module = support.load_module_by_path(
        TEST_PKG + ".games.pgr.exporter",
        os.path.join(ROOT, "games", "pgr", "exporter.py"),
    )

    # Host Submesh with one ordinary draw call, guest Submesh whose only draw
    # call is marked to render inside the host.  The guest also carries a
    # shape key, so its Position override has to run the shape command list.
    host_submesh = build_section_submesh("LOD0-100-0", 0, [build_section_draw_call(100)])
    guest_submesh = build_section_submesh(
        "LOD0-200-0", 3, [build_section_draw_call(200, cross_render_at_submesh="LOD0-100-0")]
    )
    host_model = build_section_drawib_model(support, "65b9cf5a", "Cloth", [host_submesh])
    guest_model = build_section_drawib_model(support, "d58050d1", "Body", [guest_submesh], ["Smile"])

    exporter = pgr_exporter_module.PGRExporter(FakeBlueprintModel([host_model, guest_model]))
    section_builder = m_ini_builder.M_IniBuilder()
    for drawib_model in (host_model, guest_model):
        exporter.add_drawib_sections(ini_builder=section_builder, drawib_model=drawib_model)

    section_ini_path = os.path.join(temp_dir, "section_test.ini")
    section_builder.save_to_file(section_ini_path)
    with open(section_ini_path, "r", encoding="utf-8") as ini_file:
        section_ini_text = ini_file.read()

    # VertexLimitRaise: the game's own Position VB has to grow for the mod.
    vertex_limit_block = extract_ini_block(section_ini_text, "[TextureOverride_65b9cf5a_Cloth_VertexLimitRaise]")
    check("override_byte_stride = 40" in vertex_limit_block,
          "the Position VB is raised with the 40-byte stride")
    check("override_vertex_count = 1000" in vertex_limit_block,
          "the raised VB holds every exported vertex")
    check("uav_byte_stride = 4" in vertex_limit_block,
          "the compute shader UAV is declared with its own stride")

    # Compute path: Position/Blend are raw byte-address buffers, and the
    # Position override re-dispatches the game's skinning compute shader.
    position_resource_block = extract_ini_block(section_ini_text, "[Resourced58050d1Position]")
    check("type = ByteAddressBuffer" in position_resource_block,
          "the Position resource is a raw buffer for GPU pre-skinning")
    guest_position_override = extract_ini_block(section_ini_text, "[TextureOverride_VB_d58050d1_Body_Position]")
    check("cs-t0 = Resourced58050d1Position" in guest_position_override,
          "the Position override feeds the modded Position buffer to skinning")
    check("handling = skip" in guest_position_override, "the original Position bind is skipped")
    check("dispatch = 17,1,1" in guest_position_override,
          "1000 vertices are dispatched with one extra group")
    check("run = " + pgr_command_name in guest_position_override,
          "the shape key command list runs from the guest Position override")

    # IB re-emit: the guest's crossed draw call leaves its own section.
    guest_ib_block = extract_ini_block(section_ini_text, "[TextureOverride_d58050d1_LOD0-200-0]")
    check("drawindexed = 3,200,0" not in guest_ib_block,
          "a cross-IB guest draw call is not drawn in its own section")
    check("Resource_LOD0_200_0_BK_VB0 = ref vb0" in guest_ib_block,
          "the guest captures its live vb0 binding")
    check("Resource_LOD0_200_0_BK_VB1 = ref vb1" in guest_ib_block,
          "the guest captures its live vb1 binding")

    # The host re-emits the guest IB/VB and its draw call after its own.
    host_ib_block = extract_ini_block(section_ini_text, "[TextureOverride_65b9cf5a_LOD0-100-0]")
    check("; Cross-IB:" in host_ib_block, "the host section announces the cross-IB render")
    check("ib = Resourced58050d1_LOD0-200-0_IB" in host_ib_block,
          "the host binds the guest index buffer")
    check("vb0 = Resource_LOD0_200_0_BK_VB0" in host_ib_block,
          "the host rebinds the guest vertex buffer")
    check(host_ib_block.find("drawindexed = 3,100,0") < host_ib_block.find("drawindexed = 3,200,0"),
          "the host draws its own geometry before the guest's")

    # Both backup resources must be declared, otherwise the ref lines fail.
    check("[Resource_LOD0_200_0_BK_VB0]" in section_ini_text
          and "[Resource_LOD0_200_0_BK_VB1]" in section_ini_text,
          "the cross-IB backup resources are declared")

    # Still no Naraka name anywhere in the assembled sections.
    check("Naraka" not in section_ini_text, "the copied sections stay PGR-branded")

    # ------------------------------------------------------------------
    # 6. Unsupported layouts are skipped, not silently exported
    # ------------------------------------------------------------------
    odd_model = support.build_fake_drawib_model("deadbeef", 100, ["Smile"], extra_position_element=True)
    odd_builder = m_ini_builder.M_IniBuilder()
    pgr_shapekeys.add_pgr_shapekey_ini_sections(odd_builder, {"deadbeef": odd_model})
    check(len(odd_builder.ini_section_list) == 0,
          "an unsupported Position layout produces no shape key sections")

    print()
    if failures:
        print(str(len(failures)) + " check(s) failed")
        return 1
    print("ALL PGR PRESET CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
