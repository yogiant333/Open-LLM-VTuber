param(
    [Parameter(Mandatory = $true)]
    [string]$AudioPath,

    [string]$BaseUrl = "http://127.0.0.1:18080",
    [string]$Provider = "qwen3_asr_gguf",
    [int]$Iterations = 5,
    [int]$Warmup = 1,
    [string]$ReferenceText = "",
    [string[]]$Hotwords = @()
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $AudioPath)) {
    throw "Audio file not found: $AudioPath"
}

$resolvedAudio = (Resolve-Path -LiteralPath $AudioPath).Path
$endpoint = "$BaseUrl/api/asr-benchmark/transcribe/$Provider"
$hotwordsJson = ConvertTo-Json -InputObject $Hotwords -Compress

Write-Host "ASR latency test"
Write-Host "Endpoint: $endpoint"
Write-Host "Audio: $resolvedAudio"
Write-Host "Warmup: $Warmup  Iterations: $Iterations"
Write-Host ""

$rows = New-Object System.Collections.Generic.List[object]
$totalRuns = $Warmup + $Iterations

for ($i = 1; $i -le $totalRuns; $i++) {
    $isWarmup = $i -le $Warmup
    $label = if ($isWarmup) { "warmup" } else { "run" }
    $ordinal = if ($isWarmup) { $i } else { $i - $Warmup }

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $raw = & curl.exe --noproxy "*" -s `
        -X POST `
        -F "file=@$resolvedAudio;type=audio/wav" `
        -F "hotwords=$hotwordsJson" `
        -F "reference_text=$ReferenceText" `
        $endpoint
    $timer.Stop()

    if ($LASTEXITCODE -ne 0) {
        throw "curl failed with exit code $LASTEXITCODE"
    }

    $json = $raw | ConvertFrom-Json
    if (-not $json.results -or $json.results.Count -lt 1) {
        throw "Unexpected response: $raw"
    }

    $result = $json.results[0]
    $row = [pscustomobject]@{
        Kind = $label
        Index = $ordinal
        AudioMs = [double]$json.audio.duration_ms
        AsrMs = [double]$result.elapsed_ms
        HttpMs = [math]::Round($timer.Elapsed.TotalMilliseconds, 3)
        Rtf = [double]$result.rtf
        Text = [string]$result.text
        Error = [string]$result.error
    }
    $rows.Add($row)

    "{0} {1}: audio={2:n0}ms asr={3:n1}ms http={4:n1}ms rtf={5:n3} text={6}" -f `
        $row.Kind, $row.Index, $row.AudioMs, $row.AsrMs, $row.HttpMs, $row.Rtf, $row.Text
}

$measured = $rows | Where-Object { $_.Kind -eq "run" -and -not $_.Error }
if ($measured.Count -gt 0) {
    $asr = $measured | Measure-Object -Property AsrMs -Average -Minimum -Maximum
    $http = $measured | Measure-Object -Property HttpMs -Average -Minimum -Maximum
    $rtf = $measured | Measure-Object -Property Rtf -Average -Minimum -Maximum

    Write-Host ""
    Write-Host "Summary excluding warmup"
    "ASR ms:  avg={0:n1} min={1:n1} max={2:n1}" -f $asr.Average, $asr.Minimum, $asr.Maximum
    "HTTP ms: avg={0:n1} min={1:n1} max={2:n1}" -f $http.Average, $http.Minimum, $http.Maximum
    "RTF:     avg={0:n3} min={1:n3} max={2:n3}" -f $rtf.Average, $rtf.Minimum, $rtf.Maximum
}

