"""Offline checks for the generic interaction deformation export.

The checks use stand-in model objects instead of Blender, so they can run
without a scene.  They cover the parts that decide whether the exported
mod can work at all:

1. The control weights of a region land on the right exported vertices.
2. The control record has the layout the runtime shader reads.
3. The generated INI binds the shader the way the game expects.
4. The written buffers have the byte size the resource declarations claim.
5. The shipped shader compiles as a compute shader.

Run with:
    python tools/test_interaction_export.py
"""

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.interaction import runtime  # noqa: E402
from common.interaction.exporter import collect_region_list, prepare_interaction  # noqa: E402
from common.interaction.runtime import InteractionRegion  # noqa: E402


# The stride and the layout of a GPU pre-skinning position category.
POSITION_STRIDE = 40


class FakeElement:
    """One element of the position category."""

    def __init__(self, semantic, byte_width, element_format):
        self.SemanticName = semantic
        self.ByteWidth = byte_width
        self.Format = element_format
        self.Category = "Position"


class FakeGameType:
    """The part of the data layout the interaction feature reads."""

    GPU_PreSkinning = True
    CategoryStrideDict = {"Position": POSITION_STRIDE}
    OrderedCategoryNameList = ["Position"]
    D3D11ElementList = [
        FakeElement("POSITION", 12, "R32G32B32_FLOAT"),
        FakeElement("NORMAL", 12, "R32G32B32_FLOAT"),
        FakeElement("TANGENT", 16, "R32G32B32A32_FLOAT"),
    ]


class FakeDrawCallModel:
    """One draw call of a submesh."""

    def __init__(self, obj_name):
        self.obj_name = obj_name


class FakeSubmeshModel:
    """One submesh of a DrawIB."""

    def __init__(self, submesh_name, obj_name, position_values, weights_by_group, index_vertex_id_dict, ib):
        self.submesh_name = submesh_name
        self.drawcall_model_list = [FakeDrawCallModel(obj_name)]
        self.category_buffer_dict = {"Position": position_values}
        self.index_vertex_id_dict = index_vertex_id_dict
        self.ib = ib
        self.export_vertex_attribute_dict = {
            "interaction_vertex_group_weights": {"weights_by_group": weights_by_group},
        }


class FakeDrawIBModel:
    """One DrawIB of an export."""

    def __init__(self, drawib, submesh_model_list):
        self.draw_ib = drawib
        self.d3d11_game_type = FakeGameType()
        self.submesh_model_list = submesh_model_list

    def _get_exported_vertex_count(self, submesh_model):
        if submesh_model.index_vertex_id_dict:
            return len(submesh_model.index_vertex_id_dict)
        position_buffer = submesh_model.category_buffer_dict.get("Position")
        if position_buffer is None:
            return 0
        return int(len(position_buffer) / POSITION_STRIDE)


def build_flat_grid(size=3):
    """Return a flat grid of vertices with a control group on one half."""
    coordinates = np.arange(size, dtype=np.float64) * 0.5
    grid_x, grid_y = np.meshgrid(coordinates, coordinates, indexing="ij")
    positions = np.stack([grid_x.ravel(), grid_y.ravel(), np.zeros(size * size)], axis=1)

    vertex_count = size * size
    # The control group covers the left half of the grid.
    weights = np.zeros(vertex_count, dtype=np.float64)
    for index in range(vertex_count):
        if positions[index, 0] < coordinates[-1] * 0.5 + 0.01:
            weights[index] = 1.0

    triangles = []
    for row in range(size - 1):
        for column in range(size - 1):
            corner = row * size + column
            triangles.append([corner, corner + size, corner + 1])
            triangles.append([corner + 1, corner + size, corner + size + 1])

    # Every exported vertex maps to the loop of the same Blender vertex,
    # so the exported order and the Blender order are identical here.
    index_vertex_id_dict = {index: index for index in range(vertex_count)}

    return positions, weights, triangles, index_vertex_id_dict


def build_position_buffer(positions):
    """Return the exported position buffer bytes of the given positions."""
    vertex_count = len(positions)
    values = np.zeros((vertex_count, POSITION_STRIDE // 4), dtype=np.float32)
    values[:, 0:3] = positions
    values[:, 3:6] = (0.0, 0.0, 1.0)
    values[:, 6:10] = (1.0, 0.0, 0.0, 1.0)
    # The exporter keeps the category buffer as a flat byte stream.
    return values.reshape(-1).view(np.uint8).reshape(-1)


def check_region_weights():
    """The weights of a region must land on the exported vertices."""
    positions, weights, triangles, index_vertex_id_dict = build_flat_grid()
    position_buffer = build_position_buffer(positions)

    submesh = FakeSubmeshModel(
        "LOD0.test-0", "TestBody", position_buffer,
        {"MimiInteraction_Chest": weights}, index_vertex_id_dict, triangles,
    )
    drawib_model = FakeDrawIBModel("test1234", [submesh])

    region = InteractionRegion(
        label="Chest",
        object_name="TestBody",
        vertex_group="MimiInteraction_Chest",
        offset=(0.1, 0.0, 0.0),
    )

    collected = runtime.collect_region_weights(drawib_model, region)
    if len(collected) != len(weights):
        raise AssertionError("the collected weights must cover every exported vertex")
    if not np.allclose(collected, weights):
        raise AssertionError("the collected weights do not match the control group")

    # A region that names another object must not pick up any weight.
    other_region = InteractionRegion(
        label="Other", object_name="SomeOtherBody",
        vertex_group="MimiInteraction_Chest", offset=(0.1, 0.0, 0.0),
    )
    other_collected = runtime.collect_region_weights(drawib_model, other_region)
    if float(np.abs(other_collected).max()) > 0.0:
        raise AssertionError("a region must not leak into another object")
    print("region weights: OK (" + str(len(collected)) + " vertices)")


def check_prepared_data_and_ini():
    """The prepared data and the generated INI must agree with each other."""
    positions, weights, triangles, index_vertex_id_dict = build_flat_grid()
    position_buffer = build_position_buffer(positions)

    submesh = FakeSubmeshModel(
        "LOD0.test-0", "TestBody", position_buffer,
        {"MimiInteraction_Chest": weights}, index_vertex_id_dict, triangles,
    )
    drawib_model = FakeDrawIBModel("test1234", [submesh])

    from common.interaction.backend import GpuPreSkinningBackend
    backend = GpuPreSkinningBackend()

    region = InteractionRegion(
        label="Chest", object_name="TestBody",
        vertex_group="MimiInteraction_Chest", offset=(0.1, 0.0, 0.0),
    )

    prepared = prepare_interaction([drawib_model], [region], backend)
    if "test1234" not in prepared:
        raise AssertionError("the DrawIB was not prepared")
    data = prepared["test1234"]

    vertex_count = len(positions)
    if data["vertex_count"] != vertex_count:
        raise AssertionError("the prepared vertex count is wrong")
    if data["control_record"].shape != (vertex_count, 8):
        raise AssertionError("the control record must hold eight floats per vertex")

    # The pull of the region is a fraction of the model size.
    expected_magnitude = 0.1 * data["model_extent"]
    actual_magnitude = float(np.linalg.norm(data["region_offsets"][0]))
    if abs(actual_magnitude - expected_magnitude) > 1e-6:
        raise AssertionError("the pull is not scaled by the model size")
    if actual_magnitude > data["safe_distance"] + 1e-9:
        raise AssertionError("the pull exceeds the safe distance")

    # The state buffer carries the pull of the region.
    state = data["state_record"]
    if abs(float(state[0, 0]) - float(data["region_offsets"][0][0])) > 1e-6:
        raise AssertionError("the state does not carry the pull of the first region")

    # The INI must bind the shader the way the game expects.  The builder
    # only renders its sections when it writes the file, so the check
    # reads the written file back.
    from common.m_ini_builder import M_IniBuilder
    builder = M_IniBuilder()
    runtime.append_interaction_ini_sections(
        builder,
        "test1234",
        vertex_count,
        POSITION_STRIDE,
        runtime.get_controls_buffer_filename("test1234"),
        runtime.get_state_buffer_filename("test1234"),
        "Buffers/LOD0.test1234-Position.buf",
    )
    with tempfile.TemporaryDirectory() as temporary_folder:
        ini_path = os.path.join(temporary_folder, "test.ini")
        builder.save_to_file_not_reorder(ini_path)
        with open(ini_path, "r", encoding="utf-8") as ini_file:
            text = ini_file.read()
    for expected_line in (
        "[CustomShaderComputeInteractiontest1234]",
        "cs = " + runtime.APPLY_SHADER_FILENAME,
        "cs-t40 = " + runtime.get_rest_resource_name("test1234"),
        "cs-t41 = " + runtime.get_controls_resource_name("test1234"),
        "cs-t42 = " + runtime.get_state_resource_name("test1234"),
        "cs-u5 = ref " + runtime.get_deformed_resource_name("test1234"),
        "dispatch = " + str((vertex_count + 63) // 64) + ",1,1",
        "Resource" + "test1234" + "Position = ref " + runtime.get_deformed_resource_name("test1234"),
        "stride = 32",
        "byte_width = " + str(vertex_count * POSITION_STRIDE),
    ):
        if expected_line not in text:
            raise AssertionError("the generated INI is missing: " + expected_line)
    print("prepared data and INI: OK")

    # The written buffers must have the size the declarations claim.
    with tempfile.TemporaryDirectory() as temporary_folder:
        runtime.write_interaction_files(
            temporary_folder, "test1234", data["control_record"], data["state_record"])
        controls_path = os.path.join(temporary_folder, runtime.BUFFER_SUBFOLDER, "test1234-Controls.buf")
        state_path = os.path.join(temporary_folder, runtime.BUFFER_SUBFOLDER, "test1234-State.buf")
        if os.path.getsize(controls_path) != vertex_count * 32:
            raise AssertionError("the control buffer has the wrong size")
        if os.path.getsize(state_path) != runtime.STATE_RECORD_COUNT * runtime.STATE_RECORD_SIZE:
            raise AssertionError("the state buffer has the wrong size")
    print("buffer sizes: OK")


def check_region_collection():
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
        FakeNode([FakeEntry(True, "MimiInteraction_Chest"), FakeEntry(False, "MimiInteraction_Back")]),
        FakeNode([FakeEntry(True, "")]),
    ])
    if len(region_list) != 1:
        raise AssertionError("only the enabled region with a control group may survive")
    if region_list[0].vertex_group != "MimiInteraction_Chest":
        raise AssertionError("the wrong region survived")
    print("region collection: OK")


def check_shader_compiles():
    """The shipped shader must compile as a compute shader."""
    import ctypes
    from pathlib import Path

    system = Path(os.environ["SystemRoot"]) / "System32"
    compiler = ctypes.WinDLL(str(system / "d3dcompiler_47.dll"))
    source_path = Path(__file__).resolve().parents[1] / "resources" / "interaction" / runtime.APPLY_SHADER_FILENAME
    source = source_path.read_bytes()

    code = ctypes.POINTER(ctypes.c_void_p)()
    errors = ctypes.POINTER(ctypes.c_void_p)()
    compiler.D3DCompile.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ]
    compiler.D3DCompile.restype = ctypes.c_long
    result = compiler.D3DCompile(
        source, len(source), b"interaction_apply_cs.hlsl", None, None,
        b"main", b"cs_5_0", 0, 0, ctypes.byref(code), ctypes.byref(errors))

    if errors:
        errors.contents.value
    if result < 0:
        message = ""
        if errors:
            buffer = ctypes.cast(errors, ctypes.POINTER(ctypes.c_void_p)).contents.value
            # ID3D10Blob::GetBufferPointer is the first virtual call.
            message_pointer = ctypes.c_char_p(ctypes.cast(
                ctypes.cast(buffer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents.value,
                ctypes.POINTER(ctypes.c_char_p)).contents.value)
            message = message_pointer.value.decode("utf-8", errors="replace") if message_pointer.value else ""
        raise AssertionError("the interaction shader does not compile: " + message)
    print("shader compiles as cs_5_0: OK")


def main():
    check_region_weights()
    check_prepared_data_and_ini()
    check_region_collection()
    check_shader_compiles()
    print("all interaction export checks passed")


if __name__ == "__main__":
    main()
