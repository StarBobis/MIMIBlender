# Texture Combiner Refactor Plan: Precise Alpha-Channel Merging (texconv-assisted)

> Status: design proposal. No code changed yet.
> Scope: the `texcomb/` module (fork of Grim-es/material-combiner-addon).

---

## 1. Defect Analysis of the Current Implementation

### 1.1 Pixel acquisition layer (the root of most bugs)

The pipeline never reads pixels from Blender. Instead it grabs **encoded file
bytes** and decodes them with Pillow:

- `texcomb/utils/images.py:27` `get_packed_file()` calls `image.pack()` and
  returns `image.packed_file.data`.
- `combiner_ops.py:707` decodes with `Image.open(io.BytesIO(packed_file.data))`.

Consequences:

1. **Side effect on the user's .blend**: `image.pack()` embeds the texture into
   the blend file just to read its bytes. The user's file grows silently.
2. **Unreadable image classes fall back to solid color**: generated/baked
   images (no `filepath`), unsaved images, viewer-node placeholders, UDIM
   tiles, and the excluded `.spa/.sph` formats all produce *no* packed file,
   so the material is silently downgraded to a solid-color square
   (`combiner_ops.py:319-321`).
3. **Decoding coverage is limited to Pillow's codecs.** Pillow 12.3 reads
   DXT1/3/5 and BC1–BC7, but:
   - cannot read float/HDR DDS (`R16G16B16A16_FLOAT`, `R32*`), `_SNORM`
     variants lose their signedness, and any future DXGI format is unsupported;
   - cannot **write** BC7, cannot set the sRGB DXGI flag, cannot choose the
     DXGI format at all, and cannot generate mipmaps.
4. **Colorspace is ignored.** Albedo is sRGB, normal/mask maps are linear, but
   everything is treated as raw 8-bit bytes. Resizing (LANCZOS) is performed in
   sRGB space instead of linear space — mathematically wrong, visible as
   darkened edges after downscaling. The diffuse-color multiply
   (`ImageChops.multiply`, `combiner_ops.py:716`) also happens in sRGB space.
5. **8-bit quantization happens too early and repeatedly.** `resize()` then
   `thumbnail()` then paste — every step re-quantizes to 8-bit. "Precise" is
   not achievable in this design.

### 1.2 Alpha handling (the feature the user wants to extend)

- `combiner_ops.py:722` `_apply_alpha_texture()` uses `img.putalpha(alpha_img)`
  — it **overwrites** the base texture's own alpha channel. Game DDS textures
  frequently store a data mask in alpha (this repo's own code says so:
  `common/mesh_create_helper.py:683` — "DDS/PNG/TGA preserve the alpha masks
  consumed by the GIMI shader"). The mask is destroyed when a separate alpha
  texture exists.
- Only **Principled BSDF** is supported: `utils/materials.py:442`
  `_get_alpha_socket()` hard-requires `"principled" in shader_type`. MMD,
  MToon/VRM and XNALara materials silently lose alpha.
- Source-channel selection is implicit and lossy: if the link comes from the
  image's `Alpha` output, channel A is used; otherwise the code does
  `convert("L")` (`combiner_ops.py:738`), an ITU-R 601-2 luma mix
  (0.299/0.587/0.114). A mask stored in the R channel of a data texture gets
  blended with G/B — corrupted.
- When the *same* DDS provides both base color and alpha (the standard
  embedded-alpha wiring), the behavior depends on which output socket the
  artist happened to link — invisible, fragile semantics.
- RGB and alpha are resized along **different code paths and in different
  order** (`_get_gfx` resizes then multiplies then applies alpha;
  `_apply_alpha_texture` resizes separately), so alpha can end up
  misaligned with RGB by rounding differences.
- **Semantics of the output alpha are contradictory**: the generated material
  links atlas-alpha into the BSDF Alpha input with `blend_method = "CLIP"`
  (treated as transparency, `combiner_ops.py:1094-1099`), while
  `_mark_channel_packed()` sets `alpha_mode = "CHANNEL_PACKED"` (treated as
  data, `combiner_ops.py:1077-1084`). The pipeline cannot decide whether alpha
  is coverage or data.
- There is **no user-controlled "extra alpha channel merge"**: you cannot say
  "take RGB from base.dds and A from mask.dds (or base-A × mask-R)". The
  current behavior is an incidental side effect of node wiring.

### 1.3 Output layer

- Only PNG/TGA/TIFF/BMP are written (`combiner_ops.py:966-1000`,
  `extend_types.py:56-64`). The modding pipeline this addon feeds needs DDS
  with a specific DXGI format encoded in the file name, e.g.
  `{hash}_{name}-R8G8B8A8_UNORM_SRGB.dds` (`workspace/ssmt_workspace.py:861`,
  `workspace/texture_metadata_helper.py:20`). The combiner's output cannot
  enter the pipeline without manual conversion.
- No mipmap generation, no DXGI format control, no sRGB flag control.
- The result is saved to disk and re-loaded with `bpy.data.images.load()`
  (`combiner_ops.py:1023`) — a disk round-trip just to build the material.

### 1.4 Architecture / maintainability

- `combiner_ops.py` is 1258 lines of functions mutating a bare nested dict with
  string keys (`"gfx"/"fit"/"uv"/"size"/"img_or_color"` — schema defined inline
  at `combiner_ops.py:243-262`). Passes mutate it in place:
  `get_structure` → `get_size` → `pack` → `get_atlas`. There are no dataclasses
  and no single place that documents the data shape.
- Dead/buggy sorting: `_size_sorting()` (`combiner_ops.py:367-388`) uses
  `gfx["img_or_color"]` as its 4th key, but that field is only populated later
  inside `get_atlas()` (`_set_image_or_color`, `combiner_ops.py:611`), so the
  key is always `None` at sort time. The intended deterministic ordering is
  never realized; a future `None` vs `tuple` comparison here would raise
  `TypeError`.
- `align_uvs()` (`combiner_ops.py:780-822`) encodes the Y-flip as
  `uv.y = uv_y * scaled_height + 1` with a `- gfx_height` offset — magic
  constants instead of an explicit "flip V" step; hard to verify.
- Module-level side effects: `initialize_pillow()` runs at import time
  (`combiner_ops.py:98`) and sets `Image.MAX_IMAGE_PIXELS = None` globally.
- Legacy Blender paths are dead code: `globs.py:85-88` hard-codes
  `is_blender_legacy = False`, yet every hot function keeps an
  `if is_blender_legacy` branch (e.g. `_get_image`, `_set_image_or_color`,
  `_configure_material_legacy`).
- Image math is intertwined with `bpy`, so nothing is unit-testable outside
  Blender.
- Error handling is `except Exception` + a diagnostic string, capped at 5
  warnings — real failures are easy to miss.
- The repo vendors all of Pillow plus a 1.9 MB `get-pip.py`
  (`texcomb/libs/`, `texcomb/operators/get-pip.py`); `improvement-plan.md`
  already lists the install flow as too crude.

---

## 2. Redesign Goals

1. **User-controlled extra-alpha merging** (the headline feature).
2. **Precision first, speed irrelevant**: float32 intermediates, single final
   quantization, linear-space filtering, controlled DDS encoding.
3. **Simple to understand and maintain**: a linear pipeline of small stages,
   plain dataclasses, pure-Python core that is unit-testable without Blender.
4. **External `texconv.exe` is a first-class citizen**: precise DDS encode and
   universal DDS decode fallback.

---

## 3. Target Architecture

A linear pipeline. Each stage has one job, takes plain data in, returns plain
data out. Only the two thin "blender" adapters touch `bpy`.

```
[1 Collect]  bpy material nodes  -> MaterialSource (dataclass)
[2 Decode]   image sources       -> float32 numpy RGBA planes
[3 Plan]     MaterialSource      -> ChannelPlan (per-channel sources)
[4 Layout]   sizes + packers     -> placements (reuse existing packers)
[5 Compose]  planes + placements -> float32 atlas canvas
[6 Encode]   canvas              -> PNG/TGA directly, DDS via texconv.exe
[7 Rebind]   placements          -> remapped UVs, rebuilt materials (bpy)
```

### 3.1 Directory layout (all lowercase)

```
texcomb/
  core/                     # pure python + numpy, NO bpy — pytest-able
    models.py               # dataclasses: MaterialSource, ChannelSource,
                            #   ChannelPlan, Placement, AtlasPlan, AtlasResult
    decode.py               # bytes -> float32 RGBA (Pillow), texconv fallback
    pixels.py               # float32 ops: linear resize, tile, paste, multiply
    channels.py             # alpha merge strategies (the new feature)
    layout.py               # size calculation + adapter over utils/packers
    atlas.py                # compose the float32 canvas from placements
    export.py               # write PNG/TGA; invoke texconv.exe for DDS
    texconv.py              # locate/run/verify texconv.exe (subprocess wrapper)
  blender/                  # thin bpy adapters only
    collect.py              # node-tree reading -> MaterialSource
    rebind.py               # UV remap + material rebuild
  operators/combiner/combiner.py   # orchestrates stages, no image math
  tests/                    # plain pytest, runs outside Blender
```

### 3.2 Pixel acquisition: read decoded pixels, not file bytes

New priority order in `core/decode.py` + `blender/collect.py`:

1. **Primary: `image.pixels` (float32, already decoded by Blender).**
   Blender/OIIO decodes DDS/EXR/TIFF/PSD/... for us. This fixes, in one move:
   - generated/baked images (no filepath) now work;
   - no `image.pack()` side effect on the user's blend;
   - no dependence on Pillow's codec list.
   The image's `colorspace_settings.name` decides the treatment: sRGB images
   are converted back to sRGB at encode time; `Non-Color` images are passed
   through untouched. Alpha is **always** treated as linear data and never
   color-converted.
2. **Fallback: texconv decode.** If Blender cannot load the file (rare, e.g.
   exotic DXGI), run `texconv.exe -ft PNG -f R32G32B32A32_FLOAT <file>` (or
   16-bit PNG) into a temp dir and read the result. texconv understands every
   DXGI format, so the fallback is universal.
3. Pillow remains only as an optional decoder for ordinary PNG/TGA bytes when
   a `PackedFile` is the only thing available — no longer on the critical path.

### 3.3 Intermediate representation: float32 numpy planes

- Every source becomes an `numpy.ndarray` of shape `[H, W, 4]`, float32,
  linear. All math (resize, tile, paste, diffuse multiply, alpha merge)
  happens in float32.
- **Resize in linear space**: sRGB sources go sRGB→linear, are filtered, and
  go back to sRGB exactly once at encode time.
- One separable-filter resampler (box / bilinear / lanczos3) implemented in
  ~60 lines of numpy in `core/pixels.py`. Slow is acceptable; deterministic
  and precise is the requirement. Normal maps are renormalized after resize.
- **Single final quantization**: only `core/export.py` converts float32 →
  8/16-bit, once.

### 3.4 Channel-merge model (the extra-alpha feature)

`core/models.py`:

```python
# NOTE: keep real code comments in English (repo rule).
@dataclass
class ChannelSource:
    kind: str          # "image_channel" | "constant"
    image_key: str     # which decoded plane to read ("" for constant)
    channel: str       # "R" | "G" | "B" | "A" | "LUM" | "ONE"
    scale: float = 1.0 # constant value when kind == "constant"

@dataclass
class ChannelPlan:
    r: ChannelSource
    g: ChannelSource
    b: ChannelSource
    alpha_mode: str        # "embedded" | "separate" | "multiply" | "opaque"
    alpha: ChannelSource   # used by "separate"/"multiply"
```

Per-material user choice (`alpha_mode`):

| Mode       | Resulting A                                | Use case                              |
|------------|--------------------------------------------|---------------------------------------|
| `embedded` | base texture's own A (default, = today)    | DDS already carries the mask          |
| `separate` | chosen channel of a second image           | base.dds has no alpha, mask.dds has it |
| `multiply` | base-A × second-image channel              | two stacked masks                     |
| `opaque`   | constant 1.0                                | strip alpha explicitly                |

`blender/collect.py` auto-detects the default: if the Principled Alpha input
is linked to an image, propose `separate` with the *actual linked output
socket's* channel (no more hidden luma conversion); otherwise `embedded`.
All four channels are resized **together** on the same float32 plane, so RGB
and A can never drift apart. `core/channels.py` is ~80 lines and fully
unit-tested with synthetic 2×2 patterns.

### 3.5 Encode via texconv.exe

`core/texconv.py`:

- Locate: addon preference path → `TEXCONV_PATH` env var → bundled
  `texcomb/tools/texconv.exe`. Not found → degrade to PNG/TGA with a clear
  warning (and on non-Windows, always degrade).
- Flow: export the float32 canvas once to a lossless 16-bit PNG in a temp dir,
  then `subprocess.run([texconv, "-f", fmt, "-m", mips, "-y", "-o", out, src])`.
- User-facing options: DDS pixel format enum (`R8G8B8A8_UNORM_SRGB` default —
  matches the WWMI naming convention, `R8G8B8A8_UNORM`, `BC7_UNORM_SRGB`,
  `BC7_UNORM`, `BC3_UNORM_SRGB`) and mipmap count (default 0 = full chain).
- Verify after conversion: output file exists, is non-empty, and (cheap check)
  has the expected width/height in its DDS header. Report precisely on failure.

### 3.6 Maintainability cleanups (bundled into the refactor)

- Replace the nested string-key dict with the dataclasses above; each pipeline
  stage is one pure function.
- Fix or drop the dead 4th key in `_size_sorting`.
- Rewrite `align_uvs` as explicit steps: scale → place → flip V
  (`v = 1.0 - v`) with no magic `+1`.
- Delete the `is_blender_legacy` branches (hard-coded `False` today).
- No import-time Pillow initialization; decode backends load lazily.
- Errors become typed results (`AtlasResult.errors: list[str]`) surfaced in
  full, not capped warnings.
- `texcomb/tests/`: golden-image test for a tiny atlas (allowed to be slow,
  runs texconv when present), round-trip sRGB↔linear error < 1/255, channel
  merge truth tables, UV-remap unit tests.

### 3.7 Migration plan (incremental, releasable at every step)

1. **Phase 0 — baseline**: this document + snapshot tests of current behavior.
2. **Phase 1 — core extraction**: move image math into `core/` unchanged in
   behavior; old `combiner_ops.py` becomes a thin shell. All existing tests
   (if any) and manual QA still pass.
3. **Phase 2 — channel model**: introduce `ChannelPlan` + the alpha-mode UI;
   float32 pipeline replaces the 8-bit Pillow path.
4. **Phase 3 — texconv**: DDS output + decode fallback; degrade gracefully.
5. **Phase 4 — cleanup**: remove legacy branches, dead sorting key, import-time
   side effects; finalize docs.

---

## 4. What "precise" means here (acceptance criteria)

- float32 intermediates end-to-end; exactly one 8/16-bit quantization at export.
- sRGB filtering done in linear space; alpha never color-converted.
- RGB and A always resized in the same operation on the same plane.
- DDS written exclusively by texconv with explicit `-f` format and `-m` mips;
  output verified after conversion.
- Deterministic packing order (fix the sort key) so identical inputs produce
  byte-identical atlases.
