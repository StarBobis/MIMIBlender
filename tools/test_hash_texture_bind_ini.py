"""Smoke test for the Hash Texture Bind node (conditional hash-style override).

Runs outside Blender like test_texture_bind_ini.py: bpy-dependent imports are
replaced with light stubs so the pure INI generation logic can be verified
directly. The test checks that:

1. DrawIBModel.resolve_hash_texture_bindings turns Hash Texture Bind node
   rows into (texture_hash, condition_str, resource_name) rows: FILE sources
   get a unique resource name plus a copy job, MARK sources resolve the mark
   file through the workspace helper, RESOURCE sources pass the name through,
   and the object switch condition is captured per row;
2. generate_hash_style_object_texture_ini merges the rows blueprint-wide
   into one [TextureOverride_Texture_<hash>_Switch] section per hash, with
   one if/endif block per condition and a plain this= for unconditional rows;
3. contradictory bindings (same condition, different resources, or mixed
   unconditional + conditional) raise ValueError;
4. the automatic hash pipeline skip hands managed hashes over to the
   conditional sections;
5. unconnected global hash rows copy external and marked texture files and
   emit unconditional global overrides, refreshing copies on re-export.
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
TEST_PKG = "hash_texture_bind_ini_test_pkg"

HASH_RED = "0123abcd"
HASH_BLUE = "fedc9876"


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
        @staticmethod
        def forbid_auto_texture_ini():
            return False

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

    def __init__(self, mark_name, mark_type, mark_hash=HASH_RED):
        self.mark_name = mark_name
        self.mark_type = mark_type
        self.mark_hash = mark_hash
        self.mark_slot = "ps-t1"
        self.mark_filename = mark_name + ".dds"

    def get_resource_name(self):
        return "Resource-" + self.mark_filename.split(".")[0]


class FakeSubmeshModel:
    """Minimal stand-in for SubMeshModel (only what the resolver reads)."""

    def __init__(self, submesh_name, drawcall_model_list):
        self.submesh_name = submesh_name
        self.drawcall_model_list = drawcall_model_list


def make_binding(source_type, texture_hash=HASH_RED, **kwargs):
    """Build one Hash Texture Bind row dict as BluePrintModel collects it."""
    binding = {
        "enabled": True,
        "texture_hash": texture_hash,
        "source_type": source_type,
        "mark_name": "",
        "file_path": "",
        "resource_name": "",
        "node_label": "TestHashBind",
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


def set_condition(modules, draw_model, key_name, value):
    """Attach one switch key condition to a draw call model."""
    m_key_mod = modules[TEST_PKG + ".common.m_key"]
    key = m_key_mod.M_Key()
    key.key_name = key_name
    key.tmp_value = value
    draw_model.work_key_list = [key]


def test_resolve_hash_bindings(modules, source_dir):
    """FILE / MARK / RESOURCE sources and per-row conditions."""
    draw_call_mod = modules[TEST_PKG + ".model.draw_call_model"]
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]

    red_file = os.path.join(source_dir, "hair_red.dds")
    with open(red_file, "wb") as file:
        file.write(b"red")
    mark_file = os.path.join(source_dir, "hair_mark.dds")
    with open(mark_file, "wb") as file:
        file.write(b"mark")

    # MARK source resolves the mark file through the workspace helper; the
    # test points that helper at the stand-in file.
    ini_helper_mod.M_IniHelper._get_slot_texture_source_path = classmethod(
        lambda cls, draw_ib_model, part_name, texture_markup_info: mark_file
    )

    bound_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_A", submesh_name="94517393-0")
    set_condition(modules, bound_call, "$swapkey0", 0)
    bound_call.hash_texture_binding_list = [
        make_binding("FILE", HASH_RED, file_path=red_file),
        make_binding("RESOURCE", HASH_BLUE, resource_name="ResourceSharedBlue"),
        make_binding("MARK", "0123aaaa", mark_name="HairMark"),
    ]
    plain_call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair_B", submesh_name="94517393-0")
    plain_call.hash_texture_binding_list = [
        # An External File with a Hash Source Mark keeps the automatic marked
        # filename instead of inventing a ResourceTex filename.
        make_binding("FILE", HASH_BLUE, file_path=red_file, mark_name="HairMark"),
    ]

    submesh_list = [FakeSubmeshModel("94517393-0", [bound_call, plain_call])]
    markup_dict = {
        "94517393-0": [
            FakeMarkup("HairMark", "Hash"),
            FakeMarkup("BodyDiffuse", "Slot"),
        ],
    }
    drawib_model = make_drawib(modules, "94517393", submesh_list, markup_dict)
    drawib_model.resolve_hash_texture_bindings()

    rows = bound_call.resolved_hash_texture_binding_list
    assert len(rows) == 3, rows
    # The switch condition is captured on every row of the branch.
    assert all(row["condition_str"] == "$swapkey0 == 0" for row in rows), rows
    # FILE rows get a generated resource name, recorded for copy + section.
    assert rows[0]["texture_hash"] == HASH_RED
    assert rows[0]["resource_name"].startswith("ResourceTex_94517393_94517393_0_Hair_A_hash0123abcd"), rows[0]
    # RESOURCE rows pass the name through untouched.
    assert rows[1] == {
        "texture_hash": HASH_BLUE,
        "condition_str": "$swapkey0 == 0",
        "resource_name": "ResourceSharedBlue",
    }, rows[1]
    # MARK rows resolve through the workspace helper and get their own copy.
    assert rows[2]["texture_hash"] == "0123aaaa"
    assert rows[2]["resource_name"].startswith("ResourceTex_"), rows[2]

    # The unconditioned row carries an empty condition string.
    plain_rows = plain_call.resolved_hash_texture_binding_list
    assert len(plain_rows) == 1 and plain_rows[0]["condition_str"] == "", plain_rows

    # FILE/MARK copy jobs landed in the shared job lists. The marked FILE
    # row gets the automatic marked filename, so it is a separate target even
    # though it uses the same source bytes as the plain FILE row.
    assert len(drawib_model.object_texture_binding_file_list) == 3, drawib_model.object_texture_binding_file_list
    assert len(drawib_model.object_texture_binding_resource_list) == 3, drawib_model.object_texture_binding_resource_list
    assert any(job[2] == "0123abcd_HairMark.dds" for job in drawib_model.object_texture_binding_file_list), drawib_model.object_texture_binding_file_list

    # The generated Mod copy uses the marked filename, not the generated
    # ResourceTex name, while taking its bytes from the external source.
    config_mod = sys.modules[TEST_PKG + ".common.global_config"]
    config_mod.GlobalConfig._texture_root = source_dir
    ini_helper_mod.M_IniHelper.move_object_texture_binding_files(draw_ib_model=drawib_model)
    marked_target = os.path.join(source_dir, "94517393", "0123abcd_HairMark.dds")
    assert os.path.exists(marked_target), marked_target
    with open(marked_target, "rb") as file:
        assert file.read() == b"red"

    print("test_resolve_hash_bindings OK")


def test_resolve_hash_validation(modules, source_dir):
    """Invalid rows fail loudly instead of reaching the generated INI."""
    draw_call_mod = modules[TEST_PKG + ".model.draw_call_model"]

    def expect_error(bindings, markup_dict, needle):
        call = draw_call_mod.DrawCallModel(obj_name="94517393-0.Hair", submesh_name="94517393-0")
        call.hash_texture_binding_list = bindings
        drawib_model = make_drawib(
            modules, "94517393",
            [FakeSubmeshModel("94517393-0", [call])],
            markup_dict,
        )
        try:
            drawib_model.resolve_hash_texture_bindings()
        except ValueError as error:
            assert needle in str(error), str(error)
            return
        raise AssertionError("expected ValueError containing: " + needle)

    # Bad hash format.
    expect_error(
        [make_binding("RESOURCE", "xyz123", resource_name="ResourceX")],
        {},
        "invalid texture hash",
    )
    # Same hash bound twice on one object.
    expect_error(
        [
            make_binding("RESOURCE", HASH_RED, resource_name="ResourceX"),
            make_binding("RESOURCE", HASH_RED.upper(), resource_name="ResourceY"),
        ],
        {},
        "bound twice",
    )
    # Unknown mark name.
    expect_error(
        [make_binding("MARK", "0123aaaa", mark_name="NoSuchMark")],
        {"94517393-0": [FakeMarkup("HairMark", "Hash")]},
        "was not found",
    )
    # Slot-style marks belong to the Slot Texture Bind node, not this one.
    expect_error(
        [make_binding("MARK", "0123aaaa", mark_name="BodyDiffuse")],
        {"94517393-0": [FakeMarkup("BodyDiffuse", "Slot")]},
        "only accepts Hash-style marks",
    )
    # Broken resource name on a RESOURCE row.
    expect_error(
        [make_binding("RESOURCE", HASH_RED, resource_name="9bad name")],
        {},
        "invalid resource name",
    )

    print("test_resolve_hash_validation OK")


def build_section_text(modules, texture_root, drawib_dict):
    """Run the section generator and render the builder into text."""
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    ini_builder_mod = modules[TEST_PKG + ".common.m_ini_builder"]
    config_mod = sys.modules[TEST_PKG + ".common.global_config"]
    config_mod.GlobalConfig._texture_root = texture_root

    ini_builder = ini_builder_mod.M_IniBuilder()
    ini_helper_mod.M_IniHelper.generate_hash_style_object_texture_ini(
        ini_builder=ini_builder,
        drawib_drawibmodel_dict=drawib_dict,
    )
    ini_path = os.path.join(texture_root, "hash_bind.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as file:
        return file.read()


def make_resolved_drawib(draw_ib, rows_by_call):
    """Fake drawib model whose draw calls carry resolved hash rows."""
    drawcalls = []
    for condition_str, rows in rows_by_call:
        call = types.SimpleNamespace(
            obj_name=draw_ib + "-0.Hair",
            resolved_hash_texture_binding_list=[
                {"texture_hash": texture_hash, "condition_str": condition_str, "resource_name": resource_name}
                for texture_hash, resource_name in rows
            ],
        )
        drawcalls.append(call)
    submesh = types.SimpleNamespace(submesh_name=draw_ib + "-0", drawcall_model_list=drawcalls)
    return types.SimpleNamespace(submesh_model_list=[submesh])


def test_global_hash_override(modules, texture_root):
    """Unconnected global rows copy files and emit unconditional overrides."""
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]
    ini_builder_mod = modules[TEST_PKG + ".common.m_ini_builder"]
    config_mod = sys.modules[TEST_PKG + ".common.global_config"]
    config_mod.GlobalConfig._texture_root = texture_root

    source_file = os.path.join(texture_root, "global_source.png")
    marked_source_file = os.path.join(texture_root, "marked_source.dds")
    with open(source_file, "wb") as file:
        file.write(b"global bytes v1")
    with open(marked_source_file, "wb") as file:
        file.write(b"marked bytes")

    global_rows = [{
        "enabled": True,
        "texture_hash": HASH_BLUE,
        "source_type": "FILE",
        "file_path": source_file,
        "resource_name": "",
        "node_label": "GlobalTest",
    }, {
        "enabled": True,
        "texture_hash": HASH_RED,
        "source_type": "MARK",
        "file_path": "",
        "mark_name": "DiffuseMap",
        "mark_source_submesh": "94517393-0",
        "mark_source_file_path": marked_source_file,
        "resource_name": "",
        "node_label": "GlobalTest",
    }]
    ini_builder = ini_builder_mod.M_IniBuilder()
    ini_helper_mod.M_IniHelper.generate_hash_style_global_texture_ini(
        ini_builder=ini_builder,
        global_hash_texture_binding_list=global_rows,
    )
    ini_path = os.path.join(texture_root, "global_hash.ini")
    ini_builder.save_to_file(ini_path)
    with open(ini_path, "r", encoding="utf-8") as file:
        ini_text = file.read()

    assert "[ResourceHashGlobal_" + HASH_BLUE + "]" in ini_text, ini_text
    assert "[TextureOverride_Texture_" + HASH_BLUE + "_Global]" in ini_text, ini_text
    assert "this = ResourceHashGlobal_" + HASH_BLUE in ini_text, ini_text
    assert "[ResourceHashGlobal_" + HASH_RED + "]" in ini_text, ini_text
    assert "[TextureOverride_Texture_" + HASH_RED + "_Global]" in ini_text, ini_text

    target_path = os.path.join(texture_root, "global", HASH_BLUE + "_global.png")
    assert os.path.exists(target_path), target_path
    with open(target_path, "rb") as file:
        assert file.read() == b"global bytes v1"
    marked_target_path = os.path.join(texture_root, "global", HASH_RED + "_global.dds")
    with open(marked_target_path, "rb") as file:
        assert file.read() == b"marked bytes"

    # An explicit node selection refreshes an existing generated copy.
    with open(source_file, "wb") as file:
        file.write(b"global bytes v2")
    ini_helper_mod.M_IniHelper.generate_hash_style_global_texture_ini(
        ini_builder=ini_builder_mod.M_IniBuilder(),
        global_hash_texture_binding_list=global_rows,
    )
    with open(target_path, "rb") as file:
        assert file.read() == b"global bytes v2"

    managed = ini_helper_mod.M_IniHelper._collect_hash_binding_managed_hashes(
        {}, global_hash_texture_binding_list=global_rows
    )
    assert managed == {HASH_BLUE, HASH_RED}, managed

    # A global default must serialize before a conditional refinement for the
    # same hash, so a false condition returns to the global replacement.
    ordered_builder = ini_builder_mod.M_IniBuilder()
    ini_helper_mod.M_IniHelper.generate_hash_style_global_texture_ini(
        ini_builder=ordered_builder,
        global_hash_texture_binding_list=global_rows,
    )
    ini_helper_mod.M_IniHelper.generate_hash_style_object_texture_ini(
        ini_builder=ordered_builder,
        drawib_drawibmodel_dict={
            "94517393": make_resolved_drawib("94517393", [
                ("$swapkey0 == 0", [(HASH_BLUE, "ResourceConditional")]),
            ]),
        },
    )
    ordered_path = os.path.join(texture_root, "global_hash_order.ini")
    ordered_builder.save_to_file(ordered_path)
    with open(ordered_path, "r", encoding="utf-8") as file:
        ordered_text = file.read()
    assert ordered_text.index("[TextureOverride_Texture_" + HASH_BLUE + "_Global]") < ordered_text.index("[TextureOverride_Texture_" + HASH_BLUE + "_Switch]"), ordered_text

    print("test_global_hash_override OK")


def test_section_generation(modules, texture_root):
    """One section per hash; if/endif per condition; plain this= otherwise."""
    # Red/blue hair: one hash, two switch states.
    drawib_dict = {
        "94517393": make_resolved_drawib("94517393", [
            ("$swapkey0 == 0", [(HASH_RED, "ResourceTex_RedHair")]),
            ("$swapkey0 == 1", [(HASH_RED, "ResourceTex_BlueHair")]),
        ]),
    }
    ini_text = build_section_text(modules, texture_root, drawib_dict)
    assert "[TextureOverride_Texture_" + HASH_RED + "_Switch]" in ini_text, ini_text
    assert "hash = " + HASH_RED in ini_text, ini_text
    assert "match_priority = 0" in ini_text, ini_text
    assert (
        "if $swapkey0 == 0\n  this = ResourceTex_RedHair\nendif\n"
        "if $swapkey0 == 1\n  this = ResourceTex_BlueHair\nendif"
    ) in ini_text, ini_text

    # Unconditional row: plain this=, no if block.
    drawib_dict = {
        "94517393": make_resolved_drawib("94517393", [
            ("", [(HASH_BLUE, "ResourceTexHash_Always")]),
        ]),
    }
    ini_text = build_section_text(modules, texture_root, drawib_dict)
    assert "[TextureOverride_Texture_" + HASH_BLUE + "_Switch]" in ini_text, ini_text
    assert "this = ResourceTexHash_Always" in ini_text, ini_text
    assert "if " not in ini_text, ini_text

    # Identical rows from two draw calls dedupe into a single if block, and
    # sections of different hashes stay separate.
    drawib_dict = {
        "aaaa1111": make_resolved_drawib("aaaa1111", [("$swapkey0 == 0", [(HASH_RED, "ResourceTex_RedHair")])]),
        "bbbb2222": make_resolved_drawib("bbbb2222", [("$swapkey0 == 0", [(HASH_RED, "ResourceTex_RedHair")])]),
        "cccc3333": make_resolved_drawib("cccc3333", [("$dyntime0 == 3", [(HASH_BLUE, "ResourceTex_BlueHair")])]),
    }
    ini_text = build_section_text(modules, texture_root, drawib_dict)
    assert ini_text.count("if $swapkey0 == 0") == 1, ini_text
    assert "if $dyntime0 == 3" in ini_text, ini_text
    assert ini_text.count("[TextureOverride_Texture_") == 2, ini_text

    # Same condition pointing at two different resources is a contradiction.
    drawib_dict = {
        "94517393": make_resolved_drawib("94517393", [
            ("$swapkey0 == 0", [(HASH_RED, "ResourceTex_RedHair")]),
            ("$swapkey0 == 0", [(HASH_RED, "ResourceTex_BlueHair")]),
        ]),
    }
    try:
        build_section_text(modules, texture_root, drawib_dict)
    except ValueError as error:
        assert "bound with condition" in str(error), str(error)
    else:
        raise AssertionError("expected a contradiction ValueError")

    # Mixing an unconditional row with conditional ones is ambiguous.
    drawib_dict = {
        "94517393": make_resolved_drawib("94517393", [
            ("", [(HASH_RED, "ResourceTex_RedHair")]),
            ("$swapkey0 == 1", [(HASH_RED, "ResourceTex_BlueHair")]),
        ]),
    }
    try:
        build_section_text(modules, texture_root, drawib_dict)
    except ValueError as error:
        assert "mixes an unconditional binding" in str(error), str(error)
    else:
        raise AssertionError("expected a mixed-binding ValueError")

    print("test_section_generation OK")


def test_managed_hash_skip(modules):
    """The automatic hash pipeline hands managed hashes over to the nodes."""
    ini_helper_mod = modules[TEST_PKG + ".common.m_ini_helper"]

    drawib_dict = {
        "94517393": make_resolved_drawib("94517393", [
            ("$swapkey0 == 0", [(HASH_RED, "ResourceTex_RedHair")]),
        ]),
    }
    managed = ini_helper_mod.M_IniHelper._collect_hash_binding_managed_hashes(drawib_dict)
    assert managed == {HASH_RED}, managed

    empty_dict = {"94517393": make_resolved_drawib("94517393", [])}
    managed = ini_helper_mod.M_IniHelper._collect_hash_binding_managed_hashes(empty_dict)
    assert managed == set(), managed

    print("test_managed_hash_skip OK")


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
        test_resolve_hash_bindings(modules, source_dir)
        test_resolve_hash_validation(modules, source_dir)
        test_global_hash_override(modules, temp_dir)
        test_section_generation(modules, temp_dir)
        test_managed_hash_skip(modules)

    print("ALL HASH TEXTURE BIND TESTS PASSED")


if __name__ == "__main__":
    main()
