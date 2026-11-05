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

1. Start from a clean worktree. Do not manually bump the version before using `-Bump`.
2. Run `.\release.ps1 -Bump -Push -NotesPath tmp\release-notes.txt` (or `-Notes "<description>"`).
   The script bumps only the version tuple, commits `chore(release): version X.Y.Z`, pushes,
   packs `git archive` of HEAD into `MIMIBlenderV<digits>.zip`, checks the local wrapper/version,
   creates the public `v<version>` release, checks title/body in the create/update response,
   uploads the single manual-install asset, and finishes immediately on upload success.
   If the version was already bumped by a failed run, retry without `-Bump`.
3. Report the release URL. Do not add post-release asset, hash, tag or update-channel checks.

## Chinese release notes

A Chinese `-Notes` string passed through a shell can arrive garbled. Write the text into a UTF-8
file (BOM is fine, PowerShell strips it) and pass `-NotesPath` instead. The script trims the
input and checks the exact body in the create/update response before uploading. Do not
fetch the published release again just to check its notes.

## Token precedence trap

`release.ps1` resolves a token from `MIMI_GITHUB_TOKEN` -> `GH_TOKEN` -> `GITHUB_TOKEN` -> the git
credential helper. A stale `GITHUB_TOKEN` in the environment therefore shadows a perfectly valid
credential-helper token and the preflight dies with `401 Bad credentials`. Check the three
variables first; either clear them or run the script with `MIMI_GITHUB_TOKEN` set to the helper's
token:

```powershell
$raw = ("protocol=https`nhost=github.com`n`n" | git credential fill) 2>$null
$env:MIMI_GITHUB_TOKEN = ($raw | Where-Object { $_ -like 'password=*' } | Select-Object -First 1).Substring(9).Trim()
```

`gh auth status` may report "Bad credentials" while `git push` still works: the two use different
credential stores, and push success alone does not mean the Release API is reachable.

## Source-only flow regression

After editing the release script, run `python .agents/skills/blender-addon-release/test_release_flow.py`.
It checks the actual script tail, explicit response metadata checks and published-by-default
behavior without querying GitHub. Keep the script header and body aligned; a stale tail
can otherwise reintroduce remote asset/hash/tag checks after a successful upload.

## Do not

- Do not use `-Draft` plus a manual promote round trip; the script publishes directly.
- Do not add archive extraction, syntax sweeps, test-suite gates, SHA256 or tag-zipball parity
  checks to the release. Those belong to normal development, not to shipping a version.
- Do not re-run the upload script to fix release metadata: it deletes same-named assets.
