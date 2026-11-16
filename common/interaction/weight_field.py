"""Control weight field maths for the generic interaction deformation.

The interaction feature deforms one or more named regions of a mesh by
pulling them along a direction.  Two things have to be known per vertex:

* the *weight* of the vertex in each region, which says how much of the
  pull reaches that vertex, and
* the *spatial gradient* of that weight, which says in which direction the
  weight grows fastest.

The gradient is what makes the deformation a smooth stretch instead of a
rigid translation: the runtime compute shader builds a Jacobian from it and
re-derives the normal and the tangent from that Jacobian, so the surface
keeps lighting correctly while it is pulled.

Why a surface gradient and not a plain finite difference
--------------------------------------------------------
A finite difference over a point cloud is noisy and depends on the
neighbour order.  The mesh already carries the connectivity, so the
gradient is computed analytically per triangle from the barycentric weight
interpolation and then averaged over the triangles that touch the vertex.
The result is independent of the vertex order and stays stable even when
the weight falls off towards the region border.

The gradient is a *surface* gradient: it is tangent to the mesh.  The
runtime shader only needs it to build the deformation Jacobian, so the
component along the surface normal does not influence the result.
"""

import numpy as np


# A triangle whose squared area is below this value is treated as
# degenerate and contributes nothing.  The value is a squared length, so
# it is expressed in the same unit as the squared edge length.
DEGENERATE_AREA_SQUARED = 1e-20

# The smallest total area a vertex may accumulate.  Dividing by a tiny
# total would blow the gradient up to infinity, so the result is clamped.
MIN_AREA_TOTAL = 1e-20


def compute_surface_gradients(positions, weights, triangles):
    """Return the area-weighted surface gradient of a per-vertex weight.

    positions: (vertex_count, 3) float array with the bind pose positions.
    weights: (vertex_count,) float array with the control weight per vertex.
    triangles: (triangle_count, 3) int array with the vertex indices.

    The returned array has the same shape as positions.  Vertices that
    touch no usable triangle keep a zero gradient.
    """
    vertex_count = len(positions)
    gradients = np.zeros((vertex_count, 3), dtype=np.float64)
    area_totals = np.zeros(vertex_count, dtype=np.float64)

    if len(triangles) == 0:
        return gradients

    for triangle in triangles:
        index_a, index_b, index_c = int(triangle[0]), int(triangle[1]), int(triangle[2])

        edge_1 = positions[index_b] - positions[index_a]
        edge_2 = positions[index_c] - positions[index_a]
        normal = np.cross(edge_1, edge_2)
        normal_squared = float(np.dot(normal, normal))
        if normal_squared <= DEGENERATE_AREA_SQUARED:
            # A degenerate triangle carries no usable tangent frame.
            continue

        weight_a = weights[index_a]
        weight_b = weights[index_b]
        weight_c = weights[index_c]

        # Analytic gradient of the barycentric weight interpolation.
        # Each term is the derivative of the weight with respect to the
        # vertex position, expressed in the triangle's tangent frame.
        gradient = (
            (weight_b - weight_a) * np.cross(edge_2, normal)
            + (weight_c - weight_a) * np.cross(normal, edge_1)
        ) / normal_squared

        # Weight every triangle by its area so big triangles dominate and
        # slivers contribute less.
        area = 0.5 * np.sqrt(normal_squared)
        gradients[index_a] += gradient * area
        gradients[index_b] += gradient * area
        gradients[index_c] += gradient * area
        area_totals[index_a] += area
        area_totals[index_b] += area
        area_totals[index_c] += area

    # Normalise by the area that actually contributed, so a vertex on the
    # border of the region still reports a usable gradient direction.
    safe_totals = np.maximum(area_totals, MIN_AREA_TOTAL)
    return gradients / safe_totals[:, None]


def compute_gradient_bound(gradients):
    """Return the largest gradient magnitude found in the field.

    The runtime Jacobian grows with the product of the pull distance and
    this bound, so the export uses it to keep the surface from folding.
    """
    if len(gradients) == 0:
        return 0.0
    magnitudes = np.linalg.norm(gradients, axis=1)
    return float(magnitudes.max()) if len(magnitudes) else 0.0


def compute_safe_displacement(gradient_bound, model_extent, jacobian_limit=0.45):
    """Return the largest pull distance that keeps the Jacobian sane.

    The deformation stretches the surface by roughly
    ``pull * gradient``.  Limiting that product keeps the Jacobian
    invertible, which in turn keeps the re-derived normal well defined.
    The result is also capped by a fraction of the model size, so a tiny
    gradient cannot allow an absurdly long pull.
    """
    if gradient_bound <= 1e-12:
        return 0.0
    safe_by_gradient = jacobian_limit / gradient_bound
    # The model extent is the distance the pull may never exceed.
    safe_by_model = model_extent * 0.5
    return float(min(safe_by_gradient, safe_by_model))


def build_control_data(weights_by_region, gradients_by_region):
    """Pack the per-vertex control data into the runtime layout.

    weights_by_region: list of (vertex_count,) float arrays, one per region.
    gradients_by_region: list of (vertex_count, 3) float arrays, one per
    region and in the same order.

    The runtime layout is one record per vertex:
    ``weight0, weight1, gradient0.xyz, gradient1.xyz`` as float32.
    The first region uses the two weight slots; later regions reuse them,
    so the current layout supports exactly two regions.
    """
    if len(weights_by_region) != len(gradients_by_region):
        raise ValueError("Interaction control data needs one weight and one gradient array per region")
    if not weights_by_region:
        raise ValueError("Interaction control data needs at least one region")

    vertex_count = len(weights_by_region[0])
    record = np.zeros((vertex_count, 8), dtype=np.float32)

    for region_index, weights in enumerate(weights_by_region):
        if region_index >= 2:
            # The runtime layout has two weight slots and two gradient slots.
            break
        if len(weights) != vertex_count:
            raise ValueError("Interaction region weights must cover every vertex")
        gradients = gradients_by_region[region_index]
        if len(gradients) != vertex_count:
            raise ValueError("Interaction region gradients must cover every vertex")
        record[:, region_index] = weights
        record[:, 2 + region_index * 3: 5 + region_index * 3] = gradients

    return record
