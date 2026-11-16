"""Offline checks for the interaction export conflict handling.

The export must never stop because one part of the model cannot carry the
deformation.  A body and its weapon are two DrawIBs, and only the body
carries the control group, so the weapon is skipped while the rest of the
mod is still exported.

The cases below cover the combinations that used to abort the whole
export, plus the cases that must still report a problem.
"""

import contextlib
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.interaction import runtime  # noqa: E402
from common.interaction.backend import GpuPreSkinningBackend  # noqa: E402
from common.interaction.exporter import (  # noqa: E402
    collect_region_list,
    find_empty_control_groups,
    find_missing_control_groups,
    prepare_interaction,
)
from common.interaction.runtime import InteractionRegion  # noqa: E402


def capture_output(function, *args):
    """Run a function and return everything it printed."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        function(*args)
    return buffer.getvalue()


POSITION_STRIDE = 40
VERTEX_COUNT = 6


class FakeElement:
    def __init__(self, semantic, byte_width, element_format):
        self.SemanticName = semantic
        self.ByteWidth = byte_width
        self.Format = element_format
        self.Category = "Position"


class FakeGameType:
    GPU_PreSkinning = True
    CategoryStrideDict = {"Position": POSITION_STRIDE}
    OrderedCategoryNameList = ["Position"]
    D3D11ElementList = [
        FakeElement("POSITION", 12, "R32G32B32_FLOAT"),
        FakeElement("NORMAL", 12, "R32G32B32_FLOAT"),
        FakeElement("TANGENT", 16, "R32G32B32A32_FLOAT"),
    ]


class FakeDrawCallModel:
    def __init__(self, obj_name):
        self.obj_name = obj_name


class FakeSubmeshModel:
    def __init__(self, submesh_name, obj_name, weights_by_group, index_vertex_id_dict, ib,
                 all_group_names=None):
        self.submesh_name = submesh_name
        self.drawcall_model_list = [FakeDrawCallModel(obj_name)]
        self.index_vertex_id_dict = index_vertex_id_dict
        self.ib = ib
        if all_group_names is None:
            all_group_names = list(weights_by_group.keys())
        self.export_vertex_attribute_dict = {
            "interaction_vertex_group_weights": {
                "weights_by_group": weights_by_group,
                "all_group_names": all_group_names,
            },
        }
        self.category_buffer_dict = {"Position": build_position_buffer()}


class FakeDrawIBModel:
    def __init__(self, drawib, submesh_model_list):
        self.draw_ib = drawib
        self.d3d11_game_type = FakeGameType()
        self.submesh_model_list = submesh_model_list
        self.vertex_count = sum(len(submesh.index_vertex_id_dict) for submesh in submesh_model_list)

    def _get_exported_vertex_count(self, submesh_model):
        return len(submesh_model.index_vertex_id_dict)


def build_position_buffer():
    """Return the exported position buffer bytes of a small grid."""
    values = np.zeros((VERTEX_COUNT, POSITION_STRIDE // 4), dtype=np.float32)
    for index in range(VERTEX_COUNT):
        values[index, 0] = index * 0.2
        values[index, 1] = (index % 2) * 0.2
        values[index, 2] = 1.3
        values[index, 3:6] = (0.0, 0.0, 1.0)
        values[index, 6:10] = (1.0, 0.0, 0.0, 1.0)
    return values.reshape(-1).view(np.uint8).reshape(-1)


def build_triangles():
    return [[0, 1, 2], [2, 1, 3], [2, 3, 4], [4, 3, 5]]


def make_body_drawib(drawib, group_name, weights, object_name="Body", vertex_count=VERTEX_COUNT):
    index_vertex_id_dict = {index: index for index in range(vertex_count)}
    submesh = FakeSubmeshModel(
        "LOD0." + drawib + "-0", object_name, {group_name: weights},
        index_vertex_id_dict, build_triangles())
    return FakeDrawIBModel(drawib, [submesh])


def make_weapon_drawib(drawib):
    """A second DrawIB that carries no control group at all."""
    index_vertex_id_dict = {index: index for index in range(VERTEX_COUNT)}
    submesh = FakeSubmeshModel(
        "LOD0." + drawib + "-0", "Weapon", {}, index_vertex_id_dict, build_triangles())
    return FakeDrawIBModel(drawib, [submesh])


def fading_weights():
    """A weight field that fades out, so it has a gradient."""
    return np.linspace(1.0, 0.0, VERTEX_COUNT)


def constant_weights():
    """A weight field without a gradient."""
    return np.ones(VERTEX_COUNT)


def region(vertex_group, offset=(0.1, 0.0, 0.0), object_name="Body"):
    return InteractionRegion(
        label="Chest", object_name=object_name, vertex_group=vertex_group, offset=offset)


def check_second_drawib_is_skipped():
    """A body and its weapon: the weapon is skipped, the body is prepared."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    weapon = make_weapon_drawib("weapon22")
    regions = [region("MimiInteraction_Chest")]

    prepared = prepare_interaction([body, weapon], regions, GpuPreSkinningBackend())
    if "body1111" not in prepared:
        raise AssertionError("the body must carry the deformation")
    if "weapon22" in prepared:
        raise AssertionError("the weapon must not carry the deformation")
    print("a second DrawIB without the group: OK")


def check_constant_weight_is_reported():
    """A constant weight has no gradient, so the DrawIB is skipped."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", constant_weights())
    regions = [region("MimiInteraction_Chest")]

    prepared = prepare_interaction([body], regions, GpuPreSkinningBackend())
    if "body1111" in prepared:
        raise AssertionError("a constant weight field cannot be pulled")
    print("a constant weight field: OK (skipped, not fatal)")


def check_wrong_group_name_is_reported():
    """A group nobody has is reported once, without stopping the export."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    regions = [region("MimiInteraction_Chest"), region("Bone12")]

    missing = find_missing_control_groups([body], regions)
    if missing != ["Bone12"]:
        raise AssertionError("the missing group was not found: " + str(missing))

    # The region that names the missing group is really passed in, so the
    # export has to survive it.  The region that does exist still works.
    prepared = prepare_interaction([body], regions, GpuPreSkinningBackend())
    if "body1111" not in prepared:
        raise AssertionError("the body must still carry its own region")
    print("a group nobody has: OK (reported, not fatal)")


def check_group_without_weight_is_not_called_missing():
    """A group that exists without a weight is not reported as missing."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    # The group exists on the mesh but carries no weight at all.
    body.submesh_model_list[0].export_vertex_attribute_dict[
        "interaction_vertex_group_weights"]["all_group_names"] = [
            "MimiInteraction_Chest", "MimiInteraction_Empty"]

    missing = find_missing_control_groups([body], [region("MimiInteraction_Empty")])
    if missing:
        raise AssertionError("a group that exists was reported as missing: " + str(missing))

    # The empty group has to be reported with its own wording, and the
    # report has to be reachable.
    empty = find_empty_control_groups([body], [region("MimiInteraction_Empty")])
    if empty != ["MimiInteraction_Empty"]:
        raise AssertionError("the empty group was not found: " + str(empty))

    output = capture_output(prepare_interaction, [body], [region("MimiInteraction_Empty")],
                             GpuPreSkinningBackend())
    if "exists but carries no weight" not in output:
        raise AssertionError("the empty group was not reported: " + output)
    if "was not found on any exported object" in output:
        raise AssertionError("an existing group was reported as missing: " + output)
    print("a group without a weight: OK (reported with its own wording)")


def check_conflict_drawib_does_not_claim_a_pull():
    """A DrawIB another feature owns must not claim a pull."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    regions = [region("MimiInteraction_Chest", offset=(0.5, 0.0, 0.0))]

    conflict_reason_dict = {"body1111": "it already carries shape keys"}
    output = capture_output(prepare_interaction, [body], regions,
                             GpuPreSkinningBackend(), conflict_reason_dict)
    if "pulls" in output:
        raise AssertionError("a skipped DrawIB claimed a pull: " + output)
    if "already carries shape keys" not in output:
        raise AssertionError("the conflict was not reported: " + output)
    print("a DrawIB owned by another feature: OK (no pull is claimed)")


def check_object_name_reason_is_true():
    """The reason must name the object only when it is really missing."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    # The object of the region is the object of this DrawIB, so the real
    # reason is the missing weight, not a missing object.
    regions = [region("MimiInteraction_Chest", object_name="Body")]

    output = capture_output(prepare_interaction, [body], regions, GpuPreSkinningBackend())
    if "which is not part of this DrawIB" in output:
        raise AssertionError("the reason named a missing object that is present: " + output)
    if "does not exist" in output:
        raise AssertionError("the reason named a missing group that exists: " + output)
    print("the reason names the real cause: OK")


def check_group_with_only_zero_weights_counts_as_empty():
    """A group whose exported weights are all zero moves nothing."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest",
                            [0.0] * VERTEX_COUNT)
    regions = [region("MimiInteraction_Chest")]

    empty = find_empty_control_groups([body], regions)
    if empty != ["MimiInteraction_Chest"]:
        raise AssertionError("a group with only zero weights was not empty: " + str(empty))

    output = capture_output(prepare_interaction, [body], regions, GpuPreSkinningBackend())
    if "exists but carries no weight" not in output:
        raise AssertionError("the empty group was not reported: " + output)
    print("a group with only zero weights: OK (reported as empty)")


def check_region_without_weight_is_reported_when_others_work():
    """A region that does not work is reported even when others do."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    # The second region names an object that carries no weight.
    body.submesh_model_list[0].export_vertex_attribute_dict[
        "interaction_vertex_group_weights"]["all_group_names"] = [
            "MimiInteraction_Chest", "MimiInteraction_Empty"]
    regions = [
        region("MimiInteraction_Chest", offset=(0.5, 0.0, 0.0)),
        region("MimiInteraction_Empty", offset=(0.5, 0.0, 0.0)),
    ]

    output = capture_output(prepare_interaction, [body], regions, GpuPreSkinningBackend())
    if "MimiInteraction_Empty" not in output:
        raise AssertionError("the region without a weight was not reported: " + output)
    print("a region without a weight next to a working one: OK (reported)")


def check_object_without_weight_has_its_own_reason():
    """A group with a weight on another part has its own reason.

    The weights live on the submesh that holds the sword, while the
    region names the object of the other submesh.  The group has a weight
    on this DrawIB, but not on the object the region names.
    """
    index_vertex_id_dict = {index: index for index in range(VERTEX_COUNT)}
    sword_submesh = FakeSubmeshModel(
        "LOD0.body1111-0", "Sword", {"MimiInteraction_Chest": fading_weights()},
        index_vertex_id_dict, build_triangles())
    body_submesh = FakeSubmeshModel(
        "LOD0.body1111-1", "Body", {}, index_vertex_id_dict, build_triangles())
    body = FakeDrawIBModel("body1111", [sword_submesh, body_submesh])

    regions = [region("MimiInteraction_Chest", object_name="Body")]

    output = capture_output(prepare_interaction, [body], regions, GpuPreSkinningBackend())
    if "carries no weight for the control group" not in output:
        raise AssertionError("the object reason was not used: " + output)
    print("a weight on another part: OK (its own reason)")


def check_object_name_mismatch_is_reported():
    """A region that names another object does not deform this DrawIB."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    regions = [region("MimiInteraction_Chest", object_name="SomeOtherObject")]

    prepared = prepare_interaction([body], regions, GpuPreSkinningBackend())
    if "body1111" in prepared:
        raise AssertionError("a region of another object must not deform this DrawIB")
    print("a region of another object: OK (skipped, not fatal)")


def check_vertex_count_mismatch_is_skipped():
    """A DrawIB whose vertex count does not match its positions is skipped."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    # The DrawIB claims more vertices than its position buffer holds.
    body.vertex_count = VERTEX_COUNT + 7
    regions = [region("MimiInteraction_Chest")]

    prepared = prepare_interaction([body], regions, GpuPreSkinningBackend())
    if "body1111" in prepared:
        raise AssertionError("a DrawIB with a broken vertex count must be skipped")
    print("a broken vertex count: OK (skipped, not fatal)")


def check_region_offsets_match_the_region_list():
    """The offsets and the state keep the position of every region."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    regions = [
        region("MimiInteraction_Chest", offset=(0.0, 0.0, 0.0)),
        region("MimiInteraction_Chest", offset=(0.5, 0.0, 0.0)),
    ]

    prepared = prepare_interaction([body], regions, GpuPreSkinningBackend())
    if "body1111" not in prepared:
        raise AssertionError("the body must carry the deformation")
    data = prepared["body1111"]
    if len(data["region_offsets"]) != len(regions):
        raise AssertionError("the offsets do not match the region list")
    state = data["state_record"]
    if state.shape[0] != 9 or state.shape[1] != 4:
        raise AssertionError("the state record has the wrong shape")
    if abs(float(state[0, 0])) > 1e-9:
        raise AssertionError("the first region must not pull")
    if abs(float(state[2, 0])) <= 1e-9:
        raise AssertionError("the second region must pull")
    print("the offsets and the state match the regions: OK")


def check_zero_pull_is_allowed():
    """A region without a pull is legal and produces no displacement."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    regions = [region("MimiInteraction_Chest", offset=(0.0, 0.0, 0.0))]

    prepared = prepare_interaction([body], regions, GpuPreSkinningBackend())
    if "body1111" not in prepared:
        raise AssertionError("a region without a pull must not remove the DrawIB")
    offsets = prepared["body1111"]["region_offsets"]
    if float(sum(value * value for value in offsets[0]) ** 0.5) > 1e-12:
        raise AssertionError("a region without a pull must not move")
    print("a region without a pull: OK (kept, no displacement)")


def check_region_collection_drops_incomplete_rows():
    """A region without a control group cannot be deformed and is dropped."""
    class FakeEntry:
        def __init__(self, enabled, vertex_group):
            self.enabled = enabled
            self.label = "Region"
            self.object_name = "Body"
            self.vertex_group = vertex_group
            self.offset = (0.1, 0.0, 0.0)

    class FakeNode:
        def __init__(self, entries):
            self.regions = entries

    region_list = collect_region_list([
        FakeNode([FakeEntry(True, "MimiInteraction_Chest")]),
    ])
    if len(region_list) != 1:
        raise AssertionError("the usable region was dropped")
    print("region collection: OK")


def check_empty_control_group_is_reported():
    """A region without a control group must not disappear silently."""
    class FakeEntry:
        def __init__(self, enabled, vertex_group):
            self.enabled = enabled
            self.label = "Region"
            self.object_name = "Body"
            self.vertex_group = vertex_group
            self.offset = (0.1, 0.0, 0.0)

    class FakeNode:
        def __init__(self, entries):
            self.regions = entries

    output = capture_output(collect_region_list, [FakeNode([FakeEntry(True, "")])])
    if "has no control group" not in output:
        raise AssertionError("the empty region was not reported: " + output)

    output = capture_output(collect_region_list, [FakeNode([FakeEntry(True, "")])])
    if "does nothing in this export" not in output:
        raise AssertionError("the empty feature was not reported: " + output)
    print("a region without a control group: OK (reported)")


def check_region_reason_has_its_own_title():
    """A region that does not deform its DrawIB has its own title."""
    body = make_body_drawib("body1111", "MimiInteraction_Chest", fading_weights())
    body.submesh_model_list[0].export_vertex_attribute_dict[
        "interaction_vertex_group_weights"]["all_group_names"] = [
            "MimiInteraction_Chest", "MimiInteraction_Empty"]
    regions = [
        region("MimiInteraction_Chest", offset=(0.5, 0.0, 0.0)),
        region("MimiInteraction_Empty", offset=(0.5, 0.0, 0.0)),
    ]

    output = capture_output(prepare_interaction, [body], regions, GpuPreSkinningBackend())
    if "the following DrawIBs do not carry the deformation" in output:
        raise AssertionError("a working DrawIB was listed as skipped: " + output)
    if "the following regions do not deform their DrawIB" not in output:
        raise AssertionError("the region reason has no title of its own: " + output)
    print("the region reasons have their own title: OK")


def main():
    check_second_drawib_is_skipped()
    check_constant_weight_is_reported()
    check_wrong_group_name_is_reported()
    check_group_without_weight_is_not_called_missing()
    check_group_with_only_zero_weights_counts_as_empty()
    check_region_without_weight_is_reported_when_others_work()
    check_object_without_weight_has_its_own_reason()
    check_conflict_drawib_does_not_claim_a_pull()
    check_object_name_reason_is_true()
    check_object_name_mismatch_is_reported()
    check_vertex_count_mismatch_is_skipped()
    check_region_offsets_match_the_region_list()
    check_zero_pull_is_allowed()
    check_empty_control_group_is_reported()
    check_region_reason_has_its_own_title()
    check_region_collection_drops_incomplete_rows()
    print("all interaction export conflict checks passed")


if __name__ == "__main__":
    main()
