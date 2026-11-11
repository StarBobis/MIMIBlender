# Raw-buffer descriptors for shape keys

Written after fixing `cba6274`, `23a3785` and `bce3fc9`. It records one
D3D11 rule, the three writers that emit raw buffers, and how the fix is
verified without launching the game.

## The rule

`D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS` is only valid when the buffer is
also created with `D3D11_BIND_SHADER_RESOURCE` or
`D3D11_BIND_UNORDERED_ACCESS`. A descriptor such as

```
BindFlags = D3D11_BIND_VERTEX_BUFFER (0x1)
MiscFlags = ALLOW_RAW_VIEWS          (0x20)
```

returns `E_INVALIDARG` (`0x80070057`) from `CreateBuffer` at every size and
stride. `VERTEX_BUFFER | SHADER_RESOURCE` with the same misc flag is accepted,
so a raw result that has to end up in a vertex slot needs both bits.

## Why 3Dmigoto does not save you

`CustomResource::OverrideBufferDesc` (CommandList.cpp) **replaces** the
descriptor flags with whatever the INI section spells, it does not merge them.
It also runs *after* the engine's own raw-view guard inside
`RecreateCompatibleBuffer`, so the guard's `MiscFlags &= ~ALLOW_RAW_VIEWS`
is undone for any resource whose section says `type = ByteAddressBuffer`.

Consequences, in order:

1. `CreateBuffer` fails, the resource pool stores NULL and logs
   `Resource copy failed ...` / `error creating/updating destination resource`.
2. `Resource<DrawIB>Position = ref <null>` assigns NULL to the destination
   (`SetOrDeferResource` with a null source; a custom-to-custom assignment is a
   full copy, so a null source nulls the target).
3. The next frame binds nothing to the slot that resource feeds (a VS preset
   loses `vb0`, a compute preset loses `cs-t0`), so the mesh breaks instead of
   silently ignoring the shape key.

## The three writers

| Writer | Raw result flags | Note |
| --- | --- | --- |
| `common/m_ini_helper.py` (shared) | `vertex_buffer shader_resource` | Used by GF2, GIMI, HIMI, IdentityV, ZZMI, ZZMIDX12, SnowBreak, CPUSkinning, NarakaM, AILIMIT and SRMI. |
| `games/naraka/shapekeys.py`, `games/pgr/shapekeys.py` | `shader_resource` | Consumer is a compute SRV, no vertex slot. |
| `games/yysls_shapekeys.py` | `vertex_buffer shader_resource` | Same combination as the shared writer, plus `array`. |

`common/m_time_position.py` declares file-backed `ByteAddressBuffer` frame
seeds. They are copy sources only, so nothing adds a slot flag later and the
section must spell `bind_flags = shader_resource` itself. The structured seed
used when shape keys exist (`PositionTimeBase`) is fine without bind flags:
structured without SRV/UAV is accepted, unlike raw.

`games/base/sections.py` still declares the compute-path `Position`/`Blend`
as `ByteAddressBuffer` without bind flags. That is legal today only because
`cs-t0 = Resource<DrawIB>Position` is parsed as a reference and adds
`SHADER_RESOURCE` before first use. Keeping that binding is an invariant, not
something the resource section guarantees.

## Verification

`tools/test_shapekey_descriptor_gpu.py` renders the real INI blocks, maps the
flag names back to D3D11 bits and:

- creates every emitted descriptor on a D3D11 device (hardware first, WARP
  fallback, skipped off Windows);
- re-creates the vertex-buffer-only and bind-flag-less variants and asserts
  they still return `E_INVALIDARG`;
- copies a structured accumulator into the emitted descriptor with
  `CopyResource` and reads the bytes back through a staging buffer;
- pins `cs-t0 = Resource<DrawIB>Position` for the compute path.

It proves descriptor validity and copy compatibility only. In-game acceptance
(shape key visible, mesh intact after the first frame, no
`error creating/updating destination resource` in the log) is still required.
