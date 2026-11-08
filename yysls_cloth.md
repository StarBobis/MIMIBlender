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
