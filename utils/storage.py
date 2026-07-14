"""
СОХРАНЕНИЕ РЕЗУЛЬТАТОВ И ПРОВЕРКА ДУБЛИКАТОВ
"""

import json
import os
from datetime import datetime

ALL_NEWS_FILE = "all_news.json"
FOUND_NEWS_FILE = "found_news.json"


def load_existing_urls():
    """Загружает URL уже сохранённых новостей"""
    urls = set()

    if os.path.exists(ALL_NEWS_FILE):
        with open(ALL_NEWS_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                for item in data:
                    if item.get("url"):
                        urls.add(item["url"])
            except:
                pass

    return urls


def save_results(all_news, found_news, existing_urls):
    """Сохраняет только новые новости, без дубликатов"""

    # Фильтруем дубликаты
    new_all = [n for n in all_news if n.get("url") not in existing_urls]
    new_found = [n for n in found_news if n.get("url") not in existing_urls]

    today = datetime.now().strftime('%Y-%m-%d %H:%M')

    for item in new_all:
        item['parsed_date'] = today

    for item in new_found:
        item['parsed_date'] = today

    # Загружаем старые данные
    old_all = []
    old_found = []

    if os.path.exists(ALL_NEWS_FILE):
        with open(ALL_NEWS_FILE, "r", encoding="utf-8") as f:
            try:
                old_all = json.load(f)
            except:
                pass

    if os.path.exists(FOUND_NEWS_FILE):
        with open(FOUND_NEWS_FILE, "r", encoding="utf-8") as f:
            try:
                old_found = json.load(f)
            except:
                pass

    # Объединяем
    old_all.extend(new_all)
    old_found.extend(new_found)

    # Сохраняем
    with open(ALL_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(old_all, f, ensure_ascii=False, indent=2)

    with open(FOUND_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(old_found, f, ensure_ascii=False, indent=2)

    print(f"✅ Новых: {len(new_all)} | Всего: {len(old_all)}")
    print(f"🔴 Новых совпадений: {len(new_found)} | Всего совпадений: {len(old_found)}")

    return new_found