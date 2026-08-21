param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path $ProjectDir).Path

if (-not $PythonExe) {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}
$PythonExe = (Resolve-Path $PythonExe).Path
$PythonWindowless = Join-Path (Split-Path $PythonExe) "pythonw.exe"
if (-not (Test-Path -LiteralPath $PythonWindowless -PathType Leaf)) {
    $PythonWindowless = $PythonExe
}

$entrypoint = Join-Path $ProjectDir "scripts\windows_entrypoint.py"
$worker = Join-Path $ProjectDir "main.py"
$web = Join-Path $ProjectDir "web_app.py"

foreach ($path in @($entrypoint, $worker, $web, $PythonExe)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Файл не найден: $path"
    }
}

$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -Hidden

function Install-GosParserTask {
    param(
        [string]$TaskName,
        [string]$Role,
        [string]$Description
    )
    $arguments = "-u `"$entrypoint`" $Role"
    $action = New-ScheduledTaskAction `
        -Execute $PythonWindowless `
        -Argument $arguments `
        -WorkingDirectory $ProjectDir
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $Description `
        -Force | Out-Null
}

Install-GosParserTask `
    -TaskName "GosParser-Worker" `
    -Role "worker" `
    -Description "Сбор новостей gos-parser"
Install-GosParserTask `
    -TaskName "GosParser-Web" `
    -Role "web" `
    -Description "Локальный веб-интерфейс gos-parser"

Start-ScheduledTask -TaskName "GosParser-Worker"
Start-ScheduledTask -TaskName "GosParser-Web"

Write-Host "Готово. Задачи установлены для пользователя $userId." -ForegroundColor Green
Write-Host "Сайт: http://127.0.0.1:5000"
Write-Host "Логи: $(Join-Path $ProjectDir 'runtime_logs')"
Write-Host "Проверка: .\deploy\windows\status.ps1"
