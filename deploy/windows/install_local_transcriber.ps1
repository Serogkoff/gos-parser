param(
    [string]$SourceRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $SourceRoot) {
    foreach ($Candidate in @($PSScriptRoot, (Join-Path $PSScriptRoot "..\.."))) {
        if (Test-Path (Join-Path $Candidate "local_transcriber\server.py")) {
            $SourceRoot = (Resolve-Path $Candidate).Path
            break
        }
    }
}

$SourceDir = Join-Path $SourceRoot "local_transcriber"
$InstallDir = Join-Path $env:LOCALAPPDATA "GosParserTranscriber"
$VenvDir = Join-Path $InstallDir ".venv"
$TaskName = "GosParser-Transcriber"

if (-not (Test-Path (Join-Path $SourceDir "server.py"))) {
    throw "Local transcriber sources were not found: $SourceDir"
}

# Stop an older recognizer before updating files and loading the two models.
# This prevents the previous ONNX session from competing for RAM during setup.
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

$PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
$Python = Get-Command "python.exe" -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item (Join-Path $SourceDir "server.py") $InstallDir -Force
Copy-Item (Join-Path $SourceDir "preload.py") $InstallDir -Force
Copy-Item (Join-Path $SourceDir "requirements.txt") $InstallDir -Force

Write-Host "Creating local Python environment..." -ForegroundColor Cyan
if ($PyLauncher) {
    & $PyLauncher.Source -3 -m venv $VenvDir
}
elseif ($Python) {
    & $Python.Source -m venv $VenvDir
}
else {
    throw "Python 3.10-3.14 is required. Install Python from python.org and run this installer again."
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
if (-not (Test-Path $VenvPython)) {
    throw "The local Python environment was not created."
}

Write-Host "Installing the CPU recognition engine..." -ForegroundColor Cyan
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $InstallDir "requirements.txt")

Write-Host "Downloading GigaAM once (the files remain in the local cache)..." -ForegroundColor Cyan
& $VenvPython (Join-Path $InstallDir "preload.py")

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute $VenvPythonw `
    -Argument ('"{0}"' -f (Join-Path $InstallDir "server.py")) `
    -WorkingDirectory $InstallDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Local GigaAM transcription for gos-parser" `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

try {
    $Health = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8765/health" `
        -Headers @{Origin = "https://ria.tail196372.ts.net"} `
        -TimeoutSec 10
    Write-Host "Local transcriber is ready: $($Health.engine)" -ForegroundColor Green
}
catch {
    throw "The task was installed, but its health check failed. See $InstallDir\transcriber.log"
}

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
