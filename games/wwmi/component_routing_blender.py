"""Connect the pure routing plan to disposable WWMI export data.

Only complete plans may change export ownership. Source meshes, shape keys,
vertex group names, weights, and blueprint bindings remain untouched.
Reports are Blender Text data, not writes into the user's source folders.
Source face tags precede modifiers; export triangle indices follow modifiers.
"""
import copy
import hashlib
import json
import time

import bpy
import numpy

from ...i18n.i18n import tr
from ...utils.draw_range_utils import DrawRangeUtils
from .component_routing import plan_faces


SOURCE_FACE = 'mimi_wwmi_source_face'
REPORT_DATA = 'mimi_wwmi_component_report_data'


def topology_signature(mesh):
    # Selection is only valid while source polygon/vertex indexing is unchanged.
    # Coordinates and weights may be repaired without invalidating these indices.
    # Hash ordered topology rather than trusting just vertex and face counts.
    topology = [len(mesh.vertices), [list(face.vertices) for face in mesh.polygons]]
    return hashlib.sha256(json.dumps(topology).encode('utf-8')).hexdigest()


def tag_source_faces(obj):
    # Tag the disposable copy before modifiers and triangulation run.
    # One-based values reserve zero for topology with no source correspondence.
    # Existing source attributes with this name are never modified on the source.
    mesh = obj.data
    # Discard an inherited diagnostic layer on the copy: its numbering may have
    # originated from another mesh or an earlier topology. Current polygon order
    # is the only valid reference for the source snapshot of this export attempt.
    previous = mesh.attributes.get(SOURCE_FACE)
    if previous is not None:
        mesh.attributes.remove(previous)
    attribute = mesh.attributes.new(SOURCE_FACE, 'INT', 'FACE')
    attribute.data.foreach_set('value', numpy.arange(1, len(mesh.polygons) + 1, dtype=numpy.int32))


def prepare_routing(model, context, allow_draw_state_change):
    """Analyze all faces before changing any buffer or draw assignment.

    FACE ownership survives joins and does not depend on Blender group order.
    The actual export integer layout bounds every candidate's local indices.
    A failed plan writes one complete report for this DrawIB, then cancels.
    """
    mesh = context.mesh
    owners = [temp for component in model.merged_object.components for temp in component.objects]
    owner_components = [index for index, component in enumerate(model.merged_object.components)
                        for temp in component.objects]
    attribute = mesh.attributes.get(DrawRangeUtils.OWNER_ATTRIBUTE)
    if attribute is None:
        raise ValueError('MergedComponent: export mesh lost face ownership')
    face_owners = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
    attribute.data.foreach_get('value', face_owners)
    if numpy.any(face_owners < 1) or numpy.any(face_owners > len(owners)):
        raise ValueError('MergedComponent: invalid source draw ownership')
    source_components = [int(owner_components[int(owner) - 1]) for owner in face_owners]
    # Blend layouts may span more than one integer field (for example eight
    # influences split over two four-slot elements). Use their common safe bound.
    # Planning cannot choose a slot which final localization cannot serialize.
    maximum_local = []
    for name in context.d3d11_game_type.OrderedFullElementList:
        if name.startswith('BLENDINDICES'):
            field = context.total_structured_dtype.fields[name][0]
            scalar = field.subdtype[0] if field.subdtype else field
            if scalar.kind != 'u':
                raise ValueError('MergedComponent: bone indices require an unsigned integer layout')
            maximum_local.append(numpy.iinfo(scalar).max)
    if maximum_local:
        names = {group.index: group.name for group in context.obj.vertex_groups}
        plan = plan_faces(mesh.vertices, mesh.polygons, names, source_components,
                          model.wwmi_info.components, allow_draw_state_change, min(maximum_local))
    elif 'Blend' in context.d3d11_game_type.OrderedCategoryNameList:
        # A weighted layout whose index element disappeared is a corrupt
        # workspace, not a static mesh: localizing would silently write global
        # bone ids, so keep the explicit failure.
        raise ValueError('MergedComponent: missing bone index export layout')
    else:
        # A static draw (for example WWMI's shader-fetched weapon meshes) carries
        # no bone indices at all, so no weight can constrain a palette. Every
        # triangle already belongs to exactly one blueprint component; keeping it
        # there is the identity plan. Refusing to plan would make such a capture
        # unexportable in the default MergedComponent architecture even though the
        # layout and every generated resource are complete. Weights a static
        # layout cannot serialize are dropped exactly as in the Merged mode.
        plan = dict(assignments=list(source_components), issues=[], counts=dict(
            unchanged=len(source_components), reassigned=0, ambiguous=0,
            incompatible=0, draw_state=0, island=0), islands=[])
    plan['owners'] = owners
    plan['face_owners'] = face_owners
    if plan['issues']:
        text = write_report(model.draw_ib, mesh, owners, face_owners, plan, names)
        counts = plan['counts']
        raise ValueError(tr('MergedComponent routing stopped: {incompatible} incompatible triangles, {ambiguous} ambiguous, {draw_state} require draw-state consent. Open report: {report}. No weights were deleted; repair the reported faces or explicitly use Merged.').format(
            **counts, report=text.name))
    # A component without a draw branch of its own is not an error: routing
    # clones the owning object's branch into the destination section and the
    # target component metadata supplies the match range. Only the source
    # object must exist, which the bucket keys already guarantee.
    # Per-loop localization can duplicate export vertices where palettes differ.
    # Shape deltas still come from the same source vertex for every duplicate.
    # No physical mesh split or shape-key renumbering is necessary.
    loops = numpy.empty(len(mesh.loops), dtype=numpy.int32)
    for face, target in zip(mesh.polygons, plan['assignments']):
        loops[face.loop_start:face.loop_start + face.loop_total] = target
    plan['loop_components'] = loops
    return plan


def write_report(draw_ib, mesh, owners, face_owners, plan, group_names):
    """Persist both readable repair guidance and complete machine selection data.

    A new Text block avoids overwriting a user-edited report of the same name.
    Full issue lists are retained; only the interactive error is summarized.
    Export vertex IDs are explicitly not presented as source vertex indices.
    """
    # Both face IDs are needed: the original index for selection and the export
    # triangle index for diagnosing geometry generated by modifiers. A missing
    # source tag remains unknown rather than being guessed from index order.
    # The topology digest prevents a later edit from selecting unrelated faces.
    source_faces = mesh.attributes.get(SOURCE_FACE)
    objects = {}
    for issue in plan['issues']:
        face = mesh.polygons[issue['triangle']]
        name = owners[int(face_owners[issue['triangle']]) - 1].name
        source = bpy.data.objects.get(name)
        if name not in objects:
            objects[name] = dict(topology=topology_signature(source.data) if source else '', issues=[])
        record = dict(issue)
        record['source_face'] = int(source_faces.data[face.index].value) - 1 if source_faces else -1
        record['export_vertices'] = [dict(index=int(index), weights={
            group_names.get(weight.group, str(weight.group)): float(weight.weight)
            for weight in mesh.vertices[index].groups if weight.weight > 0}) for index in face.vertices]
        objects[name]['issues'].append(record)
    report = dict(version=1, draw_ib=draw_ib, counts=plan['counts'], objects=objects,
                  islands=plan.get('islands', []))
    text = bpy.data.texts.new('mimi_wwmi_component_report.' + draw_ib + '.txt')
    text[REPORT_DATA] = json.dumps(report, ensure_ascii=False)
    text['mimi_report_time'] = time.time()
    lines = [tr('MergedComponent face routing report'), 'DrawIB: ' + draw_ib, str(plan['counts']), '',
             tr('Indices below are zero-based. Source faces precede modifiers; export triangles and vertices follow modifiers.'),
             tr('Select a source object, then press F3 > Select WWMI Problem Faces. Selection refuses changed topology.'), '',
             tr('incompatible: no original palette contains every positive weight. Check workspace/LOD and bone names; repaint only if the weights are wrong, or explicitly use Merged.'),
             tr('ambiguous: multiple target palettes fit. Separate these source faces into another object and bind it to the intended Submesh in the blueprint.'),
             tr('draw_state: one palette fits, but original target shaders/materials are not proven equivalent. Confirm the destination appearance, then enable Allow Component Draw-State Changes, or use Merged.'),
             tr('The routing plan was cancelled. Reassigned counts are proposals only. No automatic weight deletion, native shape-key renumbering, or architecture fallback was performed.'), '']
    islands = plan.get('islands', [])
    if islands:
        # Island decisions are applied before this report is written, so they
        # are a record of what already happened, not a proposal for the user.
        lines += [tr('Connected parts reassigned by island analysis:'), '']
        for island in islands:
            lines.append(json.dumps(island, ensure_ascii=False))
        lines.append('')
    for name, entry in objects.items():
        lines += [tr('Source object') + ': ' + name, tr('Source face indices') + ': ' + str(sorted({
            issue['source_face'] for issue in entry['issues'] if issue['source_face'] >= 0}))]
        # Each triangle includes all of its positive groups and exact weights.
        # Users can distinguish a per-vertex mixture from a triangle-only conflict.
        # The full record also supports future repair tools without recomputation.
        lines.extend(json.dumps(issue, ensure_ascii=False) for issue in entry['issues'])
        lines.append('')
    text.write('\n'.join(lines))
    return text


def latest_report():
    # New reports are stamped in creation order by this session's Blender data.
    # Do not rely on lexicographic sorting of automatic numeric name suffixes.
    # Callers can still inspect any older Text manually in the Text Editor.
    reports = [text for text in bpy.data.texts if REPORT_DATA in text]
    return max(reports, key=lambda text: float(text.get('mimi_report_time', 0))) if reports else None


def apply_routing(model, context, plan, submesh_names):
    """Rebucket whole IB triangles and clone draw conditions, not source meshes.

    Texture bindings are already resolved before this function runs.
    Shallow draw copies retain all key/time conditions and explicit slot lines.
    Native destination draw state changes only after the user's explicit consent.
    """
    # Keep the mutation boundary defensive even for future direct callers.
    # prepare_routing never returns an incomplete plan, but a saved or hand-built
    # plan must not bypass the all-or-nothing export contract.
    if plan.get('issues'):
        raise ValueError('MergedComponent: cannot apply an incomplete routing plan')
    # Island decisions move whole connected parts without the per-face consent,
    # so both counters must be checked before reporting a no-op.
    if not (plan['counts']['reassigned'] or plan['counts'].get('island')):
        return []
    owners = plan['owners']
    keys = set(zip(map(int, plan['face_owners']), plan['assignments']))
    # Count each source vertex once per bucket for draw statistics. Final buffer
    # deduplication may still duplicate shared corners when local indices differ.
    # The authoritative total vertex count is derived from the packed VB later.
    bucket_vertices = {key: set() for key in keys}
    for face, owner, target in zip(context.mesh.polygons, plan['face_owners'], plan['assignments']):
        bucket_vertices[(int(owner), target)].update(face.vertices)
    ordered_keys = sorted(keys, key=lambda key: (key[1], key[0]))
    buckets = {}
    new_components = [[] for component in model.merged_object.components]
    for owner, target in ordered_keys:
        temp = copy.copy(owners[owner - 1])
        # TempObject.name is only an export range identity after the final join.
        # Do not create new Blender objects or look this synthetic name up later.
        # Original object names remain on draw copies for UI and texture metadata.
        temp.name += '__mimi_component_' + str(target)
        temp.index_count = 0
        temp.index_offset = 0
        temp.vertex_count = len(bucket_vertices[(owner, target)])
        new_components[target].append(temp)
        buckets[(owner, target)] = temp
    owner_by_name = {temp.name: index + 1 for index, temp in enumerate(owners)}
    new_draws = [[] for component in model.merged_object.components]
    links = []
    # Iterate draw branches, not just object names: several conditions may draw
    # exactly the same geometry. Each branch needs one clone per destination.
    # Resolved explicit bindings follow the source; absent bindings deliberately
    # inherit the destination game's state under the opt-in consent contract.
    for component_index, group in enumerate(model.submesh_drawcall_groups):
        for draw in group:
            owner = owner_by_name.get(draw.obj_name)
            # A draw branch whose object was joined away owns no geometry any
            # more. It must still describe every bucket routed into this
            # component, otherwise the routed faces would have no draw call.
            if owner is None:
                pairs = sorted(key for key in keys if key[1] == component_index)
            else:
                pairs = sorted(key for key in keys if key[0] == owner)
            for bucket_owner, target in pairs:
                routed = copy.copy(draw)
                routed.submesh_name = submesh_names[target]
                routed.match_submesh_name = submesh_names[target]
                extracted = model.wwmi_info.components[target]
                routed.match_first_index = str(extracted.index_offset)
                routed.match_index_count = str(extracted.index_count)
                new_draws[target].append(routed)
                links.append((routed, buckets[(bucket_owner, target)]))
    # All lookups complete before mutating the export model or its FACE tags.
    # Bucket numbering follows the new component-major range-owner list exactly.
    # Buffer alignment later derives final offsets from the actual emitted IB.
    numbers = {key: index + 1 for index, key in enumerate(ordered_keys)}
    values = numpy.array([numbers[(int(owner), target)] for owner, target in zip(
        plan['face_owners'], plan['assignments'])], dtype=numpy.int32)
    context.mesh.attributes[DrawRangeUtils.OWNER_ATTRIBUTE].data.foreach_set('value', values)
    for component, objects in zip(model.merged_object.components, new_components):
        component.objects = objects
        component.vertex_count = sum(temp.vertex_count for temp in objects)
    model.submesh_drawcall_groups = new_draws
    return links
