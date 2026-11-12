"""Run the real Naraka export pipeline on an opt-in captured subdivision.

Run Blender headless with NARAKA_POSTSKIN_EVIDENCE_JSON, MOD_BUFFERS,
LAYOUT_JSON and RUNTIME_FOLDER variables (all prefixed NARAKA_POSTSKIN_).
The fixture supplies already-exported geometry arrays; no user's blend file,
workspace JSON or installed Mod is edited. All output stays under repo/tmp.
This exercises the actual exporter, section builders and buffer writer rather
than substituting their implementations with a mock INI generator.
"""
from pathlib import Path
from dataclasses import fields, MISSING
import json
import os
import re
import sys
import tempfile
import types
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Load the real modules without registering the whole interactive add-on.
# Registration would introduce unrelated preferences and startup handlers.
# The synthetic package changes import context, not the tested implementations.
PACKAGE = types.ModuleType("native_export_smoke")
PACKAGE.__path__ = [str(ROOT)]
sys.modules[PACKAGE.__name__] = PACKAGE
from native_export_smoke.common.global_config import GlobalConfig, LogicName
from native_export_smoke.common.mimi_global_properties import MIMIGlobalProperties
from native_export_smoke.common.d3d11_gametype import D3D11GameType
from native_export_smoke.model.drawib_model import DrawIBModel
from native_export_smoke.model.submesh_model import SubMeshModel
from native_export_smoke.model.draw_call_model import DrawCallModel
from native_export_smoke.games.naraka.exporter import Exporter


def blank_model(cls):
    """Initialize dataclass state without invoking Blender node traversal.

    The tested stage starts after mesh conversion, using real exported buffers.
    Node traversal/import are deliberately outside this fixture's claims.
    """
    instance = cls.__new__(cls)
    for item in fields(cls):
        if item.default_factory is not MISSING:
            value = item.default_factory()
        elif item.default is not MISSING:
            value = item.default
        else:
            value = None
        setattr(instance, item.name, value)
    return instance


evidence_path = Path(os.environ["NARAKA_POSTSKIN_EVIDENCE_JSON"])
# Separate source metadata from edited geometry: the native maps come from
# the original capture, while these buffers contain the tested subdivision.
# A complete MMT workspace JSON and a standalone collector record are accepted.
geometry = Path(os.environ["NARAKA_POSTSKIN_MOD_BUFFERS"])
layout = json.loads(Path(os.environ["NARAKA_POSTSKIN_LAYOUT_JSON"]).read_text())
temporary = ROOT / "tmp"
temporary.mkdir(exist_ok=True)
output = Path(tempfile.mkdtemp(prefix="native_export_smoke_", dir=temporary))
GlobalConfig._automation_override = {"output": str(output), "workspace_name": "native_export_smoke"}
GlobalConfig.generated_mod_name_override = "native_export_smoke"
GlobalConfig.logic_name = LogicName.Naraka
GlobalConfig.current_game_migoto_folder = os.environ["NARAKA_POSTSKIN_RUNTIME_FOLDER"]
GlobalConfig.generated_mod_number = 0

# These scene options are unrelated to geometry or the native runtime API.
# Explicit fixture values avoid reading the user's persisted scene settings.
MIMIGlobalProperties.forbid_auto_texture_ini = staticmethod(lambda: False)
MIMIGlobalProperties.simulate_xxmi_tail_comments = staticmethod(lambda: False)
# Reconstruct the post-conversion model state used by the production exporter.
# Counts and names intentionally describe this one retained c00f48ca fixture.
# This is not an arbitrary-topology or Blender mesh conversion acceptance test.
submesh = blank_model(SubMeshModel)
submesh.submesh_name = "LOD0.c00f48ca-0"
submesh.display_str = submesh.submesh_name
submesh.match_first_index = 0
draw = DrawCallModel(obj_name="native_fixture", submesh_name=submesh.submesh_name)
draw.index_count = 238512
draw.vertex_count = 53092
submesh.drawcall_model_list = [draw]
model = blank_model(DrawIBModel)
model.draw_ib = "c00f48ca"
model.draw_ib_alias = "native_fixture"
model.vertex_limit_hash = "caa1c4c4"
model.vertex_count = 53092
model.d3d11_game_type = D3D11GameType.from_submesh_json_dict(layout)
model.category_hash_dict = layout["CategoryHash"]
model.submesh_model_list = [submesh]
model.import_json_path = str(evidence_path)
source_document = json.loads(evidence_path.read_text())
model.import_json_dict = {"NarakaPostSkin": source_document.get("NarakaPostSkin", source_document)}
# Preserve every exported attribute byte; native preparation must only add its
# own input tables and must not rewrite the user's position, UV or blend data.
model.category_buffer_dict = {name: np.fromfile(geometry / ("LOD0.c00f48ca-" + name + ".buf"), np.uint8) for name in ["Position", "Texcoord", "Blend"]}
model.submesh_ib_dict = {submesh.submesh_name: np.fromfile(geometry / "LOD0.c00f48ca-0-Index.buf", "<u4").tolist()}
model.obj_name_draw_offset = {draw.obj_name: 0}
model.apply_drawib_alias = lambda: None
# Only blueprint traversal is supplied by the fixture. Exporter preflight,
# command generation and ordinary/native buffer writers execute real code.
blueprint = types.SimpleNamespace(keyname_mkey_dict={}, global_hash_texture_binding_list=[],
                                  parse_drawib_model_list=lambda **kwargs: [model])
exporter = Exporter(blueprint)
exporter.export()

ini = output / "native_export_smoke.ini"
text = ini.read_text()
# The generated Mod delegates shared execution to Package and retains model
# resources locally. Both native stages and bone capture must remain connected.
assert "run = CommandList\\NBPv1\\DeformNative" in text
assert "run = CommandList\\NBPv1\\RecalculateNormals" in text
assert "run = CommandListNative_c00f48ca_CaptureBones" in text
assert "[CustomShaderNative" not in text
# Check loader-facing output, not just successful Python return values:
# duplicate sections and missing relative resources would break a usable Mod.
sections = re.findall(r"^\[([^\]]+)\]", text, re.M)
assert len(sections) == len(set(sections))
for filename in re.findall(r"^filename\s*=\s*(.+)$", text, re.M):
    assert (output / filename.strip().replace("\\", "/")).is_file(), filename
assert len(list((output / "Buffers").glob("native_c00f48ca_*.buf"))) == 16
for name in ["Position", "Texcoord", "Blend"]:
    target = output / "Buffers" / model.get_category_buffer_filename(name)
    assert target.read_bytes() == (geometry / ("LOD0.c00f48ca-" + name + ".buf")).read_bytes()
print("PASS real Naraka exporter wrote complete native Package-linked Mod:", output)

# Exercise the production preflight and complete writer on unrelated metadata.
# Missing Package files must not affect these legacy exports. Supplying truthy
# animation state during preflight also guards the order of native-only checks.
GlobalConfig.current_game_migoto_folder = str(output / "package-does-not-exist")
for hashes in [[], ["1111111111111111"], ["1111111111111111"] * 3]:
    legacy_output = Path(tempfile.mkdtemp(prefix="legacy_export_smoke_", dir=temporary))
    GlobalConfig._automation_override["output"] = str(legacy_output)
    model.import_json_dict = {"NarakaPostSkin": {
        "SchemaVersion": 1, "Stages": [{"ShaderHash": shader} for shader in hashes]}}
    model.time_pos_frame_groups = {"fixture": {}}
    legacy_exporter = Exporter(blueprint)
    assert legacy_exporter.native_exports == {}
    # This fixture does not model animated buffers; clear them after proving
    # native preflight leaves unrelated animated models on the existing route.
    model.time_pos_frame_groups = {}
    legacy_exporter.export()
    legacy_text = (legacy_output / "native_export_smoke.ini").read_text()
    assert "NBPv1" not in legacy_text
    assert not list((legacy_output / "Buffers").glob("native_*.buf"))
    for filename in re.findall(r"^filename\s*=\s*(.+)$", legacy_text, re.M):
        assert (legacy_output / filename.strip().replace("\\", "/")).is_file(), filename
    print("PASS unrelated CS chain kept real legacy export:", len(hashes), legacy_output)
