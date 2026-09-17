"""Regression tests using real addon models and Blender's evaluated meshes.

Run with blender -b --factory-startup --python-exit-code 1 --python this_file.
The synthetic package avoids registering the entire addon. Only external
workspace lookups and frame-buffer conversion are mocked in model tests;
traversal, grouping, buffer assembly, topology checks and baking are real.
"""
import copy
import math
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("animation_test_addon")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package

from animation_test_addon.model.blueprint_model import BluePrintModel
from animation_test_addon.model.draw_call_model import DrawCallModel
from animation_test_addon.model.drawib_model import DrawIBModel
from animation_test_addon.common.m_key import M_Key
from animation_test_addon.common.m_time_position import group_time_position_frames
from animation_test_addon.common.m_shape_layout import shape_shader_for_layout
from animation_test_addon.common.global_config import GlobalConfig, LogicName
from animation_test_addon.blueprint.blueprint_time_bake import MMT_OT_BakeAnimationToTimeSwitch


def rejects(function, message):
    # Negative tests assert a useful diagnostic rather than any exception.
    # This keeps missing fixture attributes from masquerading as validation.
    try:
        function()
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError("Expected validation error: " + message)


def new_blueprint():
    """Skip UI/workspace discovery, but use the real traversal methods."""
    model = BluePrintModel.__new__(BluePrintModel)
    model.keyname_mkey_dict = {}
    model.ordered_draw_obj_data_model_list = []
    model.time_pos_frame_models = []
    model.time_pos_key_names = set()
    model._switch_alias_state_counts = {}
    model._key_group_state_counts = {}
    model._key_group_var_names = {}
    model._time_key_index = 0
    model._time_node_key_names = {}
    model._group_instance_stack = []

    # Leaf conversion is unrelated to clock provenance; build real DrawCalls.
    # Copy the condition chain exactly as normal object-node parsing does.
    def parse_leaf(node, chain):
        draw = DrawCallModel(node.obj_name, node.submesh_name)
        draw.work_key_list = copy.deepcopy(chain)
        model.ordered_draw_obj_data_model_list.append(draw)
    model.parse_single_node = parse_leaf
    return model


def time_node(alias="shared", count=2, prefix="frame"):
    # Socket order, including empty sockets, defines timeline frame indices.
    # One leaf per socket is enough to exercise the real branch-state writer.
    sockets = []
    for index in range(count):
        leaf = types.SimpleNamespace(obj_name="abcd1234-0." + prefix + str(index), submesh_name="abcd1234-0")
        sockets.append(types.SimpleNamespace(is_linked=True, links=[types.SimpleNamespace(from_node=leaf)]))
    node = types.SimpleNamespace(inputs=sockets, time_alias=alias, fps=12.0, name=prefix, comment="")
    node.as_pointer = lambda: id(node)
    return node


def test_graph_provenance():
    model = new_blueprint()
    model._parse_time_switch_node(time_node(prefix="draw"), [])
    model._parse_time_switch_node(time_node(prefix="position"), [], True)
    model._reclassify_time_pos_frames()
    # Synchronizing aliases must not reclassify the ordinary DrawIndexed path.
    assert len(model.ordered_draw_obj_data_model_list) == 2
    assert len(model.time_pos_frame_models) == 2
    assert all("draw" in d.obj_name for d in model.ordered_draw_obj_data_model_list)
    assert list(group_time_position_frames(model.time_pos_frame_models)) == ["$shared"]

    # A single position frame still replaces a base slice, never draws twice.
    single = new_blueprint()
    single._parse_time_switch_node(time_node(count=1), [], True)
    single._reclassify_time_pos_frames()
    assert not single.ordered_draw_obj_data_model_list and len(single.time_pos_frame_models) == 1

    # Revisited anonymous nodes share a stable clock; case variants of an
    # explicit alias are identical because 3Dmigoto lowercases INI tokens.
    anonymous = new_blueprint()
    node = time_node(alias="")
    anonymous._parse_time_switch_node(node, [])
    anonymous._parse_time_switch_node(node, [])
    assert len(anonymous.keyname_mkey_dict) == 1
    assert BluePrintModel._normalize_time_alias(time_node(alias="Walk")) == "$walk"
    for alias in ("123", "shapekey0", "active0", "mimi_pos_internal"):
        rejects(lambda: BluePrintModel._normalize_time_alias(time_node(alias=alias)), "alias")
    mismatch = time_node()
    mismatch.fps = 24
    rejects(lambda: model._parse_time_switch_node(mismatch, []), "same FPS")

    # Driver collisions must fail regardless of traversal order. Exercise the
    # real hotkey parser after a time node, not only the reverse order.
    switch = time_node()
    switch.mute = False
    switch.bl_idname = sys.modules[BluePrintModel.__module__].MIMINode_SwitchKey.bl_idname
    switch.key_alias = "shared"
    switch.key_name = "VK_F1"
    rejects(lambda: BluePrintModel.parse_single_node(model, switch, []), "cannot share alias")
    reverse = new_blueprint()
    reverse.keyname_mkey_dict["$shared"] = M_Key(key_name="$shared", value_list=[0, 1])
    rejects(lambda: reverse._parse_time_switch_node(time_node(), []), "both a Switch Key")

    # Whole-buffer copies cannot independently gate slices or combine clocks.
    frames = copy.deepcopy(model.time_pos_frame_models)
    duplicate = frames + [copy.deepcopy(frames[0])]
    rejects(lambda: group_time_position_frames(duplicate), "duplicate providers")
    frames[1].work_key_list.append(M_Key(key_name="$gate", tmp_value=1))
    rejects(lambda: group_time_position_frames(frames), "outer conditions")
    frames = copy.deepcopy(model.time_pos_frame_models)
    frames[1].time_position_key_name = "$other"
    frames[1].work_key_list[0].key_name = "$other"
    rejects(lambda: group_time_position_frames(frames), "shared timeline")
    print("PASS: graph provenance, aliases, single frames and invalid composition")


def test_toggle_aliases_and_shape_config():
    """Check the real graph/configuration path, not just handcrafted M_Keys.

    Shared aliases must emit one switch, and incompatible defaults or bindings
    must fail in either traversal order instead of choosing an arbitrary node.
    """
    model = new_blueprint()
    draw = time_node(prefix="draw")
    draw.toggle_key, draw.start_enabled = " ctrl f6 ", False
    position = time_node(prefix="position")
    position.toggle_key, position.start_enabled = "CTRL F6", False
    model._parse_time_switch_node(draw, [])
    model._parse_time_switch_node(position, [], True)
    assert len(model.keyname_mkey_dict) == 1
    key = model.keyname_mkey_dict["$shared"]
    assert key.toggle_key == "CTRL F6" and not key.start_enabled
    from animation_test_addon.common.m_ini_builder import M_IniBuilder
    from animation_test_addon.common.m_ini_helper import M_IniHelper
    builder = M_IniBuilder()
    M_IniHelper.add_branch_key_sections(builder, model.keyname_mkey_dict)
    lines = [line for section in builder.ini_section_list for line in section.SectionLineList]
    assert lines.count("[KeyMimiAnimation_shared]") == 1
    for binding, enabled in (("F7", False), ("CTRL F6", True), ("", False)):
        position.toggle_key, position.start_enabled = binding, enabled
        rejects(lambda: model._parse_time_switch_node(position, [], True), "same animation toggle")
    # Single-frame draw nodes keep a configured switch; blank-key legacy
    # nodes are still allowed to use their old pass-through optimization.
    single = new_blueprint()
    node = time_node(count=1)
    node.toggle_key, node.start_enabled = "F8", False
    single._parse_time_switch_node(node, [])
    assert single.keyname_mkey_dict["$shared"].toggle_key == "F8"

    from animation_test_addon.blueprint.blueprint_export_helper import BlueprintExportHelper
    output = types.SimpleNamespace(bl_idname="MIMINode_Result_Output", enable_shapekey=True, shapekey_items=[])
    shape_node = types.SimpleNamespace(bl_idname="MIMINode_TimeShapeKey", shapekey_name="blink", fps=12,
                                      weights=[types.SimpleNamespace(weight=w) for w in (0.75, 1.0)],
                                      toggle_key="f7", start_enabled=False)
    tree = types.SimpleNamespace(nodes=[output, shape_node])
    # Discovery is mocked; the actual output/shape configuration reader runs.
    # A nonzero first sample makes accidental initialization visibly wrong.
    with patch.object(BlueprintExportHelper, "get_current_blueprint_tree", return_value=tree), patch.object(BlueprintExportHelper, "runtime_output_node", None):
        parsed = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()["blink"]
    assert parsed.toggle_key == "F7" and parsed.initialize_value == 0
    assert parsed.weight_list == [0.75, 1.0]
    # A single manually entered weight is useful as an on/off shape. It is
    # only exported when a toggle is configured, preserving legacy defaults.
    shape_node.weights = shape_node.weights[:1]
    with patch.object(BlueprintExportHelper, "get_current_blueprint_tree", return_value=tree), patch.object(BlueprintExportHelper, "runtime_output_node", None):
        assert BlueprintExportHelper.get_current_shapekeyname_mkey_dict()["blink"].weight_list == [0.75]
        shape_node.toggle_key = ""
        assert BlueprintExportHelper.get_current_shapekeyname_mkey_dict() == {}
    print("PASS: shared toggle aliases, single-frame controls and shape node configuration")


def switch_node(key="VK_F1", alias="", count=2, prefix="branch"):
    # Same socket layout as a real Switch Key node: one leaf per branch,
    # so the real hotkey parsing and branch-state writer run end to end.
    sockets = []
    for index in range(count):
        leaf = types.SimpleNamespace(obj_name="abcd1234-0." + prefix + str(index), submesh_name="abcd1234-0")
        sockets.append(types.SimpleNamespace(is_linked=True, links=[types.SimpleNamespace(from_node=leaf)]))
    return types.SimpleNamespace(
        inputs=sockets, key_name=key, key_alias=alias, name=prefix, comment="", mute=False,
        bl_idname=sys.modules[BluePrintModel.__module__].MIMINode_SwitchKey.bl_idname,
    )


def test_switch_key_merging():
    """Same hotkey without an alias merges into one cycled variable.

    Two Switch Key nodes bound to the same key used to emit two [Key]
    sections cycling two independent variables; now the pre-scan computes
    the LCM period and both nodes share a single $swapkeyN variable.
    """
    from animation_test_addon.common.m_ini_builder import M_IniBuilder
    from animation_test_addon.common.m_ini_helper import M_IniHelper

    # Two nodes share "VK_F1" written in different case/whitespace forms;
    # branch counts 2 and 3 expand to 6 states by least common multiple.
    GlobalConfig.global_key_index = 0
    first = switch_node(key="VK_F1", count=2, prefix="first")
    second = switch_node(key=" vk_f1  ", count=3, prefix="second")
    model = new_blueprint()
    model._key_group_state_counts = BluePrintModel._collect_key_group_state_counts(
        types.SimpleNamespace(nodes=[first, second]))
    assert model._key_group_state_counts == {"VK_F1": 6}
    BluePrintModel.parse_single_node(model, first, [])
    BluePrintModel.parse_single_node(model, second, [])
    assert list(model.keyname_mkey_dict) == ["$swapkey0"]
    merged = model.keyname_mkey_dict["$swapkey0"]
    assert merged.value_list == [0, 1, 2, 3, 4, 5]
    # The first parsed node provides the [Key] section's binding string.
    assert merged.initialize_vk_str == "VK_F1"

    # Every leaf keeps its branch index modulo its own socket count:
    # branch k of a 2-socket node shows on states k, k+2, k+4 and branch k
    # of a 3-socket node on states k, k+3.
    states_by_leaf = {}
    for draw in model.ordered_draw_obj_data_model_list:
        states = [key.tmp_value for key in draw.work_key_list if key.key_name == "$swapkey0"]
        states_by_leaf.setdefault(draw.obj_name, []).extend(states)
    assert states_by_leaf["abcd1234-0.first0"] == [0, 2, 4]
    assert states_by_leaf["abcd1234-0.first1"] == [1, 3, 5]
    assert states_by_leaf["abcd1234-0.second0"] == [0, 3]
    assert states_by_leaf["abcd1234-0.second1"] == [1, 4]
    assert states_by_leaf["abcd1234-0.second2"] == [2, 5]

    # The INI writer emits exactly one cycled variable for the hotkey.
    builder = M_IniBuilder()
    M_IniHelper.add_branch_key_sections(builder, model.keyname_mkey_dict)
    lines = [line for section in builder.ini_section_list for line in section.SectionLineList]
    assert [line for line in lines if line.startswith("key = ")] == ["key = VK_F1"]
    assert "global persist $swapkey0 = 0" in lines
    assert "$swapkey0 = 0,1,2,3,4,5" in lines

    # Different hotkeys keep independent variables and [Key] sections.
    GlobalConfig.global_key_index = 0
    model = new_blueprint()
    BluePrintModel.parse_single_node(model, switch_node(key="VK_F1", count=2, prefix="a"), [])
    BluePrintModel.parse_single_node(model, switch_node(key="VK_F2", count=2, prefix="b"), [])
    assert sorted(model.keyname_mkey_dict) == ["$swapkey0", "$swapkey1"]
    assert all(len(key.value_list) == 2 for key in model.keyname_mkey_dict.values())

    # Blank keys never merge: each switch keeps its own variable.
    GlobalConfig.global_key_index = 0
    model = new_blueprint()
    BluePrintModel.parse_single_node(model, switch_node(key="", count=2, prefix="a"), [])
    BluePrintModel.parse_single_node(model, switch_node(key="   ", count=2, prefix="b"), [])
    assert sorted(model.keyname_mkey_dict) == ["$swapkey0", "$swapkey1"]

    # An explicit alias wins over same-key merging: the aliased node keeps
    # its named variable while the plain node gets an anonymous one.
    GlobalConfig.global_key_index = 0
    model = new_blueprint()
    model._key_group_state_counts = BluePrintModel._collect_key_group_state_counts(
        types.SimpleNamespace(nodes=[switch_node(key="VK_F1", count=2)]))
    BluePrintModel.parse_single_node(model, switch_node(key="VK_F1", alias="hero", count=2, prefix="a"), [])
    BluePrintModel.parse_single_node(model, switch_node(key="VK_F1", count=2, prefix="b"), [])
    assert sorted(model.keyname_mkey_dict) == ["$hero", "$swapkey0"]
    print("PASS: same-hotkey merge, LCM states, blank/different keys and alias precedence")


def submesh(name, offset):
    """Use explicit byte arrays so slice corruption is easy to detect."""
    draw = DrawCallModel(name + ".base", name)
    draw.index_count = 3
    position = np.arange(offset, offset + 36, dtype=np.uint8)
    return types.SimpleNamespace(
        submesh_name=name, match_draw_ib="abcd1234", drawcall_model_list=[draw],
        d3d11_game_type=types.SimpleNamespace(CategoryStrideDict={"Position": 12}, OrderedCategoryNameList=["Position"]),
        category_buffer_dict={"Position": position, "Texcoord": np.zeros(24, dtype=np.uint8)},
        index_vertex_id_dict={0: 0, 1: 1, 2: 2}, shape_key_buffer_dict={}, ib=[0, 1, 2],
    )


def test_position_pipeline():
    blueprint = new_blueprint()
    blueprint._parse_time_switch_node(time_node(), [], True)
    blueprint._reclassify_time_pos_frames()
    base = submesh("abcd1234-0", 0)
    static = submesh("abcd1234-1", 80)
    blueprint.parse_submesh_model_list = lambda: [base, static]
    # Keep real DrawIB assembly and real blueprint-to-DrawIB attachment.
    # Only workspace metadata loading requires an extracted game workspace.
    with patch.object(DrawIBModel, "_load_import_metadata_from_first_submesh", lambda self: None):
        drawib = blueprint.parse_drawib_model_list()[0]
    assert set(drawib.time_pos_frame_groups["$shared"]) == {0, 1}
    assert drawib.submesh_vertex_base_dict == {"abcd1234-0": 0, "abcd1234-1": 3}
    assert drawib.submesh_ib_dict["abcd1234-1"] == [3, 4, 5]

    # The real conversion checker compares index order, loop correspondence
    # and every shared non-Position category, not merely the buffer length.
    converted = copy.deepcopy(base)
    converted.category_buffer_dict["Position"] += 10
    module = sys.modules[DrawIBModel.__module__]
    with patch.object(module, "SubMeshModel", return_value=converted):
        with tempfile.TemporaryDirectory() as folder:
            drawib.write_time_position_files(folder)
            for frame in (0, 1):
                data = Path(folder, drawib.get_time_position_buffer_filename("shared", frame)).read_bytes()
                assert data[:36] == bytes(converted.category_buffer_dict["Position"])
                assert data[36:] == bytes(static.category_buffer_dict["Position"])
        converted.ib = [0, 2, 1]
        rejects(lambda: drawib._compute_time_pos_frame_position_bytes(blueprint.time_pos_frame_models[0], base), "topology/order")
        converted.ib = [0, 1, 2]
        converted.category_buffer_dict["Texcoord"][0] = 1
        rejects(lambda: drawib._compute_time_pos_frame_position_bytes(blueprint.time_pos_frame_models[0], base), "changes Texcoord")
    # A provider without a normally connected base must fail before it can
    # disappear from the exporter loop, including an entirely absent DrawIB.
    blueprint.parse_submesh_model_list = lambda: []
    rejects(blueprint.parse_drawib_model_list, "connect a base")
    print("PASS: real frame grouping, full-buffer slices and topology validation")


def test_validation():
    key = M_Key(key_name="$clock", key_type="time", value_list=[0, 1])
    for fps in (0, -1, math.nan, math.inf):
        key.fps = fps
        rejects(key.timeline_expression, "FPS")
    key.fps = 12
    key.value_list = [0, 2]
    rejects(key.timeline_expression, "contiguous")
    key.value_list = [0, 1]
    key.key_type = "time_shapekey"
    for weights in ([0], [0, math.nan]):
        key.weight_list = weights
        rejects(key.timeline_expression, "finite")
    # Stride-only checks previously accepted packed or reordered semantics.
    layout = types.SimpleNamespace(CategoryStrideDict={"Position": 12}, D3D11ElementList=[
        types.SimpleNamespace(Category="Position", SemanticName="POSITION", Format="R32G32B32_FLOAT", ByteWidth=12)
    ])
    assert shape_shader_for_layout(layout) == "shapes_position.hlsl"
    layout.D3D11ElementList[0].Format = "R16G16B16A16_SNORM"
    rejects(lambda: shape_shader_for_layout(layout), "Unsupported")
    print("PASS: timeline and shader layout validation")


def test_bake_and_rollback():
    scene = bpy.context.scene
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.object
    source.location = (1, 0, 0)
    source.keyframe_insert(data_path="location", frame=1)
    source.location = (4, 0, 0)
    source.keyframe_insert(data_path="location", frame=2)
    scene.frame_set(8, subframe=0.25)
    expected = []
    for frame in (1, 2):
        scene.frame_set(frame)
        expected.append(source.matrix_world @ source.data.vertices[0].co)
    scene.frame_set(8, subframe=0.25)
    bake = MMT_OT_BakeAnimationToTimeSwitch._bake_frames
    frames = bake(None, bpy.context, source, [1, 2])
    for (_, obj), coordinate in zip(frames, expected):
        assert (obj.data.vertices[0].co - coordinate).length < 1e-5
        assert obj.matrix_world.is_identity
    assert scene.frame_current == 8 and scene.frame_subframe == 0.25

    # Fail on the second depsgraph query, after the first mesh was created.
    # Rollback must restore the scene and remove only this failed bake's data.
    counts = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.collections))
    calls = 0
    def depsgraph():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("intentional sampling failure")
        return bpy.context.evaluated_depsgraph_get()
    context = types.SimpleNamespace(scene=scene, window_manager=bpy.context.window_manager, evaluated_depsgraph_get=depsgraph)
    try:
        bake(None, context, source, [1, 2])
    except RuntimeError as error:
        assert "intentional" in str(error)
    else:
        raise AssertionError("Expected failed bake")
    assert counts == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.collections))
    assert scene.frame_current == 8 and scene.frame_subframe == 0.25
    print("PASS: evaluated world transforms, subframes and transactional rollback")


def test_bake_range_prefill_and_static_tail():
    """Keyed-range prefill and trailing held-pose detection.

    Scene ranges often extend past the last keyframe; baking that padding
    freezes the animation at the end of every loop. The helpers must find
    the union of the relevant actions and flag repeated trailing content.
    """
    from animation_test_addon.blueprint.blueprint_time_range import (
        count_trailing_repeats,
        detect_animated_frame_range,
        mesh_content_hash,
        trailing_static_frame_info,
    )

    # Pure repeat counter: only runs of identical trailing items count.
    assert count_trailing_repeats([1, 2, 3]) == 0
    assert count_trailing_repeats([1, 2, 2, 2]) == 2
    assert count_trailing_repeats([5, 5, 5]) == 2
    info = trailing_static_frame_info(["a", "b", "b"], [10, 11, 12], 12.0)
    assert info == {"held_frames": 1, "held_seconds": 1 / 12.0, "last_unique_frame": 11}
    assert trailing_static_frame_info(["a", "b"], [1, 2], 12.0) is None

    # Plain objects without any action fall back to the scene range.
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    assert detect_animated_frame_range(obj) is None

    # Object transform keys define the prefill range.
    obj.location = (0, 0, 0)
    obj.keyframe_insert(data_path="location", frame=3)
    obj.location = (1, 0, 0)
    obj.keyframe_insert(data_path="location", frame=5)
    assert detect_animated_frame_range(obj) == (3, 5)

    # Shape key value animation lives on the Key datablock and must widen
    # the range to the union of both actions.
    obj.shape_key_add()
    key_block = obj.shape_key_add()
    key_block.value = 0.0
    key_block.keyframe_insert(data_path="value", frame=1)
    key_block.value = 1.0
    key_block.keyframe_insert(data_path="value", frame=40)
    assert detect_animated_frame_range(obj) == (1, 40)
    # Blender 5.x folds shape key keyframes into the object's action, so
    # clearing the keys cannot restore the narrower range; drop them so the
    # mesh bake below samples a plain deformed cube.
    obj.shape_key_clear()

    # Armature actions count too; fractional keyframes widen to whole frames.
    fake = types.SimpleNamespace(
        animation_data=None,
        data=types.SimpleNamespace(shape_keys=None),
        find_armature=lambda: types.SimpleNamespace(
            animation_data=types.SimpleNamespace(
                action=types.SimpleNamespace(frame_range=(2.5, 9.2)))),
    )
    assert detect_animated_frame_range(fake) == (2, 10)

    # Baked meshes hash by content: a held pose repeats the same hash, so a
    # bake range past the last keyframe (keys end at 7) produces a static
    # tail that the warning helper measures in frames and seconds.
    bake = MMT_OT_BakeAnimationToTimeSwitch._bake_frames
    baked = bake(None, bpy.context, obj, [3, 4, 5, 6, 7])
    tokens = [mesh_content_hash(baked_obj.data) for _, baked_obj in baked]
    assert tokens[0] != tokens[1] != tokens[2]
    static_tail = trailing_static_frame_info(tokens, [f for f, _ in baked], 12.0)
    assert static_tail is not None
    assert static_tail["held_frames"] == 2
    assert static_tail["last_unique_frame"] == 5
    assert abs(static_tail["held_seconds"] - 2 / 12.0) < 1e-9
    for _, baked_obj in baked:
        bpy.data.objects.remove(baked_obj, do_unlink=True)
    print("PASS: keyed-range prefill, content hashing and static-tail detection")


def test_rebake_wiring_and_large_ranges():
    """Re-baking replaces existing multi-links instead of drawing both sets.

    A small graph stand-in is sufficient here: the function only edits links,
    socket labels and node placement. Mesh evaluation is tested separately.
    """
    sockets = [types.SimpleNamespace(name="old", links=[object()]) for _ in range(2)]
    old_links = [socket.links[0] for socket in sockets]
    def remove_link(link):
        for socket in sockets:
            if link in socket.links:
                socket.links.remove(link)
    def new_link(output, socket):
        socket.links.append(output)
    tree = types.SimpleNamespace(
        nodes=types.SimpleNamespace(new=lambda name: types.SimpleNamespace(outputs=[object()])),
        links=types.SimpleNamespace(remove=remove_link, new=new_link),
    )
    node = types.SimpleNamespace(inputs=sockets, location=types.SimpleNamespace(x=0, y=0))
    source = types.SimpleNamespace(name="source")
    baked = [(1, types.SimpleNamespace(name="frame1")), (2, types.SimpleNamespace(name="frame2"))]
    MMT_OT_BakeAnimationToTimeSwitch._rebuild_node_wiring(None, tree, node, baked, "abcd1234-0", source)
    assert all(len(socket.links) == 1 and socket.links[0] not in old_links for socket in sockets)
    assert [socket.name for socket in sockets] == ["Frame 0", "Frame 1"]
    # The UI asks for len() before enforcing its sample cap. A lazy range
    # avoids allocating billions of Python integers for an accidental input.
    settings = types.SimpleNamespace(frame_start=1, frame_end=1000000000, frame_step=1)
    frames = MMT_OT_BakeAnimationToTimeSwitch._frame_numbers(settings)
    assert isinstance(frames, range) and len(frames) == 1000000000
    print("PASS: replacement wiring and lazy sample ranges")


def test_wwmi_time_weights():
    """Exercise WWMI's separate weight writer with real section builders.

    Its append-order serializer must merge singleton headers, and neither
    compute command list may leave the game's borrowed CS resources null.
    """
    from animation_test_addon.games.wwmi import shapekeys
    from animation_test_addon.common.m_ini_builder import M_IniBuilder
    from animation_test_addon.common.m_ini_helper import M_IniHelper
    key = M_Key(key_name="$shapekey0", key_type="time_shapekey", value_list=[0, 1], weight_list=[0.0, 1.0])
    # WWMI must use the same keyboard driver as the shared shape path.
    key.configure_animation_toggle(types.SimpleNamespace(toggle_key="F7", start_enabled=False))
    model = types.SimpleNamespace(mesh_vertex_count=65, draw_ib="abcd1234")
    builder = M_IniBuilder()
    with patch.object(shapekeys, "get_wwmi_shapekey_entries", return_value=[("blink", "blink", key)]), patch.object(shapekeys, "copy_wwmi_shapekey_shaders_to_mod_folder"):
        shapekeys.add_wwmi_shapekey_sections(builder, model)
    # Add a draw timeline later, matching the real WWMI export call order.
    clock = M_Key(key_name="$clock", key_type="time", value_list=[0, 1])
    M_IniHelper.add_branch_key_sections(builder, {clock.key_name: clock})
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "wwmi.ini")
        builder.save_to_file_not_reorder(path)
        text = Path(path).read_text()
    assert text.count("[Present]") == text.count("[Constants]") == 1
    assert "global $shapekey0" in text and "persist $shapekey0" not in text
    assert "[Key_ShapeKey_blink]" not in text
    assert "[KeyMimiAnimation_shapekey0]" in text and "key = F7" in text
    assert "post run = CommandListMimiAnimation_shapekey0" in text
    assert "global $mimi_anim_shapekey0_enabled = 0" in text
    for slot in ("cs-u5", "cs-t50", "cs-t51"):
        assert text.count(slot + " = ref ResourceShapeBackup_" + slot) == 2
        assert slot + " = null" not in text
    print("PASS: WWMI timelines, singleton sections and CS state restoration")


def test_naraka_toggle_weights():
    """Dedicated Naraka exports must include the common time toggle as well.

    The compute still runs at the skinning hook, while the post-Present driver
    prepares a zero weight on disable and restarts the clock on reactivation.
    """
    from animation_test_addon.games.naraka import shapekeys
    from animation_test_addon.common.m_ini_builder import M_IniBuilder
    key = M_Key(key_name="$shapekey0", key_type="time_shapekey", value_list=[0, 1], weight_list=[0.4, 1.0])
    key.configure_animation_toggle(types.SimpleNamespace(toggle_key="F8", start_enabled=False))
    model = types.SimpleNamespace(draw_ib="abcd1234", vertex_count=65, shapekey_name_bytelist_dict={"blink": b"x"},
                                  d3d11_game_type=types.SimpleNamespace(CategoryStrideDict={"Position": 40}),
                                  get_category_buffer_filename=lambda category: "base.buf")
    builder = M_IniBuilder()
    with patch.object(shapekeys.BlueprintExportHelper, "get_current_shapekeyname_mkey_dict", return_value={"blink": key}), patch.object(shapekeys, "copy_shapes_hlsl_to_mod_folder"):
        shapekeys.add_naraka_shapekey_ini_sections(builder, {model.draw_ib: model}, [model])
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "naraka.ini")
        builder.save_to_file(path)
        text = Path(path).read_text()
    assert text.count("[KeyMimiAnimation_shapekey0]") == 1
    assert "post run = CommandListMimiAnimation_shapekey0" in text
    assert "key = F8" in text and "global $mimi_anim_shapekey0_enabled = 0" in text
    assert "[Key_ShapeKey_blink]" not in text
    print("PASS: Naraka shape-key toggle emission")


def test_toggle_rna_roundtrip():
    """Register real Blender nodes and round-trip their controls in a library.

    This catches missing RNA annotations and confirms old defaults, node copy
    behavior and saved blend data without loading or replacing a user scene.
    """
    from animation_test_addon.blueprint.blueprint_node_base import MIMISocketObject, MIMIBlueprintTree
    from animation_test_addon.blueprint.blueprint_node_time_switch import MIMINode_TimeSwitch
    from animation_test_addon.blueprint.blueprint_node_time_pos_switch import MIMINode_TimePosSwitch
    from animation_test_addon.blueprint.blueprint_node_time_shapekey import MIMINode_TimeShapeKey, MIMINodeTimeShapeKeyWeightItem
    classes = [MIMISocketObject, MIMIBlueprintTree, MIMINodeTimeShapeKeyWeightItem,
               MIMINode_TimeSwitch, MIMINode_TimePosSwitch, MIMINode_TimeShapeKey]
    trees = []
    try:
        for cls in classes:
            bpy.utils.register_class(cls)
        tree = bpy.data.node_groups.new("toggle_roundtrip", "MIMIBlueprintTreeType")
        trees.append(tree)
        for cls in classes[-3:]:
            node = tree.nodes.new(cls.bl_idname)
            assert node.toggle_key == "" and node.start_enabled
            node.toggle_key, node.start_enabled = "CTRL F6", False
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "toggles.blend")
            bpy.data.libraries.write(path, {tree})
            with bpy.data.libraries.load(path, link=False) as (source, target):
                target.node_groups = source.node_groups
            trees.extend(target.node_groups)
        for node in trees[-1].nodes:
            assert node.toggle_key == "CTRL F6" and not node.start_enabled
        print("PASS: all three Blender RNA controls and blend-library roundtrip")
    finally:
        # Remove only test-created trees before unregistering their node types.
        for tree in trees:
            bpy.data.node_groups.remove(tree)
        for cls in reversed(classes):
            bpy.utils.unregister_class(cls)


GlobalConfig.logic_name = LogicName.GIMI
test_graph_provenance()
test_toggle_aliases_and_shape_config()
test_switch_key_merging()
test_position_pipeline()
test_validation()
test_bake_and_rollback()
test_bake_range_prefill_and_static_tail()
test_rebake_wiring_and_large_ranges()
test_wwmi_time_weights()
test_naraka_toggle_weights()
test_toggle_rna_roundtrip()
print("ALL DYNAMIC ANIMATION BLENDER TESTS PASSED")
