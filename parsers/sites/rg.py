"""Парсер свежего номера «Российской газеты»."""

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "Российская газета"
FRESH_ISSUE_URL = "https://rg.ru/gazeta/rg/svezh"
XML_FEED_URL = "https://rg.ru/xml/index.xml"
ISSUE_RE = re.compile(r"№\s*(\d+)", re.IGNORECASE)
URL_DATE_RE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/")
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
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
        FRESH_ISSUE_URL,
        SOURCE_NAME,
        timeout=30,
        verify=True,
        attempts=1,
    )
    if soup is None:
        print("  ℹ️ Страница свежего номера РГ не ответила — пробую браузер")
        soup = fetch_soup_js(
            FRESH_ISSUE_URL,
            SOURCE_NAME,
            wait_ms=1800,
            timeout_ms=45000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )
    news = _parse_fresh_issue(soup) if soup else []
    if not news:
        print("  ℹ️ Свежий номер РГ недоступен — пробую официальный XML")
        feed = fetch_soup(
            XML_FEED_URL,
            f"{SOURCE_NAME} · XML",
            timeout=20,
            verify=True,
            # html.parser не требует отдельного XML-движка и переносит
            # небольшие ошибки, которые иногда встречаются в ленте.
            parser="html.parser",
            attempts=1,
        )
        news = _parse_xml_feed(feed) if feed else []
    print(f"  ✅ {len(news)}")
    return news


def _parse_xml_feed(soup):
    """Читает официальный XML-анонс RG.RU как резерв свежего выпуска."""
    if soup is None:
        return []

    news = []
    for entry in soup.find_all(["item", "entry"]):
        title = _text(entry.find("title"))
        url = _feed_link(entry)
        publication_date = _feed_date(entry, url)
        if (
            len(title) < 15
            or is_junk(title)
            or not _is_article_url(url)
        ):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
            "section": "XML · резерв",
        }
        description = entry.find("description") or entry.find("summary")
        summary = _clean_feed_text(description)
        if summary:
            item["summary"] = summary
        news.append(item)

    news = deduplicate_news(news)
    dated = [item["date"] for item in news if item.get("date")]
    if not dated:
        return news[:80]

    # XML пополняется весь день и содержит не только текущий выпуск. Для
    # суточного газетного цикла оставляем публикации его самой свежей даты.
    newest = max(dated)
    return [item for item in news if item.get("date") == newest][:80]


def _parse_fresh_issue(soup):
    """Читает ссылки на статьи со всех полос текущего выпуска."""
    if soup is None:
        return []

    heading = soup.select_one("h1")
    heading_text = _text(heading)
    edition_date = _parse_russian_date(heading_text)
    issue_match = ISSUE_RE.search(heading_text)
    issue_id = issue_match.group(1) if issue_match else ""

    news = []
    for link in soup.select("a[href]"):
        url = urljoin(FRESH_ISSUE_URL, str(link.get("href", "")).strip())
        if not _is_article_url(url):
            continue

        title = _text(link)
        if len(title) < 15 or is_junk(title):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": _date_from_url(url) or _date_near(link) or edition_date,
        }
        if edition_date:
            item["edition_date"] = edition_date
        if issue_id:
            item["edition_id"] = issue_id
        news.append(item)

    return deduplicate_news(news)


def _is_article_url(url):
    parts = urlsplit(str(url or ""))
    hostname = (parts.hostname or "").casefold()
    return (
        (hostname == "rg.ru" or hostname.endswith(".rg.ru"))
        and URL_DATE_RE.search(parts.path) is not None
        and parts.path.casefold().endswith(".html")
    )


def _date_from_url(url):
    match = URL_DATE_RE.search(urlsplit(str(url or "")).path)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def _date_near(link):
    node = link
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        match = NUMERIC_DATE_RE.search(_text(node))
        if match:
            day, month, year = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def _parse_russian_date(value):
    match = RUSSIAN_DATE_RE.search(" ".join(str(value or "").split()))
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name.casefold())
    return f"{int(year):04d}-{month:02d}-{int(day):02d}" if month else ""


def _feed_link(entry):
    link = entry.find("link")
    if link is not None:
        value = str(link.get("href", "")).strip() or _text(link)
        # В HTML-режиме <link> считается одиночным тегом, поэтому текст
        # стандартного RSS-элемента может оказаться соседним узлом.
        if not value:
            sibling = link.next_sibling
            while sibling is not None and not getattr(sibling, "name", None):
                candidate = " ".join(str(sibling).split())
                if candidate.startswith(("http://", "https://")):
                    value = candidate
                    break
                sibling = sibling.next_sibling
        if value:
            return urljoin(XML_FEED_URL, value)
    guid = entry.find("guid") or entry.find("id")
    return urljoin(XML_FEED_URL, _text(guid)) if guid else ""


def _feed_date(entry, url):
    node = (
        entry.find("pubDate")
        or entry.find("pubdate")
        or entry.find("published")
        or entry.find("updated")
        or entry.find("date")
    )
    value = _text(node)
    if value:
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).date().isoformat()
            except ValueError:
                pass
    return _date_from_url(url)


def _clean_feed_text(node):
    if node is None:
        return ""
    raw = node.decode_contents() if hasattr(node, "decode_contents") else str(node)
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())[:1200]


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""
