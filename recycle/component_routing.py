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


def faces_by_island(faces):
    """Group faces that share an exported edge into connected parts.

    A Blender join does not weld vertices, so every absorbed source object
    keeps its own connected pieces. Those pieces are the only surviving
    evidence that a group of faces was one object before the join.
    """
    parent = list(range(len(faces)))

    def find(index):
        # Path compression keeps repeated lookups cheap on dense meshes.
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        # Merge two parts into the same root; the root itself has no meaning.
        left = find(left)
        right = find(right)
        if left != right:
            parent[right] = left

    first_face_by_edge = {}
    for face_index, face in enumerate(faces):
        corners = list(face.vertices)
        for position, corner in enumerate(corners):
            other = corners[(position + 1) % len(corners)]
            # An undirected edge key sorts the two corners once for everyone.
            if corner < other:
                key = (corner, other)
            else:
                key = (other, corner)
            owner = first_face_by_edge.get(key)
            if owner is None:
                first_face_by_edge[key] = face_index
            else:
                union(face_index, owner)

    islands = {}
    for face_index in range(len(faces)):
        islands.setdefault(find(face_index), []).append(face_index)
    return list(islands.values())


def resolve_island_targets(faces, face_masks, face_components, all_targets, expected_faces=None):
    """Return one target per connected part when a single palette covers it.

    An island only decides when the intersection of its face masks is not
    empty: every triangle of that part must fit the same component palette.
    A part whose own component already covers it never moves, so ordinary
    geometry keeps its draw even when another palette would also fit.
    Parts that fit several palettes fall back to the per-face decision, except
    when counting proves the destination: the component that is still missing
    exactly as many faces as these parts contain is the only possible target.
    """
    targets = [None] * len(faces)
    islands = []
    fixed_faces = {}
    pending = []
    for island in faces_by_island(faces):
        # Intersect every triangle mask of this part. One zero is final.
        mask = all_targets
        for index in island:
            mask &= face_masks[index]
            if mask == 0:
                break
        if mask == 0:
            continue
        sources = {face_components[index] for index in island}
        if len(sources) == 1:
            source = next(iter(sources))
            # Staying in the recorded component is always the safest answer.
            if mask & (1 << source):
                for index in island:
                    targets[index] = source
                fixed_faces[source] = fixed_faces.get(source, 0) + len(island)
                continue
        if bin(mask).count("1") != 1:
            # Several palettes fit the whole part; counting may still prove
            # one of them before the per-face rule gives up on it.
            pending.append((island, mask))
            continue
        target = mask.bit_length() - 1
        for index in island:
            targets[index] = target
        fixed_faces[target] = fixed_faces.get(target, 0) + len(island)
        islands.append(dict(source=sorted(sources), target=target, faces=len(island)))
    if pending and expected_faces:
        # A component's original face count is fixed game metadata. When this
        # part is the only component still short by exactly the pending total,
        # the export faces can only be its own; anything else cannot add up.
        remaining = sum(len(island) for island, mask in pending)
        candidates = 0
        for island, mask in pending:
            candidates |= mask
        absorbing = []
        for target in range(len(expected_faces)):
            if not (candidates & (1 << target)):
                continue
            missing = expected_faces[target] - fixed_faces.get(target, 0)
            if missing == remaining:
                absorbing.append(target)
        if len(absorbing) == 1:
            target = absorbing[0]
            for island, mask in pending:
                sources = {face_components[index] for index in island}
                for index in island:
                    targets[index] = target
                islands.append(dict(source=sorted(sources), target=target, faces=len(island)))
            pending = []
    return targets, islands


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
    # The island count is a separate decision kind: the connected part proved
    # the target, so it does not need the per-face draw-state consent.
    counts = dict(unchanged=0, reassigned=0, ambiguous=0, incompatible=0,
                  draw_state=0, island=0)
    if len(faces) != len(face_components):
        raise ValueError('MergedComponent: face ownership count does not match the export mesh')
    # Validate ownership before any mask work: an island pass would shift a
    # negative or out-of-range component id and report the wrong failure.
    for triangle, source in enumerate(face_components):
        if len(faces[triangle].vertices) != 3 or source < 0 or source >= len(maps):
            raise ValueError('MergedComponent: invalid triangle or original component ownership')

    # Cache one mask per triangle: the island pass and the per-face pass must
    # read exactly the same evidence, and a second pass would double the cost.
    face_masks = []
    for face in faces:
        mask = all_targets
        for vertex in face.vertices:
            mask &= vertex_masks[vertex]
        face_masks.append(mask)

    island_targets, islands = resolve_island_targets(
        faces, face_masks, face_components, all_targets,
        # Original face counts are fixed game metadata; the counting proof
        # needs them, and a missing value only disables that proof.
        [int(getattr(component, "index_count", 0) or 0) // 3 for component in components])

    for triangle, (face, source) in enumerate(zip(faces, face_components)):
        if len(face.vertices) != 3 or source < 0 or source >= len(maps):
            raise ValueError('MergedComponent: invalid triangle or original component ownership')
        mask = face_masks[triangle]
        # A connected part with one feasible palette already answered the
        # question; using it keeps an absorbed object intact instead of
        # splitting it across two draws face by face. Moving that part still
        # changes which draw renders it, so the same consent gates the move.
        island_target = island_targets[triangle]
        if island_target is not None:
            if island_target == source:
                assignments.append(source)
                counts['unchanged'] += 1
                continue
            if allow_draw_state_change:
                assignments.append(island_target)
                counts['island'] += 1
                continue
            # Consent is missing: report the proven island target per face so
            # the existing selection and repair tools still address it.
            counts['draw_state'] += 1
            assignments.append(source)
            bones = sorted(set().union(*(vertex_groups[index] for index in face.vertices)))
            issues.append(dict(triangle=triangle, source_component=source,
                               kind='draw_state', candidates=[island_target],
                               groups=bones, island=True,
                               unassignable_vertices=[]))
            continue
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
    return dict(assignments=assignments, issues=issues, counts=counts, islands=islands)
