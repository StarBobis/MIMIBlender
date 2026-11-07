"""Blender-free regression checks for the GF2 cross-IB export.

GF2 is the second preset that owns the cross-IB sections, and it differs from
Naraka in one way that matters for correctness: its GPU-pre-skinning types
keep the blend stream in vb2, so a guest whose backup only covered vb0/vb1
would be deformed with the host's bone weights.  These checks build the same
fake models the PGR/Naraka suites use, drive the real exporter and read the
generated INI text.

The test never imports Blender: it reuses the light stub harness shipped with
test_naraka_shapekeys.py and loads the addon modules by file path.

Run with:
    python tools/test_gf2_cross_ib.py
"""

import ast
import os
import sys
import tempfile
import types

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The Naraka shape key test ships the stub harness for exactly this kind of
# pipeline (global config paths, texture settings, ini helper).  Reusing it
# keeps one set of fakes for every preset suite.
SUPPORT_PATH = os.path.join(ROOT, "tools", "test_naraka_shapekeys.py")
SUPPORT_MODULE_NAME = "gf2_cross_ib_test_support"

# Synthetic package name used to load addon modules by file path, so the
# real addon package (which imports bpy) is never touched.  The value is
# replaced with the harness's own package name in main(), so the two can
# never drift apart.
TEST_PKG = "gf2_cross_ib_test_pkg"


def load_file_module(module_name: str, file_path: str):
    """Load one python file as a module with the given dotted name."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def exec_logic_name_class():
    """Execute the real LogicName class body from common/global_config.py.

    The module itself imports bpy, so only the class definition is taken from
    the module body and executed on its own.  The support list is built from
    these exact values, so a typo in a preset name breaks here.
    """
    with open(os.path.join(ROOT, "common", "global_config.py"), "r", encoding="utf-8") as source_file:
        tree = ast.parse(source_file.read())
    logic_name_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "LogicName"
    )
    namespace = {}
    exec(compile(ast.Module(body=[logic_name_class], type_ignores=[]), "global_config.py", "exec"), namespace)
    return namespace["LogicName"]


def build_gf2_game_type(gpu_preskinning: bool):
    """One fake GF2 game type, either the GPU or the CPU-drawn shape.

    The GPU shape is the verified capture layout: vb0 40B, vb1 28B, vb2 32B,
    with BLEND drawn by the Position category (CategoryDrawCategoryMap) and
    the blend stream in its own slot.  The CPU shape puts everything in vb0.
    """
    if not gpu_preskinning:
        return types.SimpleNamespace(
            GPU_PreSkinning=False,
            CategoryStrideDict={"Position": 40},
            OrderedCategoryNameList=["Position"],
            CategoryDrawCategoryDict={"Position": "Position"},
            CategoryExtractSlotDict={"Position": "vb0"},
        )
    return types.SimpleNamespace(
        GPU_PreSkinning=True,
        CategoryStrideDict={"Position": 40, "Texcoord": 28, "Blend": 32},
        OrderedCategoryNameList=["Position", "Texcoord", "Blend"],
        # BLEND is read from the point-list pass, so it rides the Position
        # section and lands in vb2 -- the slot a Naraka-only backup misses.
        CategoryDrawCategoryDict={"Position": "Position", "Texcoord": "Texcoord", "Blend": "Position"},
        CategoryExtractSlotDict={"Position": "vb0", "Texcoord": "vb1", "Blend": "vb2"},
    )


def build_draw_call(first_index: int, cross_render_at_submesh: str = ""):
    """One fake draw call that renders itself with a stable drawindexed line."""
    return types.SimpleNamespace(
        cross_render_at_submesh=cross_render_at_submesh,
        get_drawindexed_str=lambda offsets=None: "drawindexed = 3," + str(first_index) + ",0",
    )


def build_submesh(submesh_name: str, match_first_index: int, draw_call_list: list):
    """One fake Submesh with the identity fields the IB sections read."""
    return types.SimpleNamespace(
        submesh_name=submesh_name,
        display_str=submesh_name,
        match_first_index=match_first_index,
        drawcall_model_list=draw_call_list,
    )


def build_drawib_model(support, draw_ib: str, alias: str, submesh_list: list, gpu_preskinning=True):
    """One fake DrawIB carrying everything the copied section builders read."""
    model = support.build_fake_drawib_model(draw_ib, 1000, [])
    model.draw_ib_alias = alias
    model.d3d11_game_type = build_gf2_game_type(gpu_preskinning)
    model.submesh_model_list = submesh_list
    model.submesh_ib_dict = {submesh.submesh_name: b"ib" for submesh in submesh_list}
    model.obj_name_draw_offset = {}
    model.vertex_limit_hash = "4ccff098"
    model.get_category_buffer_filename = lambda category: "LOD0." + draw_ib + "-" + category + ".buf"
    model.get_submesh_ib_resource_name = lambda submesh: "Resource" + draw_ib + "_" + submesh.submesh_name + "_IB"
    model.get_submesh_texture_override_suffix = lambda submesh: draw_ib + "_" + submesh.submesh_name
    # No texture marks: the texture sections stay empty here.
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
    # 1. The support list decides which presets may export cross-IB
    # ------------------------------------------------------------------
    global TEST_PKG
    logic_name_class = exec_logic_name_class()
    support = load_file_module(SUPPORT_MODULE_NAME, SUPPORT_PATH)
    # The stub harness registers its own package tree, so adopt its name
    # instead of guessing it.
    TEST_PKG = support.TEST_PKG
    support.ensure_parent_packages()
    # The shared stub only registers the packages its own test needed; GF2
    # must exist before the relative imports of its exporter resolve.
    sys.modules[TEST_PKG + ".games.gf2"] = types.ModuleType(TEST_PKG + ".games.gf2")

    temp_dir = tempfile.mkdtemp(prefix="gf2_cross_ib_test_")
    mod_folder_path = os.path.join(temp_dir, "mod", "")
    os.makedirs(mod_folder_path, exist_ok=True)
    support.install_global_config_stub(mod_folder_path)
    support.install_sections_module_stubs()

    # The support module resolves LogicName from the stubbed global config.
    config_stub = sys.modules[TEST_PKG + ".common.global_config"]
    config_stub.LogicName = logic_name_class

    cross_ib_support = support.load_module_by_path(
        TEST_PKG + ".common.cross_ib_support",
        os.path.join(ROOT, "common", "cross_ib_support.py"),
    )
    check(cross_ib_support.supports_cross_ib(logic_name_class.GF2),
          "GF2 is listed as a cross-IB preset")
    check(cross_ib_support.supports_cross_ib(logic_name_class.Naraka),
          "Naraka stays a cross-IB preset")
    check(not cross_ib_support.supports_cross_ib(logic_name_class.GIMI),
          "a preset without the exporter code is not offered")
    check(cross_ib_support.CROSS_IB_ERROR_PREFIX == "Cross-IB Render: ",
          "every preset reports with the same diagnostic prefix")

    # ------------------------------------------------------------------
    # 2. The exporter runs end to end
    # ------------------------------------------------------------------
    m_ini_builder = support.load_module_by_path(
        TEST_PKG + ".common.m_ini_builder",
        os.path.join(ROOT, "common", "m_ini_builder.py"),
    )
    support.load_module_by_path(
        TEST_PKG + ".common.gimi_texture_slots",
        os.path.join(ROOT, "common", "gimi_texture_slots.py"),
    )
    sections = support.load_module_by_path(
        TEST_PKG + ".games.base.sections",
        os.path.join(ROOT, "games", "base", "sections.py"),
    )

    # The shared stub only provides what the shape key test needed; these two
    # helpers are what the IB and texture section builders call.
    helper_class = sys.modules[TEST_PKG + ".common.m_ini_helper"].M_IniHelper
    helper_class.get_drawindexed_str_list = staticmethod(
        lambda draw_call_list, obj_name_draw_offset_dict=None: [
            draw_call.get_drawindexed_str(obj_name_draw_offset_dict)
            for draw_call in draw_call_list
        ]
    )
    helper_class.add_object_texture_binding_resource_sections = staticmethod(lambda **kwargs: None)

    support.load_module_by_path(
        TEST_PKG + ".games.base.standard_exporter",
        os.path.join(ROOT, "games", "base", "standard_exporter.py"),
    )
    gf2_exporter_module = support.load_module_by_path(
        TEST_PKG + ".games.gf2.exporter",
        os.path.join(ROOT, "games", "gf2", "exporter.py"),
    )

    # Host Submesh with one ordinary draw call, guest Submesh whose only draw
    # call is marked to render inside the host.
    host_submesh = build_submesh("LOD0-100-0", 0, [build_draw_call(100)])
    guest_submesh = build_submesh(
        "LOD0-200-0", 3, [build_draw_call(200, cross_render_at_submesh="LOD0-100-0")]
    )
    host_model = build_drawib_model(support, "65b9cf5a", "Cloth", [host_submesh])
    guest_model = build_drawib_model(support, "d58050d1", "Body", [guest_submesh])

    exporter = gf2_exporter_module.GF2Exporter(FakeBlueprintModel([host_model, guest_model]))
    section_builder = m_ini_builder.M_IniBuilder()
    for drawib_model in (host_model, guest_model):
        exporter.add_drawib_sections(ini_builder=section_builder, drawib_model=drawib_model)

    section_ini_path = os.path.join(temp_dir, "section_test.ini")
    section_builder.save_to_file(section_ini_path)
    with open(section_ini_path, "r", encoding="utf-8") as ini_file:
        ini_text = ini_file.read()

    # Every slot the VB overrides replace is bound from the mod's resources.
    position_block = extract_ini_block(ini_text, "[TextureOverride_VB_65b9cf5a_Cloth_Position]")
    check("vb0 = Resource65b9cf5aPosition" in position_block,
          "the Position override replaces vb0")
    check("vb2 = Resource65b9cf5aBlend" in position_block,
          "the blend stream is replaced in vb2 for GF2")
    texcoord_block = extract_ini_block(ini_text, "[TextureOverride_VB_65b9cf5a_Cloth_Texcoord]")
    check("vb1 = Resource65b9cf5aTexcoord" in texcoord_block,
          "the Texcoord override replaces vb1")

    # Guest: the crossed draw leaves its own section, and every slot of the
    # DrawIB is captured while the mod's buffers are still bound.
    guest_ib_block = extract_ini_block(ini_text, "[TextureOverride_d58050d1_LOD0-200-0]")
    check("drawindexed = 3,200,0" not in guest_ib_block,
          "a cross-IB guest draw call is not drawn in its own section")
    for slot_name in ("VB0", "VB1", "VB2"):
        check("Resource_LOD0_200_0_BK_" + slot_name + " = ref vb" + slot_name[2] in guest_ib_block,
              "the guest captures its live vb" + slot_name[2] + " binding")

    # Host: re-emits the guest with its own index buffer and restored VB.
    host_ib_block = extract_ini_block(ini_text, "[TextureOverride_65b9cf5a_LOD0-100-0]")
    check("; Cross-IB:" in host_ib_block, "the host section announces the cross-IB render")
    check("ib = Resourced58050d1_LOD0-200-0_IB" in host_ib_block,
          "the host binds the guest index buffer")
    for slot_name in ("VB0", "VB1", "VB2"):
        check("vb" + slot_name[2] + " = Resource_LOD0_200_0_BK_" + slot_name in host_ib_block,
              "the host restores the guest vb" + slot_name[2])
    check(host_ib_block.find("drawindexed = 3,100,0") < host_ib_block.find("drawindexed = 3,200,0"),
          "the host draws its own geometry before the guest's")

    # Every ref target must be declared, otherwise the backup lines fail.
    for slot_name in ("VB0", "VB1", "VB2"):
        check("[Resource_LOD0_200_0_BK_" + slot_name + "]" in ini_text,
              "the cross-IB backup resource " + slot_name + " is declared")

    check("Naraka" not in ini_text, "no Naraka name leaks into the generated GF2 INI")

    # ------------------------------------------------------------------
    # 3. CPU-drawn types only own one stream
    # ------------------------------------------------------------------
    cpu_host_submesh = build_submesh("LOD0-300-0", 0, [build_draw_call(300)])
    cpu_guest_submesh = build_submesh(
        "LOD0-400-0", 6, [build_draw_call(400, cross_render_at_submesh="LOD0-300-0")]
    )
    cpu_host_model = build_drawib_model(support, "aa000001", "PropA", [cpu_host_submesh], gpu_preskinning=False)
    cpu_guest_model = build_drawib_model(support, "aa000002", "PropB", [cpu_guest_submesh], gpu_preskinning=False)

    cpu_exporter = gf2_exporter_module.GF2Exporter(FakeBlueprintModel([cpu_host_model, cpu_guest_model]))
    cpu_builder = m_ini_builder.M_IniBuilder()
    for drawib_model in (cpu_host_model, cpu_guest_model):
        cpu_exporter.add_drawib_sections(ini_builder=cpu_builder, drawib_model=drawib_model)

    cpu_ini_path = os.path.join(temp_dir, "cpu_test.ini")
    cpu_builder.save_to_file(cpu_ini_path)
    with open(cpu_ini_path, "r", encoding="utf-8") as ini_file:
        cpu_ini_text = ini_file.read()

    cpu_guest_block = extract_ini_block(cpu_ini_text, "[TextureOverride_aa000002_LOD0-400-0]")
    check("Resource_LOD0_400_0_BK_VB0 = ref vb0" in cpu_guest_block,
          "a CPU-drawn guest still captures vb0")
    check("BK_VB1" not in cpu_ini_text and "BK_VB2" not in cpu_ini_text,
          "a single-stream type backs up nothing it does not bind")

    # ------------------------------------------------------------------
    # 4. A host outside the export fails instead of writing dead sections
    # ------------------------------------------------------------------
    orphan_guest_submesh = build_submesh(
        "LOD0-500-0", 9, [build_draw_call(500, cross_render_at_submesh="LOD0.missing-0")]
    )
    orphan_model = build_drawib_model(support, "bb000001", "Orphan", [orphan_guest_submesh])
    try:
        gf2_exporter_module.GF2Exporter(FakeBlueprintModel([orphan_model]))
    except ValueError as error:
        check("Cross-IB Render: " in str(error) and "does not exist in this export" in str(error),
              "an unknown host Submesh aborts the export with the shared prefix")
    else:
        check(False, "an unknown host Submesh must abort the export")

    print()
    if failures:
        print(str(len(failures)) + " check(s) failed")
        return 1
    print("ALL GF2 CROSS-IB CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
