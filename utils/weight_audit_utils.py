"""Weight audit and repair helpers for skinning weights.

A reversed or imported game model keeps its four weights per vertex, but the
moment a user rebuilds a mesh, copies a part from another model or transfers
weights with Blender's Data Transfer modifier, those weights no longer follow
the surface. Two defects show up most often in Mod making:

- a weight seam: two neighbouring vertices on a smooth, same-material surface
  whose positive vertex groups do not overlap at all, so the skin snaps from
  one bone to another instead of blending through a gradient;
- a stray cluster: a few vertices far away from the main region of a vertex
  group, left behind by a nearest-neighbour weight transfer. In game these
  vertices twitch or drift and they usually sit in a hidden corner of the
  mesh where nobody notices them before publishing the Mod.

This module only reads and edits vertex-group weights. It never adds or
removes vertex groups, never touches materials, normals or UV layers and never
changes topology or shape keys, so it is safe to run on a finished Mod mesh.
Every function takes one object or one mesh and returns plain Python data, so
the UI layer stays thin and the logic can be tested inside headless Blender.

Terminology used by the comments and the returned dictionaries:

- group index: the integer index inside ``obj.vertex_groups``;
- positive group: a group whose weight on a vertex is above
  ``POSITIVE_WEIGHT_EPSILON``, that is a bone that really moves the vertex;
- seam edge: an edge on a smooth surface whose two ends have weight sets that
  do not overlap, so no bone carries the transition;
- isolated cluster: one connected component of a vertex group that is much
  smaller than the main component of the same group.

All thresholds live in ``WeightAuditSettings`` so the operators and the tests
drive the same code path and the pure functions never read ``bpy.context``.
"""

import bmesh
import math


# Weights at or below this value are treated as absent. Blender keeps a vertex
# group entry after ``group.add(..., 0.0)`` and imported game models sometimes
# carry tiny noise weights, so every comparison shares this epsilon instead of
# testing ``> 0`` (which an epsilon-sized float passes).
WEIGHT_EPSILON = 1e-6

# A group counts as a real influence on a vertex only above this value. It is
# larger than WEIGHT_EPSILON on purpose: a 1e-5 leftover must not be treated as
# a shared transition bone between two neighbouring vertices.
POSITIVE_WEIGHT_EPSILON = 1e-4


class WeightAuditSettings:
    """Thresholds for one audit run.

    The operators copy the user's scene properties into this object before
    calling the pure functions below, so no algorithm reads scene state.
    """

    def __init__(
        self,
        seam_threshold=1.0,
        smooth_angle_degrees=60.0,
        island_weight_threshold=0.05,
        island_min_vertices=8,
        max_influences=4,
        min_weight=0.01,
        normalize_tolerance=1e-3,
    ):
        # Minimum L1 weight difference that can count as a seam. Two vertices
        # bound to completely different single bones differ by 2.0, so 1.0
        # reports clear snaps while ignoring a normal blend band.
        self.seam_threshold = float(seam_threshold)
        # Faces meeting at an angle sharper than this are a geometric hard
        # edge, an expected place for a weight boundary, so those edges are
        # exempt from the seam check.
        self.smooth_angle_degrees = float(smooth_angle_degrees)
        # A group "covers" a vertex for the cluster check above this weight.
        self.island_weight_threshold = float(island_weight_threshold)
        # Components below this vertex count are reported as stray islands.
        self.island_min_vertices = int(island_min_vertices)
        # Game models export four influences per vertex; anything above this
        # is silently truncated by the exporter.
        self.max_influences = int(max_influences)
        # Weights below this value are tiny noise that cleaning removes.
        self.min_weight = float(min_weight)
        # How far a vertex weight sum may be from one before it is reported.
        self.normalize_tolerance = float(normalize_tolerance)


class WeightAuditUtils:
    """Read, analyse and rewrite the skin weights of one mesh object."""

    # ------------------------------------------------------------------
    # Reading the mesh
    # ------------------------------------------------------------------

    @staticmethod
    def collect_vertex_weights(mesh):
        """Return one ``{group index: weight}`` dict per mesh vertex.

        Only weights above ``WEIGHT_EPSILON`` are kept. Zero entries can exist
        in a mesh after an import and keeping them would make every vertex look
        influenced by a group it does not really use.
        """
        weights = []
        for vertex in mesh.vertices:
            entry = {}
            for element in vertex.groups:
                if element.weight > WEIGHT_EPSILON:
                    entry[element.group] = element.weight
            weights.append(entry)
        return weights

    @staticmethod
    def build_adjacency(mesh):
        """Return the vertex adjacency list of the mesh topology.

        Only real mesh edges are used. Two parts that overlap in space but are
        not connected by an edge therefore never count as neighbours, which is
        what keeps separate clothing pieces out of the seam check.
        """
        adjacency = [[] for _ in range(len(mesh.vertices))]
        for edge in mesh.edges:
            first, second = edge.vertices
            adjacency[first].append(second)
            adjacency[second].append(first)
        return adjacency

    @staticmethod
    def collect_smooth_internal_edges(mesh, smooth_angle_degrees):
        """Return vertex index pairs whose weight seam would be a real defect.

        An edge is skipped in three cases, because a weight boundary there is
        normal and reporting it would drown the real defect in noise:

        1. the edge is not shared by exactly two faces (an open border or a
           loose edge is a natural end of a mesh region);
        2. the two faces use different materials (different parts of a Mod);
        3. the two faces meet at an angle sharper than the tolerance (a
           geometric hard edge such as a hat brim).

        bmesh is used only to reach the two faces of an edge and their world
        independent normals; it is freed in ``finally`` so a mid-way exception
        cannot leak it in a long Blender session.
        """
        minimum_dot = math.cos(math.radians(float(smooth_angle_degrees)))
        pairs = []
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            # Link faces and normals must be valid before they are compared.
            bm.normal_update()
            bm.verts.ensure_lookup_table()
            for edge in bm.edges:
                faces = edge.link_faces
                if len(faces) != 2:
                    continue
                face_a, face_b = faces
                if face_a.material_index != face_b.material_index:
                    continue
                if face_a.normal.dot(face_b.normal) < minimum_dot:
                    continue
                pairs.append((edge.verts[0].index, edge.verts[1].index))
        finally:
            bm.free()
        return pairs

    # ------------------------------------------------------------------
    # Small weight helpers
    # ------------------------------------------------------------------

    @staticmethod
    def weight_difference(weights_a, weights_b):
        """Return the L1 distance between two vertex weight dictionaries.

        The L1 distance is chosen over the largest single difference because
        it also notices a bone that appears on one side only: a group moved
        from one bone to another yields a distance of 2.0, which is the
        strongest possible signal for two single-bone vertices.
        """
        difference = 0.0
        for group in set(weights_a) | set(weights_b):
            difference += abs(weights_a.get(group, 0.0) - weights_b.get(group, 0.0))
        return difference

    @staticmethod
    def positive_groups(weights):
        """Return the groups that really influence a vertex."""
        return {
            group
            for group, weight in weights.items()
            if weight > POSITIVE_WEIGHT_EPSILON
        }

    @staticmethod
    def normalize_entry(entry):
        """Scale one vertex weight dictionary so the weights sum to one.

        A vertex without any positive weight is left untouched: dividing by
        zero would raise and clearing it would silently unbind the vertex.
        """
        total = sum(entry.values())
        if total <= WEIGHT_EPSILON:
            return
        for group in entry:
            entry[group] = entry[group] / total

    @classmethod
    def prune_invisible_and_normalize(cls, entry):
        """Drop weights the reader ignores and renormalize the rest.

        The reader ignores weights at or below ``WEIGHT_EPSILON``, and float32
        storage can move a written value by about one relative epsilon. Keeping
        only weights above twice that line means the next read still sees every
        written weight, so the visible sum cannot drift below one.

        Normalization lowers every weight, so a weight just above the line can
        fall under it on the same pass; prune and rescale until every kept
        weight stays above it. The loop is bounded because one surviving weight
        always rescales to exactly one.
        """
        if not entry:
            return {}
        floor = 2.0 * WEIGHT_EPSILON
        for _ in range(4):
            visible = {
                group: weight for group, weight in entry.items() if weight > floor
            }
            if not visible:
                # Keep the strongest weight rather than dropping the vertex
                # binding entirely.
                strongest = max(entry, key=entry.get)
                visible = {strongest: entry[strongest]}
            cls.normalize_entry(visible)
            entry = visible
            if all(weight > floor for weight in entry.values()):
                break
        return entry

    @staticmethod
    def entries_equal(first, second):
        """Whether two weight dictionaries describe the same weights.

        The comparison uses ``WEIGHT_EPSILON`` so a vertex that is already
        normalized is not rewritten just because the float representation of
        1/3 differs in the last bit.
        """
        if set(first) != set(second):
            return False
        for group, weight in first.items():
            if abs(weight - second[group]) > WEIGHT_EPSILON:
                return False
        return True

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @classmethod
    def analyse(cls, obj, settings):
        """Inspect one mesh object and return the issue report dictionary.

        The dictionary is meant to be consumed by the UI and by the tests, so
        every value stays a plain Python type (no sets, no numpy arrays).
        """
        mesh = obj.data
        report = {
            "object": obj.name,
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "groups": len(obj.vertex_groups),
            "has_groups": len(obj.vertex_groups) > 0,
            "seam_edges": [],
            "seam_vertices": [],
            "clusters": [],
            "zero_weight_vertices": [],
            "over_influence_vertices": [],
            "unnormalized_vertices": [],
            "small_weight_count": 0,
            "issue_vertices": [],
            "has_issues": False,
        }
        # A mesh without vertex groups cannot hold a skinning defect; the UI
        # shows a dedicated hint for it instead of a misleading clean report.
        if not report["has_groups"] or len(mesh.vertices) == 0:
            return report

        weights = cls.collect_vertex_weights(mesh)
        adjacency = cls.build_adjacency(mesh)
        candidates = cls.collect_smooth_internal_edges(
            mesh, settings.smooth_angle_degrees
        )

        # ---- 1. Weight seams on smooth surfaces -----------------------
        seam_vertices = set()
        for first, second in candidates:
            first_weights = weights[first]
            second_weights = weights[second]
            # A small difference is a normal blend band, not a defect.
            if cls.weight_difference(first_weights, second_weights) < settings.seam_threshold:
                continue
            # A shared positive group is a transition bone: the two vertices
            # already blend into each other and the skin deforms smoothly.
            if cls.positive_groups(first_weights) & cls.positive_groups(second_weights):
                continue
            report["seam_edges"].append((first, second))
            seam_vertices.add(first)
            seam_vertices.add(second)
        report["seam_vertices"] = sorted(seam_vertices)

        # ---- 2. Isolated vertex-group clusters ------------------------
        report["clusters"] = cls.find_isolated_clusters(
            adjacency,
            weights,
            report["groups"],
            settings.island_weight_threshold,
            settings.island_min_vertices,
        )

        # ---- 3. Per-vertex checks -------------------------------------
        issue_vertices = set(seam_vertices)
        for cluster in report["clusters"]:
            issue_vertices.update(cluster["vertices"])
        for index, entry in enumerate(weights):
            total = 0.0
            influences = 0
            for weight in entry.values():
                total += weight
                # A weight below the cleaning threshold will be dropped by
                # the exporter or by the Clean button, so it does not count
                # as a real influence of this vertex.
                if weight >= settings.min_weight:
                    influences += 1
                else:
                    report["small_weight_count"] += 1
            if not entry or total <= WEIGHT_EPSILON:
                report["zero_weight_vertices"].append(index)
                issue_vertices.add(index)
                continue
            if influences > settings.max_influences:
                report["over_influence_vertices"].append(index)
                issue_vertices.add(index)
            if abs(total - 1.0) > settings.normalize_tolerance:
                report["unnormalized_vertices"].append(index)
                issue_vertices.add(index)
        report["issue_vertices"] = sorted(issue_vertices)
        report["has_issues"] = bool(
            report["seam_edges"]
            or report["clusters"]
            or report["zero_weight_vertices"]
            or report["over_influence_vertices"]
            or report["unnormalized_vertices"]
        )
        return report

    @staticmethod
    def find_isolated_clusters(
        adjacency,
        weights,
        group_count,
        weight_threshold,
        min_vertices,
    ):
        """Return the small connected components of every vertex group.

        A vertex group normally forms one connected region. Clothing that wraps
        around the body can legitimately form two large regions (the front and
        the back of a skirt), so only components smaller than ``min_vertices``
        are reported. Those small islands are exactly the stray weights a
        nearest-neighbour transfer leaves in a corner of the mesh.

        The group-to-member table is built once, which keeps the cost linear in
        the number of weight entries instead of walking every vertex for every
        group.
        """
        members_by_group = {group: [] for group in range(group_count)}
        for vertex, entry in enumerate(weights):
            for group, weight in entry.items():
                # An index outside the group count can only come from a broken
                # mesh, and walking it would raise on the list lookup below.
                if weight < weight_threshold or group not in members_by_group:
                    continue
                members_by_group[group].append(vertex)

        clusters = []
        for group in range(group_count):
            members = members_by_group[group]
            if len(members) < 2:
                continue
            member_set = set(members)
            visited = set()
            components = []
            # Iterative flood fill: recursion would hit Python's recursion
            # limit on a dense region of a large game mesh.
            for start in members:
                if start in visited:
                    continue
                stack = [start]
                visited.add(start)
                component = []
                while stack:
                    vertex = stack.pop()
                    component.append(vertex)
                    for neighbor in adjacency[vertex]:
                        if neighbor in member_set and neighbor not in visited:
                            visited.add(neighbor)
                            stack.append(neighbor)
                components.append(component)
            # A single component means the group is simply connected.
            if len(components) < 2:
                continue
            components.sort(key=len, reverse=True)
            main_size = len(components[0])
            for component in components[1:]:
                if len(component) >= min_vertices:
                    continue
                clusters.append(
                    {
                        "group": group,
                        "vertices": sorted(component),
                        "size": len(component),
                        "main_size": main_size,
                    }
                )
        return clusters

    # ------------------------------------------------------------------
    # Repair
    # ------------------------------------------------------------------

    @staticmethod
    def expand_vertices(mesh, vertices, rings):
        """Return the given vertices plus their neighbours up to ``rings``.

        Smoothing only the two ends of a seam moves the discontinuity one edge
        further out. Growing the target set by one ring gives the blend room to
        form a real gradient while still keeping every write local.

        Indices outside the mesh are ignored: callers may hand over a list that
        was computed from another object or from a stale vertex count, and one
        bad index must not abort a whole repair pass.
        """
        adjacency = WeightAuditUtils.build_adjacency(mesh)
        vertex_count = len(adjacency)
        result = {
            index for index in set(vertices) if 0 <= index < vertex_count
        }
        frontier = set(result)
        for _ in range(max(0, int(rings))):
            next_frontier = set()
            for vertex in frontier:
                for neighbor in adjacency[vertex]:
                    if neighbor not in result:
                        result.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
        return result

    @classmethod
    def smooth_vertices(cls, obj, target_vertices, iterations, factor):
        """Blend the target vertices towards the average weight of neighbours.

        Only the target vertices are written back; their neighbours are read
        but never modified, so a seam is repaired locally instead of being
        washed out across the whole mesh. The whole weight table is computed
        from the previous iteration's state, which makes the result
        independent of the vertex visit order.

        Returns the number of target vertices that were actually smoothed. An
        out-of-range index is dropped before it reaches the weight table, so a
        stale index from another object cannot raise.
        """
        mesh = obj.data
        weights = cls.collect_vertex_weights(mesh)
        adjacency = cls.build_adjacency(mesh)
        # Sorting and filtering keep the result independent of the caller's
        # set order and ignore stale indices instead of raising IndexError.
        vertex_count = len(weights)
        targets = sorted(
            index for index in set(target_vertices) if 0 <= index < vertex_count
        )
        # The strength is clamped here as well as in the operator: a value
        # outside 0..1 would produce negative weights or freeze the blend.
        strength = max(0.0, min(1.0, float(factor)))
        iterations = max(0, int(iterations))
        for _ in range(iterations):
            updated = {}
            for vertex in targets:
                neighbors = adjacency[vertex]
                # A lone vertex has nothing to blend towards.
                if not neighbors:
                    continue
                average = {}
                for neighbor in neighbors:
                    for group, weight in weights[neighbor].items():
                        average[group] = average.get(group, 0.0) + weight
                neighbor_count = len(neighbors)
                for group in average:
                    average[group] = average[group] / neighbor_count
                current = weights[vertex]
                blended = {}
                for group in set(current) | set(average):
                    value = (
                        current.get(group, 0.0) * (1.0 - strength)
                        + average.get(group, 0.0) * strength
                    )
                    if value > WEIGHT_EPSILON:
                        blended[group] = value
                # Every smoothed vertex must still sum to one, and no written
                # weight may be below the reader's epsilon. Normalization can
                # push a tiny weight under that line, so prune and rescale
                # until every kept weight stays visible.
                blended = cls.prune_invisible_and_normalize(blended)
                updated[vertex] = blended
            for vertex, blended in updated.items():
                weights[vertex] = blended
        cls.write_vertex_weights(obj, weights, targets)
        return len(targets)

    @classmethod
    def clean_weights(cls, obj, min_weight, max_influences):
        """Drop weak influences, cap the count and normalize every vertex.

        The strongest influence is always kept, even when every weight is
        below the threshold: removing all of them would leave the vertex
        without any bone and freeze it in the bind pose.

        Two epsilon boundaries matter here and are handled by one limit:

        - the reader (``collect_vertex_weights``) ignores weights at or below
          ``WEIGHT_EPSILON``, so a smaller weight written into the mesh would
          be invisible on the next read and make the visible sum drift;
        - Blender stores weights as float32, so a weight exactly at the
          threshold can come back a hair below it and be pruned by the next
          pass, which makes the button non-idempotent.

        The effective limit is the user threshold raised to twice the read
        epsilon, and comparisons allow one epsilon of slack.

        Returns how many vertices actually changed, so an operator can report
        a precise number instead of a mesh size.
        """
        mesh = obj.data
        weights = cls.collect_vertex_weights(mesh)
        influence_limit = max(1, int(max_influences))
        weight_limit = max(0.0, float(min_weight))
        # Weights at or below WEIGHT_EPSILON are invisible to the reader, and
        # float32 storage plus a later renormalization can move a boundary
        # weight by about one relative epsilon. The lower bound keeps a margin
        # from both: twice the read epsilon when no user threshold is set, and
        # a relative margin above the user threshold otherwise. A negative
        # margin would keep weights below the user's own threshold and would
        # still let a float32 value land under the read epsilon.
        lower_bound = max(
            weight_limit * (1.0 + WEIGHT_EPSILON), 2.0 * WEIGHT_EPSILON
        )
        changed = []
        for vertex, entry in enumerate(weights):
            if not entry:
                continue
            kept = {
                group: weight
                for group, weight in entry.items()
                if weight >= lower_bound
            }
            if not kept:
                # Keep the single strongest weight instead of leaving the
                # vertex unbound, which would freeze it in the bind pose.
                strongest = max(entry, key=entry.get)
                kept = {strongest: entry[strongest]}
            if len(kept) > influence_limit:
                ordered = sorted(kept.items(), key=lambda item: item[1], reverse=True)
                kept = dict(ordered[:influence_limit])
            # Normalization lowers every weight, so a weight that just passed
            # the threshold can fall below it on the same pass. Prune and
            # rescale until every kept weight still passes; otherwise a second
            # Clean click would silently change the same vertex again, which
            # makes the button non-idempotent. The loop is bounded because a
            # single surviving weight always rescales to exactly one.
            for _ in range(8):
                kept = {
                    group: weight
                    for group, weight in kept.items()
                    if weight >= lower_bound
                }
                if not kept:
                    strongest = max(entry, key=entry.get)
                    kept = {strongest: entry[strongest]}
                cls.normalize_entry(kept)
                if all(weight >= lower_bound for weight in kept.values()):
                    break
            # A vertex that already satisfies every rule is skipped, which
            # keeps the undo step and the mesh data limited to real changes.
            if cls.entries_equal(kept, entry):
                continue
            weights[vertex] = kept
            changed.append(vertex)
        if changed:
            cls.write_vertex_weights(obj, weights, changed)
        return len(changed)

    @classmethod
    def write_vertex_weights(cls, obj, weights, vertices):
        """Write the given weight dictionaries back into the vertex groups.

        Only groups whose value changes are touched, so locked groups and
        unrelated groups keep their exact weight. The current value is read
        from the mesh right before writing to stay correct when several
        functions edit one mesh in sequence.
        """
        groups = obj.vertex_groups
        for vertex in vertices:
            entry = weights[vertex]
            existing = {
                element.group: element.weight
                for element in obj.data.vertices[vertex].groups
            }
            for group in set(existing) | set(entry):
                new_weight = entry.get(group, 0.0)
                # Only a real zero is removed. The callers prune and normalize
                # their dictionaries before writing, so dropping a tiny positive
                # weight here would silently break the sum of one that the
                # caller just guaranteed.
                if new_weight <= 0.0:
                    # Removing only when the group was present avoids a
                    # pointless edit and keeps the undo data small.
                    if group in existing:
                        groups[group].remove([vertex])
                else:
                    groups[group].add([vertex], new_weight, "REPLACE")

    @staticmethod
    def mark_vertices(obj, vertices):
        """Select the given vertices so the user can find them in Edit Mode.

        The previous selection is cleared first: the point of the mark is to
        show exactly which vertices failed a check, so mixing them with the
        user's earlier selection would hide the result. Mesh vertex selection
        works while the object is in Object Mode, so the detection button never
        has to force the user out of the mode they are working in.
        """
        mesh = obj.data
        vertex_count = len(mesh.vertices)
        for vertex in mesh.vertices:
            vertex.select = False
        for index in vertices:
            if 0 <= index < vertex_count:
                mesh.vertices[index].select = True
        mesh.update()
