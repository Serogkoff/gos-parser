param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$LocalHealthUrl = "http://127.0.0.1:5000/healthz",
    [string]$ExternalHealthUrl = "https://ria.tail196372.ts.net/healthz",
    [int]$ExternalFailureThreshold = 2,
    [int]$CooldownMinutes = 15,
    [int]$RequestTimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path $ProjectDir).Path
$ExternalFailureThreshold = [Math]::Max(2, $ExternalFailureThreshold)
$CooldownMinutes = [Math]::Max(5, $CooldownMinutes)
$RequestTimeoutSeconds = [Math]::Max(3, $RequestTimeoutSeconds)

$logDir = Join-Path $ProjectDir "runtime_logs"
$logFile = Join-Path $logDir "watchdog.log"
$oldLogFile = Join-Path $logDir "watchdog.log.1"
$stateFile = Join-Path $logDir "watchdog-state.json"
$maintenanceFile = Join-Path $logDir "watchdog-maintenance.lock"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-WatchdogLog {
    param([string]$Level, [string]$Message)
    if ((Test-Path -LiteralPath $logFile) -and
        (Get-Item -LiteralPath $logFile).Length -ge 5MB) {
        Move-Item -LiteralPath $logFile -Destination $oldLogFile -Force
    }
    $line = "{0} | {1,-7} | {2}" -f `
        (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

if (Test-Path -LiteralPath $maintenanceFile -PathType Leaf) {
    $maintenanceAge = (
        [DateTime]::UtcNow -
        (Get-Item -LiteralPath $maintenanceFile).LastWriteTimeUtc
    ).TotalMinutes
    if ($maintenanceAge -lt 30) {
        exit 0
    }
    Remove-Item -LiteralPath $maintenanceFile -Force
    Write-WatchdogLog `
        "WARNING" `
        "Removed a stale update lock older than 30 minutes."
}

function New-WatchdogState {
    return [ordered]@{
        ExternalFailures = 0
        LastTailscaleRestartUtc = ""
        LastWebRestartUtc = ""
    }
}

function Read-WatchdogState {
    $state = New-WatchdogState
    if (-not (Test-Path -LiteralPath $stateFile -PathType Leaf)) {
        return $state
    }
    try {
        $saved = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 |
            ConvertFrom-Json
        foreach ($name in @(
            "ExternalFailures",
            "LastTailscaleRestartUtc",
            "LastWebRestartUtc"
        )) {
            if ($saved.PSObject.Properties.Name -contains $name) {
                $state[$name] = $saved.$name
            }
        }
    } catch {
        Write-WatchdogLog "WARNING" "State file is invalid; counters were reset."
    }
    return $state
}

function Save-WatchdogState {
    param($State)
    $State | ConvertTo-Json | Set-Content `
        -LiteralPath $stateFile `
        -Encoding UTF8
}

function Test-HealthEndpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest `
            -Uri $Url `
            -UseBasicParsing `
            -TimeoutSec $RequestTimeoutSeconds
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-RestartCooldown {
    param([string]$LastRestartUtc)
    if (-not $LastRestartUtc) {
        return $false
    }
    try {
        $lastRestart = [DateTimeOffset]::Parse($LastRestartUtc)
        return ((
            [DateTimeOffset]::UtcNow - $lastRestart.ToUniversalTime()
        ).TotalMinutes -lt $CooldownMinutes)
    } catch {
        return $false
    }
}

$state = Read-WatchdogState
$localOk = Test-HealthEndpoint $LocalHealthUrl

if (-not $localOk) {
    $state.ExternalFailures = 0
    if (Test-RestartCooldown $state.LastWebRestartUtc) {
        Write-WatchdogLog "WARNING" "Local site is unavailable; web restart cooldown is active."
        Save-WatchdogState $state
        exit 0
    }
    try {
        Stop-ScheduledTask -TaskName "GosParser-Web" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName "GosParser-Web"
        $state.LastWebRestartUtc = [DateTimeOffset]::UtcNow.ToString("o")
        Write-WatchdogLog "RESTART" "Local health check failed; restarted GosParser-Web."
        Start-Sleep -Seconds 10
        if (Test-HealthEndpoint $LocalHealthUrl) {
            Write-WatchdogLog "RECOVER" "Local site is healthy again."
        } else {
            Write-WatchdogLog "ERROR" "Local site is still unavailable after restart."
        }
    } catch {
        Write-WatchdogLog "ERROR" "Failed to restart GosParser-Web: $($_.Exception.Message)"
    }
    Save-WatchdogState $state
    exit 0
}

$externalOk = Test-HealthEndpoint $ExternalHealthUrl
if ($externalOk) {
    if ([int]$state.ExternalFailures -gt 0) {
        Write-WatchdogLog "RECOVER" "External Funnel recovered without restart."
    }
    $state.ExternalFailures = 0
    Save-WatchdogState $state
    exit 0
}

$state.ExternalFailures = [Math]::Min(
    $ExternalFailureThreshold,
    [int]$state.ExternalFailures + 1
)
Write-WatchdogLog `
    "WARNING" `
    "Local site is healthy but external Funnel failed: attempt $($state.ExternalFailures) of $ExternalFailureThreshold."

if ([int]$state.ExternalFailures -lt $ExternalFailureThreshold) {
    Save-WatchdogState $state
    exit 0
}

if (Test-RestartCooldown $state.LastTailscaleRestartUtc) {
    Write-WatchdogLog "WARNING" "Funnel is unavailable; Tailscale restart cooldown is active."
    Save-WatchdogState $state
    exit 0
}

try {
    Restart-Service -Name "Tailscale" -Force
    $state.LastTailscaleRestartUtc = [DateTimeOffset]::UtcNow.ToString("o")
    Write-WatchdogLog "RESTART" "External check failed twice; restarted the Tailscale service."
    Start-Sleep -Seconds 20
    if (Test-HealthEndpoint $ExternalHealthUrl) {
        $state.ExternalFailures = 0
        Write-WatchdogLog "RECOVER" "External Funnel is healthy again."
    } else {
        Write-WatchdogLog "ERROR" "External Funnel is still unavailable after Tailscale restart."
    }
} catch {
    Write-WatchdogLog "ERROR" "Failed to restart Tailscale: $($_.Exception.Message)"
}

Save-WatchdogState $state
