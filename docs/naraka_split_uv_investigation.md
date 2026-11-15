# Naraka P separation and indexed UV investigation

## Scope

Report: one object exports correctly, but separating it into three objects in
the same Submesh appears to corrupt UVs. No affected blend, workspace, generated
Mod, installed add-on version, or in-game capture was available.

## Reproduction

Run from the repository with Blender 5.2:

```text
blender --background --factory-startup --python-exit-code 1 --python tools/test_naraka_split_uv_blender.py
blender --background --factory-startup --python-exit-code 1 --python tools/test_split_draw_ranges_blender.py
```

The new fixture exports three connected quads with discontinuous corner UVs as
one object, then performs actual Edit Mode Selection separation twice. The
three resulting objects are exported into one Submesh in both object orders.
It runs production temporary copying, triangulation, joining, buffer packing,
draw ownership alignment, split-IB assembly, and drawindexed range generation.
Only workspace metadata lookup is replaced by synthetic metadata.

On 2026-11-15 both suites passed (one new test and four existing tests). The new
test compares decoded triangle position/UV pairs through the generated IB,
including each drawindexed span, and checks that source UVs remain unchanged.
It does not compare raw VB ordering: separation can legitimately duplicate
vertices, so equal raw buffers are not a correctness requirement.

## Code observations and limits

`calc_index_vertex_buffer_unified` uses `(packed corner data, vertex index)` as
the uniqueness key. UV data belongs to that packed record. It creates IB and
the category streams from the same ordered records, rather than independently
renumbering each object's UVs.

`DrawRangeUtils.align_buffer_ranges` moves whole triangle index spans and
updates draw counts/offsets. It leaves vertex records unchanged. Split-IB
assembly applies the Submesh's vertex base to its indices; drawindexed uses
an index offset with base vertex zero.

These observations and the synthetic test do not reproduce a UV mismatch
caused solely by P separation on this checkout. They do not establish that
the reported user Mod works. No game runtime, native post-skin evidence,
material/texture binding, modifiers, or historical installed release was
validated by the new fixture. No production behavior was changed.

An affected case should next compare its indexed position/UV pairs before
and after separation. If those match, inspect the generated Naraka vb1
binding, original draw state, and runtime position stream correspondence.
If they differ, retain the source UV layers and exported IB/Position/Texcoord
streams to locate the first mismatch. Avoid changing vertex deduplication
without that evidence, because it also preserves shape-key vertex identity.
