---
name: blender-addon-release
description: Publish a MIMIBlender add-on release: bump the version, package with the existing archive pipeline, publish with a short description.
---

# Blender Add-on Release

## Release contract

- The version source is `bl_info.version` in `__init__.py`. Increment the patch independently of MMT.
- The public title is `MIMIBlender <version>`. Preserve `v<version>` tags and `MIMIBlenderV<digits>.zip` asset/wrapper names.
- The release body is a short description passed with `-Notes`. Default body: `修复了部分已知问题`.
  Never use the script's automatic compare/changelog default.
- Commit and push before packaging. The updater downloads GitHub tag zipballs; unpushed local changes are not an update.

## Release steps (this is the whole flow)

1. Update only the version tuple in `__init__.py`, commit `chore(release): version X.Y.Z`, push.
2. Run `.\release.ps1 -Notes "<description>"`.
   The script is idempotent: it packs `git archive` of HEAD into `MIMIBlenderV<digits>.zip`,
   creates the public `v<version>` release, uploads the single manual-install asset and
   checks the wrapper folder, packed version and uploaded size itself.
3. Report the release URL.

## Do not

- Do not use `-Draft` plus a manual promote round trip; the script publishes directly.
- Do not add archive extraction, syntax sweeps, test-suite gates, SHA256 or tag-zipball parity
  checks to the release. Those belong to normal development, not to shipping a version.
- Do not re-run the upload script to fix release metadata: it deletes same-named assets.
