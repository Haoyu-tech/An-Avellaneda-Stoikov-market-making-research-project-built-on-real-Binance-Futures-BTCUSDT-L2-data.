param(
    [string]$Symbol = "BTCUSDT",
    [int]$MaxSeconds = 60,
    [int]$FlushEvery = 500,
    [double]$FlushInterval = 1.0,
    [switch]$IncludeTrades
)

$ErrorActionPreference = "Stop"

$python = "D:\software\anaconda3\envs\quant\python.exe"
$script = Join-Path $PSScriptRoot "collect_as_l2.py"
$projectRoot = Split-Path $PSScriptRoot -Parent
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $projectRoot "logs"
$stdoutPath = Join-Path $logDir ("collect_as_l2_{0}_{1}.out.log" -f $Symbol.ToLower(), $timestamp)
$stderrPath = Join-Path $logDir ("collect_as_l2_{0}_{1}.err.log" -f $Symbol.ToLower(), $timestamp)

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$arguments = @(
    $script
    "--symbol", $Symbol
    "--max-seconds", "$MaxSeconds"
    "--flush-every", "$FlushEvery"
    "--flush-interval", "$FlushInterval"
    "--quiet"
)

if ($IncludeTrades) {
    $arguments += "--include-trades"
}

$process = Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

Write-Host ("Started background collection for {0}" -f $Symbol)
Write-Host ("PID:  {0}" -f $process.Id)
Write-Host ("Out:  {0}" -f $stdoutPath)
Write-Host ("Err:  {0}" -f $stderrPath)
