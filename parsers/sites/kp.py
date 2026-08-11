"""Парсер свежих материалов «Комсомольской правды» из официальной RSS."""

import re
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Комсомольская правда"
RSS_URL = "https://www.kp.ru/rss/allsections.xml"
ARTICLE_PATH_RE = re.compile(r"^/daily/([^/]+)/\d+/?$", re.IGNORECASE)
MOSCOW_TIMEZONE = timezone(timedelta(hours=3))


def parse():
    rss = fetch_soup(
        RSS_URL,
        f"{SOURCE_NAME} · RSS",
        timeout=30,
        verify=False,
        parser="xml",
        attempts=1,
    )
    news = _parse_latest_rss(rss) if rss else []
    print(f"  ✅ {len(news)}")
    return news


def _parse_latest_rss(soup):
    """Оставляет материалы самой свежей московской календарной даты."""
    if soup is None:
        return []

    candidates = []
    for entry in soup.find_all("item"):
        title = _tag_text(entry, "title")
        url = _clean_url(
            _tag_text(entry, "link") or _tag_text(entry, "guid")
        )
        date = _parse_rss_date(_tag_text(entry, "pubDate"))
        if (
            len(title) < 10
            or not date
            or not _is_article_url(url)
            or is_junk(title)
        ):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": date,
            "edition_date": date,
        }
        edition_id = _edition_id(url)
        if edition_id:
            item["edition_id"] = edition_id

        category = _tag_text(entry, "category")
        if category:
            item["section"] = category

        description = _clean_html(_tag_text(entry, "description"))
        if description:
            item["summary"] = description
        candidates.append(item)

    if not candidates:
        return []
    latest_date = max(item["date"] for item in candidates)
    return deduplicate_news(
        item for item in candidates if item["date"] == latest_date
    )


def _is_article_url(url):
    parts = urlsplit(str(url or ""))
    hostname = (parts.hostname or "").casefold()
    return (
        (hostname == "kp.ru" or hostname.endswith(".kp.ru"))
        and ARTICLE_PATH_RE.fullmatch(parts.path) is not None
    )


def _edition_id(url):
    match = ARTICLE_PATH_RE.fullmatch(urlsplit(str(url or "")).path)
    return match.group(1) if match else ""


def _clean_url(url):
    parts = urlsplit(str(url or "").strip())
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")
    )


def _parse_rss_date(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
    except (TypeError, ValueError, OverflowError):
        return ""
    if not parsed:
        return ""
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(MOSCOW_TIMEZONE)
    return parsed.date().isoformat()


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_html(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())
