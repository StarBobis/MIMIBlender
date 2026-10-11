"""Offline global-to-local bone index conversion for MergedComponent.

The scene keeps its global vertex groups. Only per-loop export arrays change,
so geometry, shape keys and user weights never need destructive splitting.
Every array row is interpreted using its blueprint-assigned draw component.
"""

import re

import numpy


# Blender adds numeric suffixes when temporary joins encounter duplicate names.
# Such groups still describe the same global bone; arbitrary names are rejected
# only when a positive exported weight actually references them.
GLOBAL_GROUP_NAME = re.compile(r"^(\d+)(?:\.\d+)?$")


def localize_blendindices(element_context, components, extracted_components, draw_ib):
    """Return local export arrays, without editing mesh data or vertex groups."""
    mesh = element_context.mesh
    source = element_context.original_elementname_data_dict
    output = {}
    # Component numbering must remain identical between mesh ranges and maps.
    # A missing metadata entry must not silently produce all-zero local indices.
    if len(components) != len(extracted_components):
        raise ValueError("MergedComponent: component metadata count does not match export ranges")

    # Index offsets already describe consecutive triangle ranges in the joined
    # export object. They are the authoritative ownership, not dominant weights.
    # An unassigned component has no rows and requires no map validation.
    loop_components = numpy.full(len(mesh.loops), -1, dtype=numpy.int32)
    loop_objects = [""] * len(mesh.loops)
    for component_index, component in enumerate(components):
        for temp_object in component.objects:
            first_polygon = temp_object.index_offset // 3
            polygon_count = temp_object.index_count // 3
            if first_polygon < 0 or first_polygon + polygon_count > len(mesh.polygons):
                raise ValueError("MergedComponent: invalid polygon range for " + temp_object.name)
            for polygon in mesh.polygons[first_polygon:first_polygon + polygon_count]:
                start = polygon.loop_start
                end = start + polygon.loop_total
                if numpy.any(loop_components[start:end] != -1):
                    raise ValueError("MergedComponent: overlapping component polygon ranges")
                loop_components[start:end] = component_index
                loop_objects[start:end] = [temp_object.name] * polygon.loop_total
    if numpy.any(loop_components < 0):
        raise ValueError("MergedComponent: export loops have no blueprint component")

    # Numeric group names are the persistent global identity. Internal Blender
    # group indices can change after deletion, reordering and temporary joins.
    global_ids = {}
    for group in element_context.obj.vertex_groups:
        match = GLOBAL_GROUP_NAME.fullmatch(group.name)
        if match:
            global_ids[group.index] = int(match.group(1))

    # The actual layout determines representable local indices. Keeping the
    # wide source arrays until this point prevents accidental uint8 truncation.
    for element in element_context.d3d11_game_type.OrderedFullElementList:
        if not element.startswith("BLENDINDICES"):
            continue
        if element not in source:
            raise ValueError("MergedComponent: missing " + element)
        semantic_suffix = element[len("BLENDINDICES"):]
        weight_name = "BLENDWEIGHT" + semantic_suffix
        if weight_name not in source:
            raise ValueError("MergedComponent: missing " + weight_name)
        indices = numpy.asarray(source[element])
        weights = numpy.asarray(source[weight_name])
        if indices.shape != weights.shape or indices.ndim != 2:
            raise ValueError("MergedComponent: incompatible bone index and weight arrays")
        field_type = element_context.total_structured_dtype.fields[element][0]
        scalar_type = field_type.subdtype[0] if field_type.subdtype else field_type
        if scalar_type.kind != "u":
            raise ValueError("MergedComponent: bone indices require an unsigned integer layout")
        maximum_local = numpy.iinfo(scalar_type).max
        local_indices = numpy.zeros(indices.shape, dtype=indices.dtype)

        # Reverse the import rule, including its offset fallback for omitted
        # metadata entries. Explicit VGMap entries always override that fallback.
        # Shared global bones may have multiple local slots: choose the smallest
        # valid slot deterministically, never a slot belonging to another draw.
        for component_index, extracted in enumerate(extracted_components):
            rows = numpy.flatnonzero(loop_components == component_index)
            if rows.size == 0:
                continue
            explicit_map = {int(key): int(value) for key, value in extracted.vg_map.items()}
            reverse_map = {}
            for local_id in range(extracted.vg_count):
                if local_id > maximum_local:
                    continue
                global_id = explicit_map.get(local_id, extracted.vg_offset + local_id)
                reverse_map.setdefault(global_id, local_id)

            # Validate only final nonzero exported influences, including the
            # existing weight quantization/top-K policy. Zero-weight padding
            # always becomes local index zero and never causes a false failure.
            selected_indices = indices[rows]
            active = weights[rows] > 0
            selected_local = numpy.zeros(selected_indices.shape, dtype=indices.dtype)
            for group_index in numpy.unique(selected_indices[active]):
                group_index = int(group_index)
                matching = (selected_indices == group_index) & active
                global_id = global_ids.get(group_index)
                if global_id is None or global_id not in reverse_map:
                    first_row = int(rows[numpy.nonzero(matching)[0][0]])
                    identity = str(global_id) if global_id is not None else "unnamed group index " + str(group_index)
                    raise ValueError(
                        "MergedComponent: DrawIB " + draw_ib + ", component " + str(component_index)
                        + ", object '" + loop_objects[first_row] + "' cannot map global bone " + identity
                        + " to its original local skeleton. Keep the target component's bone range"
                        + " or use Merged for cross-component weights. No weights were deleted."
                    )
                selected_local[matching] = reverse_map[global_id]
            local_indices[rows] = selected_local
        output[element] = local_indices
    return output
