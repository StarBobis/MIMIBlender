"""Smoke test for the Naraka shape key pipeline (games/naraka/shapekeys.py).

Runs outside Blender: the bpy-dependent imports of shapekeys.py are
replaced with light stubs, so the pure INI generation logic can be
verified directly. The test builds fake DrawIB models matching the real
Naraka game type (GPU_P12_N12_TA16_T8_BW16_BI16_, Position stride 40) and
checks the generated INI text.
"""

import importlib.util
import os
import sys
import tempfile
import types
from types import SimpleNamespace

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Synthetic package name used to load addon modules by file path, so the
# real addon package (which imports bpy) is never touched.
TEST_PKG = "naraka_shapekey_test_pkg"


def load_module_by_path(module_name: str, file_path: str):
    """Load one python file as a module with the given dotted name."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def ensure_parent_packages():
    """Register empty parent packages so relative imports resolve."""
    for package_name in (
        TEST_PKG,
        TEST_PKG + ".common",
        TEST_PKG + ".games",
        TEST_PKG + ".games.naraka",
        TEST_PKG + ".blueprint",
    ):
        if package_name not in sys.modules:
            sys.modules[package_name] = types.ModuleType(package_name)


def install_global_config_stub(mod_folder_path: str):
    """Stub common.global_config with only what shapekeys.py uses."""
    stub_module = types.ModuleType(TEST_PKG + ".common.global_config")

    class GlobalConfig:
        @staticmethod
        def path_generate_mod_folder():
            # The shape key shader is copied next to the generated INI.
            return mod_folder_path

        @staticmethod
        def ini_buffer_filename(filename: str) -> str:
            # 3Dmigoto resolves resource files relative to the INI folder.
            return "Buffers\\" + filename

    stub_module.GlobalConfig = GlobalConfig
    sys.modules[TEST_PKG + ".common.global_config"] = stub_module


def install_blueprint_export_helper_stub(shapekeyname_mkey_dict: dict):
    """Stub blueprint.blueprint_export_helper with a mutable shape key config.

    The stub reads through to the given dict on every call, so the test can
    change the configured shape keys later without reinstalling the stub
    (shapekeys.py keeps the imported class reference).
    """
    stub_module = types.ModuleType(TEST_PKG + ".blueprint.blueprint_export_helper")

    class BlueprintExportHelper:
        @staticmethod
        def get_current_shapekeyname_mkey_dict(context=None):
            return shapekeyname_mkey_dict

    stub_module.BlueprintExportHelper = BlueprintExportHelper
    sys.modules[TEST_PKG + ".blueprint.blueprint_export_helper"] = stub_module


def build_fake_d3d11_game_type(extra_position_element: bool = False):
    """Build a fake game type with the real Naraka Position element layout.

    extra_position_element adds a COLOR element to the Position category,
    which makes the vertex stride differ from the 40 bytes the compute
    shader expects, simulating an unsupported game type.
    """
    element_list = [
        SimpleNamespace(SemanticName="POSITION", Format="R32G32B32_FLOAT", ByteWidth=12, Category="Position"),
        SimpleNamespace(SemanticName="NORMAL", Format="R32G32B32_FLOAT", ByteWidth=12, Category="Position"),
        SimpleNamespace(SemanticName="TANGENT", Format="R32G32B32A32_FLOAT", ByteWidth=16, Category="Position"),
        SimpleNamespace(SemanticName="TEXCOORD", Format="R32G32_FLOAT", ByteWidth=8, Category="Texcoord"),
    ]
    if extra_position_element:
        # An extra packed COLOR in the Position category: stride becomes 44.
        element_list.append(
            SimpleNamespace(SemanticName="COLOR", Format="R8G8B8A8_UNORM", ByteWidth=4, Category="Position")
        )
    return SimpleNamespace(
        D3D11ElementList=element_list,
        CategoryStrideDict={"Position": 44 if extra_position_element else 40},
    )


def build_fake_drawib_model(draw_ib: str, vertex_count: int, shapekey_names: list, extra_position_element: bool = False):
    """Build a fake DrawIB model carrying the given shape key buffers."""
    fake_model = SimpleNamespace(
        draw_ib=draw_ib,
        d3d11_game_type=build_fake_d3d11_game_type(extra_position_element),
        shapekey_name_bytelist_dict={name: b"fake" for name in shapekey_names},
        draw_number=vertex_count,
    )
    # get_category_buffer_filename is a method on the real model; the fake
    # returns the same file naming style used by the real Naraka exports.
    fake_model.get_category_buffer_filename = lambda category: "LOD0." + draw_ib + "-" + category + ".buf"
    return fake_model


def main():
    temp_dir = tempfile.mkdtemp(prefix="naraka_shapekey_test_")
    mod_folder_path = os.path.join(temp_dir, "mod", "")
    os.makedirs(mod_folder_path, exist_ok=True)

    ensure_parent_packages()
    install_global_config_stub(mod_folder_path)

    # Two configured shape keys: "Smile" with a hotkey, "Blink" without one.
    shapekeyname_mkey_dict = {
        "Smile": SimpleNamespace(key_name="$shapekey0", initialize_value=0, initialize_vk_str="F1", comment=""),
        "Blink": SimpleNamespace(key_name="$shapekey1", initialize_value=0, initialize_vk_str="", comment=""),
    }
    install_blueprint_export_helper_stub(shapekeyname_mkey_dict)

    # The real ini builder is pure python, load it directly.
    m_ini_builder = load_module_by_path(
        TEST_PKG + ".common.m_ini_builder",
        os.path.join(ROOT, "common", "m_ini_builder.py"),
    )

    # Load the module under test with the stubs in place.
    shapekeys = load_module_by_path(
        TEST_PKG + ".games.naraka.shapekeys",
        os.path.join(ROOT, "games", "naraka", "shapekeys.py"),
    )

    # --- Case 1: two DrawIBs, both with a supported Position layout ------
    cloth_model = build_fake_drawib_model("65b9cf5a", 8168, ["Smile", "Blink"])
    body_model = build_fake_drawib_model("d58050d1", 5517, ["Smile"])
    drawib_dict = {
        "65b9cf5a": cloth_model,
        "d58050d1": body_model,
    }

    ini_builder = m_ini_builder.M_IniBuilder()
    shapekeys.add_naraka_shapekey_ini_sections(ini_builder, drawib_dict)

    ini_path = os.path.join(temp_dir, "test_mod.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as ini_file:
        ini_text = ini_file.read()

    print("=" * 70)
    print(ini_text)
    print("=" * 70)

    failures = []

    def check(condition, message):
        # Tiny assert helper so every failure is reported, not just the first.
        if not condition:
            failures.append(message)
            print("FAIL: " + message)
        else:
            print("OK:   " + message)

    # The raw game-facing buffer must receive a byte copy of the result,
    # never a reference re-point at the structured working copy.
    check("Resource65b9cf5aPosition = copy cs-u5" in ini_text,
          "cloth position buffer receives the computed bytes via copy")
    check("Resourced58050d1Position = copy cs-u5" in ini_text,
          "body position buffer receives the computed bytes via copy")
    check("ref cs-u5" not in ini_text,
          "no ref re-point anywhere (raw view of the game shader must survive)")

    # The [Present] section just runs the compute command lists every frame.
    check("run = CustomShaderComputeShapesNaraka1" in ini_text, "present runs cloth command list")
    check("run = CustomShaderComputeShapesNaraka2" in ini_text, "present runs body command list")
    check("$shapekey_first_run" not in ini_text, "no first-run gate needed on this pipeline")

    # Per-key dispatches: body only has "Smile", so "Blink" must be absent there.
    check("cs-t51 = Resource65b9cf5aPosition.Smile" in ini_text, "cloth binds Smile buffer")
    check("cs-t51 = Resource65b9cf5aPosition.Blink" in ini_text, "cloth binds Blink buffer")
    check("cs-t51 = Resourced58050d1Position.Smile" in ini_text, "body binds Smile buffer")
    check("Resourced58050d1Position.Blink" not in ini_text, "body skips the missing Blink key")

    # Resource declarations: structured buffers with the Position stride.
    check("[Resource65b9cf5aPosition.1]" in ini_text, "cloth pristine base copy declared")
    check("type = buffer" in ini_text, "working buffers are structured (type = buffer)")
    check("stride = 40" in ini_text, "working buffers carry the 40-byte stride")
    check("Buffers\\LOD0.65b9cf5a-Position.buf" in ini_text, "base copy points at the position file")
    check("Buffers\\65b9cf5a-Position.Smile.buf" in ini_text, "shape key buffer file name matches the exporter")

    # Hotkeys: only "Smile" has a vk binding, so only it gets a key section.
    check("[Key_ShapeKey_Smile]" in ini_text, "Smile gets its cycle key section")
    check("[Key_ShapeKey_Blink]" not in ini_text, "Blink has no hotkey and no key section")

    # The compute shader file must be copied next to the generated INI.
    check(os.path.exists(os.path.join(mod_folder_path, "Shapes.hlsl")),
          "Shapes.hlsl copied into the mod folder")

    # --- Case 2: unsupported Position layout is skipped cleanly ----------
    # The extra COLOR element brings the Position stride to 44 bytes, which
    # no longer matches the 40-byte struct the compute shader reads.
    odd_model = build_fake_drawib_model("deadbeef", 100, ["Smile"], extra_position_element=True)
    odd_builder = m_ini_builder.M_IniBuilder()
    shapekeys.add_naraka_shapekey_ini_sections(odd_builder, {"deadbeef": odd_model})
    check(len(odd_builder.ini_section_list) == 0,
          "unsupported Position layout produces no shape key sections")

    # --- Case 3: empty blueprint config produces nothing -----------------
    # The stub reads through to the dict, so clearing it is enough.
    shapekeyname_mkey_dict.clear()
    empty_builder = m_ini_builder.M_IniBuilder()
    shapekeys.add_naraka_shapekey_ini_sections(empty_builder, drawib_dict)
    check(len(empty_builder.ini_section_list) == 0,
          "no configured shape keys means no sections at all")

    print()
    if failures:
        print(str(len(failures)) + " check(s) failed")
        return 1
    print("ALL NARAKA SHAPEKEY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
