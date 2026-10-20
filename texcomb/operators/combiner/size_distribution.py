"""Plan exact material content sizes before any destructive merge operation.

The preview uses copied UV vectors. Plans live in Scene RNA so undo and saved
blend files retain the editable list; a source fingerprint rejects stale plans.
Each equivalent baked-output group has one editable row and one packed region.
Cached member pointers map that row back to all selected source materials.
Shared source images link size constraints across distinct output variants.

Plan lifecycle:
- Generate discards prior locks and starts from current source preferences.
- Recalculate starts from source preferences again, not previously reduced sizes.
- This prevents cumulative resolution loss after several successive edits.
- Either width or height edit locks both dimensions as a single exact region.
- Unlocking retains visible values until recalculation replaces them.
- Failed planning retains editable dimensions rather than applying a partial plan.
- Success stores every placement and enables the merge action.
- Any layout setting edit immediately revokes that approval.
- Source UV and face assignment changes are detected by a fingerprint.
- Hidden placement edits are also covered by that fingerprint.
- A file-picker delay cannot bypass the execution-time fingerprint check.

Pixel-space contract:
- Source ceilings affect automatic preferences, not manual overrides.
- UV repeats describe content sampling separately from the final region size.
- User dimensions describe output content, not the size of an individual tile.
- A repeated texture may therefore use many lower-resolution tiles in a region.
- External padding is added after the content dimensions have been chosen.
- Padding stays constant throughout the budget-reduction loop.
- Composition and UV remapping use the same padding inset.
- A fixed 512 square remains 512 square in the final output image.
- Rectangular locks retain their width and height axes without rotation.
- The normal channel uses the same unrotated layout as the base channel.
- Legacy canvas resizing is bypassed for all approved distributions.
- No automatic reduction candidate may be a manually fixed material.
- Automatic solid entries retain their original small preferred size.

Safety boundaries:
- Preview copies vectors before calling the legacy in-place UV normalizer.
- Preview never removes unused material slots or deduplicates material IDs.
- Multiple objects sharing one material share one allocation.
- Visually identical materials share one UI row and one packed output region.
- Shared textures link sizes even if different tint or alpha requires separate boxes.
- Render UV layers are sampled without changing the editing layer in preview.
- All mesh writes remain in the actual combiner execution stage.
- Scene-owned RNA callbacks must invalidate their own Scene, not context.scene.
- Collection additions can invalidate previous Python entry references.
- Locks are copied into ordinary dictionaries before rebuilding collections.
- Panel redraws use a separate small signature of allocation RNA values only.
- Full fingerprints and bulk UV reads run only during planning and merging.
- Reopening a saved blend requires recalculation when datablock identity changes.
"""

import hashlib
import json
import math

import bpy
import numpy as np
from bpy.props import BoolProperty

from ....i18n.i18n import I18nOperator, tr
from ...core import layout
from ...globs import CombineListTypes
from .combiner_ops import get_data, get_mats_uv, get_size, get_structure, _get_image_size
from ...utils.materials import get_image_from_material, get_diffuse, get_effective_diffuse, get_gfx_textures, get_alpha_texture
from ...utils.images import get_packed_file

# Only layout-affecting options participate; output paths and codecs do not.
SETTINGS = (
    "uniform_size", "uniform_size_value", "original_size", "original_width",
    "original_height", "total_size", "total_width", "total_height", "crop",
    "gaps", "diffuse_size", "size", "size_width", "size_height", "packer_type",
    "include_extra_textures",
)


def invalidate_distribution(self, context):
    """RNA edits clear approval immediately, including undo-restored edits."""
    # The entry owns its Scene; do not accidentally invalidate another scene.
    scene = self if isinstance(self, bpy.types.Scene) else self.id_data
    if isinstance(scene, bpy.types.Scene):
        scene.mimi_smc_distribution_valid = False


def edit_distribution_size(self, context):
    """Typing either dimension automatically locks this material's region."""
    self.locked = True
    invalidate_distribution(self, context)


def source_signature(scene):
    """Fingerprint settings, selections, materials and the sampled UV layers.

    No texture decoding, UV alignment or material deletion occurs here.
    This full scan is reserved for explicit planning and merge operations.
    Panel redraws must use distribution_ui_signature instead.
    """
    digest = hashlib.sha256()
    # Reject approvals made before the exact per-axis UV window was introduced;
    # their stored regions assume whole-tile repeats and would stretch content.
    state = ["shared-uv-window-v2"] + [getattr(scene, "mimi_smc_" + name) for name in SETTINGS]
    selected = []
    objects = set()
    materials = set()
    for entry in scene.mimi_smc_ob_data:
        if entry.type == CombineListTypes.MATERIAL and entry.used and entry.ob and entry.mat:
            selected.append((entry.ob.as_pointer(), entry.mat.as_pointer(), entry.layer))
            objects.add(entry.ob)
            materials.add(entry.mat)
    state.append(sorted(selected))
    # Approval also covers the stored positions, dimensions and material IDs.
    # This detects deleted materials or script edits to otherwise hidden fields.
    state.append([(entry.mat.as_pointer() if entry.mat else 0, entry.width,
                   entry.height, entry.locked, entry.x, entry.y, entry.allocation_width, entry.allocation_height,
                   tuple(member.mat.as_pointer() if member.mat else 0 for member in entry.members))
                  for entry in scene.mimi_smc_distribution])
    state.append((scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height))
    # Include actual face assignments, not merely the visible material list.
    for obj in sorted(objects, key=lambda item: item.as_pointer()):
        if obj.mode == "EDIT":
            obj.update_from_editmode()
        layers = obj.data.uv_layers
        layer = next((uv for uv in layers if uv.active_render), layers.active)
        state.append((obj.as_pointer(), obj.name, layer.name if layer else "",
                      [slot.material.as_pointer() if slot.material else 0 for slot in obj.material_slots]))
        if layer:
            coords = np.empty(len(layer.data) * 2, dtype=np.float32)
            layer.data.foreach_get("uv", coords)
            digest.update(coords.tobytes())
        indices = np.empty(len(obj.data.polygons), dtype=np.int32)
        obj.data.polygons.foreach_get("material_index", indices)
        digest.update(indices.tobytes())
        # Topology can change while loop coordinates and counts stay the same.
        state.append([(poly.loop_start, poly.loop_total) for poly in obj.data.polygons])
    for mat in sorted(materials, key=lambda item: item.as_pointer()):
        state.append((mat.as_pointer(), mat.name, tuple(mat.diffuse_color),
                      mat.mimi_smc_size, mat.mimi_smc_size_width, mat.mimi_smc_size_height,
                       mat.mimi_smc_diffuse, get_diffuse(mat), mat.mimi_smc_alpha_mode,
                       mat.mimi_smc_alpha_image.as_pointer() if mat.mimi_smc_alpha_image else 0,
                       mat.mimi_smc_alpha_channel))
        if mat.node_tree:
            state.append([(link.from_node.name, link.from_socket.identifier,
                           link.to_node.name, link.to_socket.identifier)
                          for link in mat.node_tree.links])
            for node in mat.node_tree.nodes:
                image = getattr(node, "image", None)
                if image:
                    state.append((node.name, image.as_pointer(), tuple(image.size),
                                  image.filepath, image.source))
    digest.update(json.dumps(state, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def distribution_ui_signature(scene):
    """Read small RNA values only; never visit UVs, faces or shader nodes.

    Redraw cost scales with material rows, not mesh polygon or loop counts.
    Selection and scripted dimension changes are still checked immediately.
    Deep source edits are checked by the full fingerprint at merge time.
    No draw callback synchronizes edit meshes or allocates coordinate arrays.
    """
    # Reject approvals made before the exact per-axis UV window was introduced;
    # their stored regions assume whole-tile repeats and would stretch content.
    state = ["shared-uv-window-v2"] + [getattr(scene, "mimi_smc_" + name) for name in SETTINGS]
    # Include selection IDs without retaining live datablock references.
    state.append([(entry.ob.as_pointer() if entry.ob else 0,
                   entry.mat.as_pointer() if entry.mat else 0, entry.layer)
                  for entry in scene.mimi_smc_ob_data
                  if entry.type == CombineListTypes.MATERIAL and entry.used])
    # Hidden placement edits cannot bypass the lightweight UI check either.
    state.append([(entry.mat.as_pointer() if entry.mat else 0, entry.width,
                   entry.height, entry.locked, entry.x, entry.y, entry.allocation_width, entry.allocation_height,
                   tuple(member.mat.as_pointer() if member.mat else 0 for member in entry.members))
                  for entry in scene.mimi_smc_distribution])
    state.append((scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height))
    return hashlib.sha256(json.dumps(state).encode("utf-8")).hexdigest()


def distribution_ready(scene, check_sources=True):
    """Use deep checks for operators and a lightweight check for panel redraw.

    The default stays strict so existing scripts cannot accidentally bypass
    source validation. Only the UI explicitly opts out of scanning mesh data.
    A stale UV or shader source is rejected before opening the file picker and
    checked again after the picker, before alignment or image creation.
    """
    if not scene.mimi_smc_distribution_valid or not scene.mimi_smc_distribution:
        return False
    if not check_sources:
        return scene.mimi_smc_distribution_ui_signature == distribution_ui_signature(scene)
    ready = scene.mimi_smc_distribution_signature == source_signature(scene)
    # A rejected merge also revokes the lightweight UI approval immediately.
    # This write never occurs inside panel redraws, which use the branch above.
    if not ready:
        scene.mimi_smc_distribution_valid = False
    return ready


def prepare_sources(scene, read_only=True):
    """Build per-material sources without deduplication or slot deletion."""
    data = get_data(scene.mimi_smc_ob_data)
    mats_uv = get_mats_uv(scene, data, read_only=read_only)
    # Empty slots have no usable region and cannot participate in the plan.
    data = {name: {mat: layer for mat, layer in mats.items() if mats_uv[name].get(mat)}
            for name, mats in data.items()}
    data = {name: mats for name, mats in data.items() if mats}
    structure = get_structure(scene, data, mats_uv, use_roots=False)
    if len(structure) < 2:
        raise ValueError(tr("Select at least two materials with valid UVs"))
    structure = get_size(scene, structure)
    prepare_shared_sampling(scene, structure)
    return data, mats_uv, structure


def shared_uv_window(scene, structure, group):
    """Return the shared (repeat_u, repeat_v) sampling window for one family.

    Every material sharing a source image must bake identical base pixels so
    equivalent outputs can still share one packed region. The window is the
    largest normalized UV extent in the family, applied to each axis on its own.

    Two policies define that window:
    - Crop to UV bounds (default): keep the real extent, so a 2% overshoot
      costs 2% of a tile instead of a whole duplicated 2x2 block.
    - Whole tiles: the historical square power-of-two grid. Tile edges stay
      pixel aligned, but any extent above one reserves a full extra tile.
    """
    extents = [structure[mat]["gfx"]["uv_size"] for mat in group]
    # UVs that only cover part of a tile still sample the whole tile.
    extent_u = max(1.0, max(item[0] for item in extents))
    extent_v = max(1.0, max(item[1] for item in extents))
    if scene.mimi_smc_crop:
        # Exact bounds: one tile plus whatever fraction the UVs really use.
        return extent_u, extent_v
    # Legacy whole tiles: one square grid, rounded up to powers of two.
    repeat = 1 << (max(1, math.ceil(max(extent_u, extent_v))) - 1).bit_length()
    return float(repeat), float(repeat)


def prepare_shared_sampling(scene, structure):
    """Separate source aspect from UV coverage before sizing and deduplication.

    Each source-image family gets one shared sampling window, so every member
    bakes exactly the same repeated content and equivalent outputs can still
    merge into one region. The window is per axis: a texture tiled twice
    vertically does not also reserve two horizontal copies.

    Cropping to UV bounds (the default) reserves only the fraction of a tile
    that UVs actually reach. Disabling it restores the legacy whole-tile grid,
    which is explicit but duplicates a full tile for any small overshoot.
    Preview and merge both call this adapter; neither wraps polygon corners
    with modulo, which would break triangles crossing a tile boundary.
    """
    groups = texture_groups(structure)
    # Solid outputs can share a row even without a common Image datablock.
    # Give those peers one mapping too; their flat color has no tile detail.
    groups = [group for group in groups if not structure[group[0]]["gfx"]["solid"]]
    groups += [[mat for mat in group if structure[mat]["gfx"]["solid"]]
               for group in output_groups(scene, structure)]
    for group in groups:
        if not group:
            continue
        # One window for the whole family: peers must bake identical content.
        window_u, window_v = shared_uv_window(scene, structure, group)
        for mat in group:
            gfx = structure[mat]["gfx"]
            image = get_image_from_material(mat)
            source = tuple(image.size) if not gfx["solid"] else (1, 1)
            if gfx["solid"]:
                # UV overshoot must not turn a flat 32-square into 25x32.
                side = 32 if scene.mimi_smc_uniform_size or scene.mimi_smc_total_size else scene.mimi_smc_diffuse_size
                size = (layout.floor_power_of_two(side),) * 2
                # A flat color has no tile detail; keep the region square.
                native = (max(window_u, window_v),) * 2
            else:
                bounds = _get_image_size(mat, image)
                if scene.mimi_smc_uniform_size:
                    bounds = tuple(min(axis, scene.mimi_smc_uniform_size_value) for axis in bounds)
                try:
                    tile = layout.power_of_two_content(source, bounds)
                except ValueError as exc:
                    # Exact aspect and power-of-two axes are incompatible for
                    # some source ratios; never report a distorted plan as valid.
                    raise ValueError(tr("Cannot preserve source aspect with power-of-two dimensions: {material}").format(
                        material=mat.name)) from exc
                # Whole pixels derived from the shared window. repeat_plane
                # crops with the same rounding, so repeated content is not
                # resampled a second time just to fit the allocated box.
                size = (math.ceil(tile[0] * window_u), math.ceil(tile[1] * window_v))
                native = (source[0] * window_u, source[1] * window_v)
            # Spacing belongs outside the content, including automatic solids.
            # All callers subtract this same gap exactly once before budgeting.
            gfx["size"] = tuple(axis + scene.mimi_smc_gaps for axis in size)
            gfx["gaps"] = scene.mimi_smc_gaps
            gfx["uv_size"] = (window_u, window_v)
            gfx["native_extent"] = native


def texture_groups(structure):
    """Link allocations using the same source Image without pixel comparisons.

    Empty/solid materials remain independent; None is not a shared texture.
    Group detection runs only in explicit planning and merge operations.
    """
    groups = {}
    for mat in structure:
        image = get_image_from_material(mat)
        key = ("image", image.as_pointer()) if image else ("material", mat.as_pointer())
        groups.setdefault(key, []).append(mat)
    return list(groups.values())


def output_groups(scene, structure):
    """Deduplicate only equivalent baked outputs, not merely matching albedo.

    Tint, alpha mode/source and enabled PBR maps can change pixels.
    UV coverage is not source identity: prepare_shared_sampling gives peers
    one common grid before packing and merging. Keeping shading differences
    in this key still prevents visibly different outputs sharing a rectangle.
    """
    groups = {}
    for mat, item in structure.items():
        image = get_image_from_material(mat)
        packed = get_packed_file(image) if image else None
        # A packed texture keeps its own color; only an explicit, visible tint
        # may split it into another group. get_effective_diffuse() returns
        # white when the tint is off or when a texture link hid the value.
        color = get_diffuse(mat) if not packed else get_effective_diffuse(mat)
        alpha_mode = mat.mimi_smc_alpha_mode
        alpha = None
        if alpha_mode in {"SEPARATE", "MULTIPLY"}:
            alpha_image = mat.mimi_smc_alpha_image
            alpha = (alpha_image.as_pointer() if alpha_image else 0, mat.mimi_smc_alpha_channel)
        elif alpha_mode == "AUTO":
            linked = get_alpha_texture(mat)
            alpha = (linked[0].as_pointer(), linked[1]) if linked else None
        maps = get_gfx_textures(mat) if scene.mimi_smc_include_extra_textures else {}
        key = (packed.as_pointer() if packed else 0, color, alpha_mode, alpha,
               tuple(sorted((kind, source.as_pointer() if source else 0) for kind, source in maps.items())))
        groups.setdefault(key, []).append(mat)
    return list(groups.values())


def distribution_entries(scene):
    """Expand grouped rows into a material-to-row adapter for planning/merge.

    Old saved lists without members still work until regenerated. New groups
    have one allocation row shared by every member; duplicate membership fails
    before model writes. This helper reads small RNA only, never mesh data.
    """
    entries = {}
    for entry in scene.mimi_smc_distribution:
        materials = [member.mat for member in entry.members] if entry.members else [entry.mat]
        for mat in materials:
            if not mat or mat in entries:
                raise ValueError(tr("Materials changed; generate the size distribution again"))
            entries[mat] = entry
    return entries


def rebuild_distribution(scene, structure, sizes, fixed, fits=None):
    """Build one visible row per packed output group before showing the list.

    Keep all source members attached to the representative. Size budgeting and
    merge mapping use those same groups; UI never rediscovers material identity.
    Failed planning can also display grouped defaults without granting approval.
    """
    groups = output_groups(scene, structure)
    scene.mimi_smc_distribution.clear()
    for group in groups:
        root = group[0]
        entry = scene.mimi_smc_distribution.add()
        entry.mat = root
        for mat in group:
            member = entry.members.add()
            member.mat = mat
        # One representative contains all equivalent materials' allocation data.
        allocation = sizes[root]
        content = layout.fit_proportional_content(structure[root]["gfx"]["native_extent"], allocation)
        # Visible fields describe actual content, not blank reserved area.
        # A square source therefore never reports a stretched result after planning.
        entry.width, entry.height = content
        # Cache the sampling window: a row above 1 bakes its source more than
        # once. Redraws and tests read this value instead of rescanning sources.
        window_u, window_v = structure[root]["gfx"]["uv_size"]
        entry.uv_repeat_u, entry.uv_repeat_v = float(window_u), float(window_v)
        entry.allocation_width, entry.allocation_height = allocation
        entry.locked = any(mat in fixed for mat in group)
        if fits:
            entry.approved_width, entry.approved_height = content
            entry.x, entry.y = fits[root]["x"], fits[root]["y"]
    scene.mimi_smc_distribution_index = min(scene.mimi_smc_distribution_index,
                                             max(0, len(groups) - 1))


def synchronize_fixed_sizes(scene, structure, fixed):
    """Propagate one manual size to its texture peers and reject ambiguity.

    Synchronize the visible list before packing, even if the new budget fails.
    A user edit supersedes the previously approved group value; peers carrying
    that old value are not conflicting new instructions. Multiple different
    newly edited sizes still require an explicit user choice.
    """
    fixed = dict(fixed)
    entries = distribution_entries(scene)
    for group in texture_groups(structure):
        edited = {fixed[mat] for mat in group if mat in fixed and mat in entries
                  and (entries[mat].width, entries[mat].height) !=
                  (entries[mat].approved_width, entries[mat].approved_height)}
        locked = edited or {fixed[mat] for mat in group if mat in fixed}
        if len(locked) > 1:
            raise ValueError(tr("Conflicting fixed sizes for shared texture: {materials}").format(
                materials=", ".join(mat.name for mat in group)))
        if locked:
            size = next(iter(locked))
            for mat in group:
                fixed[mat] = size
                if mat in entries:
                    entries[mat].width, entries[mat].height = size
                    entries[mat].locked = True
    return fixed


def plan_sizes(scene, structure, fixed):
    """Apply source ceilings first, then preserve exact manual content sizes.

    Padding is external to content, and is never silently reduced. Legacy
    custom canvases become packing constraints instead of a final rescale.
    """
    gaps = scene.mimi_smc_gaps
    sizes = {mat: tuple(axis - item["gfx"]["gaps"] for axis in item["gfx"]["size"])
             for mat, item in structure.items()}
    # Default allocations follow native proportions instead of fitting each axis.
    # User-fixed bounds may be any shape; their extra space stays unused.
    sizes = {mat: layout.fit_proportional_content(structure[mat]["gfx"]["native_extent"], size)
             for mat, size in sizes.items()}
    minimum = (scene.mimi_smc_original_width, scene.mimi_smc_original_height) if scene.mimi_smc_original_size else (1, 1)
    maximum = (scene.mimi_smc_total_width, scene.mimi_smc_total_height) if scene.mimi_smc_total_size else (16384, 16384)
    automatic = scene.mimi_smc_uniform_size or scene.mimi_smc_original_size or scene.mimi_smc_total_size
    if not automatic and scene.mimi_smc_size in {"CUST", "STRICTCUST"}:
        maximum = (scene.mimi_smc_size_width, scene.mimi_smc_size_height)
        if scene.mimi_smc_size == "STRICTCUST":
            minimum = maximum
    # Pack one representative per equivalent output, retaining every UI row.
    # The largest preference in each texture family applies to all its outputs.
    fixed = synchronize_fixed_sizes(scene, structure, fixed)
    outputs = output_groups(scene, structure)
    representative = {mat: group[0] for group in outputs for mat in group}
    linked = []
    for group in texture_groups(structure):
        preferred = tuple(max(sizes[mat][axis] for mat in group) for axis in (0, 1))
        for mat in group:
            sizes[mat] = preferred
        if len(group) > 1:
            linked.append(set(representative[mat] for mat in group))
    boxes = {group[0]: sizes[group[0]] for group in outputs}
    locks = {representative[mat]: size for mat, size in fixed.items()}
    solids = [group[0] for group in outputs if structure[group[0]]["gfx"]["solid"]]
    # Budget reduction cannot touch locked entries, including locked solids.
    try:
        # Automatic preferences already have exact power-of-two proportions.
        # Stop at the shortest one-pixel axis instead of distorting thin images.
        fits, canvas, packed_sizes = layout.pack_budget_atlas(
            boxes, maximum, minimum, solids, locks, gaps, linked, preserve_aspect=True)
        sizes = {mat: packed_sizes[representative[mat]] for mat in structure}
        fits = {mat: fits[representative[mat]] for mat in structure}
    except ValueError as exc:
        # Preserve the explicit floor-versus-ceiling error where applicable.
        if "Original game" in str(exc):
            raise ValueError(tr("Original game texture size exceeds total maximum texture size")) from exc
        raise ValueError(tr("Fixed regions and spacing cannot fit the atlas; reduce fixed sizes or increase the maximum")) from exc
    if not automatic and scene.mimi_smc_size == "QUAD":
        side = max(canvas)
        canvas = (side, side)
    return fits, canvas, sizes


def apply_distribution(scene, structure):
    """Use the validated positions verbatim; never repack during the merge."""
    entries = distribution_entries(scene)
    if set(entries) != set(structure):
        raise ValueError(tr("Materials changed; generate the size distribution again"))
    for mat, item in structure.items():
        entry = entries[mat]
        gaps = scene.mimi_smc_gaps
        item["gfx"]["gaps"] = gaps
        allocation = (entry.allocation_width or entry.width, entry.allocation_height or entry.height)
        item["gfx"]["size"] = tuple(axis + gaps for axis in allocation)
        # The reserved box and the pasted image are deliberately separate.
        # Both image building and UV mapping use this same proportional content.
        item["gfx"]["content_size"] = (entry.width, entry.height)
        item["gfx"]["fit"] = {"x": entry.x, "y": entry.y,
                              "w": allocation[0] + gaps, "h": allocation[1] + gaps}
        # Prevent legacy whole-canvas scaling from overriding exact sizes.
        item["gfx"]["distribution"] = True
    # Combine UV lists only for truly equivalent output rectangles.
    # Composition now decodes and pastes each duplicate group exactly once.
    for group in output_groups(scene, structure):
        root = group[0]
        for mat in group[1:]:
            peer = structure[mat]
            if peer["gfx"]["fit"] != structure[root]["gfx"]["fit"]:
                raise ValueError(tr("Materials changed; generate the size distribution again"))
            structure[root]["uv"].extend(peer["uv"])
            structure[root]["dup"].append(mat.name)
            del structure[mat]
    return (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height)


def prepare_distribution_previews(scene):
    """Cache the same main texture used by the combiner once per plan.

    ID previews work with packed and generated images as well as disk images.
    No shader traversal or preview generation is allowed from a draw callback.
    Shared images are initialized once; Blender owns their preview lifetime.
    Unsupported images fall back to the material icon without failing planning.
    Preview pointers are display-only and do not affect approved pixel sizes.
    """
    prepared = set()
    for entry in scene.mimi_smc_distribution:
        entry.preview_image = get_image_from_material(entry.mat) if entry.mat else None
        image = entry.preview_image
        # The combiner uses diffuse fallback when the base image is unreadable.
        # Cache that same color here, not the generic viewport material color.
        entry.preview_solid = not bool(get_packed_file(image) if image else None)
        if entry.preview_solid:
            color = get_diffuse(entry.mat) if entry.mat else (255, 255, 255, 255)
            rgb = np.asarray(color[:3], dtype=np.float32) / 255
            linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
            entry.preview_color = tuple(float(value) for value in linear) + (color[3] / 255,)
            entry.preview_image = None
            continue
        if image and image.as_pointer() not in prepared:
            prepared.add(image.as_pointer())
            try:
                # Request preview creation only at this explicit user action.
                # Never retry on every mouse move if an image cannot preview.
                preview = image.preview_ensure()
                if not preview.image_size[0]:
                    # Blender may not populate previews for packed/generated images.
                    # Build a bounded thumbnail once from the already loaded pixels.
                    width, height = image.size
                    if width and height and image.channels == 4:
                        xs = np.linspace(0, width - 1, 64).astype(int)
                        ys = np.linspace(0, height - 1, 64).astype(int)
                        thumbnail = np.empty((64, 64, 4), dtype=np.float32)
                        for row, y in enumerate(ys):
                            # Sample only 64 rows, not an entire 4K/8K image buffer.
                            # Temporary storage is bounded by one source row.
                            start = int(y) * width * 4
                            pixels = np.asarray(image.pixels[start:start + width * 4], dtype=np.float32)
                            thumbnail[row] = pixels.reshape(width, 4)[xs]
                        # Image pixels are linear; display color previews in sRGB.
                        rgb = thumbnail[:, :, :3]
                        if not image.colorspace_settings.is_data:
                            thumbnail[:, :, :3] = np.where(rgb <= 0.0031308, rgb * 12.92,
                                                           1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - 0.055)
                        preview.image_size = (64, 64)
                        preview.image_pixels_float = thumbnail.ravel()
                        preview.icon_size = (32, 32)
                        preview.icon_pixels_float = thumbnail[::2, ::2].ravel()
            except (RuntimeError, ValueError):
                entry.preview_image = None


class GenerateSizeDistribution(I18nOperator):
    """Generate defaults or recompute automatic entries around manual locks."""

    bl_idname = "mimi.generate_size_distribution"
    bl_label = "Generate Size Distribution"
    bl_description = "Calculate editable material sizes and validate atlas packing"
    bl_options = {"UNDO"}
    recalculate: BoolProperty(default=False, options={"HIDDEN"})

    def execute(self, context):
        scene = context.scene
        # Revoke approval before preparing anything, even if preparation fails.
        scene.mimi_smc_distribution_valid = False
        scene.mimi_smc_distribution_expanded = True
        if not self.recalculate:
            # Generate is a fresh start, unlike recalculation around manual locks.
            # Clear before source preparation so failures cannot expose old rows.
            scene.mimi_smc_distribution.clear()
            scene.mimi_smc_distribution_index = 0
            # Cached canvas and approval fingerprints belong to the discarded plan.
            # A failed refresh must leave no old placements available for reuse.
            scene.mimi_smc_distribution_width = 0
            scene.mimi_smc_distribution_height = 0
            scene.mimi_smc_distribution_signature = ""
            scene.mimi_smc_distribution_ui_signature = ""
            scene.mimi_smc_distribution_message = ""
        try:
            bpy.ops.mimi.refresh_ob_data()
            _, _, structure = prepare_sources(scene)
            previous = {}
            if self.recalculate:
                for mat, entry in distribution_entries(scene).items():
                    if entry.locked:
                        # Unedited content fields retain the earlier reserved slack.
                        # Fresh edits are new bounds and are fitted proportionally.
                        size = (entry.width, entry.height)
                        if size == (entry.approved_width, entry.approved_height):
                            size = (entry.allocation_width or entry.width, entry.allocation_height or entry.height)
                        previous[mat] = size
            fixed = previous if self.recalculate else {}
            if set(fixed) - set(structure):
                raise ValueError(tr("Materials changed; generate the size distribution again"))
            # Show defaults even when packing fails, so users can reduce locks.
            if not self.recalculate:
                defaults = {mat: tuple(axis - item["gfx"]["gaps"] for axis in item["gfx"]["size"])
                            for mat, item in structure.items()}
                rebuild_distribution(scene, structure, defaults, {})
            # Failed plans still show texture identities in the editable list.
            prepare_distribution_previews(scene)
            fixed = synchronize_fixed_sizes(scene, structure, fixed)
            fits, canvas, sizes = plan_sizes(scene, structure, fixed)
            # Rebuild after collecting locks; never keep RNA references across add().
            rebuild_distribution(scene, structure, sizes, fixed, fits)
            prepare_distribution_previews(scene)
            scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height = canvas
            # Store separate approvals for cheap redraws and strict merge checks.
            # Only explicit planning and merging may scan geometry data.
            scene.mimi_smc_distribution_signature = source_signature(scene)
            scene.mimi_smc_distribution_ui_signature = distribution_ui_signature(scene)
            scene.mimi_smc_distribution_message = ""
            scene.mimi_smc_distribution_valid = True
        except (ValueError, RuntimeError) as exc:
            # Keep the editable list and fixed sizes for the user's next attempt.
            scene.mimi_smc_distribution_message = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}
