"""Offline global-to-local bone index conversion for MergedComponent.

The scene keeps its global vertex groups. Only per-loop export arrays change,
so geometry, shape keys and user weights never need destructive splitting.
Every array row is interpreted using its blueprint-assigned draw component.
"""

import numpy

from .component_routing import GLOBAL_GROUP_NAME, build_bone_maps, resolve_local


def localize_blendindices(element_context, components, extracted_components, draw_ib,
                          routed_loop_components=None):
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
    # Routing changes ownership, never mesh order or the source identity in errors.
    # Require one valid component for every loop before packing local indices.
    # The caller applies the new draw ranges only after localization succeeds.
    if routed_loop_components is not None:
        routed = numpy.asarray(routed_loop_components, dtype=numpy.int32)
        if routed.shape != loop_components.shape or numpy.any(routed < 0) or numpy.any(routed >= len(components)):
            raise ValueError("MergedComponent: invalid routed loop ownership")
        loop_components = routed

    # Numeric group names are the persistent global identity. Internal Blender
    # group indices can change after deletion, reordering and temporary joins.
    global_ids = {}
    for group in element_context.obj.vertex_groups:
        match = GLOBAL_GROUP_NAME.fullmatch(group.name)
        if match:
            global_ids[group.index] = int(match.group(1))

    # Older merged exports and reverse imports retain runtime skeleton slots,
    # whereas current imports collapse duplicate slots through VGMap. Both are
    # valid identities for the same bone: e.g. Xin slot 105 + 118 == 223 maps
    # to canonical bone 68. Recover only aliases explicitly proven by metadata;
    # never treat an arbitrary out-of-palette bone as a local index.
    _, aliases = build_bone_maps(extracted_components)

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
            reverse_map = build_bone_maps([extracted], maximum_local)[0][0]

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
                # Prefer an exact canonical identity, then resolve a legacy
                # runtime-slot alias. Cycles cannot establish a valid target.
                # This changes export arrays only, never the source groups.
                local_id = resolve_local(global_id, reverse_map, aliases)
                if global_id is None or local_id is None:
                    first_row = int(rows[numpy.nonzero(matching)[0][0]])
                    identity = str(global_id) if global_id is not None else "unnamed group index " + str(group_index)
                    raise ValueError(
                        "MergedComponent: DrawIB " + draw_ib + ", component " + str(component_index)
                        + ", object '" + loop_objects[first_row] + "' cannot map global bone " + identity
                        + " to its original local skeleton. Keep the target component's bone range"
                        + " or use Merged for cross-component weights. No weights were deleted."
                    )
                selected_local[matching] = local_id
            local_indices[rows] = selected_local
        output[element] = local_indices
    return output
