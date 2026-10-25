"""Verifies exact original-format conversion for the replacement nodes.

Runs outside Blender, like test_texture_bind_ini.py: the bpy-dependent imports
of the modules under test are replaced with light stubs, while the real
Blender-free texcomb pipeline and the real texconv.exe perform the conversion.

Covered cases:
1. A Slot Texture Bind FILE row converts a PNG to the captured BC7 format,
   the generated name ends with .dds and a stale .png sibling is removed.
2. A Hash Texture Bind FILE row replaces a Hash mark with a PNG without the
   old "file formats differ" error, and keeps the marked .dds filename.
3. A manual format override converts when no capture can be resolved.
4. Conflicting captures on one slot are not guessed: the row stays a copy.
5. The global switch restores the historical copy-as-is behaviour.
"""

# Conversion is asserted on the produced DDS header, not on a file name.
# A stale sibling from an earlier export must not survive next to the .dds.
# The manual override only applies when no capture exists, matching export.
# Conflicting captures keep the raw copy instead of picking one at random.
import importlib.util
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Plain `python tools/test_texture_format_conversion.py` starts with the tools
# folder on sys.path; the add-on packages live one level up.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TEST_PKG = "texture_format_conversion_test_pkg"

HASH_RED = "0123abcd"


def load_module_by_path(module_name, file_path):
    """Load one python file under an explicit dotted module name."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def ensure_parent_packages():
    """Register the synthetic addon packages with real search paths."""
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
        # Real directories let the pure texcomb packages import normally.
        sys.modules[package_name].__path__ = [os.path.join(ROOT, *package_name.split('.')[1:])]
    # The model layer falls back to this scan only when no local mark matched.
    marks = types.ModuleType(TEST_PKG + ".blueprint.blueprint_node_hash_texture")
    marks._load_global_hash_mark_entries = lambda: []
    sys.modules[marks.__name__] = marks


def install_stubs():
    """Stub every bpy-dependent import of the modules under test."""
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.ndarray = object
    sys.modules["numpy"] = numpy_stub

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

    properties_stub = types.ModuleType(TEST_PKG + ".common.mimi_global_properties")

    class MIMIGlobalProperties:
        # Tests flip this flag to exercise the fallback path.
        exact_texture_enabled = True

        @staticmethod
        def forbid_auto_texture_ini():
            return False

        @classmethod
        def exact_texture_format_enabled(cls):
            return cls.exact_texture_enabled

        @staticmethod
        def exact_texture_resize_filter_name():
            return "FANT"

    properties_stub.MIMIGlobalProperties = MIMIGlobalProperties
    sys.modules[TEST_PKG + ".common.mimi_global_properties"] = properties_stub

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
    """Load the bpy-free addon modules for real, by file path."""
    modules = {}
    for dotted, relative in (
        (TEST_PKG + ".common.m_key", "common/m_key.py"),
        (TEST_PKG + ".common.m_ini_builder", "common/m_ini_builder.py"),
        (TEST_PKG + ".common.m_control_flow", "common/m_control_flow.py"),
        (TEST_PKG + ".common.gimi_texture_slots", "common/gimi_texture_slots.py"),
        (TEST_PKG + ".common.texture_naming", "common/texture_naming.py"),
        (TEST_PKG + ".common.texture_output_naming", "common/texture_output_naming.py"),
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

    def __init__(self, mark_name, mark_type, slot="ps-t0", filename="", mark_hash=""):
        self.mark_name = mark_name
        self.mark_type = mark_type
        self.mark_slot = slot
        self.mark_hash = mark_hash
        self.mark_filename = filename or (mark_name + ".dds")

    def get_resource_name(self):
        return "Resource-" + self.mark_filename.split(".")[0]


class FakeSubmeshModel:
    """Minimal stand-in for SubMeshModel (only what the resolver reads)."""

    def __init__(self, submesh_name, drawcall_model_list):
        self.submesh_name = submesh_name
        self.drawcall_model_list = drawcall_model_list


def make_binding(source_type, slot="ps-t0", **kwargs):
    """Build one Texture Bind row dict as BluePrintModel would collect it."""
    binding = {
        "enabled": True,
        "slot": slot,
        "source_type": source_type,
        "mark_name": "",
        "file_path": "",
        "resource_name": "",
        "restore_after_draw": False,
        "format_mode": "AUTO",
        "manual_format": "",
        "force_original_size": False,
        "node_label": "TestBind",
    }
    binding.update(kwargs)
    return binding


def make_drawib(modules, draw_ib, submesh_list, markup_dict):
    """Build a DrawIBModel without running __post_init__ (needs Blender)."""
    drawib_mod = modules[TEST_PKG + ".model.drawib_model"]
    drawib_model = drawib_mod.DrawIBModel.__new__(drawib_mod.DrawIBModel)
    drawib_model.draw_ib = draw_ib
    drawib_model.submesh_model_list = submesh_list
    drawib_model.submesh_texturemarkinfolist_dict = markup_dict
    drawib_model.object_texture_binding_resource_list = []
    drawib_model.object_texture_binding_file_list = []
    drawib_model.exact_texture_jobs = {}
    return drawib_model


def build_original(dds_match, tmp_dir, name, pixel_format, size=(64, 64)):
    """Create one genuine captured DDS with the bundled texconv."""
    from PIL import Image
    source = os.path.join(tmp_dir, name + ".png")
    Image.new("RGBA", size, (40, 80, 120, 255)).save(source)
    header = "-dx10" if "BC7" in pixel_format or "BC5" in pixel_format else "-dx9"
    from texcomb.core.texconv import _run_texconv
    _run_texconv(["-f", pixel_format, header, "-m", "0", "-y", "-o", tmp_dir, source])
    return os.path.join(tmp_dir, name + ".dds")


def make_png(path, size=(32, 32), color=(70, 20, 90, 255)):
    """Write a small replacement image."""
    from PIL import Image
    Image.new("RGBA", size, color).save(path)
    return path


def main():
    """Run every scenario; returns a process exit code."""
    from texcomb.core import dds_match, texconv
    if not texconv.is_available():
        print("SKIP: texconv.exe is not available")
        return 0
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("SKIP: Pillow is required to build the test fixtures")
        return 0

    ensure_parent_packages()
    install_stubs()
    modules = load_real_modules()
    draw_call_mod = modules[TEST_PKG + ".model.draw_call_model"]
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    properties_mod = sys.modules[TEST_PKG + ".common.mimi_global_properties"]
    config_mod = sys.modules[TEST_PKG + ".common.global_config"]

    tmp_dir = tempfile.mkdtemp(prefix="mimi_texfmt_")
    texture_root = os.path.join(tmp_dir, "mod")
    os.makedirs(texture_root, exist_ok=True)
    config_mod.GlobalConfig._texture_root = texture_root

    bc7_original = build_original(dds_match, tmp_dir, "bc7_original", "BC7_UNORM_SRGB")
    bc3_original = build_original(dds_match, tmp_dir, "bc3_original", "BC3_UNORM_SRGB")
    original_meta = dds_match.read_dds_metadata(bc7_original)
    replacement_png = make_png(os.path.join(tmp_dir, "replacement.png"))

    # --- 1. Slot node FILE row converts to the captured format ----------
    call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_A", submesh_name="94517393-0")
    call.texture_slot_binding_list = [
        make_binding("FILE", slot="ps-t0", file_path=replacement_png),
    ]
    markup = {"94517393-0": [FakeMarkup("DiffuseMap", "Slot", slot="ps-t0", filename="diffuse.dds")]}
    ini_helper_mod.M_IniHelper._get_slot_texture_source_path = classmethod(
        lambda cls, draw_ib_model, part_name, texture_markup_info: bc7_original
    )
    model = make_drawib(modules, "94517393", [FakeSubmeshModel("94517393-0", [call])], markup)
    model.resolve_texture_slot_bindings()

    assert len(model.object_texture_binding_file_list) == 1, model.object_texture_binding_file_list
    resource, source_path, target_name = model.object_texture_binding_file_list[0]
    assert source_path == replacement_png
    assert target_name.endswith(".dds"), target_name
    assert resource in model.exact_texture_jobs, model.exact_texture_jobs
    job = model.exact_texture_jobs[resource]
    assert job["original_path"] == bc7_original, job

    # Prepare a stale .png sibling exactly like a previous release would leave.
    stale_dir = os.path.join(texture_root, "94517393")
    os.makedirs(stale_dir, exist_ok=True)
    stale_png = os.path.join(stale_dir, os.path.splitext(target_name)[0] + ".png")
    with open(stale_png, "wb") as file:
        file.write(b"stale png bytes")

    ini_helper_mod.M_IniHelper.move_object_texture_binding_files(draw_ib_model=model)
    produced = os.path.join(stale_dir, target_name)
    assert os.path.isfile(produced), produced
    produced_meta = dds_match.read_dds_metadata(produced)
    assert produced_meta.storage_key == original_meta.storage_key, produced_meta
    assert produced_meta.format == "BC7_UNORM_SRGB", produced_meta.format
    assert not os.path.isfile(stale_png), "stale .png sibling must be removed"
    print("PASS slot FILE row converts to the captured BC7 format")

    # --- 2. Hash node FILE row replaces a Hash mark with a PNG ----------
    hash_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_B", submesh_name="94517393-0")
    hash_call.hash_texture_binding_list = [{
        "enabled": True,
        "texture_hash": HASH_RED,
        "source_type": "FILE",
        "mark_name": "HairMark",
        "mark_slot": "ps-t1",
        "file_path": replacement_png,
        "resource_name": "",
        "legacy_slotless": True,
        "preserve_mark_filename": False,
        "restore_original": False,
        "format_mode": "AUTO",
        "manual_format": "",
        "force_original_size": False,
        "node_label": "TestHashBind",
    }]
    hash_markup = {"94517393-0": [
        FakeMarkup("HairMark", "Hash", slot="ps-t1", filename="hair.dds", mark_hash=HASH_RED),
    ]}
    hash_model = make_drawib(modules, "94517393", [FakeSubmeshModel("94517393-0", [hash_call])], hash_markup)
    hash_model.resolve_hash_texture_bindings()
    # A row that knows its slot binds inside the object's draw section.
    hash_rows = hash_call.resolved_hash_slot_binding_list
    assert len(hash_rows) == 1, hash_rows
    hash_jobs = hash_model.exact_texture_jobs
    assert len(hash_jobs) == 1, hash_jobs
    hash_target = hash_model.object_texture_binding_file_list[0][2]
    assert hash_target.endswith(".dds"), hash_target
    print("PASS hash FILE row accepts a PNG and keeps the marked .dds name")

    # --- 3. Manual format override without any capture -------------------
    manual_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_C", submesh_name="94517393-0")
    manual_call.texture_slot_binding_list = [
        make_binding(
            "FILE", slot="ps-t2", file_path=replacement_png,
            format_mode="MANUAL", manual_format="BC7_UNORM",
        ),
    ]
    ini_helper_mod.M_IniHelper._get_slot_texture_source_path = classmethod(
        lambda cls, draw_ib_model, part_name, texture_markup_info: ""
    )
    manual_model = make_drawib(modules, "94517393", [FakeSubmeshModel("94517393-0", [manual_call])], {"94517393-0": []})
    manual_model.resolve_texture_slot_bindings()
    assert len(manual_model.exact_texture_jobs) == 1, manual_model.exact_texture_jobs
    manual_job = list(manual_model.exact_texture_jobs.values())[0]
    assert manual_job["manual_format"] == "BC7_UNORM", manual_job
    ini_helper_mod.M_IniHelper.move_object_texture_binding_files(draw_ib_model=manual_model)
    manual_target = os.path.join(
        texture_root, "94517393", manual_model.object_texture_binding_file_list[0][2],
    )
    assert dds_match.read_dds_metadata(manual_target).format == "BC7_UNORM"
    print("PASS manual format override converts without a capture")

    # --- 4. Conflicting captures are never guessed ----------------------
    conflict_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_D", submesh_name="94517393-0")
    conflict_call.texture_slot_binding_list = [
        make_binding("FILE", slot="ps-t0", file_path=replacement_png),
    ]
    conflict_markup = {"94517393-0": [
        FakeMarkup("DiffuseA", "Slot", slot="ps-t0", filename="diffuse_a.dds"),
        FakeMarkup("DiffuseB", "Slot", slot="ps-t0", filename="diffuse_b.dds"),
    ]}
    paths = {"DiffuseA": bc7_original, "DiffuseB": bc3_original}
    ini_helper_mod.M_IniHelper._get_slot_texture_source_path = classmethod(
        lambda cls, draw_ib_model, part_name, texture_markup_info: paths[texture_markup_info.mark_name]
    )
    conflict_model = make_drawib(
        modules, "94517393", [FakeSubmeshModel("94517393-0", [conflict_call])], conflict_markup,
    )
    conflict_model.resolve_texture_slot_bindings()
    assert conflict_model.exact_texture_jobs == {}, conflict_model.exact_texture_jobs
    conflict_target = conflict_model.object_texture_binding_file_list[0][2]
    assert conflict_target.endswith(".png"), conflict_target
    print("PASS conflicting captures keep the raw copy")

    # --- 5. The global switch restores the old behaviour ----------------
    properties_mod.MIMIGlobalProperties.exact_texture_enabled = False
    disabled_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_E", submesh_name="94517393-0")
    disabled_call.texture_slot_binding_list = [
        make_binding("FILE", slot="ps-t0", file_path=replacement_png),
    ]
    ini_helper_mod.M_IniHelper._get_slot_texture_source_path = classmethod(
        lambda cls, draw_ib_model, part_name, texture_markup_info: bc7_original
    )
    disabled_model = make_drawib(
        modules, "94517393", [FakeSubmeshModel("94517393-0", [disabled_call])], markup,
    )
    disabled_model.resolve_texture_slot_bindings()
    assert disabled_model.exact_texture_jobs == {}, disabled_model.exact_texture_jobs
    assert disabled_model.object_texture_binding_file_list[0][2].endswith(".png")
    properties_mod.MIMIGlobalProperties.exact_texture_enabled = True
    print("PASS the global switch restores the copy-as-is behaviour")

    print("ALL TEXTURE FORMAT CONVERSION TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
