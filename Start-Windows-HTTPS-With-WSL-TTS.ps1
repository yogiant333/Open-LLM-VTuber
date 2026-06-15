param(
    [string]$PublicIp = "10.0.2.155",
    [string]$BindHost = "0.0.0.0",
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 18080,
    [int]$UeWsPort = 10002,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Stop-Listener {
    param(
        [int[]]$Ports,
        [string]$Label
    )

    $owners = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($ownerPid in $owners) {
        if ($ownerPid -and $ownerPid -ne 0) {
            try {
                Stop-Process -Id $ownerPid -Force -ErrorAction Stop
                Write-Host "Stopped $Label PID $ownerPid"
            } catch {
                Write-Host "Could not stop $Label PID ${ownerPid}: $($_.Exception.Message)"
            }
        }
    }
}

function Stop-ProcessTree {
    param(
        [int]$ProcessId,
        [string]$Label
    )

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId) -Label $Label
    }

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        Write-Host "Stopped $Label PID $ProcessId ($($process.ProcessName))"
    } catch {
        # The process may already have exited.
    }
}

function Stop-RecordedProcessTree {
    param(
        [string]$PidPath,
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $PidPath)) {
        return
    }

    $recordedPid = Get-Content -LiteralPath $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    if ($recordedPid -match '^\d+$') {
        Stop-ProcessTree -ProcessId ([int]$recordedPid) -Label $Label
    }
}

function Get-ExcludedTcpPortRanges {
    $ranges = @()
    $output = & netsh.exe interface ipv4 show excludedportrange protocol=tcp 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $ranges
    }

    foreach ($line in $output) {
        if ($line -match '^\s*(\d+)\s+(\d+)\s*(\*)?\s*$') {
            $ranges += [pscustomobject]@{
                Start = [int]$Matches[1]
                End = [int]$Matches[2]
            }
        }
    }

    return $ranges
}

function Test-TcpPortExcluded {
    param(
        [int]$Port,
        [object[]]$Ranges
    )

    foreach ($range in $Ranges) {
        if ($Port -ge $range.Start -and $Port -le $range.End) {
            return $true
        }
    }

    return $false
}

function Test-TcpPortBindable {
    param(
        [int]$Port,
        [string]$BindHost
    )

    try {
        if ($BindHost -eq "0.0.0.0") {
            $ipAddress = [System.Net.IPAddress]::Any
        } elseif ($BindHost -eq "::") {
            $ipAddress = [System.Net.IPAddress]::IPv6Any
        } else {
            $ipAddress = [System.Net.IPAddress]::Parse($BindHost)
        }

        $listener = [System.Net.Sockets.TcpListener]::new($ipAddress, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function Resolve-AvailableTcpPort {
    param(
        [int]$PreferredPort,
        [string]$Name,
        [string]$BindHost
    )

    $excludedRanges = Get-ExcludedTcpPortRanges
    for ($port = $PreferredPort; $port -le 65535; $port++) {
        if ((Test-TcpPortExcluded -Port $port -Ranges $excludedRanges) -or -not (Test-TcpPortBindable -Port $port -BindHost $BindHost)) {
            continue
        }

        if ($port -ne $PreferredPort) {
            Write-Host "$Name port $PreferredPort is unavailable; using $port instead."
        }

        return $port
    }

    throw "No available TCP port found for $Name starting at $PreferredPort."
}

function Enable-SelfSignedCertificateRequests {
    if ($PSVersionTable.PSEdition -eq "Desktop") {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    }
}

function Invoke-HealthRequest {
    param([string]$Url)

    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        $content = & curl.exe -k -s -f --max-time 2 $Url
        if ($LASTEXITCODE -ne 0) {
            throw "curl health request failed: $Url"
        }
        return [pscustomobject]@{
            Content = ($content -join "`n")
        }
    }

    if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey("SkipCertificateCheck")) {
        return Invoke-WebRequest -UseBasicParsing -SkipCertificateCheck -TimeoutSec 2 -Uri $Url
    }

    return Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $Url
}

function Wait-Http {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Attempts = 150,
        [System.Diagnostics.Process]$Process = $null,
        [string]$StdoutLog = $null,
        [string]$StderrLog = $null
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        if ($Process -and $Process.HasExited) {
            Start-Sleep -Milliseconds 500
            Write-Host "$Name process exited early with code $($Process.ExitCode)."
            if ($StdoutLog -and (Test-Path -LiteralPath $StdoutLog)) {
                Write-Host ""
                Write-Host "$Name stdout:"
                Get-Content -LiteralPath $StdoutLog -Tail 80
            }
            if ($StderrLog -and (Test-Path -LiteralPath $StderrLog)) {
                Write-Host ""
                Write-Host "$Name stderr:"
                Get-Content -LiteralPath $StderrLog -Tail 80
            }
            throw "$Name process exited before becoming ready: $Url"
        }

        try {
            $response = Invoke-HealthRequest -Url $Url
            Write-Host "$Name ready: $Url"
            return $response
        } catch {
            if (($i % 10) -eq 0) {
                Write-Host "waiting $Name ($i/$Attempts): $Url"
            }
            Start-Sleep -Seconds 2
        }
    }

    throw "$Name did not become ready: $Url"
}

function Stop-StartedProcess {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$PidPath,
        [string]$Label
    )

    if ($PidPath -and (Test-Path -LiteralPath $PidPath)) {
        Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    }

    if ($Process -and -not $Process.HasExited) {
        Stop-ProcessTree -ProcessId $Process.Id -Label $Label
    }
}

function Ensure-Certificate {
    param(
        [string]$Root,
        [string]$IpAddress
    )

    $certDir = Join-Path $Root ".certs"
    $keyPath = Join-Path $certDir "lan.key"
    $certPath = Join-Path $certDir "lan.crt"
    $configPath = Join-Path $certDir "lan-openssl.cnf"

    if ((Test-Path -LiteralPath $keyPath) -and (Test-Path -LiteralPath $certPath)) {
        return @{
            Key = $keyPath
            Cert = $certPath
        }
    }

    Require-Command "openssl.exe"
    New-Item -ItemType Directory -Force -Path $certDir | Out-Null

    $opensslConfig = @"
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = $IpAddress

[v3_req]
subjectAltName = @alt_names

[alt_names]
IP.1 = $IpAddress
IP.2 = 127.0.0.1
DNS.1 = localhost
"@

    Set-Content -LiteralPath $configPath -Value $opensslConfig -Encoding ascii
    & openssl.exe req -x509 -nodes -days 365 -newkey rsa:2048 `
        -keyout $keyPath `
        -out $certPath `
        -config $configPath 2>$null

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to generate HTTPS certificate."
    }

    return @{
        Key = $keyPath
        Cert = $certPath
    }
}

Require-Command "node.exe"
Require-Command "npm"
Enable-SelfSignedCertificateRequests

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $root "frontend"
$logsDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$backendPid = Join-Path $logsDir "backend-windows.pid"
$frontendPid = Join-Path $logsDir "frontend-windows.pid"

$cert = Ensure-Certificate -Root $root -IpAddress $PublicIp

Stop-RecordedProcessTree -PidPath $frontendPid -Label "Open-LLM-VTuber frontend"
Stop-RecordedProcessTree -PidPath $backendPid -Label "Open-LLM-VTuber backend"
Stop-Listener -Ports @($FrontendPort, $BackendPort, $UeWsPort) -Label "Open-LLM-VTuber"
$FrontendPort = Resolve-AvailableTcpPort -PreferredPort $FrontendPort -Name "Frontend" -BindHost $BindHost
$BackendPort = Resolve-AvailableTcpPort -PreferredPort $BackendPort -Name "Backend" -BindHost $BindHost
$frontendUrl = "https://${PublicIp}:${FrontendPort}/"
$backendUrl = "https://${PublicIp}:${BackendPort}/"

Write-Host "Starting Open-LLM-VTuber Windows HTTPS services"
Write-Host "Project:  $root"
Write-Host "Bind:     $BindHost"
Write-Host "Frontend: $frontendUrl"
Write-Host "Backend:  $backendUrl"
Write-Host ""

$backendLog = Join-Path $logsDir "backend-windows.log"
$backendErr = Join-Path $logsDir "backend-windows.err.log"
$frontendLog = Join-Path $logsDir "frontend-windows.log"
$frontendErr = Join-Path $logsDir "frontend-windows.err.log"
Remove-Item $backendLog, $backendErr, $frontendLog, $frontendErr -ErrorAction SilentlyContinue

$backendProcess = $null
$frontendProcess = $null

try {
    $backendPython = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw "Missing backend Python: $backendPython"
    }

    $backendProcess = Start-Process -FilePath $backendPython `
        -ArgumentList @("-m", "uvicorn", "run_server:create_app", "--factory", "--host", $BindHost, "--port", $BackendPort, "--ssl-keyfile", ".certs\lan.key", "--ssl-certfile", ".certs\lan.crt") `
        -WorkingDirectory $root `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $backendPid -Value $backendProcess.Id -Encoding ascii

    $frontendCommand = "set VITE_HTTPS_KEY=$($cert.Key)&& set VITE_HTTPS_CERT=$($cert.Cert)&& set VITE_BACKEND_PORT=$BackendPort&& npm run dev:web -- --host $BindHost --port $FrontendPort --strictPort --force"
    $frontendProcess = Start-Process -FilePath "cmd.exe" `
        -ArgumentList @("/c", $frontendCommand) `
        -WorkingDirectory $frontendDir `
        -RedirectStandardOutput $frontendLog `
        -RedirectStandardError $frontendErr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $frontendPid -Value $frontendProcess.Id -Encoding ascii

    Wait-Http "Frontend" $frontendUrl 60 -Process $frontendProcess -StdoutLog $frontendLog -StderrLog $frontendErr | Out-Null
    Wait-Http "Backend" $backendUrl 90 -Process $backendProcess -StdoutLog $backendLog -StderrLog $backendErr | Out-Null
} catch {
    Stop-StartedProcess -Process $frontendProcess -PidPath $frontendPid -Label "Open-LLM-VTuber frontend"
    Stop-StartedProcess -Process $backendProcess -PidPath $backendPid -Label "Open-LLM-VTuber backend"
    throw
}

if (-not $NoOpen) {
    Start-Process $frontendUrl
}

Write-Host ""
Write-Host "All services are ready."
Write-Host "Frontend: $frontendUrl"
Write-Host "Backend:  $backendUrl"
Write-Host "UE WS:    ws://${PublicIp}:${UeWsPort}"
Write-Host "TTS:      run .\Start-Windows-TTS.bat separately"
Write-Host ""
Write-Host "Logs:"
Write-Host "  $backendErr"
Write-Host "  $frontendLog"

exit 0
