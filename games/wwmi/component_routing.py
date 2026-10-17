"""Plan whole-triangle routing without changing weights or mesh data.

A bone palette is a capability, not proof of material or shader compatibility.
An existing valid assignment always wins, even when bones are shared elsewhere.
Alternative targets require one complete palette and explicit draw-state consent.
Ambiguous targets and mixed-palette triangles remain actionable failures.
This module does not import Blender, write files, or silently switch architecture.
"""
import re


GLOBAL_GROUP_NAME = re.compile(r"^(\d+)(?:\.\d+)?$")


def build_bone_maps(components, maximum_local=255):
    """Build the exact local maps and metadata-proven legacy slot aliases.

    VGMap overrides the offset fallback; it is not necessarily a full palette.
    Duplicated canonical bones select their smallest representable local slot.
    Aliases include all recorded slots, not only a target's representable slots.
    """
    maps = []
    aliases = {}
    for component in components:
        explicit = {int(key): int(value) for key, value in component.vg_map.items()}
        reverse = {}
        for local in range(component.vg_count):
            canonical = explicit.get(local, component.vg_offset + local)
            if local <= maximum_local:
                reverse.setdefault(canonical, local)
            if local in explicit:
                aliases[component.vg_offset + local] = canonical
        maps.append(reverse)
    return maps, aliases


def resolve_local(global_id, reverse, aliases):
    """Prefer a canonical identity before following proven runtime aliases.

    A cycle or unknown identity is not a reason to subtract an arbitrary offset.
    Returning None keeps failure distinct from the valid local bone numbered zero.
    The same routine is used for planning and final export-array localization.
    """
    seen = set()
    while global_id not in reverse and global_id in aliases and global_id not in seen:
        seen.add(global_id)
        global_id = aliases[global_id]
    return reverse.get(global_id)


def plan_faces(vertices, faces, group_names, face_components, components,
               allow_draw_state_change=False, maximum_local=255):
    """Find complete target palettes for all positive influences on each face.

    Inputs may be Blender mesh collections or lightweight regression fixtures.
    No top-weight choice or tiny-weight threshold hides an incompatible influence.
    All issues are collected before a caller is allowed to apply any assignment.
    Returned triangle indices address the supplied export mesh, not source faces.
    """
    maps, aliases = build_bone_maps(components, maximum_local)
    # Bit N means that component N can represent this group without weight loss.
    # Intersecting these bit sets later requires every corner to agree on a draw.
    # This avoids building a large Python set for every vertex of dense meshes.
    # Candidate order is the original metadata order, never a guessed bone count.
    all_targets = (1 << len(maps)) - 1
    group_masks = {}
    for index, name in group_names.items():
        match = GLOBAL_GROUP_NAME.fullmatch(name)
        mask = 0
        if match:
            bone = int(match.group(1))
            for target, reverse in enumerate(maps):
                if resolve_local(bone, reverse, aliases) is not None:
                    mask |= 1 << target
        group_masks[index] = mask

    # A triangle can only use a target supported by every one of its vertices.
    # Duplicating boundary vertices does not alter their bone dependencies.
    # Unweighted vertices impose no additional palette constraint.
    vertex_masks = []
    vertex_groups = []
    for vertex in vertices:
        mask = all_targets
        active = set()
        for weight in vertex.groups:
            if weight.weight > 0:
                mask &= group_masks.get(weight.group, 0)
                active.add(group_names.get(weight.group, 'unnamed group ' + str(weight.group)))
        vertex_masks.append(mask)
        vertex_groups.append(active)

    assignments = []
    issues = []
    counts = dict(unchanged=0, reassigned=0, ambiguous=0, incompatible=0, draw_state=0)
    if len(faces) != len(face_components):
        raise ValueError('MergedComponent: face ownership count does not match the export mesh')
    for triangle, (face, source) in enumerate(zip(faces, face_components)):
        if len(face.vertices) != 3 or source < 0 or source >= len(maps):
            raise ValueError('MergedComponent: invalid triangle or original component ownership')
        mask = all_targets
        for vertex in face.vertices:
            mask &= vertex_masks[vertex]
        # Staying in the explicit blueprint target is safe and deterministic.
        # Do not move a shared-bone triangle merely because another palette fits.
        # Only a missing complete target requires a migration decision.
        if mask & (1 << source):
            assignments.append(source)
            counts['unchanged'] += 1
            continue
        targets = [index for index in range(len(maps)) if mask & (1 << index)]
        if len(targets) == 1 and allow_draw_state_change:
            assignments.append(targets[0])
            counts['reassigned'] += 1
            continue
        # Preserve three different repair decisions instead of one generic error.
        # A missing target is a skeleton constraint; several targets need intent.
        # Exactly one target still needs consent to its original rendering state.
        if not targets:
            kind = 'incompatible'
        elif len(targets) > 1:
            kind = 'ambiguous'
        else:
            kind = 'draw_state'
        counts[kind] += 1
        assignments.append(source)
        bones = sorted(set().union(*(vertex_groups[index] for index in face.vertices)))
        issues.append(dict(triangle=triangle, source_component=source, kind=kind,
                           candidates=targets, groups=bones,
                           unassignable_vertices=[int(index) for index in face.vertices
                                                  if vertex_masks[index] == 0]))
    return dict(assignments=assignments, issues=issues, counts=counts)
