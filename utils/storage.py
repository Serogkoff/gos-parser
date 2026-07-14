import json
import os
from datetime import datetime

ALL_NEWS_FILE = "all_news.json"
FOUND_NEWS_FILE = "found_news.json"


def load_existing_urls():
    urls = set()
    if os.path.exists(ALL_NEWS_FILE):
        with open(ALL_NEWS_FILE, "r", encoding="utf-8") as f:
            try:
                for item in json.load(f):
                    if item.get("url"): urls.add(item["url"])
            except:
                pass
    return urls


def save_results(all_news, found_news, existing_urls):
    new_all = [n for n in all_news if n.get("url") not in existing_urls]
    new_found = [n for n in found_news if n.get("url") not in existing_urls]

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    for item in new_all:
        if not item.get('parsed_date'):
            item['parsed_date'] = now
    for item in new_found:
        if not item.get('parsed_date'):
            item['parsed_date'] = now

    old_all, old_found = [], []
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

    old_all.extend(new_all)
    old_found.extend(new_found)

    def sort_key(x):
        d = x.get('date', '')
        return d if d else x.get('parsed_date', '')

    old_all.sort(key=sort_key, reverse=True)
    old_found.sort(key=sort_key, reverse=True)

    with open(ALL_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(old_all, f, ensure_ascii=False, indent=2)
    with open(FOUND_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(old_found, f, ensure_ascii=False, indent=2)

    print(f"✅ Новых: {len(new_all)} | Всего: {len(old_all)}")
    print(f"🔴 Новых совпадений: {len(new_found)} | Всего: {len(old_found)}")
    return new_found