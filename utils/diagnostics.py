"""Понятные предупреждения для администраторских страниц Монитора."""

from collections import defaultdict
from datetime import datetime, timedelta


CHECK_STALE_AFTER = {
    "Госструктуры": timedelta(minutes=30),
    "Информагентства": timedelta(minutes=20),
    "Газеты": timedelta(hours=36),
}

NEWS_STALE_AFTER = {
    "Госструктуры": timedelta(days=14),
    "Информагентства": timedelta(hours=12),
    "Газеты": timedelta(days=3),
}


def source_alerts(sources, now=None):
    """Диагностирует источники с учётом частоты обновления их группы."""
    moment = now or datetime.now()
    alerts = []
    stale_checks = defaultdict(list)
    missing_statuses = defaultdict(list)

    for item in sources:
        if not item.get("enabled", True):
            continue

        source = item.get("source", "Источник")
        group = item.get("group_label", "Госструктуры")
        status = item.get("status_class", "unknown")
        failures = _integer(item.get("failure_streak"))

        if status in {"pending", "running"}:
            continue

        if status == "unknown":
            missing_statuses[group].append(source)
            continue

        if status == "error":
            level = "critical" if failures >= 3 else "warning"
            suffix = f" подряд: {failures}" if failures else ""
            alerts.append(_alert(
                level,
                "source-error",
                source,
                f"{source}: ошибка парсинга",
                f"Неудачных проверок{suffix}. {item.get('error') or 'Источник не ответил корректно.'}",
            ))
            continue

        if status == "empty":
            level = "critical" if failures >= 3 else "warning"
            alerts.append(_alert(
                level,
                "empty-result",
                source,
                f"{source}: пустая выдача",
                (
                    f"Парсер вернул 0 материалов"
                    f"{f' уже {failures} проверок подряд' if failures > 1 else ''}."
                ),
            ))
            continue

        checked_at = _as_datetime(item.get("checked_at"))
        check_limit = CHECK_STALE_AFTER.get(group, timedelta(hours=1))
        if source == "Киодо (共同通信)":
            check_limit = timedelta(minutes=75)
        if checked_at and moment - checked_at > check_limit:
            stale_checks[group].append((source, moment - checked_at))
            continue

        last_received = _as_datetime(item.get("last_received"))
        news_limit = NEWS_STALE_AFTER.get(group, timedelta(days=7))
        if last_received and moment - last_received > news_limit:
            alerts.append(_alert(
                "warning",
                "no-new-materials",
                source,
                f"{source}: давно нет новых материалов",
                f"Последнее пополнение базы было {_duration(moment - last_received)} назад.",
            ))
        elif not last_received and status == "ok" and _integer(item.get("total_news")) == 0:
            alerts.append(_alert(
                "warning",
                "never-received",
                source,
                f"{source}: в базе нет материалов",
                "Проверка прошла, но от этого источника ещё ничего не сохранено.",
            ))

    for group, stale in stale_checks.items():
        if len(stale) >= 3:
            oldest = max(age for _source, age in stale)
            alerts.append(_alert(
                "critical",
                "stale-schedule",
                group,
                f"{group}: расписание могло остановиться",
                (
                    f"Давно не проверялись {len(stale)} источников; "
                    f"самая старая проверка была {_duration(oldest)} назад. "
                    "Проверьте, запущен ли main.py."
                ),
            ))
        else:
            for source, age in stale:
                alerts.append(_alert(
                    "warning",
                    "stale-check",
                    source,
                    f"{source}: давно не проверялся",
                    f"Последняя проверка была {_duration(age)} назад.",
                ))

    for group, names in missing_statuses.items():
        if len(names) >= 3:
            alerts.append(_alert(
                "warning",
                "missing-status-group",
                group,
                f"{group}: нет данных о проверках",
                f"Статус отсутствует у {len(names)} источников. Запустите main.py.",
            ))
        else:
            for source in names:
                alerts.append(_alert(
                    "warning",
                    "missing-status",
                    source,
                    f"{source}: ещё не проверялся",
                    "Статус появится после запуска main.py.",
                ))

    return _sorted(alerts)


def system_alerts(database, backups, now=None):
    """Проверяет целостность базы и актуальность резервной копии."""
    moment = now or datetime.now()
    alerts = []
    integrity = str(database.get("integrity", "")).strip().casefold()
    if integrity != "ok":
        alerts.append(_alert(
            "critical",
            "database-integrity",
            "SQLite",
            "Нарушена целостность SQLite",
            f"PRAGMA integrity_check вернула: {database.get('integrity') or 'нет результата'}.",
        ))

    if not database.get("json_migrated", False):
        alerts.append(_alert(
            "warning",
            "json-migration",
            "SQLite",
            "Миграция JSON не подтверждена",
            "Проверьте импорт старой базы перед удалением JSON-файлов.",
        ))

    backup_dates = [
        date for date in (_as_datetime(item.get("modified_at")) for item in backups)
        if date is not None
    ]
    if not backup_dates:
        alerts.append(_alert(
            "critical",
            "no-backup",
            "Резервные копии",
            "Нет резервной копии базы",
            "Создайте копию кнопкой ниже или запустите main.py.",
        ))
    else:
        age = moment - max(backup_dates)
        if age > timedelta(hours=36):
            alerts.append(_alert(
                "warning",
                "stale-backup",
                "Резервные копии",
                "Резервная копия устарела",
                f"Последний снимок создан {_duration(age)} назад.",
            ))

    return _sorted(alerts)


def alert_summary(alerts):
    """Считает предупреждения по степени важности."""
    return {
        "total": len(alerts),
        "critical": sum(item["level"] == "critical" for item in alerts),
        "warning": sum(item["level"] == "warning" for item in alerts),
    }


def _alert(level, code, subject, title, message):
    return {
        "level": level,
        "level_label": "Критично" if level == "critical" else "Внимание",
        "code": code,
        "subject": subject,
        "title": title,
        "message": message,
    }


def _sorted(alerts):
    priority = {"critical": 0, "warning": 1}
    return sorted(
        alerts,
        key=lambda item: (priority.get(item["level"], 9), item["title"].casefold()),
    )


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _integer(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _duration(value):
    seconds = max(0, int(value.total_seconds()))
    if seconds >= 86400:
        days = seconds // 86400
        return f"{days} дн."
    if seconds >= 3600:
        hours = seconds // 3600
        return f"{hours} ч."
    return f"{max(1, seconds // 60)} мин."
