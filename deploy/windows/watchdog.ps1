param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$LocalHealthUrl = "http://127.0.0.1:5000/healthz",
    [string]$ExternalHealthUrl = "https://ria.tail196372.ts.net/healthz",
    [string]$ExternalProbeUrl = "",
    [int]$ExternalFailureThreshold = 2,
    [int]$ExternalSlowThreshold = 3,
    [double]$SlowResponseSeconds = 5,
    [int]$CooldownMinutes = 20,
    [int]$RequestTimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path $ProjectDir).Path
$ExternalFailureThreshold = [Math]::Max(2, $ExternalFailureThreshold)
$ExternalSlowThreshold = [Math]::Max(2, $ExternalSlowThreshold)
$SlowResponseSeconds = [Math]::Max(2, $SlowResponseSeconds)
$CooldownMinutes = [Math]::Max(5, $CooldownMinutes)
$RequestTimeoutSeconds = [Math]::Max(3, $RequestTimeoutSeconds)
if (-not $ExternalProbeUrl) {
    $externalOrigin = ([Uri]$ExternalHealthUrl).GetLeftPart(
        [UriPartial]::Authority
    )
    $ExternalProbeUrl = "$externalOrigin/static/news.css"
}

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
        ExternalSlowChecks = 0
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
            "ExternalSlowChecks",
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

function Measure-ExternalTransfer {
    param([string]$Url)
    $separator = "?"
    if ($Url.Contains("?")) {
        $separator = "&"
    }
    $probeUrl = "$Url$separator`_watchdog=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-WebRequest `
            -Uri $probeUrl `
            -UseBasicParsing `
            -Headers @{ "Cache-Control" = "no-cache" } `
            -TimeoutSec $RequestTimeoutSeconds
        $stopwatch.Stop()
        $byteCount = [Text.Encoding]::UTF8.GetByteCount(
            [string]$response.Content
        )
        return [pscustomobject]@{
            Ok = ($response.StatusCode -eq 200 -and $byteCount -ge 1024)
            Seconds = $stopwatch.Elapsed.TotalSeconds
            Bytes = $byteCount
        }
    } catch {
        $stopwatch.Stop()
        return [pscustomobject]@{
            Ok = $false
            Seconds = $stopwatch.Elapsed.TotalSeconds
            Bytes = 0
        }
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
    $state.ExternalSlowChecks = 0
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
$restartReason = ""
if (-not $externalOk) {
    $state.ExternalSlowChecks = 0
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
    $restartReason = "External health check failed $ExternalFailureThreshold times"
} else {
    if ([int]$state.ExternalFailures -gt 0) {
        Write-WatchdogLog "RECOVER" "External health check recovered."
    }
    $state.ExternalFailures = 0
    $probe = Measure-ExternalTransfer $ExternalProbeUrl
    $probeSeconds = [Math]::Round($probe.Seconds, 2)
    $probeKilobytes = [Math]::Round($probe.Bytes / 1KB, 1)
    if ($probe.Ok -and $probe.Seconds -le $SlowResponseSeconds) {
        if ([int]$state.ExternalSlowChecks -gt 0) {
            Write-WatchdogLog `
                "RECOVER" `
                "External transfer recovered: ${probeKilobytes}KB in ${probeSeconds}s."
        }
        $state.ExternalSlowChecks = 0
        Save-WatchdogState $state
        exit 0
    }

    $state.ExternalSlowChecks = [Math]::Min(
        $ExternalSlowThreshold,
        [int]$state.ExternalSlowChecks + 1
    )
    Write-WatchdogLog `
        "WARNING" `
        "External transfer is slow or incomplete: ${probeKilobytes}KB in ${probeSeconds}s; attempt $($state.ExternalSlowChecks) of $ExternalSlowThreshold."
    if ([int]$state.ExternalSlowChecks -lt $ExternalSlowThreshold) {
        Save-WatchdogState $state
        exit 0
    }
    $restartReason = "External transfer exceeded ${SlowResponseSeconds}s for $ExternalSlowThreshold checks"
}

if (Test-RestartCooldown $state.LastTailscaleRestartUtc) {
    Write-WatchdogLog "WARNING" "Funnel is unavailable; Tailscale restart cooldown is active."
    Save-WatchdogState $state
    exit 0
}

try {
    Restart-Service -Name "Tailscale" -Force
    $state.LastTailscaleRestartUtc = [DateTimeOffset]::UtcNow.ToString("o")
    Write-WatchdogLog "RESTART" "$restartReason; restarted the Tailscale service."
    Start-Sleep -Seconds 20
    $recovered = Test-HealthEndpoint $ExternalHealthUrl
    if ($recovered) {
        $recoveryProbe = Measure-ExternalTransfer $ExternalProbeUrl
        $recovered = (
            $recoveryProbe.Ok -and
            $recoveryProbe.Seconds -le $SlowResponseSeconds
        )
    }
    if ($recovered) {
        $state.ExternalFailures = 0
        $state.ExternalSlowChecks = 0
        Write-WatchdogLog "RECOVER" "External Funnel is healthy and fast again."
    } else {
        Write-WatchdogLog "ERROR" "External Funnel is still unavailable or slow after Tailscale restart."
    }
} catch {
    Write-WatchdogLog "ERROR" "Failed to restart Tailscale: $($_.Exception.Message)"
}

Save-WatchdogState $state
