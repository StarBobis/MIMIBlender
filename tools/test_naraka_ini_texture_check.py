"""Regression test for the Naraka IB override sections.

The Naraka preset used to write two kinds of checktextureoverride lines into
every [TextureOverride_*] section of a DrawIB:

- the fixed line "checktextureoverride = vb1", and
- one "checktextureoverride = ps-tN" line per Hash marked texture.

Both were removed on purpose.  A Hash marked texture is replaced by its own
hash based [TextureOverride_<hash>] section, so the checks only re-ran
texture overrides the hash matching already applies, and they tied the mod to
whatever texture happened to be bound at draw time: a replaced texture could
therefore stop the whole mod from working.

The test loads the real Naraka exporter with light stubs (the same trick the
other Blender-free tests in this folder use), exports one fake DrawIB and
proves that the generated section carries no check line at all, while the
rest of the layout stays exactly as before.

Run with:
    python tools/test_naraka_ini_texture_check.py
"""

import importlib.util
import os
import sys
import tempfile
import types
from types import SimpleNamespace

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Synthetic package name used to load addon modules by file path, so the real
# addon package (which imports bpy) is never touched.
TEST_PKG = "naraka_ini_check_test_pkg"


def register_package(package_name: str, relative_folder: str):
    """Register an empty package whose real __init__ never runs.

    Only the __path__ matters here: it lets the relative imports of the
    loaded modules resolve to the real folders without executing any
    bpy-dependent package code.
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
    return module


def install_global_config_stub():
    """Stub common.global_config with only what the loaded modules use."""
    stub_module = types.ModuleType(TEST_PKG + ".common.global_config")

    class LogicName:
        """The few preset names the cross-IB helper compares against."""
        Naraka = "Naraka"
        GF2 = "GF2"
        PGR = "PGR"

    class GlobalConfig:
        # The generated Mod number is only used by the branch key sections.
        generated_mod_number = 0

        @staticmethod
        def path_generate_mod_folder():
            return ""

        @staticmethod
        def ini_buffer_filename(filename: str) -> str:
            return "Buffers\\" + filename

    stub_module.LogicName = LogicName
    stub_module.GlobalConfig = GlobalConfig
    sys.modules[TEST_PKG + ".common.global_config"] = stub_module


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

    The Naraka exporter only asks the helper for the drawindexed lines, so a
    fixed answer is enough to prove the section layout.
    """
    stub_module = types.ModuleType(TEST_PKG + ".common.m_ini_helper")

    class M_IniHelper:
        @staticmethod
        def get_drawindexed_str_list(draw_call_model_list, obj_name_draw_offset_dict=None):
            return ["drawindexed = 3, 0, 0"]

    stub_module.M_IniHelper = M_IniHelper
    sys.modules[TEST_PKG + ".common.m_ini_helper"] = stub_module


def install_blueprint_export_helper_stub():
    """Stub blueprint.blueprint_export_helper for the shape key module."""
    stub_module = types.ModuleType(TEST_PKG + ".blueprint.blueprint_export_helper")

    class BlueprintExportHelper:
        @staticmethod
        def get_current_shapekeyname_mkey_dict(context=None):
            return {}

    stub_module.BlueprintExportHelper = BlueprintExportHelper
    sys.modules[TEST_PKG + ".blueprint.blueprint_export_helper"] = stub_module


def load_exporter_modules():
    """Load the real exporter and every module it imports."""
    register_package(TEST_PKG, "")
    register_package(TEST_PKG + ".common", "common")
    register_package(TEST_PKG + ".blueprint", "blueprint")
    register_package(TEST_PKG + ".games", "games")
    register_package(TEST_PKG + ".games.base", "games/base")
    register_package(TEST_PKG + ".games.naraka", "games/naraka")

    install_global_config_stub()
    install_mimi_global_properties_stub()
    install_m_ini_helper_stub()
    install_blueprint_export_helper_stub()

    load_module(TEST_PKG + ".common.m_ini_builder", "common/m_ini_builder.py")
    load_module(TEST_PKG + ".common.skip_draw", "common/skip_draw.py")
    load_module(TEST_PKG + ".common.cross_ib_support", "common/cross_ib_support.py")
    load_module(TEST_PKG + ".games.base.standard_exporter", "games/base/standard_exporter.py")
    load_module(TEST_PKG + ".games.base.sections", "games/base/sections.py")
    load_module(TEST_PKG + ".games.naraka.shapekeys", "games/naraka/shapekeys.py")
    return load_module(TEST_PKG + ".games.naraka.exporter", "games/naraka/exporter.py")


def make_mark(mark_type: str, mark_slot: str):
    """One texture mark, shaped like the real TextureMarkUpInfo."""
    return SimpleNamespace(
        mark_type=mark_type,
        mark_slot=mark_slot,
        mark_name="DiffuseMap",
        mark_hash="aabbccdd",
        get_resource_name=lambda: "Resource_" + mark_slot,
    )


def make_drawib_model():
    """A fake DrawIB with one Submesh and three Hash marked textures."""
    submesh_model = SimpleNamespace(
        submesh_name="LOD0_body",
        display_str="LOD0_body",
        match_first_index=0,
        skip_draw=False,
        drawcall_model_list=[
            SimpleNamespace(obj_name="Body", cross_render_at_submesh="", skip_draw=False),
        ],
        # Three Hash marks (the old "ps-tN" check lines) plus one Slot mark
        # (the slot binding that must survive the change).
        texture_markup_info_list=[
            make_mark("Hash", "ps-t1"),
            make_mark("Hash", "ps-t2"),
            make_mark("Hash", "ps-t3"),
            make_mark("Slot", "ps-t0"),
        ],
    )

    return SimpleNamespace(
        draw_ib="0734facd",
        # Naraka always pre-skins on the GPU, so the category bindings are
        # not part of the IB section.
        d3d11_game_type=SimpleNamespace(
            GPU_PreSkinning=True,
            CategoryDrawCategoryDict={},
            CategoryExtractSlotDict={},
        ),
        submesh_model_list=[submesh_model],
        submesh_ib_dict={"LOD0_body": b"\x01\x02\x03\x04"},
        obj_name_draw_offset={},
        get_submesh_ib_resource_name=lambda sm: "Resource_" + sm.submesh_name + "_IB",
        get_submesh_texture_override_suffix=lambda sm: sm.submesh_name,
        get_submesh_texture_markup_info_list=lambda sm: sm.texture_markup_info_list,
    )


def export_naraka_ib_section(exporter_module):
    """Export the Naraka IB override section of the fake DrawIB."""
    exporter_class = exporter_module.Exporter
    # The method only needs the cross-IB bookkeeping, so the constructor is
    # skipped: it would demand a full blueprint model.
    exporter = exporter_class.__new__(exporter_class)
    exporter.cross_ib_host_entries = {}
    exporter.usable_shapekey_drawib_model_list = []

    ini_builder = exporter_module.M_IniBuilder()
    exporter.add_naraka_cs_texture_override_ib_sections(ini_builder, make_drawib_model())

    with tempfile.TemporaryDirectory() as temp_folder:
        ini_path = os.path.join(temp_folder, "naraka_ib_section.ini")
        ini_builder.save_to_file_not_reorder(ini_path)
        with open(ini_path, "r", encoding="utf-8") as ini_file:
            return ini_file.read()


def check_generated_ini(ini_text: str):
    """Assert the generated section has no check line and kept its layout."""
    # The whole point of the change: no check line survives, neither the
    # fixed "vb1" one nor the per mark "ps-tN" ones.
    assert "checktextureoverride" not in ini_text.lower(), ini_text

    # The rest of the section must be untouched.
    assert "[TextureOverride_LOD0_body]" in ini_text, ini_text
    assert "hash = 0734facd" in ini_text, ini_text
    assert "match_first_index = 0" in ini_text, ini_text
    assert "handling = skip" in ini_text, ini_text
    assert "ib = Resource_LOD0_body_IB" in ini_text, ini_text
    assert "drawindexed = 3, 0, 0" in ini_text, ini_text

    # A Slot marked texture is still bound to its slot, so the texture
    # replacement itself is not affected by the removed check lines.
    assert "ps-t0 = Resource_ps-t0" in ini_text, ini_text


def check_source_scope():
    """Prove the change stayed inside the Naraka preset.

    The Naraka exporter must not write a check line any more, while the
    other presets (the shared Unity compute path and PGR) keep theirs.
    """
    naraka_source = open(
        os.path.join(ROOT, "games", "naraka", "exporter.py"), encoding="utf-8"
    ).read()
    assert '"checktextureoverride = "' not in naraka_source.lower(), naraka_source

    shared_source = open(
        os.path.join(ROOT, "games", "base", "sections.py"), encoding="utf-8"
    ).read()
    assert "checktextureoverride = " in shared_source.lower(), shared_source

    pgr_source = open(
        os.path.join(ROOT, "games", "pgr", "exporter.py"), encoding="utf-8"
    ).read()
    assert "checktextureoverride = " in pgr_source.lower(), pgr_source


def main():
    exporter_module = load_exporter_modules()
    ini_text = export_naraka_ib_section(exporter_module)
    check_generated_ini(ini_text)
    check_source_scope()
    print("PASS Naraka IB override sections carry no checktextureoverride line")
    print("     while the shared and PGR presets keep their own check lines")


if __name__ == "__main__":
    main()
