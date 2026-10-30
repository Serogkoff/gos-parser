"""Парсер официальной RSS-ленты Белорусского телеграфного агентства."""

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "БЕЛТА"
FEED_URL = "https://belta.by/rss/"
MAX_ITEMS = 100
MAX_AGE_DAYS = 30


def parse(now=None):
    soup = fetch_soup(
        FEED_URL,
        f"{SOURCE_NAME} · RSS",
        timeout=30,
        verify=True,
        parser="xml",
    )
    if soup is None:
        print("  ✅ 0")
        return []

    news = _parse_belta_feed(soup, now=now)
    print(f"  ✅ {len(news)}")
    return news


def _parse_belta_feed(soup, now=None):
    """Преобразует официальный RSS БЕЛТА в общий формат проекта."""
    now = now or datetime.now().astimezone()
    cutoff = now.date() - timedelta(days=MAX_AGE_DAYS)
    news = []

    for entry in soup.find_all("item")[:MAX_ITEMS]:
        title = _tag_text(entry, "title")
        url = _canonical_article_url(
            _tag_text(entry, "link") or _tag_text(entry, "guid")
        )
        publication_date = _parse_belta_date(_tag_text(entry, "pubDate"))

        if len(title) < 10 or not url or is_junk(title):
            continue

        if publication_date:
            parsed_date = datetime.strptime(
                publication_date,
                "%Y-%m-%d",
            ).date()
            if parsed_date < cutoff:
                continue

        section = _tag_text(entry, "category") or "Последние новости"
        summary = _clean_summary(_tag_text(entry, "description"))
        author = _tag_text(entry, "author")

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
            "section": section,
        }
        if summary:
            item["summary"] = summary
        if author:
            item["author"] = author
        news.append(item)

    return deduplicate_news(news)


def _canonical_article_url(value):
    parts = urlsplit(str(value or "").strip())
    hostname = (parts.hostname or "").casefold()
    path_parts = [part for part in parts.path.split("/") if part]
    if (
        hostname not in {"belta.by", "www.belta.by"}
        or len(path_parts) < 3
        or path_parts[1] != "view"
    ):
        return ""
    return urlunsplit(("https", "belta.by", parts.path.rstrip("/") + "/", "", ""))


def _parse_belta_date(raw_date):
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
