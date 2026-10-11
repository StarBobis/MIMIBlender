"""Regression tests for the actual GIMI exporter and MARK binding resolver.

Use the existing Blender-free test harness, not a second fake exporter.
Scratch files are unnecessary: all assertions inspect emitted INI lines.
"""
import os
import sys
import types

import test_texture_bind_ini as harness


# The harness supplies real draw models, control flow and INI builders.
def setup():
    harness.ensure_parent_packages()
    harness.install_stubs()
    modules = harness.load_real_modules()
    prefix = harness.TEST_PKG
    for name in ("games", "games.base", "games.gimi"):
        sys.modules[prefix + "." + name] = types.ModuleType(prefix + "." + name)
    base = types.ModuleType(prefix + ".games.base.standard_exporter")
    base.StandardExporter = type("StandardExporter", (), {})
    sys.modules[base.__name__] = base
    sections = types.ModuleType(prefix + ".games.base.sections")
    sys.modules[sections.__name__] = sections
    exporter = harness.load_module_by_path(
        prefix + ".games.gimi.exporter",
        os.path.join(harness.ROOT, "games/gimi/exporter.py"),
    )
    return modules, exporter


# Lightweight output capture keeps tests independent of file formatting.
class Builder:
    def __init__(self):
        self.lines = []

    def append_section(self, section):
        self.lines.extend(section.SectionLineList)


def expect_error(action):
    """Ambiguous bindings must fail instead of silently choosing an image."""
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Expected a binding conflict")


def main():
    modules, exporter = setup()
    prefix = harness.TEST_PKG
    slots = modules[prefix + ".common.gimi_texture_slots"]
    config = sys.modules[prefix + ".common.global_config"].GlobalConfig
    calls = modules[prefix + ".model.draw_call_model"]
    config.logic_name = "GIMI"

    # Exact, case-insensitive names preserve old MMT and gui_collect aliases.
    for name in ("DiffuseMap", "Diffuse", "NormalMap", "LightMap", "NatlanGlow", "NatlanTattoo"):
        assert slots.get_gimi_texture_slot(" " + name.upper() + " ")
    for name in ("FaceSDFMap", "FaceShadow", "HighLightMap", "MyNormalMap", "constructor"):
        assert slots.get_gimi_texture_slot(name) is None

    a = calls.DrawCallModel(obj_name="12345678-0.A")
    b = calls.DrawCallModel(obj_name="12345678-0.B")
    a.index_count = b.index_count = 3
    a.vertex_count = b.vertex_count = 3
    a.work_key_list = [types.SimpleNamespace(key_name="toggle", tmp_value=1)]
    # Restore on a logical MARK must not capture its obsolete physical slot.
    a.texture_slot_binding_list = [harness.make_binding("MARK", slot="ps-t9", mark_name="DiffuseMap", restore_after_draw=True)]
    marks = [harness.FakeMarkup("DiffuseMap", "Slot"), harness.FakeMarkup("LightMap", "SharedSlot"),
             harness.FakeMarkup("NatlanGlow", "Slot"), harness.FakeMarkup("NatlanTattoo", "Slot"),
             harness.FakeMarkup("FaceSDFMap", "Slot"), harness.FakeMarkup("NormalMap", "Hash")]
    submesh = harness.FakeSubmeshModel("12345678-0", [a, b])
    submesh.match_first_index = 0
    model = harness.make_drawib(modules, "12345678", [submesh], {submesh.submesh_name: marks})
    model.submesh_ib_dict = {submesh.submesh_name: [0, 1, 2]}
    model.obj_name_draw_offset = {}
    model.get_submesh_texture_override_suffix = lambda _: "Body"
    model.get_submesh_ib_resource_name = lambda _: "ResourceBodyIB"
    model.resolve_texture_slot_bindings()
    assert a.resolved_gimi_texture_bindings == {r"Resource\GIMI\Diffuse": "Resource-DiffuseMap"}
    assert not a.resolved_texture_slot_restore_lines

    # Simulate an object-specific selected resource after resolution. The next
    # object must start from automatic defaults, not inherit this override.
    a.resolved_gimi_texture_bindings[r"Resource\GIMI\Diffuse"] = "ResourceOverride"
    a.resolved_texture_slot_lines = ["ps-t7 = ResourceExplicit"]
    output = Builder()
    exporter.Exporter().add_unity_vs_texture_override_ib_sections(output, model)
    text = "\n".join(output.lines)
    assert "ORFix" not in text and "NNFix" not in text
    assert "ps-t9 =" not in text
    assert r"Resource\GIMI\NormalMap" not in text
    assert text.count(slots.GIMI_SET_TEXTURES) == 2
    assert "if " in text
    first_api = text.index(slots.GIMI_SET_TEXTURES)
    assert text.index("ResourceOverride") < first_api < text.index("ps-t7 = ResourceExplicit") < text.index("drawindexed")
    assert "Resource\\GIMI\\Diffuse = ref Resource-DiffuseMap" in text[text.index("endif"):]
    assert "Resource-FaceSDFMap" in text

    # Normal automatic exports submit once; empty IBs never submit textures.
    a.texture_slot_binding_list = []
    model.resolve_texture_slot_bindings()
    output = Builder()
    exporter.Exporter().add_unity_vs_texture_override_ib_sections(output, model)
    assert output.lines.count(slots.GIMI_SET_TEXTURES) == 1
    model.submesh_ib_dict = {}
    output = Builder()
    exporter.Exporter().add_unity_vs_texture_override_ib_sections(output, model)
    assert slots.GIMI_SET_TEXTURES not in output.lines

    # Aliases pointing at different images are an error, not last-wins.
    conflict = marks + [harness.FakeMarkup("Diffuse", "Slot")]
    expect_error(lambda: slots.collect_gimi_texture_bindings(conflict))
    logical, physical = slots.collect_gimi_texture_bindings(marks + [marks[0]])
    assert len(logical) == 4 and len(physical) == 1
    physical_only = slots.gimi_texture_lines({}, physical)
    assert slots.GIMI_SET_TEXTURES not in physical_only

    # Nested GIMI MARK rows merge by semantic; non-GIMI rows still use ps-tN.
    row = harness.make_binding("MARK", slot="ps-t8", mark_name="Diffuse")
    assert slots.texture_binding_key(row, True) == r"Resource\GIMI\Diffuse"
    assert slots.texture_binding_key(row, False) == "ps-t8"
    config.logic_name = "ZZMI"
    a.texture_slot_binding_list = [harness.make_binding("MARK", mark_name="DiffuseMap")]
    model.resolve_texture_slot_bindings()
    # Physical fallbacks now capture incoming state before the draw-local bind.
    assert a.resolved_texture_slot_lines[-1] == 'ps-t1 = Resource-DiffuseMap'
    assert len(a.resolved_texture_slot_restore_lines) == 1
    assert not a.resolved_gimi_texture_bindings
    print("PASS GIMI aliases, API order, condition branches, object isolation, empty IB, conflicts, physical fallback and other-game behavior")


if __name__ == "__main__":
    main()
