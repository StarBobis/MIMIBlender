# Editable size distribution

The MIMIBlender texture combiner requires an approved size distribution before
merging. This applies to the panel and to direct `bpy.ops.mimi.combiner` calls.

## Workflow

1. Refresh/select the materials to combine and set source maximum, original
   game canvas minimum, and total atlas maximum as required.
2. Click **Generate Size Distribution**. This resets manual locks and shows
   default allocations for each participating material.
3. Type a material's width or height to automatically mark it **Fixed**.
   Dimensions describe its final content region, excluding texture spacing.
4. Click **Recalculate Size Distribution**. Fixed content sizes stay exact;
   automatic regions are reduced as necessary until a real rectangle layout fits.
5. Only an approved allocation enables **Combine Textures**. Dimensions,
   selection and layout settings are checked cheaply during redraw. UV and
   shader-source changes are checked when combining, and stale plans are
   rejected before any model writes. Canceling the file picker does not
   normalize UVs or delete material slots.

Uncheck **Fixed** for every row sharing that texture to restore automatic
allocation on the next recalculation; a remaining locked peer keeps the group fixed.
If fixed regions cannot fit, lower their dimensions, release a lock, reduce
spacing or increase the total maximum. The planner never silently shrinks locks.

## Semantics

- Automatic defaults retain the existing source-size and UV-repeat calculations.
- UVs that reach past one tile reserve a sampling window, not a whole grid.
  With **Crop to UV Bounds** on (the default) the region is the real per-axis
  extent, so a 2% overshoot costs 2% of a tile. Each row shows its window as
  `[2x2]` beside the name and the panel lists how many rows are tiled.
  Unchecking the option restores the legacy whole-tile power-of-two grid, where
  any overshoot above one reserves a full extra tile in each axis.
- A vertical tiling can therefore produce a portrait atlas. Orientation is not
  forced: rotating the finished canvas would swap approved region positions.
- Manual dimensions override the automatic preference, including its source cap.
  They describe reserved content bounds, not independent stretch axes. The source
  image and repeated UV extent fit proportionally inside those bounds; unused
  right/bottom pixels remain blank. A square inside a 64x388 allocation stays
  64x64, and UV mapping samples only that 64x64 content. After planning, visible
  width/height show actual fitted content (64x64), while hidden reservation fields
  retain the 64x388 box. Repeated recalculation preserves that blank slack instead
  of displaying reserved bounds as if they were stretched image dimensions.
- Source ceilings and per-material custom source limits use one scale for both
  axes. Largest-axis power-of-two reduction never independently rounds the
  second axis or forces the image to fill every reserved pixel.
- PBR channels share the material's content region and UV remapping.
- Materials sharing the same source Image have linked content dimensions.
  Editing one row propagates its requested size and lock to peers on recalculation.
  A later single-row edit supersedes the group's last approved size; conflicting
  new manual requests are rejected instead of being silently overwritten.
- Generation deduplicates equivalent baked outputs before displaying allocations:
  one row, one size control and one packed region per output group. A count beside
  the thumbnail shows shared materials; select the row and expand Shared Materials
  to inspect member names. Membership is cached as material pointers, not rebuilt
  during redraw. Recalculation can split/merge groups when output settings change.
- Equivalent baked outputs share one packed region even with distinct material IDs.
  Different tint, alpha or enabled PBR maps keep separate regions. UV coverage is
  normalized to one window per source image, so peers never disagree about which
  tiles they bake, and materials sharing the source image keep equal dimensions.
- The merge uses stored, approved positions; it does not repack, rotate or resize
  the finished canvas, since those operations could change manual dimensions.
- Legacy custom canvas limits are packing constraints rather than post-resizes.
  The current power-of-two packing search rounds ceilings down and floors up;
  conflicting non-power-of-two strict custom dimensions are rejected.
- Automatic solids retain their preferred small size. A solid can still receive
  a manually fixed size. Padding always lies outside the requested content.
- Preview dimensions can be preserved in a saved blend, but source identity
  changes on reopening require recalculation before another merge.

## Texture identification

Each allocation row shows its cached base-color texture thumbnail instead of a
material sphere. Selecting a row shows a larger preview and the image name below
the list. Preview images are resolved during generation/recalculation only;
redrawing never searches shader nodes, reads pixels or initializes previews.
Packed/generated images without native previews receive a bounded 64-pixel
thumbnail. Solid materials show a read-only color swatch in the list and a
larger selected color preview. The cached color matches the combiner's diffuse
fallback and is stored in linear RGB for Blender's display color widget.
Unavailable image previews retain the material icon.

## Redraw performance

The allocation list is a bounded scrollable UIList, not one layout tree for
all materials. Panel readiness reads only settings, selection IDs and allocation
values. It never reads mesh UV arrays, synchronizes edit meshes, visits polygons
or walks shader nodes. Full fingerprints run during planning and both merge
entry points so faster redraws cannot bypass the source validation gate.

Performance regression: run `tools/test_texcomb_distribution_performance.py`
with the same factory-startup Blender arguments shown below. This test uses a
100,000-polygon mesh and rejects stale UVs through the actual combiner operator.

## Automated checks

Pure Python: `python -m pytest texcomb/tests -q`.

Blender integration (synthetic factory scene only):

```text
blender -b --factory-startup --python-exit-code 1 -P tools/test_texcomb_distribution.py
```

The integration test exercises sixteen materials within 1024 x 1024, fixed
512 x 512 and rectangular hero regions, invalid plans, external UV edits,
spacing, unlocking, legacy custom canvases, actual PNG pixels and final UV spans.
Existing automation that directly invokes the combiner must first call
`bpy.ops.mimi.generate_size_distribution()` and check its result.
