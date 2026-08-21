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
$taskNames = @("GosParser-Worker", "GosParser-Web")

Push-Location $ProjectDir
try {
    if (git status --porcelain) {
        throw "Рабочее дерево изменено. Обновление отменено."
    }
    if ((Test-Path -LiteralPath ".git\rebase-apply") -or
        (Test-Path -LiteralPath ".git\rebase-merge") -or
        (Test-Path -LiteralPath ".git\MERGE_HEAD")) {
        throw "Git-операция не завершена. Обновление отменено."
    }

    git fetch origin main
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось получить origin/main."
    }

    git merge-base --is-ancestor HEAD origin/main
    if ($LASTEXITCODE -ne 0) {
        throw "Текущую ветку нельзя безопасно обновить fast-forward."
    }

    $currentCommit = (git rev-parse HEAD).Trim()
    $newCommit = (git rev-parse origin/main).Trim()
    if ($currentCommit -eq $newCommit) {
        Write-Host "Обновлений нет: $currentCommit" -ForegroundColor Green
        return
    }

    $dependencyChanges = git diff --name-only HEAD origin/main -- requirements.txt
    if ($dependencyChanges) {
        throw "Изменился requirements.txt. Зависимости нужно обновить вручную."
    }

    $testDir = Join-Path `
        ([System.IO.Path]::GetTempPath()) `
        ("gos-parser-update-" + [guid]::NewGuid().ToString("N"))
    try {
        git worktree add --detach $testDir origin/main
        if ($LASTEXITCODE -ne 0) {
            throw "Не удалось создать временную копию для тестов."
        }
        Push-Location $testDir
        try {
            & $PythonExe -m unittest discover -s test -p "test_*.py" -v
            if ($LASTEXITCODE -ne 0) {
                throw "Тесты новой версии не прошли. Рабочая версия не изменена."
            }
        } finally {
            Pop-Location
        }
    } finally {
        if (Test-Path -LiteralPath $testDir) {
            git worktree remove --force $testDir
        }
    }

    $tasksStopped = $false
    try {
        foreach ($taskName in $taskNames) {
            Stop-ScheduledTask `
                -TaskName $taskName `
                -ErrorAction SilentlyContinue
        }
        $tasksStopped = $true

        & $PythonExe -c `
            "from utils.storage import create_manual_backup; print(create_manual_backup()['path'])"
        if ($LASTEXITCODE -ne 0) {
            throw "Не удалось создать резервную копию базы."
        }

        git merge --ff-only origin/main
        if ($LASTEXITCODE -ne 0) {
            throw "Не удалось применить проверенное обновление."
        }
    } finally {
        if ($tasksStopped) {
            foreach ($taskName in $taskNames) {
                Start-ScheduledTask -TaskName $taskName
            }
        }
    }

    Write-Host "Обновление установлено: $newCommit" -ForegroundColor Green
    Write-Host "Проверка: .\deploy\windows\status.ps1"
} finally {
    Pop-Location
}
