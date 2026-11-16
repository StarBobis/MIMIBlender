"""Offline checks for the generic interaction weight field maths.

The gradient is the part of the interaction feature that decides where the
surface is stretched, so it is verified twice:

1. Algebraically.  For a triangle, the barycentric weight interpolation has
   a gradient that is fully determined by the three corner weights.  The
   analytic result must satisfy two exact identities:

       gradient . edge_1 == weight_b - weight_a
       gradient . edge_2 == weight_c - weight_a

   Both identities are checked on random triangles, which catches a flipped
   cross product order immediately.

2. Numerically.  A flat grid carries a weight field that is linear in the
   plane, so the gradient must point along the known direction and its
   magnitude must match the analytic value.

Run with:
    python tools/test_interaction_weight_field.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.interaction.weight_field import (  # noqa: E402
    build_control_data,
    compute_gradient_bound,
    compute_safe_displacement,
    compute_surface_gradients,
)


def check_algebraic_identity():
    """The analytic gradient must match the barycentric identities."""
    random_state = np.random.default_rng(20261116)
    checked = 0
    worst_edge_1_error = 0.0
    worst_edge_2_error = 0.0

    for _ in range(400):
        positions = random_state.normal(size=(3, 3))
        weights = random_state.random(3)
        triangles = np.array([[0, 1, 2]], dtype=np.int64)

        gradients = compute_surface_gradients(positions, weights, triangles)

        # A single triangle gives every corner the same area weight, so the
        # per-vertex gradient equals the triangle gradient.
        edge_1 = positions[1] - positions[0]
        edge_2 = positions[2] - positions[0]

        for corner in range(3):
            gradient = gradients[corner]
            error_1 = abs(float(gradient @ edge_1) - (weights[1] - weights[0]))
            error_2 = abs(float(gradient @ edge_2) - (weights[2] - weights[0]))
            worst_edge_1_error = max(worst_edge_1_error, error_1)
            worst_edge_2_error = max(worst_edge_2_error, error_2)
            checked += 1

    print("algebraic identity: checked " + str(checked) + " corners")
    print("  worst edge_1 error = " + str(worst_edge_1_error))
    print("  worst edge_2 error = " + str(worst_edge_2_error))
    if worst_edge_1_error > 1e-9 or worst_edge_2_error > 1e-9:
        raise AssertionError("surface gradient does not satisfy the barycentric identities")
    print("  OK")


def check_flat_grid_direction():
    """A linear weight field on a flat grid must give a constant gradient."""
    grid_size = 9
    coordinates = np.arange(grid_size, dtype=np.float64) * 0.1
    grid_x, grid_y = np.meshgrid(coordinates, coordinates, indexing="ij")
    positions = np.stack([grid_x.ravel(), grid_y.ravel(), np.zeros(grid_size * grid_size)], axis=1)

    # The weight grows along +X and shrinks along +Y.
    weights = grid_x.ravel() - 0.5 * grid_y.ravel()

    triangles = []
    for row in range(grid_size - 1):
        for column in range(grid_size - 1):
            corner = row * grid_size + column
            triangles.append([corner, corner + grid_size, corner + 1])
            triangles.append([corner + 1, corner + grid_size, corner + grid_size + 1])
    triangles = np.array(triangles, dtype=np.int64)

    gradients = compute_surface_gradients(positions, weights, triangles)

    # Interior vertices carry the full area of their neighbours, so their
    # gradient is the exact planar gradient of the weight field.
    interior = []
    for row in range(1, grid_size - 1):
        for column in range(1, grid_size - 1):
            interior.append(row * grid_size + column)
    interior_gradients = gradients[np.array(interior, dtype=np.int64)]

    expected = np.array([1.0, -0.5, 0.0])
    errors = np.linalg.norm(interior_gradients - expected, axis=1)
    print("flat grid direction: worst interior error = " + str(float(errors.max())))
    if float(errors.max()) > 1e-9:
        raise AssertionError("surface gradient direction is wrong on a flat grid")

    bound = compute_gradient_bound(gradients)
    print("  gradient bound = " + str(bound))
    print("  OK")
    return bound


def check_control_data_layout():
    """The packed control record must match the runtime layout."""
    vertex_count = 5
    weights_a = np.linspace(0.0, 1.0, vertex_count)
    weights_b = np.linspace(1.0, 0.0, vertex_count)
    gradients_a = np.ones((vertex_count, 3))
    gradients_b = np.full((vertex_count, 3), 2.0)

    record = build_control_data([weights_a, weights_b], [gradients_a, gradients_b])
    if record.shape != (vertex_count, 8):
        raise AssertionError("control record must be 8 floats per vertex")
    if not np.allclose(record[:, 0], weights_a):
        raise AssertionError("first region weight is in the wrong slot")
    if not np.allclose(record[:, 1], weights_b):
        raise AssertionError("second region weight is in the wrong slot")
    if not np.allclose(record[:, 2:5], gradients_a):
        raise AssertionError("first region gradient is in the wrong slot")
    if not np.allclose(record[:, 5:8], gradients_b):
        raise AssertionError("second region gradient is in the wrong slot")
    print("control data layout: OK")


def check_safe_displacement():
    """The pull limit must shrink when the gradient grows."""
    small = compute_safe_displacement(1.0, 1.0)
    large = compute_safe_displacement(10.0, 1.0)
    print("safe displacement: gradient 1 -> " + str(small) + ", gradient 10 -> " + str(large))
    if not (0.0 < large < small):
        raise AssertionError("a stronger gradient must reduce the allowed pull distance")
    print("  OK")


def main():
    check_algebraic_identity()
    check_flat_grid_direction()
    check_control_data_layout()
    check_safe_displacement()
    print("all interaction weight field checks passed")


if __name__ == "__main__":
    main()
