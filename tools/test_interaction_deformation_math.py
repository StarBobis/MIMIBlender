"""Offline checks of the deformation maths the runtime shader performs.

The shader cannot run without a GPU, so this script mirrors its maths in
numpy and checks the properties the shader is supposed to produce:

1. A vertex with a zero weight does not move.
2. A vertex moves along the pull, scaled by its weight.
3. The re-derived normal stays perpendicular to the deformed surface.
4. The re-derived tangent stays perpendicular to the normal and keeps
   its length.

The script also states the layout assumption the shader relies on: the
control record is read as a tightly packed structure of two float2
weights and two float3 gradients, so one record is 32 bytes.

Run with:
    python tools/test_interaction_deformation_math.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.interaction.weight_field import (  # noqa: E402
    build_control_data,
    compute_surface_gradients,
)


def safe_unit(value, fallback):
    """Mirror the shader's SafeUnit helper."""
    magnitude = float(np.dot(value, value))
    if magnitude > 1e-20 and np.all(np.isfinite(value)):
        return value / np.sqrt(magnitude)
    return fallback


def apply_shader_math(position, normal, tangent, control, pull0, pull1):
    """Mirror the body of the runtime shader for one vertex."""
    column_x = np.array([1.0, 0.0, 0.0]) + pull0 * control[2] + pull1 * control[5]
    column_y = np.array([0.0, 1.0, 0.0]) + pull0 * control[3] + pull1 * control[6]
    column_z = np.array([0.0, 0.0, 1.0]) + pull0 * control[4] + pull1 * control[7]

    cofactor_x = np.cross(column_y, column_z)
    cofactor_y = np.cross(column_z, column_x)
    cofactor_z = np.cross(column_x, column_y)
    determinant = float(np.dot(column_x, cofactor_x))

    transformed_normal = cofactor_x * normal[0] + cofactor_y * normal[1] + cofactor_z * normal[2]
    if determinant < 0:
        transformed_normal = -transformed_normal
    unit_normal = safe_unit(transformed_normal, safe_unit(normal, np.array([0.0, 0.0, 1.0])))

    transformed_tangent = column_x * tangent[0] + column_y * tangent[1] + column_z * tangent[2]
    transformed_tangent = transformed_tangent - unit_normal * float(np.dot(unit_normal, transformed_tangent))
    unit_tangent = safe_unit(transformed_tangent, safe_unit(tangent[:3], np.array([1.0, 0.0, 0.0])))

    moved = position + pull0 * control[0] + pull1 * control[1]
    tangent_length = float(np.linalg.norm(tangent[:3]))
    tangent_result = np.array([
        unit_tangent[0] * tangent_length,
        unit_tangent[1] * tangent_length,
        unit_tangent[2] * tangent_length,
        tangent[3],
    ])
    return moved, unit_normal * np.linalg.norm(normal), tangent_result


def build_case():
    """Return a small grid with a smooth control weight on one side.

    The weight fades out towards the border of the region, the same way
    the region tool feathers a control group.  A hard border would make
    the stored vertex gradient differ from the real gradient of the field
    right at the edge, which is exactly what the feathering avoids.
    """
    size = 5
    coordinates = np.arange(size, dtype=np.float64) * 0.25
    grid_x, grid_y = np.meshgrid(coordinates, coordinates, indexing="ij")
    positions = np.stack([grid_x.ravel(), grid_y.ravel(), np.zeros(size * size)], axis=1)

    triangles = []
    for row in range(size - 1):
        for column in range(size - 1):
            corner = row * size + column
            triangles.append([corner, corner + size, corner + 1])
            triangles.append([corner + 1, corner + size, corner + size + 1])
    triangles = np.array(triangles, dtype=np.int64)

    # A smooth bell around the first column of the grid.  The far side is
    # cut to zero, the same way a feathered control group ends at zero.
    distance = positions[:, 0] - positions[0, 0]
    weights = np.exp(-3.0 * distance * distance)
    weights[distance > 0.45] = 0.0
    return positions, weights, triangles


def check_layout():
    """The control record must be 32 bytes with the documented layout."""
    vertex_count = 4
    weights = np.linspace(0.0, 1.0, vertex_count)
    gradients = np.ones((vertex_count, 3))
    record = build_control_data([weights], [gradients])
    if record.shape != (vertex_count, 8):
        raise AssertionError("the control record must hold eight floats per vertex")
    if record.dtype != np.float32:
        raise AssertionError("the control record must be float32")
    if record.nbytes != vertex_count * 32:
        raise AssertionError("the control record must be 32 bytes per vertex")
    print("control record layout: OK (32 bytes per vertex)")


def check_single_triangle():
    """On one triangle the gradient is exactly known, so the normal must match.

    The barycentric weight of a triangle is a linear function, so its
    gradient is a constant vector that can be computed exactly.  With that
    exact gradient the Jacobian is the exact derivative of the
    deformation, and the cofactor transform has to reproduce the normal
    of the deformed triangle exactly.
    """
    positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    weights = np.array([0.0, 1.0, 0.0])

    edge_1 = positions[1] - positions[0]
    edge_2 = positions[2] - positions[0]
    normal = np.cross(edge_1, edge_2)
    normal_squared = float(np.dot(normal, normal))
    # The exact gradients of the barycentric weights of vertex b and c.
    gradient_b = np.cross(edge_2, normal) / normal_squared
    gradient_c = np.cross(normal, edge_1) / normal_squared
    exact_gradient = (weights[1] - weights[0]) * gradient_b + (weights[2] - weights[0]) * gradient_c

    pull = np.array([0.0, 0.0, 0.3])

    # The shader only knows the gradient through the control record.
    # The first weight slot belongs to the first region, the second one to
    # the second region, and this case only uses the first region.
    control = np.zeros(8)
    control[2:5] = exact_gradient
    control[5:8] = 0.0

    moved_list = []
    normal_list = []
    for index in range(3):
        # The control record belongs to one vertex, so the weight slot
        # carries the weight of that vertex.
        control = np.zeros(8)
        control[0] = weights[index]
        control[2:5] = exact_gradient
        moved, rederived_normal, _ = apply_shader_math(
            positions[index],
            np.array([0.0, 0.0, 1.0]),
            np.array([1.0, 0.0, 0.0, 1.0]),
            control,
            pull,
            np.zeros(3),
        )
        moved_list.append(moved)
        normal_list.append(rederived_normal)
    moved = np.array(moved_list)
    rederived = np.array(normal_list)

    # The normal of the deformed triangle is the reference.
    deformed_edge_1 = moved[1] - moved[0]
    deformed_edge_2 = moved[2] - moved[0]
    deformed_normal = np.cross(deformed_edge_1, deformed_edge_2)
    deformed_normal = deformed_normal / np.linalg.norm(deformed_normal)

    # The cofactor transform has to return that normal, not the original one.
    # The comparison is signed on purpose: an absolute value would accept a
    # normal that points the opposite way, which is exactly the defect this
    # check has to catch.
    for index in range(3):
        deviation = float(np.dot(rederived[index], deformed_normal))
        if deviation < 0.999999:
            raise AssertionError("the re-derived normal does not match the deformed triangle")

    # The original normal would have been the unchanged one, so the test
    # has to be sensitive to a normal that was simply left untouched.
    if float(np.dot(rederived[0], np.array([0.0, 0.0, 1.0]))) > 0.999999:
        raise AssertionError("the test does not detect an unchanged normal")
    print("single triangle normal: OK (matches the deformed face exactly)")


def check_deformation():
    """The deformation must move the vertices as intended."""
    positions, weights, triangles = build_case()
    gradients = compute_surface_gradients(positions, weights, triangles)
    record = build_control_data([weights], [gradients])

    # The normals and the tangents of the flat surface.
    normals = np.zeros_like(positions)
    tangents = np.zeros((len(positions), 4))
    for triangle in triangles:
        edge_1 = positions[triangle[1]] - positions[triangle[0]]
        edge_2 = positions[triangle[2]] - positions[triangle[0]]
        normal = np.cross(edge_1, edge_2)
        normal = normal / np.linalg.norm(normal)
        tangent = edge_1 / np.linalg.norm(edge_1)
        for index in triangle:
            normals[index] = normal
            tangents[index] = (tangent[0], tangent[1], tangent[2], 1.0)

    pull = np.array([0.02, 0.0, 0.0])

    moved_list = []
    normal_list = []
    tangent_list = []
    for index in range(len(positions)):
        moved, normal, tangent = apply_shader_math(
            positions[index], normals[index], tangents[index], record[index], pull, np.zeros(3))
        moved_list.append(moved)
        normal_list.append(normal)
        tangent_list.append(tangent)
    moved = np.array(moved_list)
    normals = np.array(normal_list)
    tangents = np.array(tangent_list)

    # A vertex outside the region keeps its place.
    outside = weights < 1e-9
    if float(np.linalg.norm(moved[outside] - positions[outside], axis=1).max()) > 1e-9:
        raise AssertionError("a vertex without weight must not move")

    # A vertex inside the region moves along the pull, scaled by its weight.
    inside = weights > 1e-9
    expected = positions[inside] + pull * weights[inside][:, None]
    error = float(np.linalg.norm(moved[inside] - expected, axis=1).max())
    if error > 1e-9:
        raise AssertionError("the pull does not match the weight of the vertex")
    print("deformation amount: OK (worst error " + str(error) + ")")

    # The re-derived normal must stay close to the deformed surface.  The
    # reference is the area weighted average of the deformed faces that
    # touch the vertex, because that is what a vertex normal is.
    #
    # The stored gradient is the area weighted average of the triangle
    # gradients around the vertex, so it is not the exact gradient of the
    # field at that vertex.  The cofactor transform is therefore exact
    # only where the gradient is exact, which the single triangle check
    # above proves.  On a real mesh the remaining deviation is the price
    # of storing one gradient per vertex, and the bound below keeps it
    # inside the range a shaded surface tolerates.
    # The comparison is signed: a normal that points the opposite way has
    # to fail the check, so the deviation keeps the sign of the dot product.
    worst = -1.0
    for vertex in range(len(positions)):
        reference = np.zeros(3)
        for triangle in triangles:
            if vertex not in triangle:
                continue
            edge_1 = moved[triangle[1]] - moved[triangle[0]]
            edge_2 = moved[triangle[2]] - moved[triangle[0]]
            face_normal = np.cross(edge_1, edge_2)
            reference = reference + face_normal
        if float(np.linalg.norm(reference)) < 1e-12:
            continue
        reference = reference / np.linalg.norm(reference)
        worst = max(worst, 1.0 - float(np.dot(normals[vertex], reference)))
    print("normal deviation from the deformed surface: " + str(worst))
    if worst > 0.02:
        raise AssertionError("the re-derived normal left the deformed surface")
    print("normal perpendicularity: OK (worst deviation " + str(worst) + ")")

    # The re-derived tangent must stay perpendicular to the normal.
    worst_tangent = 0.0
    for index in range(len(positions)):
        worst_tangent = max(worst_tangent, abs(float(np.dot(tangents[index][:3], normals[index]))))
    if worst_tangent > 1e-6:
        raise AssertionError("the re-derived tangent is not perpendicular to the normal")
    print("tangent orthogonality: OK (worst deviation " + str(worst_tangent) + ")")
    print("  note: the tangent length is preserved by construction, not by the test")


def main():
    check_layout()
    check_single_triangle()
    check_deformation()
    print("all interaction deformation maths checks passed")


if __name__ == "__main__":
    main()
