# ZZMI byte color import/export contract

## Explicit-policy follow-up (2026-11-15)

New MMT layouts now declare BYTECOLOR_LINEAR, BYTECOLOR_SRGB,
FLOATCOLOR_LINEAR or FLOATCOLOR_SRGB in BlenderColorType. Import and export
resolve the same pair of Blender storage type and API property. Modern XXMI
standard imports use FLOATCOLOR_LINEAR, which is now the new ZZMI preset
default. Existing storage-only and missing hints retain the legacy fallback
described below; explicit policies always win over the game preset.

BYTECOLOR_LINEAR inherently quantizes values through byte sRGB storage.
It is not a lossless choice for arbitrary linear byte payloads. Existing
user workspaces and saved color layers are not automatically rewritten.
The four-policy Blender regression additionally checks all combinations,
cross-preset independence and rejection of unknown values. This does not
establish game rendering correctness for untested games.

## Custom-layer conversion follow-up

Explicit policies no longer block export solely because a custom model uses
the other Blender storage type. Conversion reads native payload values from
`color_srgb` for BYTE_COLOR or `color` for FLOAT_COLOR, then writes and reads
the configured API on a scratch layer of the destination storage type.
This is numeric payload migration: a native byte value of 128 remains 128
when exported as FLOATCOLOR_LINEAR. It does not infer the API used to author
the source layer or restore values changed by older workflows.

The scratch mesh contains color samples only and is always removed. Source
geometry, layer storage, domain and values remain unchanged, including for
direct parser callers. POINT-domain colors are expanded to face corners.
Matched storage continues using the configured API; legacy metadata keeps
its previous interpretation. Byte destinations necessarily quantize and
clamp values to their representable range.

Seven color tests and nine outline tests pass. The custom-layer test covers
both source storages, POINT/CORNER domains, both opposite-storage target
spaces, native value preservation and scratch mesh cleanup.

The actual saved `belle school.blend` body was also run through production
Generate Mod using a temporary blueprint and a scratch copy of workspace
metadata requiring FLOATCOLOR_LINEAR. Export completed from its original
BYTE_COLOR layer, without changing source geometry, weights or either color
API view. All COLOR bytes match the supplied working Mod; indices, position,
normals, UVs and skinning fields match as well. This body-buffer check does
not reproduce the user's original texture bindings or establish game rendering
correctness. Retained scripts/results: `D:/Dev/SSMT5/tmp/zzmi-holes/`, including
`full-auto-converted/result.json` and `comparison.json`.

See the separate MIMITools manual page
`docs/newbie/MIMIBlender/color-types/color-types.md` for the editable per-game
record, fixed upstream versions and blank entries awaiting investigation.

## Original byte-color investigation

Validated on 2026-11-15 with Blender 5.2.0, starting from MIMIBlender
`346285b`. This is a scoped color fix, not a complete ZZMI compatibility audit.

## Reproduction and evidence

A user-supplied working Mod has 32,475 vertices and 179,292 indices for
`feb1c4cd`. Exporting the current scene before this fix produced identical
indices, positions, normals, UVs and bone indices, but different COLOR RGB
bytes for all vertices. A stored RGB channel of 128 became 55. Alpha stayed
identical. Tangents and weights differed by at most 1.7881393432617188e-7.
Both the working reference and the scene contain zero-weight vertices;
that observation does not establish the cause of the visual holes.

Blender BYTE_COLOR exposes linear RGB through `color` and stored sRGB values
through `color_srgb`. The former is unsuitable for preserving this reference's
byte-domain control values. ZZMI BYTE_COLOR import and export now both use
`color_srgb`. FLOAT_COLOR and other presets retain their previous behavior.
Existing projects imported with the old linear setter may already contain
changed stored bytes; this patch does not infer or rewrite their history.

After the fix, all COLOR bytes match the supplied working reference exactly.
The current Blender session was reloaded and its first exported COLOR changed
from [55,255,0,0] to [128,255,0,0], without editing scene mesh data.

## Verification

Run from any directory, with the executable path adjusted as needed:

```text
blender --background --factory-startup --python-exit-code 1 --python D:/Dev/MIMIBlender/tools/test_zzmi_byte_colors_blender.py
blender --background --factory-startup --python-exit-code 1 --python D:/Dev/MIMIBlender/tools/test_outline_policies_blender.py
```

Three color tests pass: all 256 values through production import/export,
legacy byte-layer export plus another preset's unchanged behavior, and
FLOAT_COLOR preservation. Nine outline policy tests also pass.

Session-only scene copies, comparison scripts and logs are retained under
`D:/Dev/SSMT5/tmp/zzmi-holes/`; they are not portable fixtures or committed
user assets. The committed regression uses synthetic data only.

## Limits

The supplied INI uses MARK sections and the legacy Position-hash skinning
route; it must not be treated as a generated fixture for latest XXMI-Tools.
The online-fetched upstream commit inspected was
`leotorrez/XXMITools@45be554727cb3c79f07cffa810d60073c19f4b3d`.
Its triangulation and four-weight extraction were compared, but no complete
upstream exporter run or Package release audit was performed. MMT metadata
changes are unnecessary for this scoped BYTE_COLOR API correction.
Game rendering of the newly generated Mod still needs user verification;
this evidence proves a color serialization defect, not that the screenshot's
holes have already been resolved. No adversarial sub-agent review was run.
