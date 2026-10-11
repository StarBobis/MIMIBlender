"""Smoke test for the Time Switch (wall-clock driven) INI output.

Runs outside Blender: the bpy-dependent imports of common/m_ini_helper.py are
replaced with light stubs, so the pure INI generation logic can be verified
directly.  The test checks that:

1. time-driven variables are plain globals, not persisted user settings,
   avoiding dirty settings and stale clock values restored on reload,
2. the [Present] section recomputes them with
   "$name = ((time % (step * count)) // step) % count",
3. no [KeySwap] section is emitted for time-driven variables while regular
   hotkey variables still get theirs,
4. DrawCallModel conditions for a time variable come out as "$name == N"
   (safe because "//" floor division yields exact integer-valued floats),
5. the frame formula itself yields exact integers in [0, count) over a sweep
   of wall-clock times (float32 rounding after every INI operator).
"""

import importlib.util
import math
import struct
import os
import sys
import tempfile
import types

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Synthetic package name used to load addon modules by file path, so the
# real addon package (which imports bpy) is never touched.
TEST_PKG = "time_switch_ini_test_pkg"


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


def install_stubs():
    """Stub the bpy-dependent imports of common/m_ini_helper.py."""
    # common.global_config: only generated_mod_number is read by the tested function.
    config_stub = types.ModuleType(TEST_PKG + ".common.global_config")

    class GlobalConfig:
        generated_mod_number = 1

    config_stub.GlobalConfig = GlobalConfig
    sys.modules[TEST_PKG + ".common.global_config"] = config_stub

    # common.mimi_global_properties: unused by the tested function.
    properties_stub = types.ModuleType(TEST_PKG + ".common.mimi_global_properties")

    class MIMIGlobalProperties:
        pass

    properties_stub.MIMIGlobalProperties = MIMIGlobalProperties
    sys.modules[TEST_PKG + ".common.mimi_global_properties"] = properties_stub

    # model.drawib_model: only used as a type hint inside m_ini_helper.
    drawib_stub = types.ModuleType(TEST_PKG + ".model.drawib_model")

    class DrawIBModel:
        pass

    drawib_stub.DrawIBModel = DrawIBModel
    sys.modules[TEST_PKG + ".model.drawib_model"] = drawib_stub

    # utils.format_utils: only Fatal is imported by m_ini_helper.
    format_stub = types.ModuleType(TEST_PKG + ".utils.format_utils")

    class Fatal(Exception):
        pass

    format_stub.Fatal = Fatal
    sys.modules[TEST_PKG + ".utils.format_utils"] = format_stub

    # workspace / blueprint modules: unused by the tested function.
    workspace_stub = types.ModuleType(TEST_PKG + ".workspace.mmt_workspace")

    class MMTWorkSpace:
        pass

    workspace_stub.MMTWorkSpace = MMTWorkSpace
    sys.modules[TEST_PKG + ".workspace.mmt_workspace"] = workspace_stub

    export_helper_stub = types.ModuleType(TEST_PKG + ".blueprint.blueprint_export_helper")

    class BlueprintExportHelper:
        pass

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
        (TEST_PKG + ".common.m_ini_builder", "common/m_ini_builder.py"),
        (TEST_PKG + ".common.m_control_flow", "common/m_control_flow.py"),
        (TEST_PKG + ".common.texture_naming", "common/texture_naming.py"),
        (TEST_PKG + ".utils.mmt_error_utils", "utils/mmt_error_utils.py"),
        (TEST_PKG + ".utils.json_utils", "utils/json_utils.py"),
        (TEST_PKG + ".model.draw_call_model", "model/draw_call_model.py"),
        (TEST_PKG + ".common.m_ini_helper", "common/m_ini_helper.py"),
    ):
        modules[dotted] = load_module_by_path(dotted, os.path.join(ROOT, relative))
    return modules


def build_ini_text(ini_builder, ini_path):
    """Render the builder into a file and read the text back."""
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as file:
        return file.read()


def test_time_key_sections(modules):
    m_key_mod = modules[TEST_PKG + ".common.m_key"]
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    ini_builder_mod = modules[TEST_PKG + ".common.m_ini_builder"]

    time_key = m_key_mod.M_Key()
    time_key.key_name = "$dyntime0"
    time_key.key_type = "time"
    time_key.fps = 12.0
    time_key.value_list = [0, 1, 2]
    time_key.initialize_value = 0
    time_key.comment = "test anim"

    hot_key = m_key_mod.M_Key()
    hot_key.key_name = "$swapkey0"
    hot_key.value_list = [0, 1]
    hot_key.initialize_value = 0
    hot_key.initialize_vk_str = "VK_F1"

    key_dict = {"$dyntime0": time_key, "$swapkey0": hot_key}

    ini_builder = ini_builder_mod.M_IniBuilder()
    ini_helper_mod.M_IniHelper.add_branch_key_sections(
        ini_builder=ini_builder, key_name_mkey_dict=key_dict
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        ini_path = os.path.join(temp_dir, "time_switch.ini")
        ini_text = build_ini_text(ini_builder, ini_path)

    # 1. Time variable is a plain global, the hotkey variable stays persist.
    assert "global $dyntime0 = 0\n" in ini_text, "time variable must be a plain global:\n" + ini_text
    assert "persist $dyntime0" not in ini_text, "time variable must never be persist:\n" + ini_text
    assert "global persist $swapkey0 = 0\n" in ini_text, "hotkey variable must stay persist:\n" + ini_text

    # 2. [Present] recomputes the time variable from wall-clock time.
    expected_step = repr(1.0 / 12.0)
    expected_line = "$dyntime0 = ((time % (" + expected_step + " * 3)) // " + expected_step + ") % 3"
    assert expected_line in ini_text, "missing Present update line:\n" + ini_text

    # 3. No [KeySwap] section for the time variable, one for the hotkey one.
    assert ini_text.count("[KeySwap_") == 1, "exactly one hotkey section expected:\n" + ini_text
    assert "[KeySwap_0]" in ini_text and "$swapkey0 = 0,1" in ini_text

    print("test_time_key_sections OK")


def test_time_condition_str(modules):
    """A time key on a DrawCallModel must produce the usual == condition."""
    m_key_mod = modules[TEST_PKG + ".common.m_key"]
    draw_call_mod = modules[TEST_PKG + ".model.draw_call_model"]

    time_key = m_key_mod.M_Key()
    time_key.key_name = "$dyntime0"
    time_key.key_type = "time"
    time_key.tmp_value = 3

    draw_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Face")
    draw_call.work_key_list = [time_key]
    assert draw_call.get_condition_str() == "$dyntime0 == 3", draw_call.get_condition_str()

    print("test_time_condition_str OK")


def test_frame_formula_exactness():
    """Round after each operator, just like CommandList float evaluation.

    Double-only sweeps missed out-of-range indices near a cycle boundary.
    Probe adjacent representable float32 times as well as long-running clocks;
    the final modulo must always leave a valid, exactly comparable frame.
    """
    def f32(value):
        return struct.unpack("<f", struct.pack("<f", value))[0]

    for fps in (0.01, 12.0, 23.976, 29.97, 60.0, 120.0):
        for count in (1, 3, 24, 997):
            step = f32(1.0 / fps)
            cycle = f32(step * count)
            times = [i * 0.031 for i in range(2000)] + [86400.0, 1234567.0]
            # Enumerate float32 neighbours, not tiny double-only epsilons.
            for boundary in (step, cycle, cycle * 10):
                bits = struct.unpack("<I", struct.pack("<f", boundary))[0]
                times += [struct.unpack("<f", struct.pack("<I", bits + delta))[0] for delta in (-1, 0, 1)]
            for time_value in times:
                remainder = f32(math.fmod(f32(time_value), cycle))
                frame = f32(math.fmod(f32(math.floor(f32(remainder / step))), count))
                assert frame == int(frame) and 0 <= frame < count, (fps, count, time_value, frame)
    print("test_frame_formula_exactness OK")


def main():
    ensure_parent_packages()
    install_stubs()
    modules = load_real_modules()
    test_time_key_sections(modules)
    test_time_condition_str(modules)
    test_frame_formula_exactness()
    print("ALL TIME SWITCH TESTS PASSED")


if __name__ == "__main__":
    main()
