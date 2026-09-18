# YYSLS draw-local cloth bypass

## Behavior

The exporter packages one local replacement asset for every verified shader
variant beside each generated mod INI. It never installs a global ShaderFixes
replacement.

The currently supported variants are:

| Original VS hash | Filter | Local asset | ABI note |
| --- | ---: | --- | --- |
| `ab148fe238420411` | `823114` | `yysls_no_cloth.hlsl` | TEXCOORD0, then TANGENT/BINORMAL |
| `49bf02a13c364cd9` | `823115` | `yysls_no_cloth_49bf02a13c364cd9.hlsl` | TEXCOORD0 and TEXCOORD1, then TANGENT/BINORMAL |

The second hash is the supplied `ShaderFixes/49bf02a13c364cd9-vs_replace.txt`.
It uses the same b0-b3 constant-buffer family, `t11` position-deformation
texture, `t14` historical skeleton map, and `SV_VertexID`-addressed cloth
path as the first shader. It is not safe to reuse the first replacement because
its input signature declares a second UV channel and different register layout.

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

For a supported hash, the parent emits nested `vs == filter` routes. Each
matching route enters the corresponding CustomShader asset; the final route
runs the same shared list with the game's original VS. This keeps both shader
variants draw-local without introducing a global switch or a guessed ABI.

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

Both assets are derived from the supplied decompiled vertex-shader contracts.
Unused constant declarations and unreachable cloth branches are removed.
Explicit constant offsets, bone-row swizzles, tangent safeguards, historical
skeleton sampling, UV channels, and output semantics are preserved.

The first asset still compiles to identical executable DXBC and input/output
signatures when compared with the backed-up working no-cloth replacement. The
second asset compiles independently and has identical input/output signatures
to the supplied `49bf02a13c364cd9` source; its executable necessarily differs
because the t11 cloth reads are intentionally removed. Reflection metadata is
deliberately excluded because unused declarations were removed.

The shader no longer consumes the game's t11 cloth results. It does not stop
the upstream physical simulation, and it does not implement a new solver.
Normal skeletal animation remains enabled.

## Migration from a global replacement

A global `ShaderFixes/ab148fe238420411-vs_replace.txt` or its compiled `.bin`
counterpart would still affect unrelated meshes. Back it up outside the
loader's active ShaderFixes directory before enabling this local approach.
Do not automatically delete arbitrary files from a user's game installation
when exporting a new mod; the exporter only packages its own local asset.

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
python tools/test_yysls_cloth_shader.py --reference <backed-up-vs_replace.txt>
python tools/test_yysls_cloth_shader.py --reference-49bf-signature <49bf-vs_replace.txt>
```

The first command runs eleven tests without Blender, exercising the real
exporter, builder, shared draw helper, both shader routes, and asset packaging.
A small command model checks the emitted conditions but is not an actual
3Dmigoto parser. The shader test compiles both assets on Windows with
System32/d3dcompiler_47.dll without loading the mod loader or modifying a game
process.

In-game acceptance still needs these checks:

- Enable RuiHeXian: target-VS Mod draws use the no-cloth geometry.
- Disable with F6: original geometry and native cloth return.
- Observe an unrelated mesh sharing the target VS: native cloth remains.
- Inspect another pass using a different VS: no custom VS is injected there.
- Toggle object variants and hidden parts: no stale shader selection persists.
- Reload repeatedly and test multiple exported mods for marker conflicts.

This change deliberately does not apply either replacement to unknown VS
hashes. Other passes retain the previous exporter behavior, including any
preexisting cloth or indirect-draw limitations. It does not add per-character
instance selection beyond the existing index-buffer/submesh matches.
