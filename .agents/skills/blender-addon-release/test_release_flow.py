"""Source-only release policy regression; never contacts GitHub."""

from pathlib import Path
import re

# Resolve from this file so the check works from either repository root.
root = Path(__file__).resolve().parents[3]
source = (root / "release.ps1").read_text(encoding="utf-8-sig")

# Inspect only the tail after the successful upload, not local preflight checks.
# A header claiming a short flow must not hide a returning verification stage.
marker = 'Write-Ok "uploaded $zipName"'
assert source.count(marker) == 1, "Expected exactly one successful upload marker"
tail = source.split(marker, 1)[1]
for forbidden in ("Invoke-RestMethod", "Invoke-WebRequest", "Get-FileHash", "git ls-remote"):
    assert forbidden not in tail, f"Post-release operation returned: {forbidden}"
assert "Write-Step 'Done'" in tail, "Upload must lead directly to the summary"

# Public metadata is checked in the create/update response before uploading.
# This proves note equality without fetching the published release again.
assert 'name             = "MIMIBlender $releaseVersion"' in source
assert '[string]$release.body -cne $Notes' in source
assert '[string]$release.name -cne "MIMIBlender $releaseVersion"' in source
assert source.index('[string]$release.body -cne $Notes') < source.index(marker)

# Ordinary releases publish immediately; Draft remains an explicit opt-in.
# Do not silently enable automatic commit-history notes in the release request.
assert "draft            = [bool]$Draft" in source
assert not re.search(r"generate_release_notes\s*=\s*\$true", source)
# Strict custom notes must fail before version changes or public mutations.
# Validate actual parameter and guard ordering, not the descriptive header.
assert '[switch]$CustomNotes' in source
assert "if ($CustomNotes) {" in source
assert "[string]::IsNullOrWhiteSpace($Notes)" in source
assert source.index("if ($CustomNotes) {") < source.index("# -- 1. Version bump")
print("PASS release policy: reviewed notes, explicit metadata, published by default, no post-release checks")
