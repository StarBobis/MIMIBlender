# ZZMI byte color import/export contract

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
