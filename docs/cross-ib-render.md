# Cross-IB rendering (Naraka / GF2 / PGR)

Status labels used here: **verified** (reproduced from the current source or a
committed test), **hypothesis** (consistent with the code but not observed),
**unverified** (no evidence either way).

## What the feature actually moves

A cross-IB pair moves where a draw call is *issued*, not which index buffer it
uses. The guest's `drawindexed` lines are removed from the guest Submesh
section and appended to the host Submesh section, so the guest geometry is
rendered while the host's pixel shader and textures are bound. Every draw still
binds its own index buffer (`ib = <guest IB>`).

**Verified**: `games/naraka/exporter.py` (`add_naraka_cs_texture_override_ib_sections`),
`games/gf2/exporter.py` (`add_unity_vs_texture_override_ib_sections`), and the
INI text asserted by `tools/test_naraka_cross_ib_blender.py` and
`tools/test_gf2_cross_ib.py`.

Consequence: the name "cross-IB" is a modder shorthand. What crosses is the
TextureOverride section.

## Why the vertex-buffer backup exists

A guest's vertex buffers are only bound while the game draws that guest. By the
time the host section runs, `vb0..vbN` point at the host's buffers. The guest
section therefore ends with one `ref` line per slot:

```ini
Resource_LOD0_200_0_BK_VB0 = ref vb0
```

and the host section restores them right before re-emitting the guest draw:

```ini
ib = Resourced58050d1_LOD0-200-0_IB
vb0 = Resource_LOD0_200_0_BK_VB0
vb2 = Resource_LOD0_200_0_BK_VB2
```

The backup resources are declared with no `type` and no `filename`; 3Dmigoto
fills them from the live binding at run time.

**Verified**: generated INI of `tools/test_gf2_cross_ib.py` (structure, ordering,
resource declarations).

## Per-preset slot list

| preset | slots backed up | why |
| --- | --- | --- |
| Naraka | `vb0`, `vb1` | Its compute path writes the skinned position into the game's own VB and replaces the texcoord stream; the blend data never reaches the final draw. |
| GF2 (GPU types) | `vb0`, `vb1`, `vb2` | The blend stream (BLENDWEIGHTS/BLENDINDICES) has its own slot and the game's own skinning reads it. |
| GF2 (CPU-drawn types) | `vb0` | The whole vertex stream lives in one slot. |
| PGR | `vb0`, `vb1` | Its compute path has the same position/texcoord backup shape as Naraka, while the exporter remains PGR-branded. |

The list is derived from the game type
(`GF2Exporter.get_cross_ib_backup_slot_list`), not hard-coded, so a type with a
different slot split works without editing the exporter.

**Verified**: `tools/test_gf2_cross_ib.py` asserts all three slots for a GPU
type and exactly one for a CPU type.

PGR uses the shared blueprint post-processor and its own exporter copy.
**Verified**: `tools/test_pgr_preset.py` checks the generated PGR host/guest
sections, and `tools/test_naraka_cross_ib_blender.py` checks that PGR reaches
the shared node path.

## Constraints the exporter enforces

- The host object must be part of the export and must map to exactly one
  Submesh (`collect_cross_ib_host_entries`, `_resolve_host_submesh_name`).
- A Submesh that takes part in a pair cannot be Skip Draw: its section would
  never run, so the backup would stay empty (`common/skip_draw.py`).
- Two requests for the same draw with different hosts abort the export
  instead of leaving half the draws rewritten.

## Unverified / hypotheses

- **Hypothesis**: the host draw must be issued after the guest draw in the same
  frame. The backup is filled by the guest section, so a host that is drawn
  first would restore an empty resource on the first frame. No capture was
  taken to confirm the draw order.
- **Unverified**: how a GF2 host shader behaves when the guest uses a different
  `vb1` variant (28 / 24 / 20 bytes). The host's input layout reads the guest's
  buffer, so a mismatched element layout should produce wrong UVs or normals.
  Nothing in code prevents such a pair today.
- **Unverified in game**: none of this change was run in either game. The
  regression tests only prove the generated INI.

## Acceptance

```text
python tools/test_gf2_cross_ib.py
python tools/test_pgr_preset.py
blender -b --factory-startup --python-exit-code 1 --python tools/test_naraka_cross_ib_blender.py
```

In-game check, still outstanding: build a two-Submesh mod with one pair and
confirm the guest appears at the host's draw with the host's material and its
own silhouette.
