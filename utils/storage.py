import json
import os
import tempfile
from threading import RLock
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger
from utils.news import deduplicate_news, merge_news, normalize_url

PROJECT_DIR = Path(__file__).resolve().parent.parent
ALL_NEWS_FILE = PROJECT_DIR / "all_news.json"
FOUND_NEWS_FILE = PROJECT_DIR / "found_news.json"
logger = get_logger("storage")
STORAGE_LOCK = RLock()


def _load_json(path):
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError("ожидался JSON-массив")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as error:
        logger.error(f"Не удалось прочитать {path.name}: {error}")
        return []


def _write_json_atomic(path, data):
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
            temp_name = file.name
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def load_existing_urls():
    return {
        normalize_url(item["url"])
        for item in _load_json(ALL_NEWS_FILE)
        if item.get("url")
    }


def save_results(all_news, found_news, existing_urls):
    with STORAGE_LOCK:
        return _save_results(all_news, found_news, existing_urls)


def _save_results(all_news, found_news, existing_urls):
    all_news = deduplicate_news(all_news)
    found_news = deduplicate_news(found_news)
    new_all = [
        n for n in all_news
        if normalize_url(n.get("url", "")) not in existing_urls
    ]
    new_found = [
        n for n in found_news
        if normalize_url(n.get("url", "")) not in existing_urls
    ]

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    for item in new_all:
        if not item.get('parsed_date'):
            item['parsed_date'] = now
    for item in new_found:
        if not item.get('parsed_date'):
            item['parsed_date'] = now

    old_all = _load_json(ALL_NEWS_FILE)
    old_found = _load_json(FOUND_NEWS_FILE)

    # Передаём все свежие записи, а не только новые: так уже сохранённые
    # материалы получают найденную позднее дату публикации.
    old_all = merge_news(old_all, all_news)
    old_found = merge_news(old_found, found_news)

    def sort_key(x):
        d = x.get('date', '')
        return d if d else x.get('parsed_date', '')

    old_all.sort(key=sort_key, reverse=True)
    old_found.sort(key=sort_key, reverse=True)

    _write_json_atomic(ALL_NEWS_FILE, old_all)
    _write_json_atomic(FOUND_NEWS_FILE, old_found)

    print(f"✅ Новых: {len(new_all)} | Всего: {len(old_all)}")
    print(f"🔴 Новых совпадений: {len(new_found)} | Всего: {len(old_found)}")
    return new_found
