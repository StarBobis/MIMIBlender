"""Smoke test for the Time Position Switch / Time Shape Key INI output.

Runs outside Blender with the same stub approach as test_time_switch_ini.py:
the bpy-dependent imports are replaced with light stubs, so the pure INI
generation logic can be verified directly.  The test checks that:

1. append_time_position_sections() declares one buffer resource per frame and
   emits the conditional "dst = copy src" lines into [Present];
2. shape composition changes the accumulation seed (PositionTimeBase),
   never the immutable delta reference (Position.1);
3. get_time_position_support_error() blocks the WWMI/NTEMI presets;
4. M_IniHelper.append_time_shapekey_weight_lines() emits the local frame
   counter plus the if/elif weight mapping, and add_shapekey_ini_sections()
   declares time-driven weights as plain "global" and skips their [Key].
"""

import importlib.util
import os
import sys
import tempfile
import types

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Synthetic package name used to load addon modules by file path, so the
# real addon package (which imports bpy) is never touched.
TEST_PKG = "time_position_ini_test_pkg"


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
        TEST_PKG + ".model",
        TEST_PKG + ".utils",
        TEST_PKG + ".workspace",
        TEST_PKG + ".blueprint",
    ):
        if package_name not in sys.modules:
            sys.modules[package_name] = types.ModuleType(package_name)


# The logic names the tested code compares against; values only need to be
# unique constants, not the real enum strings.
class LogicName:
    WWMI = "WWMI"
    NTEMI = "NTEMI"
    EFMI = "EFMI"
    Naraka = "Naraka"
    GIMI = "GIMI"


class GlobalConfig:
    generated_mod_number = 1
    logic_name = LogicName.GIMI

    @staticmethod
    def ini_buffer_filename(file_name: str) -> str:
        # Mirror the real helper: buffer files live in the Buffers subfolder.
        return "Buffers\\" + file_name

    @staticmethod
    def path_generate_mod_folder() -> str:
        return tempfile.gettempdir()


# The shapekey dictionary the export helper reports; the test flips it.
TEST_SHAPEKEY_DICT = {}


class BlueprintExportHelper:
    @staticmethod
    def get_current_shapekeyname_mkey_dict():
        return TEST_SHAPEKEY_DICT


def install_stubs():
    """Stub the bpy-dependent imports of the tested modules."""
    config_stub = types.ModuleType(TEST_PKG + ".common.global_config")
    config_stub.GlobalConfig = GlobalConfig
    config_stub.LogicName = LogicName
    sys.modules[TEST_PKG + ".common.global_config"] = config_stub

    properties_stub = types.ModuleType(TEST_PKG + ".common.mimi_global_properties")

    class MIMIGlobalProperties:
        pass

    properties_stub.MIMIGlobalProperties = MIMIGlobalProperties
    sys.modules[TEST_PKG + ".common.mimi_global_properties"] = properties_stub

    drawib_stub = types.ModuleType(TEST_PKG + ".model.drawib_model")

    class DrawIBModel:
        pass

    drawib_stub.DrawIBModel = DrawIBModel
    sys.modules[TEST_PKG + ".model.drawib_model"] = drawib_stub

    format_stub = types.ModuleType(TEST_PKG + ".utils.format_utils")

    class Fatal(Exception):
        pass

    format_stub.Fatal = Fatal
    sys.modules[TEST_PKG + ".utils.format_utils"] = format_stub

    workspace_stub = types.ModuleType(TEST_PKG + ".workspace.mmt_workspace")

    class MMTWorkSpace:
        pass

    workspace_stub.MMTWorkSpace = MMTWorkSpace
    sys.modules[TEST_PKG + ".workspace.mmt_workspace"] = workspace_stub

    export_helper_stub = types.ModuleType(TEST_PKG + ".blueprint.blueprint_export_helper")
    export_helper_stub.BlueprintExportHelper = BlueprintExportHelper
    sys.modules[TEST_PKG + ".blueprint.blueprint_export_helper"] = export_helper_stub

    texture_meta_stub = types.ModuleType(TEST_PKG + ".workspace.texture_metadata_helper")

    class TextureMetadataResolver:
        pass

    class TextureMarkUpInfo:
        pass

    texture_meta_stub.TextureMetadataResolver = TextureMetadataResolver
    texture_meta_stub.TextureMarkUpInfo = TextureMarkUpInfo
    sys.modules[TEST_PKG + ".workspace.texture_metadata_helper"] = texture_meta_stub


def load_real_modules():
    """Load the bpy-free addon modules for real (by file path)."""
    modules = {}
    for dotted, relative in (
        (TEST_PKG + ".common.m_key", "common/m_key.py"),
        (TEST_PKG + ".common.m_shape_layout", "common/m_shape_layout.py"),
        (TEST_PKG + ".common.m_ini_builder", "common/m_ini_builder.py"),
        (TEST_PKG + ".common.m_control_flow", "common/m_control_flow.py"),
        (TEST_PKG + ".common.texture_naming", "common/texture_naming.py"),
        (TEST_PKG + ".utils.mmt_error_utils", "utils/mmt_error_utils.py"),
        (TEST_PKG + ".utils.json_utils", "utils/json_utils.py"),
        (TEST_PKG + ".model.draw_call_model", "model/draw_call_model.py"),
        (TEST_PKG + ".common.m_time_position", "common/m_time_position.py"),
        (TEST_PKG + ".common.m_ini_helper", "common/m_ini_helper.py"),
    ):
        modules[dotted] = load_module_by_path(dotted, os.path.join(ROOT, relative))
    return modules


def build_ini_text(ini_builder, ini_path):
    """Render the builder into a file and read the text back."""
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as file:
        return file.read()


def make_fake_drawib_model(shapekey_buffers=None):
    """A minimal stand-in exposing exactly what the INI emission reads."""
    draw_ib = "65b9cf5a"
    # Describe the actual layout, not just its stride, as the writer validates
    # semantics and packed formats before selecting the matching shader.
    game_type = types.SimpleNamespace(CategoryStrideDict={"Position": 12}, D3D11ElementList=[
        types.SimpleNamespace(Category="Position", SemanticName="POSITION", Format="R32G32B32_FLOAT", ByteWidth=12)
    ])
    fake = types.SimpleNamespace(
        draw_ib=draw_ib,
        d3d11_game_type=game_type,
        shapekey_name_bytelist_dict=shapekey_buffers or {},
        time_pos_frame_groups={"$dyntime0": {0: [object()], 1: [object()], 2: [object()]}},
    )
    # Fallback resources use the original file, never a mutated target.
    fake.get_category_buffer_filename = lambda category: draw_ib + "-" + category + ".buf"
    # Mirror DrawIBModel.get_time_position_buffer_filename (no LOD here).
    fake.get_time_position_buffer_filename = (
        lambda var_name, frame_value: draw_ib + "-position_timeframe." + var_name + "_" + str(frame_value) + ".buf"
    )
    # Mirror DrawIBModel.get_time_position_resource_name.
    fake.get_time_position_resource_name = (
        lambda ib, var_name, frame_value: "Resource" + ib + "PositionTimeFrame." + var_name + "_" + str(frame_value)
    )
    return fake


def make_fake_blueprint_model(modules):
    m_key_mod = modules[TEST_PKG + ".common.m_key"]
    time_key = m_key_mod.M_Key()
    time_key.key_name = "$dyntime0"
    time_key.key_type = "time"
    time_key.fps = 12.0
    time_key.value_list = [0, 1, 2]
    return types.SimpleNamespace(
        time_pos_frame_models=[object()],
        time_pos_key_names={"$dyntime0"},
        keyname_mkey_dict={"$dyntime0": time_key},
    )


def test_time_position_sections(modules):
    m_time_position = modules[TEST_PKG + ".common.m_time_position"]
    ini_builder_mod = modules[TEST_PKG + ".common.m_ini_builder"]

    blueprint_model = make_fake_blueprint_model(modules)
    drawib_model = make_fake_drawib_model()

    ini_builder = ini_builder_mod.M_IniBuilder()
    m_time_position.append_time_position_sections(
        ini_builder=ini_builder,
        blueprint_model=blueprint_model,
        drawib_models=[drawib_model],
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        ini_text = build_ini_text(ini_builder, os.path.join(temp_dir, "pos.ini"))

    # 1. One resource per frame with the buffer file name.
    assert "[Resource65b9cf5aPositionTimeFrame.dyntime0_0]" in ini_text, ini_text
    assert "filename = Buffers\\65b9cf5a-position_timeframe.dyntime0_2.buf" in ini_text, ini_text
    assert "stride = 12" in ini_text, ini_text

    # 2. The Present block copies the active frame into the bound resource.
    assert "if $dyntime0 == 0" in ini_text, ini_text
    assert "  Resource65b9cf5aPosition = copy Resource65b9cf5aPositionTimeFrame.dyntime0_0" in ini_text, ini_text
    assert "elif $dyntime0 == 1" in ini_text, ini_text
    assert "elif $dyntime0 == 2" in ini_text, ini_text
    assert "endif" in ini_text, ini_text

    print("test_time_position_sections OK")


def test_time_position_shapekey_composition(modules):
    m_time_position = modules[TEST_PKG + ".common.m_time_position"]

    # Without shape keys the copy targets the bound position resource.
    plain_model = make_fake_drawib_model()
    plain_target = m_time_position.get_time_position_copy_target("65b9cf5a", plain_model)
    assert plain_target == "Resource65b9cf5aPosition", plain_target

    # With shape key buffers the copy targets the pristine backup, so the
    # shape key compute (which reads the backup every frame) layers the
    # weights on top of the frame positions.
    shapekey_model = make_fake_drawib_model(shapekey_buffers={"Smile": b"x"})
    shapekey_target = m_time_position.get_time_position_copy_target("65b9cf5a", shapekey_model)
    assert shapekey_target == "Resource65b9cf5aPositionTimeBase", shapekey_target

    print("test_time_position_shapekey_composition OK")


def test_time_position_support_error(modules):
    m_time_position = modules[TEST_PKG + ".common.m_time_position"]
    blueprint_model = make_fake_blueprint_model(modules)

    GlobalConfig.logic_name = LogicName.GIMI
    assert m_time_position.get_time_position_support_error(blueprint_model) == ""

    GlobalConfig.logic_name = LogicName.WWMI
    assert "WWMI" in m_time_position.get_time_position_support_error(blueprint_model)

    GlobalConfig.logic_name = LogicName.NTEMI
    assert "NTEMI" in m_time_position.get_time_position_support_error(blueprint_model)

    # No frames -> never an error, regardless of the preset.
    empty_model = types.SimpleNamespace(time_pos_frame_models=[])
    GlobalConfig.logic_name = LogicName.WWMI
    assert m_time_position.get_time_position_support_error(empty_model) == ""
    GlobalConfig.logic_name = LogicName.GIMI

    print("test_time_position_support_error OK")


def test_time_shapekey_weight_lines(modules):
    m_key_mod = modules[TEST_PKG + ".common.m_key"]
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    ini_builder_mod = modules[TEST_PKG + ".common.m_ini_builder"]

    time_shapekey = m_key_mod.M_Key()
    time_shapekey.key_name = "$shapekey1"
    time_shapekey.key_type = "time_shapekey"
    time_shapekey.fps = 12.0
    time_shapekey.value_list = [0, 1, 2]
    time_shapekey.weight_list = [0.0, 0.5, 1.0]

    section = ini_builder_mod.M_IniSection(ini_builder_mod.M_SectionType.Present)
    ini_helper_mod.M_IniHelper.append_time_shapekey_weight_lines(section, time_shapekey)
    text = "\n".join(str(line) for line in section.SectionLineList)

    # The local frame counter drives the weight through an if/elif chain.
    assert "local $shapekey1_frame" in text, text
    expected_step = repr(1.0 / 12.0)
    assert "$shapekey1_frame = ((time % (" + expected_step + " * 3)) // " + expected_step + ") % 3" in text, text
    assert "if $shapekey1_frame == 0" in text, text
    assert "$shapekey1 = 0.0" in text, text
    assert "elif $shapekey1_frame == 1" in text, text
    assert "$shapekey1 = 0.5" in text, text
    assert "elif $shapekey1_frame == 2" in text, text
    assert "$shapekey1 = 1.0" in text, text
    assert "endif" in text, text

    print("test_time_shapekey_weight_lines OK")


def test_time_shapekey_full_sections(modules):
    """The shared shapekey writer: plain global, no [Key], Present timeline."""
    m_key_mod = modules[TEST_PKG + ".common.m_key"]
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    ini_builder_mod = modules[TEST_PKG + ".common.m_ini_builder"]

    time_shapekey = m_key_mod.M_Key()
    time_shapekey.key_name = "$shapekey0"
    time_shapekey.key_type = "time_shapekey"
    time_shapekey.fps = 12.0
    time_shapekey.value_list = [0, 1]
    time_shapekey.weight_list = [0.0, 1.0]
    time_shapekey.initialize_vk_str = "VK_F2"  # must be ignored for time keys

    hotkey_shapekey = m_key_mod.M_Key()
    hotkey_shapekey.key_name = "$shapekey1"
    hotkey_shapekey.initialize_vk_str = "VK_F3"

    TEST_SHAPEKEY_DICT.clear()
    TEST_SHAPEKEY_DICT["Blink"] = time_shapekey
    TEST_SHAPEKEY_DICT["Smile"] = hotkey_shapekey

    draw_ib = "65b9cf5a"
    # Describe the actual layout, not just its stride, as the writer validates
    # semantics and packed formats before selecting the matching shader.
    game_type = types.SimpleNamespace(CategoryStrideDict={"Position": 12}, D3D11ElementList=[
        types.SimpleNamespace(Category="Position", SemanticName="POSITION", Format="R32G32B32_FLOAT", ByteWidth=12)
    ])
    fake_drawib = types.SimpleNamespace(
        shapekey_name_bytelist_dict={"Blink": b"x", "Smile": b"y"},
        d3d11_game_type=game_type,
        draw_number=100,
        get_category_buffer_filename=lambda category: draw_ib + "-" + category + ".buf",
    )

    ini_builder = ini_builder_mod.M_IniBuilder()
    ini_helper_mod.M_IniHelper.add_shapekey_ini_sections(
        ini_builder=ini_builder,
        drawib_drawibmodel_dict={draw_ib: fake_drawib},
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        ini_text = build_ini_text(ini_builder, os.path.join(temp_dir, "sk.ini"))

    # Time-driven weight: plain global, never persist, no hotkey section.
    assert "global $shapekey0 = 0" in ini_text, ini_text
    assert "persist $shapekey0" not in ini_text, ini_text
    assert "Key_ShapeKey_Blink" not in ini_text, ini_text

    # The hotkey-driven weight is unchanged.
    assert "global persist $shapekey1 = 0" in ini_text, ini_text
    assert "[Key_ShapeKey_Smile]" in ini_text, ini_text

    # The weight timeline sits in [Present] before the per-frame compute
    # dispatch (the first_run block also dispatches once, so compare against
    # the LAST dispatch line, which is the per-frame one).
    assert "local $shapekey0_frame" in ini_text, ini_text
    assert "if $shapekey0_frame == 0" in ini_text, ini_text
    assert "$shapekey0 = 1.0" in ini_text, ini_text
    timeline_index = ini_text.index("local $shapekey0_frame")
    dispatch_index = ini_text.rindex("run = CustomShaderComputeShapes1")
    assert timeline_index < dispatch_index, "weight timeline must precede the per-frame compute dispatch:\n" + ini_text

    # Multiple contributors must serialize one singleton section, and the
    # old initialization pass must not dispatch a second time after reload.
    assert ini_text.count("[Present]") == 1 and ini_text.count("[Constants]") == 1
    assert "shapekey_first_run" not in ini_text
    assert ini_text.count("run = CustomShaderComputeShapes1") == 1
    assert "cs = shapes_position.hlsl" in ini_text
    assert "Dispatch = 2,1,1" in ini_text
    assert "type = StructuredBuffer" in ini_text
    assert "cs-t50 = ref Resource65b9cf5aPosition.1" in ini_text
    assert "cs-u5 = ref Resource65b9cf5aShapeBackup_cs-u5" in ini_text
    # A structured accumulator is compute-only: copy into a raw VB before
    # referencing it from the game's vertex slot (verified with D3D11 WARP).
    assert "Resource65b9cf5aPosition = ref cs-u5" not in ini_text
    assert "PositionComputed = copy cs-u5" in ini_text
    assert "bind_flags = vertex_buffer" in ini_text
    print("test_time_shapekey_full_sections OK")


def test_combined_animation_sections(modules):
    """Combine all contributors, the path that formerly duplicated headers.

    Shape deltas must use the immutable reference, while only the accumulator
    reads the frame seed. Gated/off and empty-frame states restore the base.
    """
    builder = modules[TEST_PKG + ".common.m_ini_builder"].M_IniBuilder()
    helper = modules[TEST_PKG + ".common.m_ini_helper"].M_IniHelper
    blueprint = make_fake_blueprint_model(modules)
    model = make_fake_drawib_model({"Blink": b"x", "Smile": b"y"})
    model.vertex_count = 65
    helper.add_branch_key_sections(builder, blueprint.keyname_mkey_dict, blueprint, [model])
    helper.add_shapekey_ini_sections(builder, {model.draw_ib: model})
    with tempfile.TemporaryDirectory() as folder:
        text = build_ini_text(builder, os.path.join(folder, "combined.ini"))
        # WWMI uses the append-order serializer; separated contributions must
        # remain singleton sections there too, including repeated serialization.
        unordered_path = os.path.join(folder, "append_order.ini")
        builder.save_to_file_not_reorder(unordered_path)
        with open(unordered_path, encoding="utf-8") as file:
            unordered_text = file.read()
        assert unordered_text.count("[Present]") == unordered_text.count("[Constants]") == 1
        assert build_ini_text(builder, os.path.join(folder, "repeat.ini")) == text
    assert text.count("[Present]") == text.count("[Constants]") == 1
    assert "Resource65b9cf5aPosition.1 = copy" not in text
    assert "cs-u5 = copy Resource65b9cf5aPositionTimeBase" in text
    assert "cs-t50 = ref Resource65b9cf5aPosition.1" in text
    assert "Resource65b9cf5aPositionTimeBase = copy Resource65b9cf5aPositionTimeOriginal" in text
    # The cache compares the selected frame, including -1 for inactive gates,
    # so identical rendered frames do not cause redundant full-buffer copies.
    assert "if $mimi_pos_65b9cf5a_dyntime0_selected != $mimi_pos_65b9cf5a_dyntime0" in text
    assert text.index("$dyntime0 = ((time") < text.index("local $mimi_pos_")
    # Gate-sensitive copies and shape compute run after input handling, in
    # this order, so a hotkey change cannot leave the next draw on an old seed.
    assert text.index("post run = CommandListMimiTimePosition") < text.index("post run = CustomShaderComputeShapes1")
    assert "[CommandListMimiTimePosition]" in text
    print("test_combined_animation_sections OK")


def main():
    ensure_parent_packages()
    install_stubs()
    modules = load_real_modules()
    test_time_position_sections(modules)
    test_time_position_shapekey_composition(modules)
    test_time_position_support_error(modules)
    test_time_shapekey_weight_lines(modules)
    test_time_shapekey_full_sections(modules)
    test_combined_animation_sections(modules)
    print("ALL TIME POSITION/SHAPEKEY TESTS PASSED")


if __name__ == "__main__":
    main()
