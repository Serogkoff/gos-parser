param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$ExternalHealthUrl = "https://ria.tail196372.ts.net/healthz"
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path $ProjectDir).Path
$watchdog = Join-Path $ProjectDir "deploy\windows\watchdog.ps1"
if (-not (Test-Path -LiteralPath $watchdog -PathType Leaf)) {
    throw "Watchdog script not found: $watchdog"
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principalContext = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principalContext.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
    throw "Run PowerShell as Administrator to install the watchdog."
}

$powerShellExe = Join-Path `
    $env:SystemRoot `
    "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = (
    "-NoProfile -NonInteractive -ExecutionPolicy Bypass " +
    "-File `"$watchdog`" " +
    "-ProjectDir `"$ProjectDir`" " +
    "-ExternalHealthUrl `"$ExternalHealthUrl`""
)
$action = New-ScheduledTaskAction `
    -Execute $powerShellExe `
    -Argument $arguments `
    -WorkingDirectory $ProjectDir
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$repeatTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -Hidden

Register-ScheduledTask `
    -TaskName "GosParser-Watchdog" `
    -Action $action `
    -Trigger @($startupTrigger, $repeatTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Description "Monitor local web app and external Tailscale Funnel" `
    -Force | Out-Null

Start-ScheduledTask -TaskName "GosParser-Watchdog"
Write-Host "GosParser-Watchdog installed and started." -ForegroundColor Green
Write-Host "Health check every 5 minutes: $ExternalHealthUrl"
Write-Host "Log: $(Join-Path $ProjectDir 'runtime_logs\watchdog.log')"
