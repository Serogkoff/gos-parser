"""Парсер японских материалов Kyodo с главной страницы 47NEWS."""

import json
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Киодо (共同通信)"
HOME_URL = "https://www.47news.jp/"
PUBLISHER_NAME = "共同通信"
MAX_AGE_DAYS = 30

# На главной странице 47NEWS каждая рубрика содержит шесть самых свежих
# материалов. Поэтому один лёгкий запрос заменяет обход множества страниц.
SECTION_KEYS = (
    ("topNews", "Главное"),
    ("nationalNews", "Общество"),
    ("politicsNews", "Политика"),
    ("economicsNews", "Экономика"),
    ("worldNews", "Международные новости"),
    ("sportsNews", "Спорт"),
    ("cultural", "Культура"),
    ("medical", "Медицина"),
    ("scienceEnvironment", "Наука и экология"),
    ("entertainment", "Развлечения"),
    ("opnion", "Мнения"),
    ("obituary", "Некрологи"),
)


def parse():
    soup = fetch_soup(
        HOME_URL,
        SOURCE_NAME,
        timeout=35,
        verify=True,
    )
    if soup is None:
        print("  ✅ 0")
        return []

    news = _parse_47news_page(soup)
    print(f"  ✅ {len(news)}")
    return news


def _parse_47news_page(soup, now=None):
    """Читает JSON страницы и оставляет только публикации 共同通信."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    page_props = _next_page_props(soup)
    news = []

    for key, section in SECTION_KEYS:
        entries = _section_entries(page_props.get(key))
        for entry in entries:
            publisher = (entry.get("user") or {}).get("title", "")
            if publisher != PUBLISHER_NAME:
                continue

            title = " ".join(str(entry.get("title", "")).split())
            url = urljoin(HOME_URL, str(entry.get("url", "")))
            publication_date = _parse_47news_date(entry.get("startDate", ""))

            if (
                len(title) < 5
                or is_junk(title)
                or not _is_47news_article_url(url)
            ):
                continue

            if publication_date:
                parsed = datetime.strptime(publication_date, "%Y-%m-%d")
                if parsed < cutoff:
                    continue

            summary = _clean_summary(entry.get("body", ""))
            image = entry.get("image") or {}

            item = {
                "source": SOURCE_NAME,
                "title": title,
                "url": url,
                "date": publication_date,
                "section": section,
                "source_id": str(entry.get("id", "")),
            }
            if summary:
                item["summary"] = summary
            if image.get("url"):
                item["image"] = str(image["url"])
            news.append(item)

    return deduplicate_news(news)


def _next_page_props(soup):
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None:
        return {}
    try:
        data = json.loads(script.string or script.get_text())
    except (TypeError, json.JSONDecodeError):
        return {}
    return data.get("props", {}).get("pageProps", {})


def _section_entries(value):
    # topNews хранит список в поле Article; остальные рубрики — напрямую.
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        entries = value.get("Article", [])
        return entries if isinstance(entries, list) else []
    return []


def _parse_47news_date(raw_date):
    try:
        return datetime.strptime(
            str(raw_date).strip(),
            "%Y-%m-%d %H:%M:%S",
        ).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _is_47news_article_url(url):
    parts = urlsplit(str(url))
    hostname = (parts.hostname or "").casefold()
    path = parts.path.strip("/")
    return (
        hostname in {"47news.jp", "www.47news.jp"}
        and path.endswith(".html")
        and path[:-5].isdigit()
    )


def _clean_summary(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.replace("...", "").split())
