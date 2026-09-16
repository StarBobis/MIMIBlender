#!/usr/bin/env pwsh
<#
.SYNOPSIS
    MIMIBlender one-command release: bump version -> zip add-on -> GitHub Release -> upload zip.

.DESCRIPTION
    Automates the release flow for this Blender add-on repository:

      1. Preflight: run from repo root, clean worktree, valid bl_info version,
         remote tag not taken yet, GitHub token available.
      2. (-Bump / -Version) Write the new version into bl_info in __init__.py,
         commit it, and (with -Push) push it to origin. The push is mandatory
         before publishing, because GitHub builds the tag (and the zipball the
         add-on updater downloads) from the REMOTE branch, not local files.
      3. Pack the add-on with `git archive` so the zip matches every existing
         release exactly: one wrapper folder "MIMIBlenderVxxxx/" containing all
         git-tracked files (no .git, no __pycache__, no *_updater staging).
      4. Create (or update) the GitHub Release tagged "vX.Y.Z" with the same
         "Full Changelog" compare link GitHub itself generates.
      5. Upload "MIMIBlenderVxxxx.zip" as the single release asset
         (idempotent: an existing asset with the same name is replaced).
      6. Verify: asset present with matching size, tag visible on the remote.

    Naming rules (identical to every existing release, e.g. v1.0.12):
      tag / release name : v1.0.12
      asset file name    : MIMIBlenderV1012.zip  ("MIMIBlenderV" + version digits)
      zip inner folder   : MIMIBlenderV1012/     (same base name as the zip)

    Note: addon_updater.py installs updates from the tag zipball (use_releases
    = False, select_link uses tag["zipball_url"]), so a non-draft release - and
    the tag GitHub creates with it - is what publishes the update to users.
    The uploaded zip asset is the manual-install package only.

.PARAMETER Bump
    Increment the patch component of the bl_info version (1.0.12 -> 1.0.13).

.PARAMETER Version
    Set an explicit X.Y.Z version instead of -Bump. Mutually exclusive.

.PARAMETER Push
    Push the version-bump commit (and any already-committed local work) to
    origin before publishing. Required whenever local HEAD is ahead of origin.

.PARAMETER Draft
    Create the release as a draft instead of publishing it directly.
    Re-run without -Draft (same version) to promote it to published.

.PARAMETER DryRun
    Run preflight only: shows what would be released, changes nothing.

.PARAMETER Notes / NotesPath
    Custom release body (inline text or a UTF-8 file). Default: the usual
    "**Full Changelog**: <compare link>" line, same as past releases.

.EXAMPLE
    # Bump patch version, commit+push, publish release v1.0.13
    .\release.ps1 -Bump -Push

.EXAMPLE
    # Publish an explicit version
    .\release.ps1 -Version 1.1.0 -Push

.EXAMPLE
    # Preflight only, change nothing
    .\release.ps1 -Bump -DryRun
#>
[CmdletBinding()]
param(
    [switch]$Bump,
    [switch]$Push,
    [switch]$Draft,
    [switch]$DryRun,
    [string]$Version,
    [string]$Notes,
    [string]$NotesPath,
    [string]$Repo = 'StarBobis/MIMIBlender'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# -- Constants ---------------------------------------------------------------
# The add-on entry point holding bl_info; version is the single source of truth.
$InitPyPath = '__init__.py'
# Staging directory for the zip and the API payload (already in .gitignore).
$TmpDir = 'tmp'
# Asset/inner-folder base: "MIMIBlenderV" + version digits, e.g. 1.0.12 -> MIMIBlenderV1012.
$AssetPrefix = 'MIMIBlenderV'

# -- Output helpers ------------------------------------------------------------
function Write-Step([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Info([string]$Text) { Write-Host "  [ .. ] $Text" -ForegroundColor Gray }
function Write-Warn2([string]$Text) { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Fail([string]$Text) { Write-Host "`n  [FAIL] $Text" -ForegroundColor Red; exit 1 }

function Format-Size([long]$Bytes) {
    # Human-readable file size for progress output.
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N2} MB' -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ('{0:N1} KB' -f ($Bytes / 1KB)) }
    return "$Bytes B"
}

# Resolve a GitHub token: environment first, then the git credential helper
# (credentials live in Windows Credential Manager, no need to paste tokens).
function Resolve-GitHubToken {
    foreach ($name in @('MIMI_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { return @{ Token = $value.Trim(); Source = "environment variable $name" } }
    }
    try {
        $raw = ("protocol=https`nhost=github.com`n`n" | git credential fill) 2>$null
        $line = $raw | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
        if ($line) {
            $value = $line.Substring('password='.Length).Trim()
            if ($value) { return @{ Token = $value; Source = 'git credential helper' } }
        }
    } catch {
        Write-Info "git credential fill returned nothing: $($_.Exception.Message)"
    }
    return $null
}

function Get-GitHubErrorBody($ErrorRecord) {
    # PowerShell 7 puts the GitHub JSON error body into ErrorDetails.
    try {
        if ($ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
            return $ErrorRecord.ErrorDetails.Message
        }
    } catch { }
    return $ErrorRecord.Exception.Message
}

# -- 0. Location and preflight -------------------------------------------------
Write-Step 'Preflight'
if (-not (Test-Path -LiteralPath $InitPyPath)) {
    Fail "Run this script from the repository root ($InitPyPath not found, cwd: $(Get-Location))"
}
$repoRoot = (Get-Location).Path
Write-Ok "repository root $repoRoot"

# Read bl_info version from __init__.py: the single version source of truth.
$initContent = Get-Content -LiteralPath $InitPyPath -Raw
$versionRx = [regex]'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)'
$versionMatch = $versionRx.Match($initContent)
if (-not $versionMatch.Success) { Fail "Could not parse bl_info version from $InitPyPath" }
$currentVersion = '{0}.{1}.{2}' -f $versionMatch.Groups[1].Value, $versionMatch.Groups[2].Value, $versionMatch.Groups[3].Value
Write-Ok "bl_info version $currentVersion"

# Worktree must be clean: `git archive` packs HEAD, so uncommitted changes
# would silently be missing from the release zip.
if (-not $DryRun) {
    $dirty = @(git status --porcelain)
    if ($dirty.Count -gt 0) {
        Write-Warn2 'uncommitted changes detected:'
        $dirty | ForEach-Object { Write-Host "          $_" -ForegroundColor DarkYellow }
        Fail 'Commit or stash first; the zip is packed from HEAD and would miss these changes.'
    }
    Write-Ok 'worktree clean'
}
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-Ok "current branch $branch"

# Resolve the target version: explicit -Version wins over -Bump patch increment.
if ($Version -and $Bump) { Fail '-Version and -Bump cannot be used together' }
if ($Version -and $Version -notmatch '^\d+\.\d+\.\d+$') { Fail "invalid -Version format: $Version" }
if ($Bump) {
    $parts = $currentVersion.Split('.')
    $Version = "$($parts[0]).$($parts[1]).$([int]$parts[2] + 1)"
}
$releaseVersion = if ($Version) { $Version } else { $currentVersion }

# Release naming derived from the version - must match all existing releases.
$tag = "v$releaseVersion"                                   # v1.0.12
$baseName = "$AssetPrefix$($releaseVersion -replace '\.', '')"  # MIMIBlenderV1012
$zipName = "$baseName.zip"                                  # MIMIBlenderV1012.zip
$zipPath = Join-Path $TmpDir $zipName
Write-Ok "release target: tag $tag, asset $zipName (inner folder $baseName/)"

# List remote tags once: used both for the "tag not taken" check and to find
# the previous tag for the auto-generated Full Changelog compare link.
$remoteTagLines = @(git ls-remote --tags origin 'refs/tags/v*' 2>$null)
$remoteTags = @($remoteTagLines | ForEach-Object {
        if ($_ -match 'refs/tags/(v\d+\.\d+\.\d+)$') { $Matches[1] }
    } | Sort-Object -Unique)
if ($Version -and $Version -ne $currentVersion -and $remoteTags -contains $tag) {
    Fail "tag $tag already exists on origin; pick another version number"
}

# Previous tag = highest remote version tag below the current one (for the
# compare link GitHub puts into auto-generated release notes).
$previousTag = @($remoteTags | Where-Object { $_ -ne $tag } |
    Sort-Object { [version]($_.TrimStart('v')) } -Descending | Select-Object -First 1)[0]
if ($previousTag) { Write-Ok "previous tag $previousTag" } else { Write-Info 'no previous tag found' }

# Token: mandatory for a real run, only warned about during -DryRun.
$auth = Resolve-GitHubToken
$headers = $null
if ($auth) {
    $headers = @{
        Authorization          = "token $($auth.Token)"
        Accept                 = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
        'User-Agent'           = 'MIMIBlender-Release-Script'
    }
    try {
        $who = Invoke-RestMethod -Uri 'https://api.github.com/user' -Headers $headers -TimeoutSec 30
        Write-Ok "GitHub identity $($who.login) (token from $($auth.Source))"
    } catch {
        Fail "GitHub token validation failed: $(Get-GitHubErrorBody $_)"
    }
} elseif ($DryRun) {
    Write-Warn2 'no GitHub token found (fine for -DryRun; a real run would stop here)'
} else {
    Fail 'No GitHub token. Set MIMI_GITHUB_TOKEN, or run a git push once so the credential helper stores it.'
}

if ($DryRun) {
    Write-Step 'DryRun finished'
    Write-Host "  would release : $tag  ->  https://github.com/$Repo/releases/tag/$tag" -ForegroundColor Gray
    Write-Host "  would pack    : $zipName  (git archive of HEAD, inner folder $baseName/)" -ForegroundColor Gray
    Write-Host "  draft         : $([bool]$Draft)" -ForegroundColor Gray
    exit 0
}

# -- 1. Version bump -----------------------------------------------------------
if ($Version -and $Version -ne $currentVersion) {
    Write-Step "Version bump $currentVersion -> $Version"
    # Replace only the version tuple, keeping the surrounding bl_info formatting.
    $tuple = $Version -replace '\.', ', '                     # 1.0.13 -> 1, 0, 13
    $newContent = $versionRx.Replace($initContent, ('"version": ({0})' -f $tuple), 1)
    # -NoNewline: -Raw content already carries its trailing newline; keep the
    # file byte-identical except for the version digits.
    Set-Content -LiteralPath $InitPyPath -Value $newContent -Encoding utf8 -NoNewline
    $check = [regex]::Match((Get-Content -LiteralPath $InitPyPath -Raw), '"version"\s*:\s*\(([^)]+)\)').Groups[1].Value
    if ($check -ne $tuple) { Fail "version write-back verification failed (got ($check))" }
    Write-Ok "$InitPyPath now has version ($tuple)"

    git add -- $InitPyPath
    git commit -m "chore(release): version $Version" | Out-Null
    Write-Ok 'version bump committed'
} else {
    Write-Step "Version unchanged ($releaseVersion), re-releasing current HEAD"
}

# -- 2. Push / remote sync -------------------------------------------------------
# GitHub creates the release tag from the REMOTE branch, and the add-on updater
# downloads the tag zipball - so local HEAD must be on origin before publishing.
Write-Step 'Sync with origin'
$headSha = (git rev-parse HEAD).Trim()
$remoteLine = git ls-remote origin -h "refs/heads/$branch"
$remoteSha = if ($remoteLine) { ($remoteLine -split '\s+')[0] } else { '' }
if ($remoteSha -ne $headSha) {
    if (-not $Push) {
        Fail "local HEAD is not on origin/$branch (local $headSha, remote $remoteSha). Re-run with -Push or push manually."
    }
    git push origin HEAD
    Write-Ok "pushed $headSha to origin/$branch"
} else {
    Write-Ok "origin/$branch already at HEAD ($headSha)"
}

# -- 3. Pack the zip --------------------------------------------------------------
Write-Step "Pack $zipName"
if (-not (Test-Path -LiteralPath $TmpDir)) { New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null }
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

# git archive packs exactly the tracked files of HEAD with the required wrapper
# folder as --prefix: matches existing releases (includes .gitignore/AGENTS.md,
# excludes .git, __pycache__, *_updater staging folders and other untracked files).
git archive --format=zip "--prefix=$baseName/" -o $zipPath HEAD
if ($LASTEXITCODE -ne 0) { Fail "git archive failed (exit $LASTEXITCODE)" }
$zipItem = Get-Item -LiteralPath $zipPath
Write-Ok "$zipName  $(Format-Size $zipItem.Length)"

# Sanity-check the archive: wrapper folder present, entry point inside it, and
# the packed __init__.py carries the version being released.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entryNames = @($zip.Entries | ForEach-Object { $_.FullName })
    if ($entryNames.Count -eq 0) { Fail 'archive is empty' }
    $outside = @($entryNames | Where-Object { -not $_.StartsWith("$baseName/") })
    if ($outside.Count -gt 0) { Fail "archive contains files outside $baseName/: $($outside[0])" }
    $initEntry = $zip.Entries | Where-Object { $_.FullName -eq "$baseName/$InitPyPath" } | Select-Object -First 1
    if (-not $initEntry) { Fail "archive misses $baseName/$InitPyPath" }
    $reader = New-Object System.IO.StreamReader($initEntry.Open())
    $packedInit = $reader.ReadToEnd()
    $reader.Close()
    $packedVersion = [regex]::Match($packedInit, '"version"\s*:\s*\(([^)]+)\)').Groups[1].Value -replace '\s', ''
    if ($packedVersion -ne ($releaseVersion -replace '\.', ',')) {
        Fail "packed bl_info version ($packedVersion) != release version ($releaseVersion)"
    }
    Write-Ok "archive verified: $($entryNames.Count) entries, all under $baseName/, version $releaseVersion"
} finally {
    $zip.Dispose()
}

# -- 4. Release notes ---------------------------------------------------------------
Write-Step 'Release notes'
if (-not $Notes) {
    if ($NotesPath) {
        if (-not (Test-Path -LiteralPath $NotesPath)) { Fail "notes file not found: $NotesPath" }
        $Notes = (Get-Content -LiteralPath $NotesPath -Raw).Trim()
        Write-Ok "notes from $NotesPath ($($Notes.Length) chars)"
    } elseif ($previousTag) {
        # Same one-liner GitHub generates for these releases historically.
        $Notes = "**Full Changelog**: https://github.com/$Repo/compare/$previousTag...$tag"
        Write-Ok "auto compare notes ($previousTag...$tag)"
    } else {
        $Notes = "MIMIBlender $tag"
        Write-Info 'fallback notes (no previous tag to compare against)'
    }
}

# -- 5. Create / update the release ---------------------------------------------------
Write-Step "Publish to GitHub ($Repo @ $tag)"
$releaseUri = "https://api.github.com/repos/$Repo/releases"
$existing = $null
try {
    $existing = Invoke-RestMethod -Uri "$releaseUri/tags/$tag" -Headers $headers -TimeoutSec 30
} catch {
    $status = $null
    try { $status = [int]$_.Exception.Response.StatusCode } catch { }
    if ($status -ne 404) { Fail "release lookup failed: $(Get-GitHubErrorBody $_)" }
    # Draft releases have no real tag yet, so /releases/tags/{tag} 404s on them;
    # fall back to matching tag_name in the recent release list.
    try {
        $recent = Invoke-RestMethod -Uri "${releaseUri}?per_page=20" -Headers $headers -TimeoutSec 30
        $existing = @($recent | Where-Object { $_.tag_name -eq $tag } | Select-Object -First 1)[0]
    } catch { }
}

$payloadObject = [ordered]@{
    tag_name         = $tag
    target_commitish = $branch
    name             = $tag                # existing releases are named after the tag
    body             = $Notes
    draft            = [bool]$Draft
    prerelease       = $false
    # GitHub requires make_latest on PATCH and rejects a JSON boolean for it;
    # it must be the string "true"/"false" (verified against the live API).
    make_latest      = if ($Draft) { 'false' } else { 'true' }
}
# Pass the body via a UTF-8 file: inline JSON strings hit encoding pitfalls.
$payloadPath = Join-Path $repoRoot "$TmpDir/release-payload.json"
$payloadObject | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $payloadPath -Encoding utf8

function Send-ReleaseRequest {
    param([string]$Uri, [string]$Method)
    # The release endpoint occasionally returns a 500 that a retry fixes.
    $delays = @(2, 5, 10)
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            return Invoke-RestMethod -Uri $Uri -Method $Method -Headers $headers `
                -ContentType 'application/json; charset=utf-8' -InFile $payloadPath -TimeoutSec 60
        } catch {
            $status = $null
            try { $status = [int]$_.Exception.Response.StatusCode } catch { }
            if ($status -ge 500 -and $attempt -le $delays.Count) {
                Write-Warn2 "$Method release returned HTTP $status, retry $($delays[$attempt - 1])s (attempt $attempt)"
                Start-Sleep -Seconds $delays[$attempt - 1]
                continue
            }
            Write-Warn2 "$Method $Uri -> HTTP ${status}: $(Get-GitHubErrorBody $_)"
            return $null
        }
    }
    return $null
}

if ($existing) {
    Write-Info "release exists (id=$($existing.id), assets $(@($existing.assets).Count))"
    $release = Send-ReleaseRequest -Uri "$releaseUri/$($existing.id)" -Method Patch
    if (-not $release) {
        # Not fatal: keep the existing release and still (re-)upload the asset.
        Write-Warn2 'could not update release metadata; continuing with asset upload'
        $release = Invoke-RestMethod -Uri "$releaseUri/$($existing.id)" -Headers $headers -TimeoutSec 30
    }
} else {
    $release = Send-ReleaseRequest -Uri $releaseUri -Method Post
    if (-not $release) { Fail 'release creation failed' }
}
Write-Ok "release ready: $($release.html_url) (draft=$($release.draft))"

# -- 6. Upload the asset ---------------------------------------------------------------
Write-Step 'Upload asset'
# Replace any same-named asset so the script is safe to re-run.
foreach ($old in @($release.assets | Where-Object { $_.name -eq $zipName })) {
    Invoke-RestMethod -Uri "https://api.github.com/repos/${Repo}/releases/assets/$($old.id)" `
        -Method Delete -Headers $headers -TimeoutSec 30 | Out-Null
    Write-Info "removed old asset $zipName (id=$($old.id))"
}
$uploadUri = "https://uploads.github.com/repos/${Repo}/releases/$($release.id)/assets?name=$([uri]::EscapeDataString($zipName))"
Write-Info "uploading $zipName  $(Format-Size $zipItem.Length) ..."
$null = Invoke-WebRequest -Uri $uploadUri -Method Post -Headers $headers `
    -ContentType 'application/zip' -InFile $zipPath -TimeoutSec 900
Write-Ok "uploaded $zipName"

# -- 7. Verify --------------------------------------------------------------------------
Write-Step 'Verify'
# Re-fetch by release id (a draft's tag does not resolve via /tags/{tag}).
$release = Invoke-RestMethod -Uri "$releaseUri/$($release.id)" -Headers $headers -TimeoutSec 30
$remoteAsset = @($release.assets) | Where-Object { $_.name -eq $zipName } | Select-Object -First 1
if (-not $remoteAsset) { Fail "$zipName missing from the release after upload" }
if ($remoteAsset.size -ne $zipItem.Length) {
    Fail "$zipName remote size $($remoteAsset.size) != local $($zipItem.Length)"
}
$localHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
Write-Ok "$zipName  $($remoteAsset.size) bytes  SHA256(local)=$($localHash.Substring(0,16))..."

# The add-on updater polls tags, so the tag must exist on the remote for a
# published release (drafts legitimately have no tag yet).
$tagOnRemote = @($remoteTags -contains $tag)
if (-not $tagOnRemote) {
    $tagOnRemote = [bool](git ls-remote --tags origin "refs/tags/$tag" 2>$null)
}
if ($tagOnRemote) {
    Write-Ok "tag $tag visible on origin (updater channel live)"
} elseif ($release.draft) {
    Write-Warn2 "draft release: tag $tag appears when the draft is published"
} else {
    Write-Warn2 "tag $tag not visible on origin yet (GitHub propagation, check shortly)"
}

# -- Summary -----------------------------------------------------------------------------
Write-Step 'Done'
Write-Host "  version : $releaseVersion" -ForegroundColor White
Write-Host "  release : $($release.html_url)" -ForegroundColor White
Write-Host "  zip     : $zipPath" -ForegroundColor Gray
if ($release.draft) {
    Write-Host "`n  Draft only - users get nothing yet. Publish it on GitHub, or re-run without -Draft." -ForegroundColor Yellow
} else {
    Write-Host "`n  Published - the add-on updater will offer $releaseVersion from the tag zipball." -ForegroundColor Green
}
