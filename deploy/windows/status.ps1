param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path $ProjectDir).Path

Get-ScheduledTask -TaskName "GosParser-Worker", "GosParser-Web" |
    Get-ScheduledTaskInfo |
    Select-Object TaskName, LastRunTime, LastTaskResult, NextRunTime

Write-Host ""
try {
    $response = Invoke-WebRequest `
        -Uri "http://127.0.0.1:5000/healthz" `
        -UseBasicParsing `
        -TimeoutSec 10
    Write-Host "Сайт: OK ($($response.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "Сайт пока не отвечает: $($_.Exception.Message)" -ForegroundColor Yellow
}

$logDir = Join-Path $ProjectDir "runtime_logs"
if (Test-Path -LiteralPath $logDir) {
    Get-ChildItem -LiteralPath $logDir -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object Name, Length, LastWriteTime
}
