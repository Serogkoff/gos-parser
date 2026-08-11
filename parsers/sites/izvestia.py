"""Парсер печатного номера газеты «Известия»."""

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "Известия"
NEWSPAPER_URL = "https://iz.ru/newspaper"
RSS_URL = "https://iz.ru/xml/rss/all.xml"
ARTICLE_PATH_RE = re.compile(r"^/\d+(?:/[^/]+){1,4}/?$", re.IGNORECASE)
RUSSIAN_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+"
    r"(20\d{2})\b",
    re.IGNORECASE,
)
MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def parse():
    soup = fetch_soup(
        NEWSPAPER_URL,
        f"{SOURCE_NAME} · свежий номер",
        timeout=25,
        verify=True,
        attempts=1,
    )
    if soup is None:
        print("  ℹ️ Страница номера Известий отклонена — пробую браузер")
        soup = fetch_soup_js(
            NEWSPAPER_URL,
            f"{SOURCE_NAME} · свежий номер",
            wait_ms=2000,
            timeout_ms=45000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )

    news = _parse_newspaper_page(soup) if soup else []
    if not news:
        print("  ℹ️ Номер не разобран — использую официальную RSS Известий")
        rss = fetch_soup(
            RSS_URL,
            f"{SOURCE_NAME} · RSS",
            timeout=30,
            verify=False,
            parser="xml",
            attempts=1,
        )
        news = _parse_rss(rss) if rss else []

    print(f"  ✅ {len(news)}")
    return news


def _parse_newspaper_page(soup):
    if soup is None:
        return []

    edition_date = _page_edition_date(soup)
    news = []
    for link in soup.select("main a[href], article a[href], a[href]"):
        url = urljoin(NEWSPAPER_URL, str(link.get("href", "")).strip())
        if not _is_article_url(url):
            continue

        title = _text(link)
        if len(title) < 15 or is_junk(title):
            continue

        date = _date_near(link) or edition_date
        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": date,
        }
        if edition_date:
            item["edition_date"] = edition_date
        news.append(item)

    return deduplicate_news(news)


def _parse_rss(soup):
    if soup is None:
        return []

    news = []
    for entry in soup.find_all("item"):
        title = _tag_text(entry, "title")
        url = _tag_text(entry, "link") or _tag_text(entry, "guid")
        if len(title) < 10 or not _is_article_url(url) or is_junk(title):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": _parse_rss_date(_tag_text(entry, "pubDate")),
        }
        description = _clean_html(_tag_text(entry, "description"))
        if description:
            item["summary"] = description
        news.append(item)
    return deduplicate_news(news)


def _page_edition_date(soup):
    candidates = (
        soup.select_one("h1"),
        soup.select_one("[class*='newspaper'][class*='date']"),
        soup.select_one("meta[property='og:title']"),
        soup.select_one("title"),
    )
    for node in candidates:
        value = (
            str(node.get("content", ""))
            if node and node.name == "meta"
            else _text(node)
        )
        date = _parse_russian_date(value)
        if date:
            return date
    return ""


def _date_near(link):
    node = link
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        date = _parse_russian_date(_text(node))
        if date:
            return date
    return ""


def _is_article_url(url):
    parts = urlsplit(str(url or ""))
    hostname = (parts.hostname or "").casefold()
    return (
        (hostname == "iz.ru" or hostname.endswith(".iz.ru"))
        and ARTICLE_PATH_RE.fullmatch(parts.path.rstrip("/") or "/") is not None
    )


def _parse_russian_date(value):
    match = RUSSIAN_DATE_RE.search(" ".join(str(value or "").split()))
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name.casefold())
    return f"{int(year):04d}-{month:02d}-{int(day):02d}" if month else ""


def _parse_rss_date(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed.date().isoformat() if parsed else ""


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_html(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""
