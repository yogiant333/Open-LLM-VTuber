param(
    [string]$InstallRoot = "",
    [int[]]$Ports = @(3000, 18010, 18080, 10002, 50005)
)

$ErrorActionPreference = "Stop"

function Stop-ProcessTree {
    param([int]$ProcessId, [string]$Label)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId) -Label $Label
    }

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        Write-Host "Stopped $Label PID $ProcessId ($($process.ProcessName))"
    } catch {
    }
}

$Root = if ($InstallRoot) { (Resolve-Path -LiteralPath $InstallRoot).Path } else { $PSScriptRoot }
$PidFiles = @(
    (Join-Path $Root "logs\frontend-runtime.pid"),
    (Join-Path $Root "logs\backend-only-windows.pid"),
    (Join-Path $Root "Open-LLM-VTuber\logs\backend-only-windows.pid")
)

foreach ($pidFile in $PidFiles) {
    if (Test-Path -LiteralPath $pidFile) {
        $pidText = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        if ($pidText -match '^\d+$') {
            Stop-ProcessTree -ProcessId ([int]$pidText) -Label "recorded service"
        }
    }
}

$owners = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($ownerPid in $owners) {
    if ($ownerPid -and $ownerPid -gt 4) {
        Stop-ProcessTree -ProcessId ([int]$ownerPid) -Label "listener"
    }
}

Write-Host "Stop requested for ports: $($Ports -join ', ')"
