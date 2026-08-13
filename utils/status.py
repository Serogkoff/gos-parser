import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock

from utils.logger import get_logger


PROJECT_DIR = Path(__file__).resolve().parent.parent
STATUS_FILE = PROJECT_DIR / "parser_status.json"
logger = get_logger("status")
STATUS_LOCK = RLock()


def save_parser_status(statuses, project_version, now=None, merge=False):
    """Сохраняет состояние источников и время последнего успешного запуска."""
    with STATUS_LOCK:
        return _save_parser_status(
            statuses,
            project_version,
            now=now,
            merge=merge,
        )


def _save_parser_status(statuses, project_version, now=None, merge=False):
    now = now or datetime.now()
    checked_at = now.strftime("%Y-%m-%d %H:%M:%S")
    previous = _load_previous()
    previous_by_source = {
        item.get("source"): item for item in previous.get("sources", [])
    }

    prepared = []
    for status in statuses:
        item = dict(status)
        item["checked_at"] = checked_at

        old = previous_by_source.get(item.get("source"), {})
        if item.get("status") == "disabled":
            item["last_success"] = old.get("last_success", "")
            item["failure_streak"] = int(old.get("failure_streak", 0))
            item["availability"] = "disabled"
        elif item.get("status") == "ok":
            item["last_success"] = checked_at
            item["failure_streak"] = 0
            item["availability"] = "ok"
        else:
            item["last_success"] = old.get("last_success", "")
            item["failure_streak"] = int(old.get("failure_streak", 0)) + 1
            item["availability"] = _availability(
                item["last_success"],
                now,
            )
        prepared.append(item)

    if merge:
        updates = {
            item.get("source"): item
            for item in prepared
        }
        merged = []
        for old in previous.get("sources", []):
            source = old.get("source")
            merged.append(updates.pop(source, old))
        merged.extend(updates.values())
        prepared = merged

    document = {
        "project_version": project_version,
        "generated_at": checked_at,
        "summary": {
            "total_sources": len(prepared),
            "ok": sum(item["status"] == "ok" for item in prepared),
            "empty": sum(item["status"] == "empty" for item in prepared),
            "errors": sum(item["status"] == "error" for item in prepared),
            "disabled": sum(item["status"] == "disabled" for item in prepared),
            "total_news": sum(item.get("news_count", 0) for item in prepared),
            "total_matches": sum(
                item.get("matches_count", 0) for item in prepared
            ),
        },
        "sources": prepared,
    }
    _write_atomic(document)
    return document


def _availability(last_success, now):
    """Отличает краткий сетевой сбой от длительно неработающего источника."""
    if not last_success:
        return "down"
    try:
        successful_at = datetime.strptime(last_success, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return "down"
    return "temporary" if now - successful_at <= timedelta(hours=24) else "down"


def print_status_table(statuses):
    """Печатает компактную сводку после полного цикла."""
    print("\n" + "=" * 94)
    print("📡 СОСТОЯНИЕ ИСТОЧНИКОВ")
    print("=" * 94)
    print(
        f"{'Источник':<24} {'Статус':<9} {'Новостей':>8} "
        f"{'С датой':>8} {'Совп.':>6} {'Время':>9}"
    )
    print("-" * 94)

    labels = {
        "ok": "✅ OK",
        "empty": "⚠️ Пусто",
        "error": "❌ Ошибка",
        "disabled": "⏸ Пауза",
    }
    for item in statuses:
        source = item.get("source", "")[:24]
        label = labels.get(item.get("status"), item.get("status", ""))[:9]
        print(
            f"{source:<24} {label:<9} "
            f"{item.get('news_count', 0):>8} "
            f"{item.get('with_date', 0):>8} "
            f"{item.get('matches_count', 0):>6} "
            f"{item.get('duration_seconds', 0):>7.2f} с"
        )
    print("=" * 94)


def _load_previous():
    if not STATUS_FILE.exists():
        return {}
    try:
        with STATUS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as error:
        logger.warning(f"Не удалось прочитать {STATUS_FILE.name}: {error}")
        return {}


def _write_atomic(data):
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=STATUS_FILE.parent,
            prefix=f".{STATUS_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
            temp_name = file.name
        os.replace(temp_name, STATUS_FILE)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
