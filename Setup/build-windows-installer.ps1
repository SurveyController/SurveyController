[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Version = "",

    [Parameter(Mandatory = $false)]
    [ValidateSet("amd64", "arm64")]
    [string]$Arch = "amd64",

    [Parameter(Mandatory = $false)]
    [string]$ReleaseDir = "Releases\win\stable",

    [switch]$SkipClean
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

function Resolve-Version {
    param(
        [string]$RepoRoot,
        [string]$ProvidedVersion
    )

    if (-not [string]::IsNullOrWhiteSpace($ProvidedVersion)) {
        $version = $ProvidedVersion.Trim()
        if ($version.StartsWith("v")) {
            return $version
        }
        return "v$version"
    }

    $configPath = Join-Path $RepoRoot "apps\desktop\build\config.yml"
    $configText = Get-Content -LiteralPath $configPath -Raw
    $match = [regex]::Match($configText, '(?m)^\s*version:\s*"([^"]+)"')
    if (-not $match.Success) {
        throw ("Failed to resolve version from: {0}" -f $configPath)
    }
    $version = $match.Groups[1].Value.Trim()
    if ($version.StartsWith("v")) {
        return $version
    }
    return "v$version"
}

$repoRoot = Resolve-RepoRoot
$desktopRoot = Join-Path $repoRoot "apps\desktop"
$binRoot = Join-Path $desktopRoot "bin"
$releaseRoot = Join-Path $repoRoot $ReleaseDir
$packVersion = Resolve-Version -RepoRoot $repoRoot -ProvidedVersion $Version

$installerName = "SurveyController-$Arch-installer.exe"
$versionedInstallerName = "SurveyController $packVersion.exe"

Write-Step "Check environment"
Assert-CommandAvailable -Name "go" -InstallHint "Install Go 1.26+ and ensure go is available in PATH."
Assert-CommandAvailable -Name "node" -InstallHint "Install Node.js and ensure node is available in PATH."
Assert-CommandAvailable -Name "npm" -InstallHint "Install npm and ensure npm is available in PATH."
Assert-CommandAvailable -Name "wails3" -InstallHint "Install Wails v3: go install github.com/wailsapp/wails/v3/cmd/wails3@v3.0.0-alpha2.104"
Assert-CommandAvailable -Name "task" -InstallHint "Install go-task: go install github.com/go-task/task/v3/cmd/task@latest"
Assert-CommandAvailable -Name "makensis" -InstallHint "Install NSIS and ensure makensis is available in PATH."

Write-Host ("Repo root: {0}" -f $repoRoot)
Write-Host ("Desktop root: {0}" -f $desktopRoot)
Write-Host ("Release dir: {0}" -f $releaseRoot)
Write-Host ("Version: {0}" -f $packVersion)
Write-Host ("Arch: {0}" -f $Arch)
Write-Host "Install scope: user"

if (-not $SkipClean) {
    Write-Step "Clean old desktop build artifacts"
    foreach ($path in @($binRoot, $releaseRoot)) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

Write-Step "Build Windows installer"
Push-Location $desktopRoot
try {
    task windows:package ARCH=$Arch INSTALL_SCOPE=user
}
finally {
    Pop-Location
}

Write-Step "Copy release artifacts"
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

$installerPath = Join-Path $binRoot $installerName

if (-not (Test-Path $installerPath)) {
    throw ("Installer not found: {0}" -f $installerPath)
}

Copy-Item -Force $installerPath (Join-Path $releaseRoot $installerName)
Copy-Item -Force $installerPath (Join-Path $releaseRoot $versionedInstallerName)

Write-Step "Build finished"
Get-ChildItem -LiteralPath $releaseRoot | Sort-Object Name | Format-Table Name, Length, LastWriteTime -AutoSize

Write-Host ""
Write-Host ("Release dir: {0}" -f $releaseRoot) -ForegroundColor Green
Write-Host ("Installer: {0}" -f (Join-Path $releaseRoot $versionedInstallerName)) -ForegroundColor Green
