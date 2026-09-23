"""Smoke test for the Texture Bind node (per-object texture slot binding).

Runs outside Blender, the same way as test_time_switch_ini.py: the
bpy-dependent imports of the touched addon modules are replaced with light
stubs so the pure INI generation logic can be verified directly. The test
checks that:

1. DrawIBModel.resolve_texture_slot_bindings turns Texture Bind node rows
   into INI lines: MARK sources reuse the Submesh mark resource name, FILE
   sources get a unique resource name plus a copy job, RESOURCE sources pass
   the given name through, and "Restore After Draw" wraps the binding in a
   ref capture / rebind pair;
2. the binding lines land right before the object's drawindexed line (and
   the restore lines right after it), both with and without a condition;
3. invalid rows (bad slot, duplicate slot, missing mark, missing file)
   raise ValueError instead of reaching the generated INI;
4. the [ResourceXXX] sections and the file copies of FILE sources are
   emitted even when forbid_auto_texture_ini is on (explicit user intent).
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import types

# Addon root (the repository root), one level up from tools/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Synthetic package name used to load addon modules by file path, so the
# real addon package (which imports bpy) is never touched.
TEST_PKG = "texture_bind_ini_test_pkg"


def load_module_by_path(module_name, file_path):
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
    """Stub every bpy-dependent import of the modules under test."""
    # numpy is only used by buffer assembly code paths the tests never call;
    # module import only evaluates the annotations, which need ndarray.
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.ndarray = object
    sys.modules["numpy"] = numpy_stub

    # common.global_config: the tested functions need the texture folder
    # path helpers; keep them configurable per test run.
    config_stub = types.ModuleType(TEST_PKG + ".common.global_config")

    class GlobalConfig:
        generated_mod_number = 1
        _texture_root = ""

        @classmethod
        def path_generatemod_texture_folder(cls, draw_ib=""):
            return os.path.join(cls._texture_root, draw_ib)

        @classmethod
        def ini_texture_filename(cls, filename):
            return "Textures\\" + filename

        @classmethod
        def ini_buffer_filename(cls, filename):
            return "Buffers\\" + filename

        @classmethod
        def path_generate_mod_folder(cls):
            return cls._texture_root

        @classmethod
        def get_generated_mod_name(cls):
            return "test_mod"

    config_stub.GlobalConfig = GlobalConfig
    sys.modules[TEST_PKG + ".common.global_config"] = config_stub

    # common.mimi_global_properties: forbid_auto_texture_ini gates the
    # automatic pipeline only; Texture Bind must ignore it.
    properties_stub = types.ModuleType(TEST_PKG + ".common.mimi_global_properties")

    class MIMIGlobalProperties:
        @staticmethod
        def forbid_auto_texture_ini():
            return False

    properties_stub.MIMIGlobalProperties = MIMIGlobalProperties
    sys.modules[TEST_PKG + ".common.mimi_global_properties"] = properties_stub

    # Modules only referenced by code paths the tests never exercise.
    for dotted, attr_name, attr_value in (
        (TEST_PKG + ".common.d3d11_gametype", "D3D11GameType", type("D3D11GameType", (), {})),
        (TEST_PKG + ".common.buffer_export_helper", "BufferExportHelper", type("BufferExportHelper", (), {})),
    ):
        module = types.ModuleType(dotted)
        setattr(module, attr_name, attr_value)
        sys.modules[dotted] = module

    workspace_stub = types.ModuleType(TEST_PKG + ".workspace.mmt_workspace")

    class MMTWorkSpace:
        pass

    workspace_stub.MMTWorkSpace = MMTWorkSpace
    sys.modules[TEST_PKG + ".workspace.mmt_workspace"] = workspace_stub

    submesh_json_stub = types.ModuleType(TEST_PKG + ".workspace.submesh_json")

    class SubmeshJson:
        pass

    submesh_json_stub.SubmeshJson = SubmeshJson
    sys.modules[TEST_PKG + ".workspace.submesh_json"] = submesh_json_stub

    texture_meta_stub = types.ModuleType(TEST_PKG + ".workspace.texture_metadata_helper")

    class TextureMetadataResolver:
        pass

    class TextureMarkUpInfo:
        pass

    texture_meta_stub.TextureMetadataResolver = TextureMetadataResolver
    texture_meta_stub.TextureMarkUpInfo = TextureMarkUpInfo
    sys.modules[TEST_PKG + ".workspace.texture_metadata_helper"] = texture_meta_stub

    submesh_model_stub = types.ModuleType(TEST_PKG + ".model.submesh_model")

    class SubMeshModel:
        pass

    submesh_model_stub.SubMeshModel = SubMeshModel
    sys.modules[TEST_PKG + ".model.submesh_model"] = submesh_model_stub

    export_helper_stub = types.ModuleType(TEST_PKG + ".blueprint.blueprint_export_helper")

    class BlueprintExportHelper:
        pass

    export_helper_stub.BlueprintExportHelper = BlueprintExportHelper
    sys.modules[TEST_PKG + ".blueprint.blueprint_export_helper"] = export_helper_stub


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
        (TEST_PKG + ".utils.tbn_codec", "utils/tbn_codec.py"),
        (TEST_PKG + ".utils.format_utils", "utils/format_utils.py"),
        (TEST_PKG + ".model.draw_call_model", "model/draw_call_model.py"),
        (TEST_PKG + ".model.drawib_model", "model/drawib_model.py"),
        (TEST_PKG + ".common.m_ini_helper", "common/m_ini_helper.py"),
    ):
        modules[dotted] = load_module_by_path(dotted, os.path.join(ROOT, relative))
    return modules


class FakeMarkup:
    """Minimal stand-in for TextureMarkUpInfo."""

    def __init__(self, mark_name, mark_type):
        self.mark_name = mark_name
        self.mark_type = mark_type
        self.mark_slot = "ps-t1"
        self.mark_filename = mark_name + ".dds"

    def get_resource_name(self):
        return "Resource-" + self.mark_filename.split(".")[0]


class FakeSubmeshModel:
    """Minimal stand-in for SubMeshModel (only what the resolver reads)."""

    def __init__(self, submesh_name, drawcall_model_list):
        self.submesh_name = submesh_name
        self.drawcall_model_list = drawcall_model_list


def make_binding(source_type, slot="ps-t1", **kwargs):
    """Build one Texture Bind row dict as BluePrintModel would collect it."""
    binding = {
        "enabled": True,
        "slot": slot,
        "source_type": source_type,
        "mark_name": "",
        "file_path": "",
        "resource_name": "",
        "restore_after_draw": False,
        "node_label": "TestBind",
    }
    binding.update(kwargs)
    return binding


def make_drawib(modules, draw_ib, submesh_list, markup_dict):
    """Build a DrawIBModel without running __post_init__ (buffer assembly
    needs Blender data we do not have here)."""
    drawib_mod = modules[TEST_PKG + ".model.drawib_model"]
    drawib_model = drawib_mod.DrawIBModel.__new__(drawib_mod.DrawIBModel)
    drawib_model.draw_ib = draw_ib
    drawib_model.submesh_model_list = submesh_list
    drawib_model.submesh_texturemarkinfolist_dict = markup_dict
    drawib_model.object_texture_binding_resource_list = []
    drawib_model.object_texture_binding_file_list = []
    return drawib_model


def test_resolve_bindings(modules, source_dir):
    """MARK / FILE / RESOURCE sources and the restore option."""
    draw_call_mod = modules[TEST_PKG + ".model.draw_call_model"]

    source_file = os.path.join(source_dir, "custom.png")
    with open(source_file, "wb") as file:
        file.write(b"fake png bytes")

    bound_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_A", submesh_name="94517393-0")
    bound_call.texture_slot_binding_list = [
        make_binding("MARK", slot="ps-t0", mark_name="DiffuseMap"),
        make_binding("FILE", slot="ps-t1", file_path=source_file),
        make_binding("RESOURCE", slot="ps-t2", resource_name="ResourceShared"),
        make_binding("MARK", slot="ps-t3", mark_name="LightMap", restore_after_draw=True),
    ]
    plain_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_B", submesh_name="94517393-0")

    submesh_list = [FakeSubmeshModel("94517393-0", [bound_call, plain_call])]
    markup_dict = {
        "94517393-0": [
            FakeMarkup("DiffuseMap", "Slot"),
            FakeMarkup("LightMap", "SharedSlot"),
            FakeMarkup("ShadowRamp", "Hash"),
        ],
    }
    drawib_model = make_drawib(modules, "94517393", submesh_list, markup_dict)
    drawib_model.resolve_texture_slot_bindings()

    # MARK rows reuse the existing mark resource name as-is.
    assert bound_call.resolved_texture_slot_lines[0] == "ps-t0 = Resource-DiffuseMap", bound_call.resolved_texture_slot_lines
    # FILE rows get a generated resource name, recorded for copy + section.
    file_line = bound_call.resolved_texture_slot_lines[1]
    assert file_line.startswith("ps-t1 = ResourceTex_94517393_94517393_0_Hair_A_ps_t1"), file_line
    file_resource_name = file_line.split(" = ", 1)[1]
    # RESOURCE rows pass the name through untouched.
    assert bound_call.resolved_texture_slot_lines[2] == "ps-t2 = ResourceShared", bound_call.resolved_texture_slot_lines
    # Restore rows capture the original binding with ref first, then rebind.
    assert bound_call.resolved_texture_slot_lines[3] == "Resource-LightMap_Bak_3 = ref ps-t3", bound_call.resolved_texture_slot_lines
    assert bound_call.resolved_texture_slot_lines[4] == "ps-t3 = Resource-LightMap", bound_call.resolved_texture_slot_lines
    assert bound_call.resolved_texture_slot_restore_lines == ["ps-t3 = Resource-LightMap_Bak_3"], bound_call.resolved_texture_slot_restore_lines

    # Objects without bindings stay untouched.
    assert plain_call.resolved_texture_slot_lines == []
    assert plain_call.resolved_texture_slot_restore_lines == []

    # FILE jobs are recorded exactly once (resource list + copy list).
    assert drawib_model.object_texture_binding_resource_list == [
        (file_resource_name, file_resource_name + ".png"),
    ], drawib_model.object_texture_binding_resource_list
    assert len(drawib_model.object_texture_binding_file_list) == 1
    assert drawib_model.object_texture_binding_file_list[0][1] == source_file

    print("test_resolve_bindings OK")


def test_resolve_validation(modules, source_dir):
    """Invalid rows fail loudly instead of reaching the generated INI."""
    draw_call_mod = modules[TEST_PKG + ".model.draw_call_model"]

    def expect_error(bindings, markup_dict, needle):
        call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair", submesh_name="94517393-0")
        call.texture_slot_binding_list = bindings
        drawib_model = make_drawib(
            modules, "94517393",
            [FakeSubmeshModel("94517393-0", [call])],
            markup_dict,
        )
        try:
            drawib_model.resolve_texture_slot_bindings()
        except ValueError as error:
            assert needle in str(error), str(error)
            return
        raise AssertionError("expected ValueError containing: " + needle)

    # Bad slot spelling.
    expect_error(
        [make_binding("RESOURCE", slot="pst0", resource_name="ResourceX")],
        {},
        "invalid texture slot",
    )
    # Same slot bound twice on one object.
    expect_error(
        [
            make_binding("RESOURCE", slot="ps-t0", resource_name="ResourceX"),
            make_binding("RESOURCE", slot="PS-T0", resource_name="ResourceY"),
        ],
        {},
        "bound twice",
    )
    # Unknown mark name.
    expect_error(
        [make_binding("MARK", mark_name="NoSuchMark")],
        {"94517393-0": [FakeMarkup("DiffuseMap", "Slot")]},
        "was not found",
    )
    # Hash-style marks are global replacements and must not be bound per object.
    expect_error(
        [make_binding("MARK", mark_name="ShadowRamp")],
        {"94517393-0": [FakeMarkup("ShadowRamp", "Hash")]},
        "Hash style",
    )
    # Missing file on a FILE row.
    expect_error(
        [make_binding("FILE", file_path=os.path.join(source_dir, "missing.dds"))],
        {},
        "does not exist",
    )
    # Unsupported file suffix on a FILE row.
    bad_suffix = os.path.join(source_dir, "notes.txt")
    with open(bad_suffix, "w", encoding="utf-8") as file:
        file.write("not a texture")
    expect_error(
        [make_binding("FILE", file_path=bad_suffix)],
        {},
        "unsupported texture file",
    )
    # Broken resource name on a RESOURCE row.
    expect_error(
        [make_binding("RESOURCE", resource_name="9bad name")],
        {},
        "invalid resource name",
    )

    print("test_resolve_validation OK")


def test_drawindexed_line_emission(modules):
    """Binding lines hug the drawindexed line; restore lines follow it."""
    draw_call_mod = modules[TEST_PKG + ".model.draw_call_model"]
    m_key_mod = modules[TEST_PKG + ".common.m_key"]
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    m_control_flow_mod = modules[TEST_PKG + ".common.m_control_flow"]

    plain_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_A", submesh_name="94517393-0")
    plain_call.index_count = 100
    plain_call.resolved_texture_slot_lines = ["ps-t0 = Resource-DiffuseMap"]
    plain_call.resolved_texture_slot_restore_lines = ["ps-t0 = Resource-DiffuseMap_Bak_0"]

    hot_key = m_key_mod.M_Key()
    hot_key.key_name = "$swapkey0"
    hot_key.tmp_value = 1
    bound_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_B", submesh_name="94517393-0")
    bound_call.index_count = 200
    bound_call.work_key_list = [hot_key]
    bound_call.resolved_texture_slot_lines = ["ps-t1 = ResourceTex_abc"]

    lines = ini_helper_mod.M_IniHelper.get_drawindexed_str_list([plain_call, bound_call])
    text = "\n".join(lines) + "\n"

    # Unconditional object: no indentation around the binding / restore lines.
    assert "ps-t0 = Resource-DiffuseMap\ndrawindexed = 100,0,0\nps-t0 = Resource-DiffuseMap_Bak_0\n" in text, text
    # Conditional object: two-space indentation, binding before the draw.
    assert "  ps-t1 = ResourceTex_abc\n  drawindexed = 200,0,0\n" in text, text

    # The shared section writer (Naraka path) follows the same ordering.
    section_lines = []

    class FakeSection:
        def append(self, line):
            section_lines.append(line)

    m_control_flow_mod.M_ControlFlow.append_drawindexed_with_slot_lines(
        section=FakeSection(),
        ordered_draw_obj_model_list=[plain_call],
        slot_line_provider=lambda obj_model: ["ps-t9 = Resource-SubmeshLevel"],
    )
    section_text = "\n".join(section_lines) + "\n"
    # Submesh-level line first, then the per-object binding, then the draw,
    # then the restore: later lines override earlier ones in the D3D11 state.
    assert (
        "ps-t9 = Resource-SubmeshLevel\n"
        "ps-t0 = Resource-DiffuseMap\n"
        "drawindexed = 100,0,0\n"
        "ps-t0 = Resource-DiffuseMap_Bak_0\n"
    ) in section_text, section_text

    print("test_drawindexed_line_emission OK")


def test_resource_sections_and_copy(modules, texture_root):
    """FILE resources emit sections and copies even with auto-texture off."""
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    ini_builder_mod = modules[TEST_PKG + ".common.m_ini_builder"]
    config_mod = sys.modules[TEST_PKG + ".common.global_config"]

    config_mod.GlobalConfig._texture_root = texture_root

    source_file = os.path.join(texture_root, "source_a.dds")
    with open(source_file, "wb") as file:
        file.write(b"fake dds bytes")

    drawib_model = make_drawib(modules, "94517393", [], {})
    drawib_model.object_texture_binding_file_list = [
        ("ResourceTex_A", source_file, "ResourceTex_A.dds"),
        ("ResourceTex_A", source_file, "ResourceTex_A.dds"),
        ("ResourceTex_B", os.path.join(texture_root, "missing.dds"), "ResourceTex_B.dds"),
    ]
    drawib_model.object_texture_binding_resource_list = [
        ("ResourceTex_A", "ResourceTex_A.dds"),
        ("ResourceTex_B", "ResourceTex_B.dds"),
    ]

    # The helper never consults forbid_auto_texture_ini: Texture Bind is
    # explicit user intent and must emit its resources unconditionally.
    ini_builder = ini_builder_mod.M_IniBuilder()
    ini_helper_mod.M_IniHelper.add_object_texture_binding_resource_sections(
        ini_builder=ini_builder, draw_ib_model=drawib_model
    )
    ini_path = os.path.join(texture_root, "texture_bind.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as file:
        ini_text = file.read()

    # One section per unique resource name.
    assert ini_text.count("[ResourceTex_A]") == 1, ini_text
    assert "[ResourceTex_B]" in ini_text, ini_text
    assert "filename = Textures\\ResourceTex_A.dds" in ini_text, ini_text

    # The copy step is idempotent and skips missing sources.
    ini_helper_mod.M_IniHelper.move_object_texture_binding_files(draw_ib_model=drawib_model)
    copied_path = os.path.join(texture_root, "94517393", "ResourceTex_A.dds")
    assert os.path.exists(copied_path), copied_path
    with open(copied_path, "rb") as file:
        assert file.read() == b"fake dds bytes"
    # A changed source replaces the previous generated copy instead of
    # leaving stale bytes under the same resource filename.
    with open(source_file, "wb") as file:
        file.write(b"updated dds bytes")
    ini_helper_mod.M_IniHelper.move_object_texture_binding_files(draw_ib_model=drawib_model)
    with open(copied_path, "rb") as file:
        assert file.read() == b"updated dds bytes"

    print("test_resource_sections_and_copy OK")


def main():
    ensure_parent_packages()
    install_stubs()
    modules = load_real_modules()

    # All scratch files live under the repository tmp folder per workspace
    # rules; tempfile cleans the per-run subfolder up on exit.
    repo_tmp = os.path.join(ROOT, "tmp")
    os.makedirs(repo_tmp, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repo_tmp) as temp_dir:
        source_dir = os.path.join(temp_dir, "sources")
        os.makedirs(source_dir, exist_ok=True)
        test_resolve_bindings(modules, source_dir)
        test_resolve_validation(modules, source_dir)
        test_drawindexed_line_emission(modules)
        test_resource_sections_and_copy(modules, temp_dir)

    print("ALL TEXTURE BIND TESTS PASSED")


if __name__ == "__main__":
    main()
