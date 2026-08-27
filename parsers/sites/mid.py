"""Парсер официальных RSS/Atom-лент МИД России."""

from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.dates import parse_date
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "МИД РФ"
PRIMARY_FEED_URL = "https://mid.ru/ru/rss.php"
FALLBACK_FEED_URL = "https://www.mid.ru/ru/rss"
MAX_ITEMS = 60
BROWSER_WAIT_MS = 7000


def parse():
    """Читает RSS МИДа, проходя JavaScript-защиту только при необходимости."""
    for feed_url in (PRIMARY_FEED_URL, FALLBACK_FEED_URL):
        soup = fetch_soup(
            feed_url,
            SOURCE_NAME,
            timeout=30,
            verify=False,
            parser="xml",
            attempts=1,
        )
        news = _parse_feed(soup)
        if news:
            print(f"  ✅ {len(news)}")
            return news

    # МИД периодически возвращает requests не RSS, а HTML-заглушку bobcmn.
    # Браузер выполняет её JavaScript, получает служебную cookie и дожидается
    # настоящей ленты. Этот более тяжёлый путь используется только после того,
    # как оба обычных запроса не дали ни одной записи.
    for feed_url in (PRIMARY_FEED_URL, FALLBACK_FEED_URL):
        soup = fetch_soup_js(
            feed_url,
            SOURCE_NAME,
            wait_ms=BROWSER_WAIT_MS,
            timeout_ms=45000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
            parser="xml",
        )
        news = _parse_feed(soup)
        if news:
            print(f"  ✅ {len(news)} (через браузер)")
            return news

    print("  ✅ 0")
    return []


def _parse_feed(soup):
    """Преобразует RSS 2.0 или Atom в общий формат проекта."""
    if soup is None:
        return []

    entries = soup.find_all("item") or soup.find_all("entry")
    news = []

    for entry in entries[:MAX_ITEMS]:
        title = _tag_text(entry, "title")
        url = _entry_url(entry)
        publication_date = _parse_feed_date(
            _first_tag_text(entry, "pubDate", "published", "updated", "date")
        )

        if len(title) < 4 or not _is_mid_article_url(url):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
        }
        summary = _clean_summary(
            _first_tag_text(entry, "description", "summary", "content")
        )
        if summary and summary != title:
            item["summary"] = summary
        news.append(item)

    return deduplicate_news(news)


def _entry_url(entry):
    """Читает ссылку как из RSS-текста, так и из Atom href."""
    for link in entry.find_all("link"):
        href = str(link.get("href", "")).strip()
        if href and link.get("rel", "alternate") in {"", "alternate"}:
            return _absolute_mid_url(href)
        text = " ".join(link.get_text(" ", strip=True).split())
        if text:
            return _absolute_mid_url(text)
    return _absolute_mid_url(_first_tag_text(entry, "guid", "id"))


def _absolute_mid_url(value):
    return urljoin("https://mid.ru/", str(value or "").strip())


def _is_mid_article_url(value):
    parts = urlsplit(str(value or "").strip())
    hostname = (parts.hostname or "").casefold()
    return (
        parts.scheme.casefold() in {"http", "https"}
        and (hostname == "mid.ru" or hostname.endswith(".mid.ru"))
        and parts.path not in {"", "/", "/ru/rss", "/ru/rss.php"}
    )


def _parse_feed_date(raw_date):
    value = str(raw_date or "").strip()
    if not value:
        return ""

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed:
        return parsed.date().isoformat()

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        parsed = None
    if parsed:
        return parsed.date().isoformat()

    return parse_date(value)


def _first_tag_text(entry, *names):
    for name in names:
        value = _tag_text(entry, name)
        if value:
            return value
    return ""


def _tag_text(entry, name):
    # После Chromium RSS может быть сериализован как HTML, где BeautifulSoup
    # приводит pubDate к нижнему регистру.
    tag = entry.find(name) or entry.find(str(name).casefold())
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_summary(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())
