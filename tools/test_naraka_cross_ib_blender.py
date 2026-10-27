"""Naraka timeline-level Cross-IB batch regression tests.

The batch feature has two layers:

1. the parser stamps every draw of a DrawIndex timeline with the timeline's
   graph-provenance key (covered by test_dynamic_animation_blender.py),
2. the Naraka post-processor turns that key into one host Submesh and rejects
   ambiguous or contradictory configurations (covered here).

Run with:
    blender -b --factory-startup --python-exit-code 1 --python this_file
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "naraka_cross_ib_test_addon"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE_NAME] = package

from naraka_cross_ib_test_addon.common.global_config import GlobalConfig, LogicName
from naraka_cross_ib_test_addon.model.draw_call_model import DrawCallModel
from naraka_cross_ib_test_addon.blueprint.blueprint_node_group import GROUP_NODE_IDNAME
from naraka_cross_ib_test_addon.blueprint.blueprint_node_time_switch import (
    MIMINode_TimeSwitch,
    time_switch_owner_key,
)
from naraka_cross_ib_test_addon.games.naraka.nodes import MIMINode_NarakaCrossIBRender
from naraka_cross_ib_test_addon.games.naraka.cross_ib import apply_cross_ib_render_nodes


HOST_SUBMESH = "LOD0.host-0"
GUEST_SUBMESH = "LOD0.guest-3"
TIMELINE_KEY = "Blueprint::Timeline"


def rejects(function, expected_message):
    """Assert that a call fails with the specific diagnostic we expect."""
    try:
        function()
    except ValueError as error:
        assert expected_message in str(error), str(error)
    else:
        raise AssertionError("Expected validation error: " + expected_message)


def make_draw(obj_name, submesh_name, owner_key=""):
    """One parsed draw call with the fields the post-processor reads."""
    draw = DrawCallModel(obj_name=obj_name, submesh_name=submesh_name)
    draw.time_switch_owner_key = owner_key
    return draw


def make_model(draw_list, parsed_keys):
    """Minimal model surface used by the tree post-processor."""
    return types.SimpleNamespace(
        ordered_draw_obj_data_model_list=list(draw_list),
        parsed_time_switch_owner_keys=set(parsed_keys),
    )


def make_time_node(name="Timeline", enabled=True, host_name="Host", muted=False):
    """Fake DrawIndex timeline node; the real class supplies the bl_idname."""
    host_object = None
    if host_name:
        host_object = types.SimpleNamespace(name=host_name, type='MESH')
    node = types.SimpleNamespace(
        bl_idname=MIMINode_TimeSwitch.bl_idname,
        mute=muted,
        name=name,
        id_data=types.SimpleNamespace(name="Blueprint"),
        cross_ib_enabled=enabled,
        cross_ib_host_object=host_object,
    )
    node.as_pointer = lambda: id(node)
    return node


def make_cross_node(pair_list):
    """Fake manual Cross-IB node with (source, target) rows."""
    pairs = []
    for source_name, target_name in pair_list:
        pairs.append(types.SimpleNamespace(source_object=source_name, target_object=target_name))
    return types.SimpleNamespace(
        bl_idname=MIMINode_NarakaCrossIBRender.bl_idname,
        mute=False,
        name="CrossIB",
        pairs=pairs,
    )


def make_group_node(child_tree):
    """Fake custom group node so the scan has to recurse into its tree."""
    return types.SimpleNamespace(
        bl_idname=GROUP_NODE_IDNAME,
        mute=False,
        node_tree=child_tree,
    )


def make_tree(node_list):
    return types.SimpleNamespace(nodes=list(node_list))


def run_with_logic(logic_name, tree, model):
    """Run the post-processor under a chosen preset and restore it afterwards."""
    original_logic_name = GlobalConfig.logic_name
    GlobalConfig.logic_name = logic_name
    try:
        apply_cross_ib_render_nodes(tree, model)
    finally:
        GlobalConfig.logic_name = original_logic_name


def run_naraka(tree, model):
    run_with_logic(LogicName.Naraka, tree, model)


def test_batch_marks_every_frame():
    host_draw = make_draw("Host", HOST_SUBMESH)
    frame_draw_list = [
        make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY),
        make_draw("Frame1", GUEST_SUBMESH, TIMELINE_KEY),
        make_draw("Frame2", GUEST_SUBMESH, TIMELINE_KEY),
    ]
    model = make_model([host_draw] + frame_draw_list, [TIMELINE_KEY])

    run_naraka(make_tree([make_time_node()]), model)

    assert all(draw.cross_render_at_submesh == HOST_SUBMESH for draw in frame_draw_list)
    assert host_draw.cross_render_at_submesh == ""
    print("PASS: every frame of one timeline is marked with the host Submesh")


def test_manual_pair_still_works():
    host_draw = make_draw("Host", HOST_SUBMESH)
    guest_draw = make_draw("Guest", GUEST_SUBMESH)
    model = make_model([host_draw, guest_draw], [])

    run_naraka(make_tree([make_cross_node([("Guest", "Host")])]), model)

    assert guest_draw.cross_render_at_submesh == HOST_SUBMESH
    assert host_draw.cross_render_at_submesh == ""
    print("PASS: the original manual pair path is unchanged")


def test_group_nested_timeline_is_found():
    host_draw = make_draw("Host", HOST_SUBMESH)
    frame_draw = make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY)
    model = make_model([host_draw, frame_draw], [TIMELINE_KEY])
    inner_tree = make_tree([make_time_node()])
    root_tree = make_tree([make_group_node(inner_tree)])

    run_naraka(root_tree, model)

    assert frame_draw.cross_render_at_submesh == HOST_SUBMESH
    print("PASS: a timeline inside a custom group is found by the scan")


def test_conflicting_hosts_are_rejected():
    host_draw = make_draw("Host", HOST_SUBMESH)
    other_host_draw = make_draw("OtherHost", "LOD0.other-1")
    frame_draw = make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY)
    model = make_model([host_draw, other_host_draw, frame_draw], [TIMELINE_KEY])
    tree = make_tree([
        make_time_node(),
        # The manual pair asks for a different host for the same draw.
        make_cross_node([("Frame0", "OtherHost")]),
    ])

    rejects(lambda: run_naraka(tree, model), "two different host Submeshes")
    print("PASS: a timeline and a manual pair cannot disagree silently")


def test_frames_already_at_host_are_rejected():
    host_draw = make_draw("Host", HOST_SUBMESH)
    frame_draw = make_draw("Frame0", HOST_SUBMESH, TIMELINE_KEY)
    model = make_model([host_draw, frame_draw], [TIMELINE_KEY])

    rejects(
        lambda: run_naraka(make_tree([make_time_node()]), model),
        "needs no cross-IB",
    )
    print("PASS: frames already inside the host Submesh produce a clear error")


def test_missing_host_is_rejected():
    host_draw = make_draw("Host", HOST_SUBMESH)
    frame_draw = make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY)
    model = make_model([host_draw, frame_draw], [TIMELINE_KEY])

    rejects(
        lambda: run_naraka(make_tree([make_time_node(host_name=None)]), model),
        "no host object",
    )
    print("PASS: enabling the batch without a host object is rejected")


def test_empty_timeline_is_rejected():
    host_draw = make_draw("Host", HOST_SUBMESH)
    model = make_model([host_draw], [TIMELINE_KEY])

    rejects(
        lambda: run_naraka(make_tree([make_time_node()]), model),
        "no exported frame objects",
    )
    print("PASS: a connected timeline without exported frames is rejected")


def test_unconnected_timeline_is_ignored():
    host_draw = make_draw("Host", HOST_SUBMESH)
    frame_draw = make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY)
    # The key is not in the parsed set: the timeline is not wired to the output.
    model = make_model([host_draw, frame_draw], [])

    run_naraka(make_tree([make_time_node()]), model)

    assert frame_draw.cross_render_at_submesh == ""
    print("PASS: an unconnected timeline node does not affect the export")


def test_muted_timeline_is_ignored():
    host_draw = make_draw("Host", HOST_SUBMESH)
    frame_draw = make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY)
    model = make_model([host_draw, frame_draw], [TIMELINE_KEY])

    run_naraka(make_tree([make_time_node(muted=True)]), model)

    assert frame_draw.cross_render_at_submesh == ""
    print("PASS: a muted timeline node does not affect the export")


def test_host_with_multiple_submeshes_is_rejected():
    host_draw_a = make_draw("Host", "LOD0.host-0")
    host_draw_b = make_draw("Host", "LOD0.host-1")
    frame_draw = make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY)
    model = make_model([host_draw_a, host_draw_b, frame_draw], [TIMELINE_KEY])

    rejects(
        lambda: run_naraka(make_tree([make_time_node()]), model),
        "more than one Submesh",
    )
    print("PASS: a host object with two Submeshes is rejected")


def test_source_equal_to_target_is_rejected():
    host_draw = make_draw("Host", HOST_SUBMESH)
    model = make_model([host_draw], [])

    rejects(
        lambda: run_naraka(make_tree([make_cross_node([("Host", "Host")])]), model),
        "must be different objects",
    )
    print("PASS: a self-referencing manual pair is rejected")


def test_non_naraka_preset_is_rejected():
    host_draw = make_draw("Host", HOST_SUBMESH)
    frame_draw = make_draw("Frame0", GUEST_SUBMESH, TIMELINE_KEY)
    model = make_model([host_draw, frame_draw], [TIMELINE_KEY])

    rejects(
        lambda: run_with_logic(LogicName.GIMI, make_tree([make_time_node()]), model),
        "only supported under the Naraka",
    )
    print("PASS: the batch stays Naraka-only")


def main():
    # The provenance helper itself must stay stable because the parser and the
    # post-processor independently rebuild it from the same node.
    assert time_switch_owner_key(make_time_node()) == TIMELINE_KEY

    test_batch_marks_every_frame()
    test_manual_pair_still_works()
    test_group_nested_timeline_is_found()
    test_conflicting_hosts_are_rejected()
    test_frames_already_at_host_are_rejected()
    test_missing_host_is_rejected()
    test_empty_timeline_is_rejected()
    test_unconnected_timeline_is_ignored()
    test_muted_timeline_is_ignored()
    test_host_with_multiple_submeshes_is_rejected()
    test_source_equal_to_target_is_rejected()
    test_non_naraka_preset_is_rejected()
    print("ALL NARAKA CROSS-IB BATCH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
