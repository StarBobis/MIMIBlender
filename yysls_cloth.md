# YYSLS native cloth source mapping

The production exporter now uses `games/yysls_cloth_preserve.py`. The older
`games/yysls_cloth.py` and `resources/yysls_no_cloth.hlsl` remain legacy assets;
they are no longer the default YYSLS export path.

## Data contract

MMT retains native VB index addressing, including prefix records. New extraction
JSON declares `YYSLSClothSource` version 1, `preserved-index`, `VertexIdBase: 0`.
Segmented imports add the segment vertex window start, independently of WWMI's
shape-key offset. The importer records each decoded game-space reference position
and source ID in POINT attributes plus an independent reference table.

The exporter builds a separate `YYSLSClothMap` category using the evaluated mesh
and the real unique-output-to-loop map. Each output point has four R32_UINT words:
reference XYZ float bit patterns, followed by its original simulation vertex ID.
UV/hard-normal splits share source identity while keeping distinct output points.
The exporter captures each object's source table before joining and associates
it with evaluated triangles via their draw ownership. A draw without matching
provenance or with positions edited from the imported reference writes
`0xffffffff` in the simulation ID field for its entire range. UV and material
edits that retain the original points can keep cloth. If two draws share a
Blender vertex, different cloth records produce separate exported vertices.

## Runtime

Known main VS `21bcfc11171589cb` uses filter 823116. Known shadow VS
`18939b13d3a1abcf` uses the package-compatible filter 823115. A local CustomShader
binds the map at reserved VS t118 before the shared VB/IB/draw commands, then
explicitly clears t118. No t119 no-cloth marker is emitted. When an enabled mod
matches the IB and draw range, passes without a cloth shader match run the shared
draw list with the original VS and the mod's buffers.

VS c01b8886cbc05321 uses filter 823114 and shares the native cloth template
with 21bcfc11171589cb. Compiling the shared remap with the original c01
constant declarations produced identical executable instructions and shader
signatures. The c01 material-only declaration differences are unused by its VS.
The observed 89f65adb8660822d pass has active cloth and uses filter 823118.
It keeps the original geometry until its replacement ABI can be validated.

The main, c01 and shadow variants treat the sentinel as ordinary skinning.
The main variant bypasses current deformation, tangent reconstruction and
historical deformation together. Mapped draws retain native t11 simulation
and skeleton animation. They address
simulation with the mapped source ID, and transport the decoded edited-reference
minus original-reference position offset through the existing skinning path.
The main pass applies the offset to both current and historical cloth positions.
This preserves the existing simulation topology; it does not rebuild collisions,
constraints or cloth topology for newly created geometry. Simulated normals and
tangent frames remain authoritative for native cloth.

Packed simulation normals and tangent-plane texels require `asuint` before bit
extraction. They are not numeric float values. A captured word `0x009e3fe9` is
approximately `1.45e-38` as float, so numeric integer conversion produces zero.
Normals use three packed bytes; tangent/binormal use signed 16-bit components.
Zero-vector safeguards remain in both shipped shaders.

## Legacy scene recovery

`common/yysls_cloth_map.py::recover_source_ids` intersects source-position and UV
candidates with oriented original triangles until stable. It does not assume
preserved vertex order and refuses any referenced point with ambiguous identity.
It supports suitable unchanged-position/deletion-only legacy meshes, not arbitrary
retopology or edited reference positions. Loose points remain -1 and cannot be
used in exported faces until a source is assigned. Do not infer identity from
nearest positions alone or silently choose one of several coincident points.

On 2026-11-15, the open `LOD0.e92032c5-0` scene was recovered from the supplied
`FrameAnalysis-2026-11-15-202422`: 7158 scene points, 6693 referenced points with
unique IDs, 465 unused points left unmapped, 8339 verified original triangles.
The staged export had 6825 output points and 25017 indices. Its four preexisting
VB/IB files were byte-identical to the user's Mod; only the map, shaders and INI
were added/changed. Scene copies were saved before/after migration without
replacing the user's original file. The user confirmed first that explosion was
removed, then that lighting was normal after the packed-frame decode correction.
This is acceptance for that installation and mesh, not every shader/game build.
No adversarial sub-agent review was requested or performed.

## Reproduction

From this repository:

```text
python tools/test_yysls_cloth.py
python tools/test_yysls_native_cloth_gpu.py
blender --background --factory-startup --python-exit-code 1 --python tools/test_yysls_cloth_map_blender.py -- --capture <FrameAnalysis root>
blender --background --factory-startup --python-exit-code 1 --python tools/test_yysls_blend.py
```

INI tests exercise real generation and serialization, not the loader parser.
WARP tests compile both VS assets and execute their actual packed decode helpers
against an independent signed-word CPU oracle. Blender tests exercise reference
editing, output reordering, UV-style splits, legacy ambiguity rejection, subdivision
rejection and the real 8773-point captured import/export. The initial shader ABI
checks matched the supplied main shader and the retained shadow reference; the
current game acceptance above additionally covers the tested shadow appearance.

## Historical bypass implementation (superseded)

The material below records the older implementation and its historical gates;
its supported-hash table and no-cloth behavior do not describe the current exporter.

# YYSLS draw-local cloth bypass

## Behavior

The exporter packages one local replacement asset for every verified shader
variant beside each generated mod INI. It never installs a global ShaderFixes
replacement.

The currently supported variant is:

| Original VS hash | Filter | Local asset | ABI note |
| --- | ---: | --- | --- |
| `c01b8886cbc05321` | `823114` | `yysls_no_cloth.hlsl` | TEXCOORD0, then TANGENT/BINORMAL |

A custom no-cloth draw requires all of the following:

1. The existing TextureOverride matches the original IB hash, first index,
   and index count of the submesh.
2. The game package's root `$costume_mods` switch is enabled.
3. The original per-object draw conditions allow that object to be drawn.
4. The current VS has one of the exact hashes and filter values in the table.

The parent TextureOverride checks the original VS before assigning any mod
VB, IB, or texture slot. For a matching VS, it invokes one CustomShader for
the submesh. CustomShader installs VS first, then calls a shared CommandList
containing the complete binding and conditional drawing sequence. The
original shader is restored only after that shared list returns.

On another VS, the parent invokes the same shared CommandList directly,
without a shader replacement. Keeping one body prevents the two paths from
drifting in buffer bindings, texture assignments, object conditions or draw
offsets. Per-object texture restoration remains after the object's draw,
inside the shared list and therefore inside the selected shader scope.

For a supported hash, the parent emits a nested `vs == filter` route. A
matching route enters the CustomShader asset; the final route runs the same
shared list with the game's original VS. This keeps the replacement draw-local
without introducing a global switch or a guessed ABI.

Do not revert to a CustomShader around only `drawindexed`: that selects the
shader after submesh and object resources have already been replaced. The
regression suite now checks the active VS at each binding, not just at draw.

The ShaderOverride section contains only hash identification metadata. It
never draws, skips, or replaces anything on unrelated game meshes. Generated
mods opt into duplicate hash markers cooperatively and use the same filter
value for this exact hash. A third-party mod assigning that filter to another
hash, or changing this hash's filter, requires conflict resolution; the
marker is identification metadata, not a globally reserved 3Dmigoto ID.

Disabled costume mods do not execute skip, resource binding, or custom draw
commands in these IB overrides. Intentionally hidden parts still skip their
original draw while enabled, but never invoke a CustomShader.

## Shader contract

The asset is derived from the supplied decompiled vertex-shader contract.
Unused constant declarations and unreachable cloth branches are removed.
Explicit constant offsets, bone-row swizzles, tangent safeguards, historical
skeleton sampling, UV channels, and output semantics are preserved.

It is checked for the absence of `Texture2DArray`, `cVertexDeformType`,
`cDeformationMisc`, and the compiled `tPositionDeformTex` resource. The
remaining t14 historical skeleton-map branch is ordinary motion-vector
skinning, not cloth solving, and is intentionally retained. Reflection
metadata is deliberately excluded because unused declarations were removed.

The shader no longer consumes the game's t11 cloth results. It does not stop
the upstream physical simulation, and it does not implement a new solver.
Normal skeletal animation remains enabled.

## Game update of 2026-11-08

The game recompiled this vertex shader and the hash moved from
`ab148fe238420411` to `c01b8886cbc05321`. It was not rewritten:

* The refreshed capture references `c01b8886cbc05321` and contains neither
  `ab148fe238420411` nor `49bf02a13c364cd9`, so the old variants were dropped
  rather than kept alongside the new one.
* Comparing the new dump against the reviewed `ab148fe238420411` dump leaves
  the 658-line reflection block identical (constant buffers with their
  `[unused]` markers, resource bindings, input and output signatures) and
  every instruction identical except one output write:

  ```hlsl
  // ab148fe238420411
  o8.xyz = r6.yyy ? r2.xyz : float3(10,10,1);
  o8.w   = 1;

  // c01b8886cbc05321
  r2.w    = 1;
  o8.xyzw = r6.yyyy ? r2.xyzw : float4(10,10,1,0);
  ```

  `r6.y` is `VBufferParam.w > -0.001`, so both forms agree whenever that flag
  is set and differ only in the sentinel branch, where TEXCOORD6.w becomes 0
  instead of 1. The asset reproduces the new split exactly.
* The filter value stayed at `823114`. Filters are per hash, so an already
  exported mod and a newly exported one resolve to the same slot and do not
  conflict.
* The input ABI is unchanged apart from the read masks: removing the cloth
  solver is exactly what stops the shader from reading `SV_VertexID`, and that
  shows up as one byte in the input signature's per-component read mask.

The old `49bf02a13c364cd9` variant and its asset were removed with this update.
A game build that still ships either retired hash is not covered by this asset
and needs its own dump and its own variant entry.

## Migration from a global replacement

Global `ShaderFixes/ab148fe238420411-vs_replace.txt`,
`ShaderFixes/49bf02a13c364cd9-vs_replace.txt` and
`ShaderFixes/c01b8886cbc05321-vs_replace.txt` files, or their compiled `.bin`
counterparts, would still affect unrelated meshes. Back them up outside the
loader's active ShaderFixes directory before enabling this local approach.

Every duplicate `[ShaderOverride]` for a supported hash must repeat its
matching `filter_index`. 3Dmigoto keeps one override record per hash and the
last duplicate's filter wins; a later hash-only `VSCheck.ini` section without
`filter_index` collapses `vs` to `1.0`, so the nested routes cannot
distinguish the shaders. The existing generated `VSCheck.ini` must therefore
use the same filter values as the local markers. Do not automatically delete
arbitrary files from a user's game installation when exporting a new mod; the
exporter only packages its own local asset.

For the supplied RuiHeXian installation, migration preserved the original INI
and shader under `D:/MMTCacheFolder/3Dmigoto/YYSLS/backup_local_cloth/`, updated
the three existing submesh overrides, copied the local asset, and removed the
verified backed-up `.txt` replacement from active ShaderFixes. Vertex/index
buffer contents were not changed. The migrated INI's non-comment commands
were compared against production generator output for all three submeshes.

Reload the game package's configuration/shaders (normally F10). If an already
running loader retains the removed global replacement, restart the game.
The current package uses F6 for `$costume_mods`; that variable is supplied by
its root d3dx.ini, not declared separately by every generated mod.

Update the actually installed addon copy first, then save your Blender work
and reload its modules or restart Blender before exporting again. Installed
addon folders may be independent copies rather than links to this checkout;
a restart alone will not copy repository changes into them. The examined
Blender 5.2 installation had old independent copies named MIMIBlender and
MIMIBlenderV1017. Neither copy was silently overwritten during this fix.

An already running Blender may also retain an old Python exporter in memory.
Merely copying the local HLSL beside an INI does not activate it: the INI must
contain ShaderOverride identification, the early VS check, CustomShader, and
the shared binding/draw CommandList.
The reported failure was followed by an on-disk INI in the old format with
no CustomShader invocation; its newly exported draw count of 9654 for part 1
is preserved by the follow-up migration. This observation does not establish
which configuration was loaded at the instant the screenshot was taken.

## Validation

Run from the addon root:

```text
python tools/test_yysls_cloth.py
python tools/test_yysls_cloth_shader.py
python tools/test_yysls_cloth_shader.py --reference-abi <c01b8886cbc05321-vs_replace.txt>
python tools/test_yysls_cloth_shader.py --reference <previous no-cloth asset>
```

The first command runs ten tests without Blender, exercising the real
exporter, builder, shared draw helper, shader route, and asset packaging.
A small command model checks the emitted conditions but is not an actual
3Dmigoto parser. The shader test compiles the asset on Windows with
System32/d3dcompiler_47.dll without loading the mod loader or modifying a game
process.

`--reference-abi` compiles a dumped game shader and requires the input/output
element names, indices, component formats, input slots and declared masks to
match, while reporting the read-mask differences the cloth removal causes.
`--reference` requires byte-identical ISGN/OSGN/SHDR/SHEX and therefore only
holds against an asset from the same build; a recompiled build changes
scheduled instructions without changing the ABI.

In-game acceptance still needs these checks:

- Enable RuiHeXian: target-VS Mod draws use the no-cloth geometry.
- Disable with F6: original geometry and native cloth return.
- Observe an unrelated mesh sharing the target VS: native cloth remains.
- Inspect another pass using a different VS: no custom VS is injected there.
- Toggle object variants and hidden parts: no stale shader selection persists.
- Reload repeatedly and test multiple exported mods for marker conflicts.

This change deliberately does not apply the replacement to unknown VS hashes,
including a future recompile of this shader. Other passes retain the previous
exporter behavior, including any preexisting cloth or indirect-draw
limitations. It does not add per-character instance selection beyond the
existing index-buffer/submesh matches.
