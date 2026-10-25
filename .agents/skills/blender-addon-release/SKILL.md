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
2. Run `.\release.ps1 -Bump -Push -NotesPath tmp\release-notes.txt` (or `-Notes "<description>"`).
   The script is idempotent: it bumps, commits, pushes, packs `git archive` of HEAD into
   `MIMIBlenderV<digits>.zip`, creates the public `v<version>` release, uploads the single
   manual-install asset and checks the wrapper folder, packed version and uploaded size itself.
3. Report the release URL.

## Chinese release notes

A Chinese `-Notes` string passed through a shell can arrive garbled. Write the text into a UTF-8
file (BOM is fine, PowerShell strips it) and pass `-NotesPath` instead; verify afterwards with
`GET /repos/<repo>/releases/tags/v<version>` that `body` has no U+FEFF and the expected characters.

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

## Do not

- Do not use `-Draft` plus a manual promote round trip; the script publishes directly.
- Do not add archive extraction, syntax sweeps, test-suite gates, SHA256 or tag-zipball parity
  checks to the release. Those belong to normal development, not to shipping a version.
- Do not re-run the upload script to fix release metadata: it deletes same-named assets.
