"""Helpers for finding and removing material slots that no polygon uses.

Shared by the MMD cleanup sidebar panel and the texture combiner list so
both features agree on what an "unused material slot" is: a slot whose
index is never referenced by any polygon of the object's mesh.

The removal routine remaps polygon material indices after every pop so
the remaining faces keep pointing at their original materials.
"""


def collect_used_slot_indices(obj):
    """Return the set of material slot indices referenced by any polygon.

    Args:
        obj: The mesh object to inspect.

    Returns:
        A set of integer slot indices. Empty for non-mesh objects.
    """
    # Non-mesh objects cannot own polygon material assignments at all.
    if obj is None or obj.type != 'MESH':
        return set()
    # A set comprehension keeps exactly one entry per referenced slot.
    return {polygon.material_index for polygon in obj.data.polygons}


def remove_unused_material_slots(obj):
    """Remove every material slot that no polygon of the mesh references.

    Slots are removed from the highest index downwards. After each removal
    every polygon that pointed at a slot above the removed one is shifted
    down by one, so existing material assignments stay intact. Blender's
    slot pop does not remap polygon indices by itself, so this step is
    mandatory to avoid faces silently switching materials.

    Args:
        obj: The mesh object to clean up.

    Returns:
        The number of material slots that were removed.
    """
    # Guard against the same accidental misuse as the collector above.
    if obj is None or obj.type != 'MESH':
        return 0
    mesh = obj.data
    used_indices = collect_used_slot_indices(obj)
    removed = 0
    # Walk from the last slot to the first so earlier removals never
    # disturb the indices of slots that have not been checked yet.
    for slot_index in range(len(mesh.materials) - 1, -1, -1):
        if slot_index in used_indices:
            continue
        # Drop the slot itself; this also drops an empty slot's entry.
        mesh.materials.pop(index=slot_index)
        # Slots above the removed one shift down by one position.
        for polygon in mesh.polygons:
            if polygon.material_index > slot_index:
                polygon.material_index -= 1
        # Keep the bookkeeping set aligned with the shifted indices.
        used_indices = {
            index - 1 if index > slot_index else index
            for index in used_indices
        }
        removed += 1
    return removed
