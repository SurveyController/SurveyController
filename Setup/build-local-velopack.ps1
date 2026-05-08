[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Channel = "stable",

    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "Releases",

    [switch]$SkipClean,
    [switch]$SkipPyInstaller,
    [switch]$SkipRenameSetup
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-CommandAvailable {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw ("Missing command: {0}. {1}" -f $Name, $InstallHint)
    }
}

function Resolve-RepoRoot {
    $scriptRoot = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
        $scriptRoot = Split-Path -Parent $PSCommandPath
    }
    return (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

function Get-PreviousReleaseDir {
    param(
        [string]$RepoRoot,
        [string]$Channel
    )

    $candidate = Join-Path $RepoRoot ("build\velopack-baseline\{0}" -f $Channel)
    New-Item -ItemType Directory -Path $candidate -Force | Out-Null
    return $candidate
}

function Copy-PreviousReleasePackages {
    param(
        [string]$SourceDir,
        [string]$TargetDir
    )

    if (-not (Test-Path $SourceDir)) {
        return
    }

    Get-ChildItem -Path $SourceDir -File -Filter "*.nupkg" -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $TargetDir $_.Name) -Force
    }

    $releaseFiles = @(
        Get-ChildItem -Path $SourceDir -File -Filter "releases.*.json" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $SourceDir -File -Filter "assets.*.json" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $SourceDir -File -Filter "RELEASES-*" -ErrorAction SilentlyContinue
    )
    foreach ($file in $releaseFiles) {
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $TargetDir $file.Name) -Force
    }
}

function Save-ReleasePackagesForNextBuild {
    param(
        [string]$SourceDir,
        [string]$TargetDir
    )

    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    Get-ChildItem -Path $TargetDir -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Copy-PreviousReleasePackages -SourceDir $SourceDir -TargetDir $TargetDir
}

function ConvertTo-PackVersion {
    param([string]$RawVersion)

    $normalized = ""
    if ($null -ne $RawVersion) {
        $normalized = $RawVersion.Trim()
    }
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        throw "Version must not be empty."
    }
    if ($normalized.StartsWith("v", [System.StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring(1)
    }
    return $normalized
}

function Get-AppVersionFromPythonFile {
    param([string]$RepoRoot)

    $versionFile = Join-Path $RepoRoot "software\app\version.py"
    if (-not (Test-Path $versionFile)) {
        throw ("Version file not found: {0}" -f $versionFile)
    }

    $content = Get-Content $versionFile -Raw -Encoding UTF8
    $match = [regex]::Match($content, '__VERSION__\s*=\s*"(?<version>[^"]+)"')
    if (-not $match.Success) {
        throw ("Could not read __VERSION__ from: {0}" -f $versionFile)
    }

    return $match.Groups["version"].Value
}

$repoRoot = Resolve-RepoRoot
$appVersion = Get-AppVersionFromPythonFile -RepoRoot $repoRoot
$packVersion = ConvertTo-PackVersion -RawVersion $appVersion
$tagName = if ($appVersion.StartsWith("v", [System.StringComparison]::OrdinalIgnoreCase)) { $appVersion } else { "v$packVersion" }
$releaseDir = Join-Path $repoRoot $OutputDir
$previousReleaseDir = Get-PreviousReleaseDir -RepoRoot $repoRoot -Channel $Channel
$distDir = Join-Path $repoRoot "dist"
$packDir = Join-Path $distDir "lib"
$mainExe = Join-Path $packDir "SurveyController.exe"
$iconPath = Join-Path $packDir "icon.ico"
$generatedSetup = Join-Path $releaseDir ("SurveyController-{0}-Setup.exe" -f $Channel)
$renamedSetup = Join-Path $releaseDir ("SurveyController_{0}_setup.exe" -f $tagName)
$releaseFeed = Join-Path $releaseDir ("releases.{0}.json" -f $Channel)

Write-Step "Check environment"
Assert-CommandAvailable -Name "python" -InstallHint "Install Python first and ensure python is available in PATH."
Assert-CommandAvailable -Name "dotnet" -InstallHint "Install .NET SDK 8 or newer first."

$toolPath = Join-Path $env:USERPROFILE ".dotnet\tools"
if (Test-Path $toolPath) {
    $env:PATH = "${toolPath};$env:PATH"
}
Assert-CommandAvailable -Name "vpk" -InstallHint "Run: dotnet tool install -g vpk"

Write-Host ("Repo root: {0}" -f $repoRoot)
Write-Host ("App version: {0}" -f $appVersion)
Write-Host ("Pack version: {0}" -f $packVersion)
Write-Host ("Channel: {0}" -f $Channel)
Write-Host ("Output dir: {0}" -f $releaseDir)

if (-not $SkipClean) {
    Write-Step "Clean old artifacts"
    foreach ($path in @($distDir, $releaseDir)) {
        if (Test-Path $path) {
            Remove-Item -Recurse -Force $path
        }
    }
}

if (-not $SkipPyInstaller) {
    Write-Step "Run PyInstaller"
    Push-Location $repoRoot
    try {
        python -m PyInstaller SurveyController.spec --noconfirm --clean
    }
    finally {
        Pop-Location
    }
}

Write-Step "Verify PyInstaller output"
if (-not (Test-Path $packDir)) {
    throw ("Pack directory not found: {0}" -f $packDir)
}
if (-not (Test-Path $mainExe)) {
    throw ("Main executable not found: {0}" -f $mainExe)
}
if (-not (Test-Path $iconPath)) {
    throw ("Icon file not found: {0}" -f $iconPath)
}
$blockedPlaywrightPaths = @(
    "playwright\driver\package\lib\tools\backend",
    "playwright\driver\package\lib\tools\cli-client",
    "playwright\driver\package\lib\tools\cli-daemon",
    "playwright\driver\package\lib\tools\dashboard",
    "playwright\driver\package\lib\tools\mcp",
    "playwright\driver\package\lib\tools\utils",
    "playwright\driver\package\lib\tools\exports.js"
)
foreach ($relativePath in $blockedPlaywrightPaths) {
    $candidate = Join-Path $packDir $relativePath
    if (Test-Path $candidate) {
        throw ("Blocked Playwright tool payload was packaged: {0}" -f $candidate)
    }
}

Write-Step "Run vpk pack"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Copy-PreviousReleasePackages -SourceDir $previousReleaseDir -TargetDir $releaseDir
Push-Location $repoRoot
try {
    $vpkArgs = @(
        "pack"
        "--packId"
        "SurveyController"
        "--packTitle"
        "SurveyController"
        "--packVersion"
        $packVersion
        "--packDir"
        $packDir
        "--mainExe"
        "SurveyController.exe"
        "--icon"
        $iconPath
        "--delta"
        "BestSpeed"
        "--channel"
        $Channel
        "--outputDir"
        $releaseDir
    )
    & vpk @vpkArgs
}
finally {
    Pop-Location
}

Write-Step "Verify Velopack artifacts"
if (-not (Test-Path $generatedSetup)) {
    throw ("Velopack setup executable not found: {0}" -f $generatedSetup)
}
if (-not (Test-Path $releaseFeed)) {
    throw ("Release feed not found: {0}" -f $releaseFeed)
}

$nupkgs = Get-ChildItem -Path $releaseDir -Filter "*.nupkg" -ErrorAction SilentlyContinue
if (-not $nupkgs) {
    throw "No .nupkg package was generated."
}

if (-not $SkipRenameSetup) {
    Write-Step "Rename setup executable"
    Move-Item -LiteralPath $generatedSetup -Destination $renamedSetup -Force
}

Write-Step "Cache release packages for next build"
Save-ReleasePackagesForNextBuild -SourceDir $releaseDir -TargetDir $previousReleaseDir

Write-Step "Build finished"
Get-ChildItem $releaseDir | Sort-Object Name | Format-Table Name, Length, LastWriteTime -AutoSize

Write-Host ""
Write-Host ("Local artifact dir: {0}" -f $releaseDir) -ForegroundColor Green
if (-not $SkipRenameSetup) {
    Write-Host ("Setup exe: {0}" -f $renamedSetup) -ForegroundColor Green
} else {
    Write-Host ("Setup exe: {0}" -f $generatedSetup) -ForegroundColor Green
}
Write-Host ("Release feed: {0}" -f $releaseFeed) -ForegroundColor Green
