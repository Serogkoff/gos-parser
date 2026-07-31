"""Поиск и редактирование ключевых слов."""

import json
from pathlib import Path

from config import KEYWORDS, YONHAP_KEYWORDS
from utils.storage import (
    ALL_NEWS_FILE,
    FOUND_NEWS_FILE,
    STORAGE_LOCK,
    _load_json,
    _write_json_atomic,
)


KEYWORDS_FILE = Path(__file__).resolve().parent.parent / "keywords.json"
KEYWORD_MIGRATIONS_FILE = (
    Path(__file__).resolve().parent.parent / "keyword_migrations.json"
)
YONHAP_KEYWORDS_MIGRATION = "yonhap_keywords_v1"


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
    words = None
    if KEYWORDS_FILE.exists():
        try:
            with KEYWORDS_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                words = _clean_keywords(data)
        except (OSError, json.JSONDecodeError):
            pass
    if words is None:
        words = _clean_keywords(KEYWORDS)
    return _apply_keyword_migrations(words)


def _apply_keyword_migrations(words):
    """Один раз добавляет новые штатные слова в пользовательский список."""
    completed = []
    if KEYWORD_MIGRATIONS_FILE.exists():
        try:
            with KEYWORD_MIGRATIONS_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                completed = [str(value) for value in data]
        except (OSError, json.JSONDecodeError):
            pass

    if YONHAP_KEYWORDS_MIGRATION in completed:
        return _clean_keywords(words)

    migrated = _clean_keywords([*words, *YONHAP_KEYWORDS])
    _write_json_atomic(KEYWORDS_FILE, migrated)
    _write_json_atomic(
        KEYWORD_MIGRATIONS_FILE,
        [*completed, YONHAP_KEYWORDS_MIGRATION],
    )
    return migrated


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
    """Ищет слова в заголовках, а у Yonhap также в RSS-описании."""
    keywords = load_keywords() if keywords is None else _clean_keywords(keywords)
    found = []
    for item in news_list:
        text_parts = [str(item.get("title", ""))]
        if item.get("source") == "Yonhap":
            text_parts.append(str(item.get("summary", "")))
        text = " ".join(text_parts).casefold()
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
