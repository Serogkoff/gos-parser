"""Парсер открытой официальной RSS-ленты ТАСС."""

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "ТАСС"
FEED_URL = "https://tass.ru/rss/v2.xml"
MAX_ITEMS = 100
MAX_AGE_DAYS = 30


def parse():
    soup = fetch_soup(
        FEED_URL,
        SOURCE_NAME,
        timeout=30,
        verify=True,
        parser="xml",
    )
    if soup is None:
        print("  ✅ 0")
        return []

    news = _parse_tass_feed(soup)
    print(f"  ✅ {len(news)}")
    return news


def _parse_tass_feed(soup, now=None):
    """Преобразует элементы RSS ТАСС в общий формат проекта."""
    now = now or datetime.now().astimezone()
    cutoff = now.date() - timedelta(days=MAX_AGE_DAYS)
    news = []

    for entry in soup.find_all("item")[:MAX_ITEMS]:
        title = _tag_text(entry, "title")
        url = _tag_text(entry, "link") or _tag_text(entry, "guid")
        publication_date = _parse_tass_date(
            _tag_text(entry, "pubDate"),
        )

        if (
            len(title) < 10
            or not url.startswith(("https://tass.ru/", "http://tass.ru/"))
            or is_junk(title)
        ):
            continue

        if publication_date:
            parsed_date = datetime.strptime(
                publication_date,
                "%Y-%m-%d",
            ).date()
            if parsed_date < cutoff:
                continue

        categories = [
            " ".join(category.get_text(" ", strip=True).split())
            for category in entry.find_all("category")
            if category.get_text(" ", strip=True)
        ]
        summary = _clean_summary(_tag_text(entry, "description"))

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
            "section": categories[0] if categories else "Последние новости",
        }
        if summary:
            item["summary"] = summary
        news.append(item)

    return deduplicate_news(news)


def _parse_tass_date(raw_date):
    """Читает стандартную дату RSS, включая часовой пояс ТАСС."""
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed.date().isoformat() if parsed else ""


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_summary(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())
