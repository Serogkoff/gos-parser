"""Парсер журнала «Россия в глобальной политике»."""

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "Россия в глобальной политике"
RSS_URL = "https://globalaffairs.ru/feed/"
FALLBACK_PAGES = (
    ("Текущий номер", "https://globalaffairs.ru/issues/current/"),
    ("Аналитика", "https://globalaffairs.ru/analytics/"),
)
ARTICLE_PATH_RE = re.compile(r"^/articles/[^/]+/?$", re.IGNORECASE)
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)")
EXCLUDED_CATEGORY_PARTS = (
    "анонс",
    "мероприят",
    "подкаст",
    "международное обозрение",
    "тележурнал",
)
MAX_ARTICLES = 30


def parse():
    rss = fetch_soup(
        RSS_URL,
        f"{SOURCE_NAME} · RSS",
        timeout=30,
        verify=True,
        parser="xml",
        attempts=1,
    )
    news = _parse_rss(rss)
    if not news:
        news = _load_fallback_pages()
    news = deduplicate_news(news)[:MAX_ARTICLES]
    print(f"  ✅ {len(news)}")
    return news


def _parse_rss(soup):
    if soup is None:
        return []

    news = []
    for entry in soup.find_all("item"):
        title = _tag_text(entry, "title")
        url = _clean_article_url(
            _tag_text(entry, "link") or _tag_text(entry, "guid")
        )
        categories = [
            " ".join(tag.get_text(" ", strip=True).split())
            for tag in entry.find_all("category")
        ]
        if (
            len(title) < 10
            or not url
            or is_junk(title)
            or _is_excluded(categories)
        ):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": _parse_rss_date(_tag_text(entry, "pubDate")),
            "section": _display_category(categories),
        }
        summary = _clean_html(_tag_text(entry, "description"))
        if summary:
            item["summary"] = summary
        news.append(item)
    return news


def _load_fallback_pages():
    news = []
    for section, url in FALLBACK_PAGES:
        soup = fetch_soup(
            url,
            f"{SOURCE_NAME} · {section}",
            timeout=12,
            verify=True,
            attempts=1,
        )
        news.extend(_parse_listing(soup, section, url))

    if news:
        return news

    for section, url in FALLBACK_PAGES:
        rendered = fetch_soup_js(
            url,
            f"{SOURCE_NAME} · {section}",
            wait_ms=1500,
            timeout_ms=35000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )
        news.extend(_parse_listing(rendered, section, url))
    return news


def _parse_listing(soup, section, page_url):
    if soup is None:
        return []

    by_url = {}
    order = []
    for link in soup.select("a[href]"):
        url = _clean_article_url(urljoin(page_url, link.get("href")))
        title = " ".join(link.get_text(" ", strip=True).split())
        if not url or len(title) < 10 or is_junk(title):
            continue
        if url not in by_url:
            order.append(url)
        previous = by_url.get(url)
        if previous and len(previous["title"]) >= len(title):
            continue
        by_url[url] = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": _listing_date(link),
            "section": section,
        }
    return [by_url[url] for url in order if url in by_url]


def _listing_date(link):
    container = link.find_parent(("article", "li", "div")) or link.parent
    if container:
        time_tag = container.find("time")
        if time_tag:
            value = time_tag.get("datetime") or time_tag.get_text(" ", strip=True)
            parsed = _parse_iso_date(value)
            if parsed:
                return parsed
        match = DATE_RE.search(container.get_text(" ", strip=True))
        if match:
            day, month, year = match.groups()
            try:
                return datetime(int(year), int(month), int(day)).date().isoformat()
            except ValueError:
                pass
    return datetime.now().date().isoformat()


def _clean_article_url(value):
    parts = urlsplit(str(value or "").strip())
    hostname = (parts.hostname or "").casefold()
    if hostname not in {"globalaffairs.ru", "www.globalaffairs.ru"}:
        return ""
    path = parts.path.rstrip("/")
    if ARTICLE_PATH_RE.fullmatch(path) is None:
        return ""
    return urlunsplit(("https", "globalaffairs.ru", path, "", ""))


def _parse_rss_date(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
    except (TypeError, ValueError, OverflowError):
        return ""
    if parsed is None:
        return ""
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=3)))
    return parsed.date().isoformat()


def _parse_iso_date(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _is_excluded(categories):
    normalized = " ".join(categories).casefold()
    return any(part in normalized for part in EXCLUDED_CATEGORY_PARTS)


def _display_category(categories):
    for category in categories:
        if category and not _is_excluded((category,)):
            return category
    return "Аналитика"


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_html(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())
