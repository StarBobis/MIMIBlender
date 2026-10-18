---
name: blender-addon-release
description: Publish and verify a MIMIBlender add-on release using the existing archive pipeline and non-destructive draft promotion.
---

# Blender Add-on Release

## Release contract

- The version source is `bl_info.version` in `__init__.py`. Increment the patch independently of MMT.
- The public title is `MIMIBlender <version>`. Preserve `v<version>` tags and `MIMIBlenderV<digits>.zip` asset/wrapper names.
- Explicitly provide the project-mandated fixed body with `-Notes`. Never use the script's historical automatic compare/changelog default.
- Commit and push before packaging. The updater downloads GitHub tag zipballs; unpushed local changes are not an update.
- Keep temporary packages, extracted test roots and logs under `tmp/`. Never touch a live Blender scene or saved preferences during release checks.

## Safe publication

1. Read `release.ps1` and check the latest authenticated release metadata before selecting an unused patch.
2. Update only the version tuple, commit with an English message, and push. Run the existing preflight with `-DryRun -Notes <fixed-body>`.
3. Run `release.ps1 -Draft -Notes <fixed-body>` without another bump. It uses `git archive` and uploads one manual-install ZIP.
4. Verify the archive wrapper, version, all Python syntax and source content. Run skeleton unit/cleanup/settings suites from the extracted package in separate factory-startup Blender processes. Exercise registration steps directly so the fault-tolerant wrapper cannot conceal errors; repeat register/unregister.
5. Verify every remote asset size and SHA256 against the local approved file using an authenticated GitHub API request.
6. Record asset IDs and digests. Promote through `PATCH /repos/StarBobis/MIMIBlender/releases/{id}` with the explicit fixed title/body, `draft: false`, `prerelease: false`, and `make_latest: "true"`.
7. Re-read release metadata and assert public/latest status plus unchanged asset IDs/digests. Do not rerun the upload script merely to promote: it deletes same-named uploads.
8. Download the manual ZIP publicly and verify its exact SHA256. Fetch the updater tag zipball and compare all Python members to the approved manual package. Verify the tag resolves to the pushed version-bump commit.

## Observed pitfalls

- Local `git archive` can export CRLF through Git configuration, while committed blobs and GitHub zipballs use LF. Normalize only CRLF to LF for source-content comparisons; never normalize the ZIP bytes used for integrity hashes.
- A draft asset URL can include an `untagged-*` placeholder. After promotion, refresh release metadata before using `browser_download_url`; cached draft URLs can return 404 even when the real public asset is healthy.
- Keep GitHub tokens in memory. Strip Authorization on redirects to a different host, and use unauthenticated direct public download URLs to prove user accessibility.
- Use a fresh staging directory for each archive test. A failed pre-extraction assertion does not create it; a later failed test does. Do not delete or overwrite a previous test root just to retry.
