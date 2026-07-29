"""Поиск и редактирование ключевых слов."""

import json
from pathlib import Path

from config import KEYWORDS
from utils.storage import (
    ALL_NEWS_FILE,
    FOUND_NEWS_FILE,
    STORAGE_LOCK,
    _load_json,
    _write_json_atomic,
)


KEYWORDS_FILE = Path(__file__).resolve().parent.parent / "keywords.json"


def _clean_keywords(words):
    result = []
    seen = set()
    for word in words:
        word = str(word).strip()
        key = word.casefold()
        if word and key not in seen:
            seen.add(key)
            result.append(word)
    return result


def load_keywords():
    if KEYWORDS_FILE.exists():
        try:
            with KEYWORDS_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                return _clean_keywords(data)
        except (OSError, json.JSONDecodeError):
            pass
    return _clean_keywords(KEYWORDS)


def save_keywords(words):
    words = _clean_keywords(words)
    _write_json_atomic(KEYWORDS_FILE, words)
    return words


def add_keyword(word):
    return save_keywords([*load_keywords(), word])


def remove_keyword(word):
    needle = word.strip().casefold()
    return save_keywords(
        keyword for keyword in load_keywords() if keyword.casefold() != needle
    )


def search_keywords(news_list, keywords=None):
    """Ищет активные ключевые слова в заголовках новостей."""
    keywords = load_keywords() if keywords is None else _clean_keywords(keywords)
    found = []
    for item in news_list:
        text = item.get("title", "").casefold()
        matched = [kw for kw in keywords if kw.casefold() in text]
        if matched:
            copy = dict(item)
            copy["keywords"] = matched
            found.append(copy)
    return found


def rebuild_found_news():
    """Пересобирает раздел «Совпадения» после изменения списка слов."""
    with STORAGE_LOCK:
        found = search_keywords(_load_json(ALL_NEWS_FILE))
        _write_json_atomic(FOUND_NEWS_FILE, found)
    return found
