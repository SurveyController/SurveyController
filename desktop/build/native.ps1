[CmdletBinding()]
param(
    [ValidateSet('restore', 'build', 'rebuild', 'clean', 'package', 'preview', 'test')]
    [string]$Action = 'build',
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Debug'
)

$ErrorActionPreference = 'Stop'

$desktopRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $desktopRoot
$solution = Join-Path $desktopRoot 'native\SurveyController.sln'
$testProject = Join-Path $desktopRoot 'native\tests\SurveyController.Native.Tests\SurveyController.Native.Tests.vcxproj'
$testOutput = Join-Path $desktopRoot "native\x64\$Configuration\SurveyController.Native.Tests\SurveyController.Native.Tests.exe"
$releaseOutput = Join-Path $desktopRoot 'native\x64\Release\SurveyController.App'
$packageRoot = Join-Path $desktopRoot 'bin\native-x64'
$installerOutput = Join-Path $desktopRoot 'bin\SurveyController-amd64-installer.exe'
$installerIcon = Join-Path $repoRoot 'assets\icon.ico'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'

if (-not (Test-Path -LiteralPath $vswhere)) {
    throw '未找到 Visual Studio Installer。'
}

$msbuild = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
if (-not $msbuild) {
    throw '未找到带 MSVC 的 MSBuild。'
}

# MSBuild supplies the toolchain library paths; discard stale LIB entries from
# an older Visual Studio installation before invoking it.
$env:LIB = ''

function Stop-PreviewProcess {
    param([Parameter(Mandatory = $true)][string]$ExecutablePath)

    $targetPath = [IO.Path]::GetFullPath($ExecutablePath)
    $matchingProcesses = @()
    foreach ($process in Get-Process -Name 'SurveyController' -ErrorAction SilentlyContinue) {
        try {
            if ($process.Path -and [IO.Path]::GetFullPath($process.Path) -ieq $targetPath) {
                $matchingProcesses += $process
            }
        } catch {
            # Some foreign or protected processes do not expose their image path.
        }
    }

    foreach ($process in $matchingProcesses) {
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
        if (-not $process.WaitForExit(5000)) {
            throw "预览进程未能在 5 秒内退出：$targetPath"
        }
    }
}

if ($Action -eq 'restore') {
    & $msbuild $solution /t:Restore /m
    exit $LASTEXITCODE
}

if ($Action -eq 'test') {
    & $msbuild $testProject /restore /t:Build /p:Configuration=$Configuration /p:Platform=x64 /m
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    if (-not (Test-Path -LiteralPath $testOutput)) {
        throw "未找到原生测试程序：$testOutput"
    }
    & $testOutput
    exit $LASTEXITCODE
}

if ($Action -eq 'package') {
    $Configuration = 'Release'
}

if ($Action -in @('build', 'rebuild', 'package', 'preview')) {
    $backendOutput = Join-Path $desktopRoot "native\x64\$Configuration\SurveyController.App\SurveyController.Backend.exe"
    if ($Action -eq 'preview') {
        Stop-PreviewProcess -ExecutablePath (Join-Path $desktopRoot "native\x64\$Configuration\SurveyController.App\SurveyController.exe")
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $backendOutput) -Force | Out-Null
    $goArguments = @('build', '-buildvcs=false', '-o', $backendOutput)
    if ($Configuration -eq 'Release') {
        $goArguments = @('build', '-buildvcs=false', '-trimpath', '-ldflags=-s -w', '-o', $backendOutput)
    }
    Push-Location -LiteralPath $desktopRoot
    try {
        & go @goArguments '.'
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

$target = switch ($Action) {
    'rebuild' { 'Rebuild' }
    'clean' { 'Clean' }
    default { 'Build' }
}

& $msbuild $solution /restore /t:$target /p:Configuration=$Configuration /p:Platform=x64 /m
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($Action -eq 'preview') {
    $previewExecutable = Join-Path $desktopRoot "native\x64\$Configuration\SurveyController.App\SurveyController.exe"
    if (-not (Test-Path -LiteralPath $previewExecutable)) {
        throw "未找到原生预览程序：$previewExecutable"
    }
    $developmentRoot = Join-Path $env:LOCALAPPDATA 'SurveyController\Development'
    $previousConfigHome = $env:SURVEYCONTROLLER_CONFIG_HOME
    $previousLocalDataHome = $env:SURVEYCONTROLLER_LOCAL_DATA_HOME
    try {
        $env:SURVEYCONTROLLER_CONFIG_HOME = Join-Path $developmentRoot 'Config'
        $env:SURVEYCONTROLLER_LOCAL_DATA_HOME = Join-Path $developmentRoot 'LocalData'
        Start-Process -FilePath $previewExecutable
    } finally {
        $env:SURVEYCONTROLLER_CONFIG_HOME = $previousConfigHome
        $env:SURVEYCONTROLLER_LOCAL_DATA_HOME = $previousLocalDataHome
    }
    exit 0
}

if ($Action -ne 'package') {
    exit 0
}

if (-not (Test-Path -LiteralPath $releaseOutput)) {
    throw "未找到原生 Release 输出：$releaseOutput"
}

$binRoot = Split-Path -Parent $packageRoot
$resolvedBinRoot = [System.IO.Path]::GetFullPath($binRoot)
$resolvedPackageRoot = [System.IO.Path]::GetFullPath($packageRoot)
if (-not $resolvedPackageRoot.StartsWith($resolvedBinRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "打包目录超出 bin：$resolvedPackageRoot"
}
if (Test-Path -LiteralPath $resolvedPackageRoot) {
    Remove-Item -LiteralPath $resolvedPackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $resolvedPackageRoot -Force | Out-Null

$excludedExtensions = @('.exp', '.lib', '.pdb')
$excludedNames = @('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.Core.winmd')
Get-ChildItem -LiteralPath $releaseOutput -Recurse -File |
    Where-Object {
        $excludedExtensions -notcontains $_.Extension.ToLowerInvariant() -and
        $excludedNames -notcontains $_.Name
    } |
    ForEach-Object {
        $relativePath = [System.IO.Path]::GetRelativePath($releaseOutput, $_.FullName)
        $destination = Join-Path $resolvedPackageRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }

$configText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.yml') -Raw
$versionMatch = [regex]::Match($configText, '(?m)^\s+version:\s*["'']?([^"''#\r\n]+)')
if (-not $versionMatch.Success) {
    throw 'build/config.yml 缺少 info.version。'
}
$version = $versionMatch.Groups[1].Value.Trim()
$makensis = (Get-Command makensis -ErrorAction SilentlyContinue).Source
if (-not $makensis) {
    throw '未找到 NSIS makensis。'
}
if (-not (Test-Path -LiteralPath $installerIcon)) {
    throw "未找到安装程序图标：$installerIcon"
}

& $makensis `
    '/INPUTCHARSET' `
    'UTF8' `
    '-DINFO_COMPANYNAME=HUNGRY_M0' `
    '-DINFO_PRODUCTNAME=SurveyController' `
    "-DINFO_PRODUCTVERSION=$version" `
    '-DINFO_COPYRIGHT=(c) 2026, HUNGRY_M0' `
    "-DARG_NATIVE_PAYLOAD=$resolvedPackageRoot" `
    "-DARG_INSTALLER_OUTPUT=$installerOutput" `
    "-DARG_INSTALLER_ICON=$installerIcon" `
    (Join-Path $desktopRoot 'build\windows\nsis\project.nsi')
exit $LASTEXITCODE
