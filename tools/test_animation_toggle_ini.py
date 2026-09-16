"""Exercise generated animation switch commands outside Blender.

The small interpreter below covers only the exporter-generated test subset;
it is not a replacement for the 3Dmigoto parser or an in-game integration test.
It executes pre-Present, input cycles, then post-Present in engine order, so
assertions catch stale frames, wrong reset behavior and incorrect copy timing.
"""
import os
import re
import tempfile
import types

import test_time_position_ini as support


def parse_sections(text):
    # Reject duplicate sections rather than silently replacing earlier text.
    # The real builder merges Constants/Present before either serializer runs.
    sections = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("["):
            current = line[1:-1]
            assert current not in sections, current
            sections[current] = []
        else:
            assert current is not None
            sections[current].append(line)
    return sections


class Runtime:
    """Evaluate trusted, locally generated command text with explicit state.

    Resource copies keep symbolic source identities instead of allocating GPU
    buffers. Shader calls record the weight and seed visible at dispatch time;
    actual shader arithmetic already has separate D3D11 WARP coverage.
    """
    def __init__(self, sections):
        self.sections = sections
        self.values = {}
        self.resources = {}
        self.copies = 0
        self.dispatches = []
        self.run(sections["Constants"], 0)

    def expression(self, text, time):
        # eval only receives expressions emitted by the addon in this test.
        # No user text, imports, builtins or filesystem functions are exposed.
        text = re.sub(r"\$[a-z_][a-z0-9_]*", lambda match: "values[" + repr(match[0]) + "]", text)
        text = re.sub(r"!(?!=)", " not ", text).replace("&&", " and ").replace("||", " or ")
        return eval(text.strip(), {"__builtins__": {}}, {"values": self.values, "time": time})

    def run(self, lines, time):
        stack = []
        active = True
        for line in lines:
            # Track parent activity and whether an earlier branch matched.
            # Both are needed for nested ifs in the restart and copy commands.
            if line.startswith("if "):
                result = active and bool(self.expression(line[3:], time))
                stack.append([active, result])
                active = result
                continue
            if line.startswith("elif "):
                parent, matched = stack[-1]
                active = parent and not matched and bool(self.expression(line[5:], time))
                stack[-1][1] |= active
                continue
            if line == "else":
                parent, matched = stack[-1]
                active = parent and not matched
                stack[-1][1] = True
                continue
            if line == "endif":
                active = stack.pop()[0]
                continue
            if not active:
                continue
            if line.startswith("local "):
                self.values.setdefault(line[6:], 0)
                continue
            if line.startswith("run = "):
                target = line[6:]
                if target.startswith("CustomShader"):
                    self.dispatches.append((dict(self.values), dict(self.resources)))
                else:
                    self.run(self.sections[target], time)
                continue
            # Global declarations without an initializer default to zero.
            # A persisted animation control is an error, not a simulated feature.
            assert not line.startswith("global persist "), line
            line = line.removeprefix("global ")
            if " = " not in line:
                self.values[line] = 0
                continue
            target, expression = line.split(" = ", 1)
            if expression.startswith("copy "):
                source = expression[5:]
                self.resources[target] = self.resources.get(source, source)
                self.copies += 1
            else:
                self.values[target] = self.expression(expression, time)
        assert not stack

    def step(self, time, press=None):
        # The old bug-prone arrangement updated clocks before input, but copied
        # positions afterwards. Testing this exact phase boundary is essential.
        present = self.sections["Present"]
        self.run([line for line in present if not line.startswith("post ")], time)
        if press:
            for name, lines in self.sections.items():
                if not name.startswith("KeyMimiAnimation_") or "key = " + press not in lines:
                    continue
                assert "smart = true" in lines and "type = cycle" in lines
                assignment = next(line for line in lines if line.startswith("$"))
                variable, sequence = assignment.split(" = ", 1)
                cycle = [int(value) for value in sequence.split(",")]
                # Mirror KeyOverrideCycle::UpdateCurrent followed by DownEvent.
                current = cycle.index(self.values[variable])
                self.values[variable] = cycle[(current + 1) % len(cycle)]
        self.run([line[5:] for line in present if line.startswith("post ")], time)


def build_combined(modules, start_enabled):
    """Use all real writers, including shared shape output and Position copies."""
    helper = modules[support.TEST_PKG + ".common.m_ini_helper"].M_IniHelper
    builder = modules[support.TEST_PKG + ".common.m_ini_builder"].M_IniBuilder()
    blueprint = support.make_fake_blueprint_model(modules)
    timeline = blueprint.keyname_mkey_dict["$dyntime0"]
    settings = types.SimpleNamespace(toggle_key=" f6 ", start_enabled=start_enabled)
    timeline.fps = 10
    timeline.configure_animation_toggle(settings)
    key_type = modules[support.TEST_PKG + ".common.m_key"].M_Key
    shape = key_type(key_name="$shapekey0", key_type="time_shapekey", fps=10,
                     value_list=[0, 1, 2], weight_list=[0.25, 0.6, 1.0], initialize_value=0.25)
    shape.configure_animation_toggle(settings)
    # A legacy weight-cycle binding must never compete with the toggle driver.
    shape.initialize_vk_str = "F2"
    support.TEST_SHAPEKEY_DICT.clear()
    support.TEST_SHAPEKEY_DICT["blink"] = shape
    model = support.make_fake_drawib_model({"blink": b"x"})
    model.vertex_count = 65
    helper.add_branch_key_sections(builder, blueprint.keyname_mkey_dict, blueprint, [model])
    helper.add_shapekey_ini_sections(builder, {model.draw_ib: model})
    with tempfile.TemporaryDirectory() as folder:
        text = support.build_ini_text(builder, os.path.join(folder, "toggles.ini"))
    sections = parse_sections(text)
    assert sum(name.startswith("KeyMimiAnimation_") for name in sections) == 2
    assert not any(name.startswith("KeySwap_") or name.startswith("Key_ShapeKey_") for name in sections)
    # Verify the post command order rather than relying on textual placement
    # of command definitions, which the serializer is free to reorder.
    post = sections["Present"]
    assert post.index("post run = CommandListMimiAnimation_dyntime0") < post.index("post run = CommandListMimiTimePosition")
    assert post.index("post run = CommandListMimiAnimation_shapekey0") < post.index("post run = CustomShaderComputeShapes1")
    return Runtime(sections)


def test_toggle_lifecycle(modules):
    for initially_enabled in (False, True):
        runtime = build_combined(modules, initially_enabled)
        target = "Resource65b9cf5aPositionTimeBase"
        original = "Resource65b9cf5aPositionTimeOriginal"
        frame_prefix = "Resource65b9cf5aPositionTimeFrame.dyntime0_"
        runtime.step(100)
        assert runtime.values["$dyntime0"] == 0
        assert runtime.values["$shapekey0"] == (0.25 if initially_enabled else 0)
        assert runtime.resources[target] == (frame_prefix + "0" if initially_enabled else original)
        # One press must invert either initial state, not repeat its value.
        runtime.step(100.125, press="F6")
        assert runtime.values["$mimi_anim_dyntime0_enabled"] == int(not initially_enabled)
        if initially_enabled:
            assert runtime.resources[target] == original and runtime.values["$shapekey0"] == 0
            runtime.step(101, press="F6")
            epoch = 101
        else:
            epoch = 100.125
        assert runtime.values["$dyntime0"] == 0 and runtime.values["$shapekey0"] == 0.25
        runtime.step(epoch + 0.125)
        assert runtime.values["$dyntime0"] == 1 and runtime.values["$shapekey0"] == 0.6
        assert runtime.resources[target] == frame_prefix + "1"
        copies = runtime.copies
        runtime.step(epoch + 0.15)
        assert runtime.copies == copies, "unchanged animation frames should not copy again"
        runtime.step(epoch + 0.16, press="F6")
        assert runtime.values["$dyntime0"] == runtime.values["$shapekey0"] == 0
        assert runtime.resources[target] == original
        # Waiting while disabled must not advance the resumed animation phase.
        runtime.step(500)
        runtime.step(501, press="F6")
        assert runtime.values["$dyntime0"] == 0 and runtime.values["$shapekey0"] == 0.25
        assert runtime.resources[target] == frame_prefix + "0"
        weights, resources = runtime.dispatches[-1]
        assert weights["$shapekey0"] == 0.25 and resources[target] == frame_prefix + "0"
    print("PASS: both defaults, first press, disable, restart, copy cache and compute ordering")


def test_configuration(modules):
    key = modules[support.TEST_PKG + ".common.m_key"].M_Key()
    key.configure_animation_toggle(types.SimpleNamespace(toggle_key=" ctrl   f6 ", start_enabled=False))
    assert key.toggle_key == "CTRL F6" and not key.start_enabled
    # Old files have no new properties. Blank keys also override an unused
    # false checkbox so existing autoplay cannot become permanently disabled.
    key.configure_animation_toggle(types.SimpleNamespace())
    assert not key.toggle_key and key.start_enabled
    key.configure_animation_toggle(types.SimpleNamespace(toggle_key=" ", start_enabled=False))
    assert key.start_enabled
    for text in ("F6\nrun = evil", "F6;comment", "[KeyBad]"):
        try:
            key.configure_animation_toggle(types.SimpleNamespace(toggle_key=text))
        except ValueError:
            pass
        else:
            raise AssertionError("Expected invalid binding to fail")
    print("PASS: old-file defaults, binding normalization and delimiter rejection")


if __name__ == "__main__":
    support.ensure_parent_packages()
    support.install_stubs()
    modules = support.load_real_modules()
    test_configuration(modules)
    test_toggle_lifecycle(modules)
    print("ALL ANIMATION TOGGLE INI TESTS PASSED")
