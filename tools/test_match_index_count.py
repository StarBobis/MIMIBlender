"""Match identity tests: every IB override carries match_index_count.

3Dmigoto selects a draw by its hash, its first index and its index count.  A
Submesh override that only writes match_first_index therefore also matches any
other draw that happens to start at the same offset, which is common on the
GPU pre-skinning presets.  Every game exporter now writes the Submesh's index
count directly after the first index line.

The value comes from the import side: SubMeshJson.IndexCount is copied into
SubMeshModel.match_index_count and corrected by the workspace model later on.
It may still be -1 ("never resolved") or 0, and those two values must never
reach the INI: the draw would never match.  The one guarded writer lives in
common/skip_draw.py, so this test checks the writer, the two shared builders,
one preset per construction style and the source inventory.

Nothing here imports Blender: the addon modules are loaded by file path inside
a synthetic package, with light stubs for the bpy-dependent modules, exactly
like test_naraka_ini_texture_check.py does.

Run with:
    python tools/test_match_index_count.py
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Synthetic package name used to load addon modules by file path, so the real
# addon package (which imports bpy) is never touched.
TEST_PKG = "match_index_count_test_pkg"

DRAW_IB = "94517393"
HOST_SUBMESH = "LOD0_body"
GUEST_SUBMESH = "LOD0_cloth"
MISSING_SUBMESH = "LOD0_missing"

# Naraka always pre-skins on the GPU, and the GPU shape keeps the category
# bindings out of the IB section, so one game type serves every fake model.
GPU_GAME_TYPE = SimpleNamespace(
    GPU_PreSkinning=True,
    CategoryDrawCategoryDict={},
    CategoryExtractSlotDict={},
    OrderedCategoryNameList=[],
    CategoryStrideDict={},
)


# ----------------------------------------------------------------------
# Blender-free loading harness
# ----------------------------------------------------------------------

def register_package(package_name: str, relative_folder: str):
    """Register an empty package whose real __init__ never runs.

    Only the __path__ matters: it lets the relative imports of the loaded
    modules resolve to the real folders without executing bpy code.
    """
    package = types.ModuleType(package_name)
    package.__path__ = [os.path.join(ROOT, relative_folder)]
    sys.modules[package_name] = package
    return package


def load_module(module_name: str, relative_path: str):
    """Load one addon file as a module inside the synthetic test package."""
    file_path = os.path.join(ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    # Expose the module on its parent package as well: "from ..base import
    # sections" style imports otherwise depend on an import-system fallback.
    parent_name, _, child_name = module_name.rpartition(".")
    parent_module = sys.modules.get(parent_name)
    if parent_module is not None:
        setattr(parent_module, child_name, module)
    return module


def install_global_config_stub():
    """Stub common.global_config with only what the loaded modules use."""
    stub_module = types.ModuleType(TEST_PKG + ".common.global_config")

    class LogicName:
        """The preset names the cross-IB support list compares against."""
        Naraka = "Naraka"
        GF2 = "GF2"
        PGR = "PGR"

    class GlobalConfig:
        # Only the branch key sections read the mod number, and those are not
        # part of the sections tested here.
        generated_mod_number = 0
        # The IdentityV exporter lists this folder to find Submeshes that only
        # exist as workspace folders ("missing" entries).
        workspace_folder_path = ""

        @staticmethod
        def path_workspace_folder():
            return GlobalConfig.workspace_folder_path

        @staticmethod
        def path_generate_mod_folder():
            return ""

        @staticmethod
        def ini_buffer_filename(filename: str) -> str:
            return "Buffers\\" + filename

        @staticmethod
        def ini_texture_filename(filename: str) -> str:
            return "Textures\\" + filename

    stub_module.LogicName = LogicName
    stub_module.GlobalConfig = GlobalConfig
    sys.modules[TEST_PKG + ".common.global_config"] = stub_module
    return stub_module


def install_mimi_global_properties_stub():
    """Stub common.mimi_global_properties, whose real module needs bpy."""
    stub_module = types.ModuleType(TEST_PKG + ".common.mimi_global_properties")

    class MIMIGlobalProperties:
        @staticmethod
        def forbid_auto_texture_ini() -> bool:
            return False

        @staticmethod
        def simulate_xxmi_tail_comments() -> bool:
            return False

    stub_module.MIMIGlobalProperties = MIMIGlobalProperties
    sys.modules[TEST_PKG + ".common.mimi_global_properties"] = stub_module


def install_m_ini_helper_stub():
    """Stub common.m_ini_helper, whose real module pulls in the model layer.

    The tested section builders only ask it for drawindexed lines and for the
    texture binding resource sections, so fixed answers are enough to prove
    the layout of the generated override.
    """
    stub_module = types.ModuleType(TEST_PKG + ".common.m_ini_helper")

    class M_IniHelper:
        @staticmethod
        def get_drawindexed_str_list(draw_call_model_list, obj_name_draw_offset_dict=None):
            return ["drawindexed = 3, 0, 0"]

        @staticmethod
        def add_object_texture_binding_resource_sections(**kwargs):
            return None

    stub_module.M_IniHelper = M_IniHelper
    sys.modules[TEST_PKG + ".common.m_ini_helper"] = stub_module


def install_blueprint_export_helper_stub():
    """Stub blueprint.blueprint_export_helper for the Naraka shape key module."""
    stub_module = types.ModuleType(TEST_PKG + ".blueprint.blueprint_export_helper")

    class BlueprintExportHelper:
        @staticmethod
        def get_current_shapekeyname_mkey_dict(context=None):
            return {}

    stub_module.BlueprintExportHelper = BlueprintExportHelper
    sys.modules[TEST_PKG + ".blueprint.blueprint_export_helper"] = stub_module


def load_modules():
    """Load the real exporter and builder modules this test drives."""
    register_package(TEST_PKG, "")
    register_package(TEST_PKG + ".common", "common")
    register_package(TEST_PKG + ".blueprint", "blueprint")
    register_package(TEST_PKG + ".games", "games")
    register_package(TEST_PKG + ".games.base", "games/base")
    register_package(TEST_PKG + ".games.naraka", "games/naraka")

    global_config_stub = install_global_config_stub()
    install_mimi_global_properties_stub()
    install_m_ini_helper_stub()
    install_blueprint_export_helper_stub()

    loaded = SimpleNamespace(global_config_stub=global_config_stub)
    loaded.m_ini_builder = load_module(TEST_PKG + ".common.m_ini_builder", "common/m_ini_builder.py")
    loaded.skip_draw = load_module(TEST_PKG + ".common.skip_draw", "common/skip_draw.py")
    load_module(TEST_PKG + ".common.cross_ib_support", "common/cross_ib_support.py")
    load_module(TEST_PKG + ".games.base.standard_exporter", "games/base/standard_exporter.py")
    loaded.base_sections = load_module(TEST_PKG + ".games.base.sections", "games/base/sections.py")
    loaded.naraka_exporter = load_module(TEST_PKG + ".games.naraka.exporter", "games/naraka/exporter.py")
    loaded.identityv = load_module(TEST_PKG + ".games.identityv", "games/identityv.py")
    return loaded


# ----------------------------------------------------------------------
# Fake models, shaped like the real import-side models
# ----------------------------------------------------------------------

def make_draw_call(obj_name: str, cross_render_at_submesh: str = ""):
    """One fake draw call: drawn in its own section unless it is a guest."""
    return SimpleNamespace(
        obj_name=obj_name,
        cross_render_at_submesh=cross_render_at_submesh,
        skip_draw=False,
    )


def make_submesh(submesh_name: str, match_first_index: int = 0,
                 match_index_count: int = 924, skip_draw: bool = False):
    """One fake Submesh carrying the identity fields the builders read."""
    return SimpleNamespace(
        submesh_name=submesh_name,
        display_str=submesh_name,
        match_first_index=match_first_index,
        match_index_count=match_index_count,
        skip_draw=skip_draw,
        drawcall_model_list=[make_draw_call(submesh_name)],
    )


def make_drawib(submesh_model_list: list, draw_ib: str = DRAW_IB):
    """One fake DrawIB exposing only the accessors the section builders call."""
    return SimpleNamespace(
        draw_ib=draw_ib,
        d3d11_game_type=GPU_GAME_TYPE,
        submesh_model_list=submesh_model_list,
        # A non-empty index buffer keeps the Submesh visible in every builder.
        submesh_ib_dict={submesh.submesh_name: b"\x01\x02\x03" for submesh in submesh_model_list},
        obj_name_draw_offset={},
        get_submesh_texture_markup_info_list=lambda submesh: [],
        get_submesh_texture_override_suffix=lambda submesh: submesh.submesh_name.replace(".", "_").replace("-", "_"),
        get_submesh_ib_resource_name=lambda submesh: "Resource_" + submesh.submesh_name.replace(".", "_") + "_Index",
        # Only the cross-IB backup names read this one.
        get_submesh_unique_key=lambda submesh: submesh.submesh_name.replace(".", "_").replace("-", "_"),
    )


# ----------------------------------------------------------------------
# INI text helpers
# ----------------------------------------------------------------------

def flatten(builder):
    """Flatten an M_IniBuilder into plain INI lines for text assertions."""
    lines = []
    for section in builder.ini_section_list:
        lines.extend(section.SectionLineList)
    return lines


def find_block(lines: list, header: str):
    """Return the lines of one [section], from its header to the next one."""
    try:
        start = lines.index(header)
    except ValueError:
        raise AssertionError("section not found: " + header + " in " + repr(lines))
    end = start + 1
    while end < len(lines) and not lines[end].strip().startswith("["):
        end += 1
    return lines[start:end]


def count_lines(block: list, prefix: str):
    """Return the lines of one section that start with the given prefix."""
    return [line for line in block if line.strip().startswith(prefix)]


def render_naraka_ib(modules, drawib_model, cross_ib_host_entries=None):
    """Render the Naraka IB override section of one fake DrawIB."""
    exporter_class = modules.naraka_exporter.Exporter
    # The constructor demands a full blueprint model, and the IB builder only
    # needs the cross-IB bookkeeping, so the instance is built empty-handed.
    exporter = exporter_class.__new__(exporter_class)
    exporter.cross_ib_host_entries = cross_ib_host_entries or {}
    exporter.usable_shapekey_drawib_model_list = []

    builder = modules.m_ini_builder.M_IniBuilder()
    exporter.add_naraka_cs_texture_override_ib_sections(builder, drawib_model)
    return flatten(builder)


# ----------------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------------

class SharedWriterTests(unittest.TestCase):
    """The one guarded writer every preset calls."""

    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()

    def make_section(self):
        return self.modules.m_ini_builder.M_IniSection(
            self.modules.m_ini_builder.M_SectionType.TextureOverrideIB
        )

    def test_positive_count_is_written(self):
        section = self.make_section()
        self.modules.skip_draw.append_match_index_count(section, make_submesh(HOST_SUBMESH, match_index_count=924))
        self.assertEqual(section.SectionLineList, ["match_index_count = 924"])

    def test_unknown_counts_are_not_written(self):
        # -1 means "the workspace never resolved the value", 0 is the empty
        # string parsed as a number: both must stay out of the INI.
        for unknown_count in (-1, 0, -7, "0", "", None, "not a number"):
            section = self.make_section()
            self.modules.skip_draw.append_match_index_count(
                section, make_submesh(HOST_SUBMESH, match_index_count=unknown_count)
            )
            self.assertEqual(section.SectionLineList, [], "count " + repr(unknown_count) + " must write nothing")

    def test_string_counts_are_converted(self):
        # Imported JSON can carry the count as a string; the writer converts it.
        section = self.make_section()
        self.modules.skip_draw.append_match_index_count(
            section, make_submesh(HOST_SUBMESH, match_index_count="924")
        )
        self.assertEqual(section.SectionLineList, ["match_index_count = 924"])

    def test_missing_attribute_is_treated_as_unknown(self):
        # Older Submesh stand-ins and preview views do not carry the field.
        section = self.make_section()
        self.modules.skip_draw.append_match_index_count(section, SimpleNamespace(submesh_name=HOST_SUBMESH))
        self.assertEqual(section.SectionLineList, [])

    def test_hidden_submesh_section_keeps_the_count(self):
        # Skip Draw reuses the same helper, so a hidden Submesh is matched by
        # first index plus count as well and only the bare skip is written.
        section = self.make_section()
        self.modules.skip_draw.append_hidden_submesh_section(
            section, DRAW_IB, HOST_SUBMESH, 0, make_submesh(HOST_SUBMESH, match_index_count=3)
        )
        self.assertIn("match_index_count = 3", section.SectionLineList)
        self.assertIn("handling = skip", section.SectionLineList)
        self.assertLess(section.SectionLineList.index("match_index_count = 3"),
                        section.SectionLineList.index("handling = skip"))

    def test_hidden_submesh_section_drops_an_unknown_count(self):
        section = self.make_section()
        self.modules.skip_draw.append_hidden_submesh_section(
            section, DRAW_IB, HOST_SUBMESH, 0, make_submesh(HOST_SUBMESH, match_index_count=-1)
        )
        self.assertEqual(count_lines(section.SectionLineList, "match_index_count"), [])


class NarakaSectionTests(unittest.TestCase):
    """Naraka: the preset whose IB section is fully its own copy."""

    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()

    def test_count_comes_from_the_submesh_model(self):
        drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=0, match_index_count=924)])
        block = find_block(render_naraka_ib(self.modules, drawib_model), "[TextureOverride_" + HOST_SUBMESH + "]")
        self.assertIn("match_first_index = 0", block)
        # The count must be the very next line, before handling = skip.
        self.assertEqual(block[block.index("match_first_index = 0") + 1], "match_index_count = 924")

    def test_count_follows_the_submesh_value(self):
        # Same section, different Submesh metadata: the value is not a constant.
        drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=180, match_index_count=111)])
        block = find_block(render_naraka_ib(self.modules, drawib_model), "[TextureOverride_" + HOST_SUBMESH + "]")
        self.assertIn("match_first_index = 180", block)
        self.assertIn("match_index_count = 111", block)

    def test_unknown_count_writes_no_line(self):
        for unknown_count in (-1, 0):
            drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_index_count=unknown_count)])
            block = find_block(render_naraka_ib(self.modules, drawib_model), "[TextureOverride_" + HOST_SUBMESH + "]")
            self.assertEqual(count_lines(block, "match_index_count"), [],
                             "count " + repr(unknown_count) + " must not reach the INI")

    def test_texture_slot_check_runs_before_the_index_buffer(self):
        # The NBP-Package command list must see the slots of the matched draw,
        # so it has to run before the modded index buffer is bound.
        host_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=0, match_index_count=924)])
        guest_submesh = make_submesh(GUEST_SUBMESH, match_first_index=924, match_index_count=300)
        guest_model = make_drawib([guest_submesh], draw_ib="aabbccdd")
        cross_ib_host_entries = {
            HOST_SUBMESH: [{
                "guest_drawib_model": guest_model,
                "guest_submesh_model": guest_submesh,
                "draw_call_list": [make_draw_call(GUEST_SUBMESH)],
            }],
        }

        lines = render_naraka_ib(self.modules, host_model, cross_ib_host_entries)
        block = find_block(lines, "[TextureOverride_" + HOST_SUBMESH + "]")

        # One run before the host's own index buffer and one before the guest's.
        self.assertEqual(count_lines(block, "run = CommandListSkinCheckTextureSlot"), 
                         ["run = CommandListSkinCheckTextureSlot"] * 2)
        host_ib_text = "ib = Resource_" + HOST_SUBMESH.replace(".", "_") + "_Index"
        guest_ib_text = "ib = Resource_" + GUEST_SUBMESH.replace(".", "_") + "_Index"
        self.assertIn(host_ib_text, block)
        self.assertIn(guest_ib_text, block)
        # Index comparison: every run line sits strictly before the bind it
        # belongs to, and the count line still sits next to the first index.
        self.assertLess(block.index("run = CommandListSkinCheckTextureSlot"),
                        block.index(host_ib_text))
        self.assertLess(block.index("run = CommandListSkinCheckTextureSlot", block.index(host_ib_text)),
                        block.index(guest_ib_text))
        self.assertEqual(block[block.index("match_first_index = 0") + 1], "match_index_count = 924")


class SharedBuilderTests(unittest.TestCase):
    """Both shared builders: CPU pre-skinning (VS) and GPU pre-skinning (CS)."""

    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()

    def render(self, drawib_model, compute_shader: bool):
        builder = self.modules.m_ini_builder.M_IniBuilder()
        blueprint_model = SimpleNamespace(keyname_mkey_dict={})
        if compute_shader:
            self.modules.base_sections.add_unity_cs_texture_override_ib_sections(
                ini_builder=builder,
                drawib_model=drawib_model,
                blueprint_model=blueprint_model,
            )
        else:
            self.modules.base_sections.add_unity_vs_texture_override_ib_sections(
                ini_builder=builder,
                drawib_model=drawib_model,
                blueprint_model=blueprint_model,
            )
        return flatten(builder)

    def test_vertex_shader_builder_writes_the_count(self):
        drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=0, match_index_count=924)])
        block = find_block(self.render(drawib_model, compute_shader=False), "[TextureOverride_" + HOST_SUBMESH + "]")
        self.assertEqual(block[block.index("match_first_index = 0") + 1], "match_index_count = 924")

    def test_compute_shader_builder_writes_the_count(self):
        drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=0, match_index_count=924)])
        block = find_block(self.render(drawib_model, compute_shader=True), "[TextureOverride_" + HOST_SUBMESH + "]")
        self.assertEqual(block[block.index("match_first_index = 0") + 1], "match_index_count = 924")

    def test_both_builders_drop_an_unknown_count(self):
        for compute_shader in (False, True):
            drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_index_count=-1)])
            block = find_block(self.render(drawib_model, compute_shader=compute_shader),
                               "[TextureOverride_" + HOST_SUBMESH + "]")
            self.assertEqual(count_lines(block, "match_index_count"), [],
                             "builder compute_shader=" + str(compute_shader) + " wrote an unknown count")


class IdentityVDictPathTests(unittest.TestCase):
    """IdentityV: the only preset whose IB section is built from a dictionary."""

    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()

    def setUp(self):
        # A workspace folder is needed so the exporter also produces its
        # "missing Submesh" entry (workspace folder without a blueprint object).
        self.temp_folder = tempfile.TemporaryDirectory(prefix="match_index_count_identityv_")
        self.addCleanup(self.temp_folder.cleanup)
        missing_folder = os.path.join(self.temp_folder.name, DRAW_IB + "-" + MISSING_SUBMESH + "-200")
        os.makedirs(missing_folder, exist_ok=True)
        self.modules.global_config_stub.GlobalConfig.workspace_folder_path = self.temp_folder.name
        self.addCleanup(
            setattr, self.modules.global_config_stub.GlobalConfig, "workspace_folder_path", ""
        )

    def make_exporter(self):
        # __new__ skips the blueprint parse; the IB builder only needs the
        # branch key dict, and the DrawIB below has no branch keys anyway.
        exporter = self.modules.identityv.ExportIdentityV.__new__(self.modules.identityv.ExportIdentityV)
        exporter.blueprint_model = SimpleNamespace(keyname_mkey_dict={})
        return exporter

    def render(self, drawib_model):
        builder = self.modules.m_ini_builder.M_IniBuilder()
        self.make_exporter().add_unity_vs_texture_override_ib_sections(builder, drawib_model)
        return flatten(builder)

    def test_dictionary_carries_the_count_of_both_entry_kinds(self):
        drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=0, match_index_count=4242)])
        entries = self.make_exporter()._get_drawib_submesh_entries(drawib_model)
        entries_by_name = {entry["submesh_name"]: entry for entry in entries}
        # The parsed Submesh contributes its real count ...
        self.assertEqual(entries_by_name[HOST_SUBMESH]["match_index_count"], 4242)
        # ... while a workspace-only Submesh has no parsed count at all.
        self.assertEqual(entries_by_name[DRAW_IB + "-" + MISSING_SUBMESH + "-200"]["match_index_count"], 0)

    def test_normal_path_writes_the_count(self):
        drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=0, match_index_count=4242)])
        block = find_block(self.render(drawib_model), "[TextureOverride_" + HOST_SUBMESH + "]")
        self.assertEqual(block[block.index("match_first_index = 0") + 1], "match_index_count = 4242")

    def test_missing_submesh_keeps_the_first_index_only_match(self):
        drawib_model = make_drawib([make_submesh(HOST_SUBMESH, match_first_index=0, match_index_count=4242)])
        lines = self.render(drawib_model)
        # IdentityV normalizes dashes to underscores in the section name.
        missing_header = "[TextureOverride_" + (DRAW_IB + "-" + MISSING_SUBMESH + "-200").replace("-", "_") + "]"
        block = find_block(lines, missing_header)
        self.assertIn("handling = skip", block)
        self.assertEqual(count_lines(block, "match_index_count"), [])

    def test_dictionary_value_writer_outputs_a_known_count(self):
        # The dictionary path reads submesh_entry["match_index_count"] and
        # converts it with the shared value writer.  A missing Submesh always
        # carries 0, so the positive case is proven on its own.
        section = self.modules.m_ini_builder.M_IniSection(
            self.modules.m_ini_builder.M_SectionType.TextureOverrideIB
        )
        self.make_exporter()._append_missing_texture_override_ib_section(
            section,
            DRAW_IB,
            {
                "submesh_name": DRAW_IB + "-" + MISSING_SUBMESH + "-200",
                "match_first_index": 200,
                "match_index_count": 77,
            },
        )
        self.assertEqual(section.SectionLineList[2], "match_first_index = 200")
        self.assertEqual(section.SectionLineList[3], "match_index_count = 77")
        self.assertEqual(section.SectionLineList[4], "handling = skip")


class SourceInventoryTests(unittest.TestCase):
    """Every exporter path keeps calling the one guarded writer."""

    # Number of "append_match_index_count(" occurrences per file, i.e. the
    # call itself (the import line has no parenthesis and is covered by the
    # import of these modules failing at load time instead).  A preset that
    # loses its call fails here instead of silently writing no count.
    EXPECTED_CALLS = {
        # Definition + the model docstring reference + the value docstring
        # reference + the hidden section helper call.
        "common/skip_draw.py": 4,
        "games/base/sections.py": 2,       # VS builder + CS builder
        "games/efmi.py": 1,
        "games/gf2/exporter.py": 1,
        "games/gimi/exporter.py": 1,
        "games/identityv.py": 1,           # normal path only (dict path uses the value variant)
        "games/naraka/exporter.py": 1,
        "games/pgr/exporter.py": 1,
        "games/snowbreak.py": 1,
        "games/srmi.py": 1,
        "games/yysls.py": 1,
        "games/zzmi.py": 1,
        "games/zzmidx12.py": 1,
    }

    def test_every_override_builder_calls_the_shared_writer(self):
        for relative_path, expected_count in self.EXPECTED_CALLS.items():
            text = open(os.path.join(ROOT, relative_path), encoding="utf-8").read()
            self.assertEqual(
                text.count("append_match_index_count("), expected_count,
                relative_path + " lost its match_index_count writer call",
            )

    def test_no_exporter_hand_builds_the_count_line(self):
        # The line only comes from the shared writer.  NTEMI is the single
        # exception because it matches one whole DrawIB range whose value is a
        # computed total, not a Submesh's own count.
        hand_built_files = []
        games_folder = os.path.join(ROOT, "games")
        for folder, _, file_list in os.walk(games_folder):
            for file_name in file_list:
                if not file_name.endswith(".py"):
                    continue
                file_path = os.path.join(folder, file_name)
                text = open(file_path, encoding="utf-8").read()
                if 'match_index_count = "' in text:
                    hand_built_files.append(os.path.relpath(file_path, ROOT).replace("\\", "/"))
        self.assertEqual(hand_built_files, [])

        ntemi_text = open(os.path.join(ROOT, "games/ntemi/sections.py"), encoding="utf-8").read()
        self.assertIn("match_index_count = {total_index_count}", ntemi_text)
        # The WWMI component section keeps using the shared value writer.
        wwmi_text = open(os.path.join(ROOT, "games/wwmi/exporter.py"), encoding="utf-8").read()
        # One call; the import line carries no parenthesis.
        self.assertEqual(wwmi_text.count("append_match_index_count_value("), 1)
        self.assertIn("append_match_index_count_value(texture_override_component, component_object.index_count)",
                      wwmi_text)

    def test_texture_slot_check_stays_naraka_only(self):
        # Only the Naraka package declares CommandListSkinCheckTextureSlot.
        naraka_text = open(os.path.join(ROOT, "games/naraka/exporter.py"), encoding="utf-8").read()
        self.assertIn('SKIN_CHECK_TEXTURE_SLOT_COMMAND_LIST = "CommandListSkinCheckTextureSlot"', naraka_text)
        self.assertEqual(naraka_text.count('"run = " + SKIN_CHECK_TEXTURE_SLOT_COMMAND_LIST'), 2)

        for folder, _, file_list in os.walk(os.path.join(ROOT, "games")):
            for file_name in file_list:
                if not file_name.endswith(".py"):
                    continue
                file_path = os.path.join(folder, file_name)
                if os.path.abspath(file_path) == os.path.abspath(os.path.join(ROOT, "games/naraka/exporter.py")):
                    continue
                text = open(file_path, encoding="utf-8").read()
                self.assertNotIn("CommandListSkinCheckTextureSlot", text,
                                 "the Naraka-only command list leaked into " + file_path)


if __name__ == "__main__":
    suite = unittest.TestSuite()
    for case in (SharedWriterTests, NarakaSectionTests, SharedBuilderTests,
                 IdentityVDictPathTests, SourceInventoryTests):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
