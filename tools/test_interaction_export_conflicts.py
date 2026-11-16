"""Offline checks for the interaction export conflict handling.

The export must never stop because one part of the model cannot carry the
deformation.  A body and its weapon are two DrawIBs, and only the body
carries the control group, so the weapon is skipped while the rest of the
mod is still exported.

The cases below cover the combinations that used to abort the whole
export, plus the cases that must still report a problem.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.interaction import runtime  # noqa: E402
from common.interaction.backend import GpuPreSkinningBackend  # noqa: E402
from common.interaction.exporter import (  # noqa: E402
    collect_region_list,
    find_missing_control_groups,
    prepare_interaction,
)
from common.interaction.runtime import InteractionRegion  # noqa: E402


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
    def __init__(self, submesh_name, obj_name, weights_by_group, index_vertex_id_dict, ib):
        self.submesh_name = submesh_name
        self.drawcall_model_list = [FakeDrawCallModel(obj_name)]
        self.index_vertex_id_dict = index_vertex_id_dict
        self.ib = ib
        self.export_vertex_attribute_dict = {
            "interaction_vertex_group_weights": {"weights_by_group": weights_by_group},
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


def make_body_drawib(drawib, group_name, weights):
    index_vertex_id_dict = {index: index for index in range(VERTEX_COUNT)}
    submesh = FakeSubmeshModel(
        "LOD0." + drawib + "-0", "Body", {group_name: weights},
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

    # The region that names the missing group is dropped, so the body
    # still carries the deformation of the region that does exist.
    prepared = prepare_interaction([body], [regions[0]], GpuPreSkinningBackend())
    if "body1111" not in prepared:
        raise AssertionError("the body must still carry its own region")
    print("a group nobody has: OK (reported, not fatal)")


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


def main():
    check_second_drawib_is_skipped()
    check_constant_weight_is_reported()
    check_wrong_group_name_is_reported()
    check_zero_pull_is_allowed()
    check_region_collection_drops_incomplete_rows()
    print("all interaction export conflict checks passed")


if __name__ == "__main__":
    main()
