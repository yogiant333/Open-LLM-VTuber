param(
    [string]$OutputRoot = "",
    [string]$PackageName = "",
    [string]$LiveTalkingDir = "E:\AI\LiveTalking",
    [string]$TtsDir = "C:\AI\voxcpm2-nanovllm-win-venv",
    [switch]$SkipFrontendBuild,
    [switch]$SkipBackendVenv,
    [switch]$SkipModels,
    [switch]$SkipLiveTalking,
    [switch]$SkipLiveTalkingVenv,
    [switch]$SkipTts,
    [switch]$NoArchive
)

$ErrorActionPreference = "Stop"

function Invoke-Robocopy {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing source directory: $Source"
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $args = @(
        $Source,
        $Destination,
        "/MIR",
        "/R:2",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NP",
        "/XJ"
    )

    if ($ExcludeDirs.Count -gt 0) {
        $args += "/XD"
        $args += $ExcludeDirs
    }

    if ($ExcludeFiles.Count -gt 0) {
        $args += "/XF"
        $args += $ExcludeFiles
    }

    & robocopy.exe @args | Out-Host
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit code ${LASTEXITCODE}: $Source -> $Destination"
    }
}

function Copy-FileRequired {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing file: $Source"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $PackageName) {
    $PackageName = "Open-LLM-VTuber-production-$Stamp"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $ProjectRoot "deployment_packages"
}

$PackageRoot = Join-Path $OutputRoot $PackageName
$ProjectOut = Join-Path $PackageRoot "Open-LLM-VTuber"
$FrontendOut = Join-Path $PackageRoot "frontend-runtime"

Write-Host "Project root: $ProjectRoot"
Write-Host "Package root: $PackageRoot"
Write-Host ""

if (-not $SkipFrontendBuild) {
    Push-Location (Join-Path $ProjectRoot "livetalking-showcase")
    try {
        if (-not (Test-Path -LiteralPath "node_modules")) {
            npm install
        }
        npm run build
    } finally {
        Pop-Location
    }
}

Remove-Item -LiteralPath $PackageRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $PackageRoot | Out-Null

$projectExcludeDirs = @(
    ".git",
    ".cursor",
    ".gemini",
    "__pycache__",
    ".certs",
    ".claude",
    ".omx",
    ".playwright-mcp",
    "logs",
    "reports",
    "cache",
    "downloads",
    "tmp",
    "frontend\node_modules",
    "livetalking-showcase\node_modules",
    "livetalking-showcase\dist",
    "deployment_packages"
)

if ($SkipBackendVenv) {
    $projectExcludeDirs += ".venv"
}

if ($SkipModels) {
    $projectExcludeDirs += "models"
    $projectExcludeDirs += "Qwen3-ASR-GGUF\model"
}

$projectExcludeFiles = @("*.pyc")

Invoke-Robocopy -Source $ProjectRoot -Destination $ProjectOut -ExcludeDirs $projectExcludeDirs -ExcludeFiles $projectExcludeFiles

New-Item -ItemType Directory -Force -Path $FrontendOut | Out-Null
Invoke-Robocopy -Source (Join-Path $ProjectRoot "livetalking-showcase\dist") -Destination (Join-Path $FrontendOut "dist")
Copy-FileRequired -Source (Join-Path $ProjectRoot "scripts\frontend_runtime_server.js") -Destination (Join-Path $FrontendOut "server.js")

Copy-FileRequired -Source (Join-Path $ProjectRoot "start_all.ps1") -Destination (Join-Path $PackageRoot "start_all.ps1")
Copy-FileRequired -Source (Join-Path $ProjectRoot "stop_all.ps1") -Destination (Join-Path $PackageRoot "stop_all.ps1")
Copy-FileRequired -Source (Join-Path $ProjectRoot "healthcheck.ps1") -Destination (Join-Path $PackageRoot "healthcheck.ps1")
Copy-FileRequired -Source (Join-Path $ProjectRoot "start_all.bat") -Destination (Join-Path $PackageRoot "start_all.bat")
Copy-FileRequired -Source (Join-Path $ProjectRoot "stop_all.bat") -Destination (Join-Path $PackageRoot "stop_all.bat")
Copy-FileRequired -Source (Join-Path $ProjectRoot "healthcheck.bat") -Destination (Join-Path $PackageRoot "healthcheck.bat")
Copy-FileRequired -Source (Join-Path $ProjectRoot "README_PRODUCTION_DEVICE.md") -Destination (Join-Path $PackageRoot "README_PRODUCTION_DEVICE.md")

if (-not $SkipLiveTalking) {
    if (Test-Path -LiteralPath $LiveTalkingDir) {
        $liveExcludeDirs = @(".git", "__pycache__", ".omx", ".playwright-mcp", "logs", "temp")
        if ($SkipLiveTalkingVenv) {
            $liveExcludeDirs += ".venv"
        }
        Invoke-Robocopy -Source $LiveTalkingDir -Destination (Join-Path $PackageRoot "LiveTalking") -ExcludeDirs $liveExcludeDirs -ExcludeFiles @("*.pyc", "livetalking.log")
    } else {
        Write-Host "Skipping LiveTalking copy; directory not found: $LiveTalkingDir"
    }
}

if (-not $SkipTts) {
    if (Test-Path -LiteralPath $TtsDir) {
        Invoke-Robocopy -Source $TtsDir -Destination (Join-Path $PackageRoot "voxcpm2-nanovllm-win-venv") `
            -ExcludeDirs @(".git", "__pycache__", ".omx", ".playwright-mcp", "logs", "tmp", "temp") `
            -ExcludeFiles @("*.pyc", "*.log")
    } else {
        Write-Host "Skipping TTS copy; directory not found: $TtsDir"
    }
}

$Manifest = [ordered]@{
    created_at = (Get-Date).ToString("s")
    package_root = $PackageRoot
    frontend_url = "http://127.0.0.1:3000/"
    backend_url = "http://127.0.0.1:18080/"
    livetalking_url = "http://127.0.0.1:18010/"
    tts_url = "http://127.0.0.1:50005/health"
    live_talking_source = $LiveTalkingDir
    tts_source = $TtsDir
    includes_backend_venv = -not $SkipBackendVenv
    includes_models = -not $SkipModels
    includes_livetalking = (-not $SkipLiveTalking) -and (Test-Path -LiteralPath $LiveTalkingDir)
    includes_livetalking_venv = (-not $SkipLiveTalking) -and (-not $SkipLiveTalkingVenv) -and (Test-Path -LiteralPath (Join-Path $LiveTalkingDir ".venv"))
    includes_tts = (-not $SkipTts) -and (Test-Path -LiteralPath $TtsDir)
}

$Manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $PackageRoot "package-manifest.json") -Encoding utf8

if (-not $NoArchive) {
    $ArchivePath = Join-Path $OutputRoot "$PackageName.zip"
    Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $ArchivePath -Force
    Write-Host "Archive: $ArchivePath"
}

Write-Host "Package created: $PackageRoot"
Write-Host ""
Write-Host "Deploy by copying the package contents to C:\AI, then run:"
Write-Host "  C:\AI\start_all.bat"
