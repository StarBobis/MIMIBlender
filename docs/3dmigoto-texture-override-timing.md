# 3Dmigoto texture replacement timing and the `persistent` myth

Scope: 3Dmigoto 1.4.9 as vendored under `tmp/3dmigoto-src` (bo3b/3Dmigoto,
`version.h` = 1.4.9) and the XXMI 1.9.2 packages under
`D:\Softs\XXMI-Launcher-Portable-v1.9.2`.

## Symptom

A generated mod is correct, but every time a character is switched in, the
model shows a wrong/garbled texture for about a second and then becomes
correct. The mesh itself is right immediately.

## The claim under test

A widely repeated answer says the root cause is a texture resource missing
`persistent = true`, i.e.:

```ini
[Resource-Diffuse]
filename = Textures/diffuse.dds
persistent = true      ; claimed to keep the texture resident
```

## Evidence that `persistent` is not a 3Dmigoto ini key

1. Resource sections are parsed by `ParseResourceSections()`
   (`tmp/3dmigoto-src/DirectX11/IniHandler.cpp:1745-1835`). It reads exactly
   these keys: `filename`, `max_copies_per_frame`, `type`, `mode`, `format`,
   `width`, `height`, `depth`, `mips`, `array`, `msaa`, `msaa_quality`,
   `byte_width`, `stride`, `width_multiply`, `height_multiply`, `bind_flags`,
   `misc_flags`, plus `data` from `ParseResourceInitialData()`
   (`IniHandler.cpp:1602-1610`). There is no persistence key.
2. The only persistence keyword in 3Dmigoto is `persist`, and it belongs to
   `[Constants]` variables: `global persist $some_persistent_variable = 1`
   (documented in `tmp/3dmigoto-src/Dependencies/d3dx.ini:300-303`), saved to
   `d3dx_user.ini`. It has nothing to do with resource lifetime.
3. A resource section is not a command list section, so an unknown key there
   is not even reported: the parser simply never reads it. Adding
   `persistent = true` is a silent no-op.
4. String analysis of the shipped GIMI `d3d11.dll`
   (`D:\Softs\XXMI-Launcher-Portable-v1.9.2\GIMI\d3d11.dll`, 2,906,624 bytes)
   finds `persistent` exactly twice: once as the ASCII text of the generated
   `d3dx_user.ini` header ("...whenever any persistent settings are altered
   by hot key or command list...") and once as the wide log format string
   `3DMigoto analyse_options (persistent): %08x`. Neither is a key name.

Conclusion: the recipe in circulation cannot be the reason the symptom
disappears. Any observed improvement after adding it came from something
else in the same session (warm file cache, another edit, an ini reload).

## What actually happens

Two independent match triggers are involved, and only one of them follows
the mod's timing.

### Mesh replacement follows the draw

`[TextureOverride_LOD0.<hash>_<n>]` with `hash = <shader hash>` and
`match_first_index = <n>` is evaluated against the draw call itself, so the
replacement index buffer is in place on the very first frame the game draws
that mesh.

### Hash texture replacement follows the game's binding

A hash-style replacement is a `[TextureOverride]` section whose `this =`
names a custom resource. The substitution is resolved when a command list
line references the slot, by looking up overrides for **the resource the game
currently has bound there**:

- `ResourceCopyTarget::FindTextureOverrides()` calls
  `find_texture_overrides_for_resource(resource, matches, ...)`
  (`CommandList.cpp:6242-6264`).
- The match key is the hash 3Dmigoto stored when the game created that
  texture (`HackerDevice::CreateTexture2D` -> `process_texture_override`,
  `HackerDevice.cpp:2044-2112`).

So a hash replacement can only fire once the game binds a texture whose hash
equals the captured one. `ps-t0 = Resource...` written directly in the draw
section has no such dependency: it forces the custom resource into the slot
regardless of what the game bound.

### Custom textures are loaded lazily, inside the draw

`CustomResource::Substantiate()` states it explicitly: "If the resource
section has enough information to create a resource we do so the first time
it is loaded from" (`CommandList.cpp:4384-4396`), and the DDS read plus GPU
upload happens there (`CommandList.cpp:4455-4511`). There is no preload and
no time-based unloading: `CustomResource::expire()` only handles a device
mismatch (`CommandList.cpp:5079-5132`).

### Why the owner sees "garbled for a second, then normal"

On a character switch the game streams its own textures; the first frames of
the new character are drawn while the slot still holds the previous or a
placeholder texture. The mesh is already the mod's (draw match), the texture
is not (hash still unmatched), so the mod model renders with the game's
foreign texture for that moment - which reads as garbage because the mod
geometry/UVs no longer correspond to it. As soon as the game binds the
captured texture, the `this =` substitution fires and the model looks right.

## The correct substitution

Bind the replacement at draw time, in the object's own draw section, and keep
the hash section only as a fallback for other consumers of the same texture:

```ini
[TextureOverride_LOD0.94517393_0]
hash = 94517393
match_first_index = 0
ps-t0 = ResourceDiffuse          ; ours, independent of the game's binding
ib = ResourceIndex
drawindexed = 12345,0,0
```

XXMI's own core states the same direction. `ZZMI\Core\ZZMI\main.ini:559-578`
keeps its hash-based normal map override only as a compatibility shim and
marks it: "This temporary fix should be removed once mods have been
transitioned over to slots". The newer `Libraries\SlotFix\SlotFix.ini` binds
`ps-tN = ref Resource\ZZMI\...` inside command lists, i.e. by slot.

## Where the generator stands (MIMIBlender)

- Slot / SharedSlot marks already produce `[Resource-XXX]` sections that the
  draw section binds with `ps-tN = ...` (`model/drawib_model.py:450-...`,
  `common/m_ini_helper.py:862`).
- Hash marks go through `M_IniHelper.generate_hash_style_texture_ini()`
  (`common/m_ini_helper.py:680-859`), which writes one resource plus one
  global `[TextureOverride_Texture_<hash>] ... this = ...` section and never
  binds the slot in the draw. The captured `MarkSlot` is available on the
  mark but is not used by that path.

That is the defect behind the reported symptom: the automatic hash pipeline
depends on the game's binding timing, while the slot pipeline does not.

Candidate fix (not applied yet, because it changes every generated mod and
must be verified in game):

1. In `generate_hash_style_texture_ini()` (and the global hash generator at
   `common/m_ini_helper.py:349-622`), when the mark carries a usable
   `MarkSlot`, also register a per-object slot binding for the owning draw so
   `ps-tN = <resource>` is emitted before that object's `drawindexed`
   (with the existing restore-after-draw machinery).
2. Keep the hash section unchanged as the cross-object fallback.
3. Add a regression test that asserts both lines exist for one hash row.

## Verification plan

- In game: switch the character in and watch whether the first frames are
  already the mod texture.
- `d3d11_log.txt`: `Loading custom texture resource` shows when the lazy
  load actually ran; `matched resource with hash=` (HackerDevice.cpp:2086)
  shows which frame the hash override fired on.
