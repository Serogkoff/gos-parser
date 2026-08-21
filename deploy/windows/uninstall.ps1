$ErrorActionPreference = "Stop"

foreach ($taskName in @("GosParser-Worker", "GosParser-Web")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Удалена задача: $taskName"
    }
}

Write-Host "Код, news.db, резервные копии и логи не удалялись." -ForegroundColor Green
