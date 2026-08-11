"""Парсер материалов текущего номера газеты «Красная звезда»."""

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "Красная звезда"
# На redstar.ru HTTPS периодически отвечает TLSV1_UNRECOGNIZED_NAME.
# Официальная ссылка раздела работает по HTTP, поэтому не форсируем HTTPS.
ISSUE_URL = "http://redstar.ru/category/nomer/"
ISSUE_RSS_URL = "http://redstar.ru/category/nomer/feed/"
DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
NON_ARTICLE_PATHS = {
    "", "category", "tag", "author", "page", "feed", "wp-content",
    "wp-admin", "nomer",
}


def parse():
    soup = fetch_soup(
        ISSUE_URL,
        SOURCE_NAME,
        timeout=25,
        verify=False,
        attempts=1,
    )
    if soup is None:
        print("  ℹ️ Страница номера «Красной звезды» не ответила — пробую браузер")
        soup = fetch_soup_js(
            ISSUE_URL,
            SOURCE_NAME,
            wait_ms=1800,
            timeout_ms=45000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )

    news = _parse_issue_page(soup) if soup else []
    if not news:
        rss = fetch_soup(
            ISSUE_RSS_URL,
            f"{SOURCE_NAME} · RSS",
            timeout=25,
            verify=False,
            parser="xml",
            attempts=1,
        )
        news = _parse_issue_rss(rss) if rss else []

    print(f"  ✅ {len(news)}")
    return news


def _parse_issue_page(soup):
    if soup is None:
        return []

    news = []
    cards = soup.select("article, .post, .type-post")
    for card in cards:
        link = card.select_one(
            "h1 a[href], h2 a[href], h3 a[href], .entry-title a[href]"
        )
        if link is None:
            continue
        item = _make_item(
            title=_text(link),
            url=urljoin(ISSUE_URL, str(link.get("href", "")).strip()),
            date=_card_date(card),
            summary=_card_summary(card),
        )
        if item:
            news.append(item)

    return deduplicate_news(news)


def _parse_issue_rss(soup):
    if soup is None:
        return []

    news = []
    for entry in soup.find_all("item"):
        item = _make_item(
            title=_tag_text(entry, "title"),
            url=_tag_text(entry, "link") or _tag_text(entry, "guid"),
            date=_parse_rss_date(_tag_text(entry, "pubDate")),
            summary=_clean_html(_tag_text(entry, "description")),
        )
        if item:
            news.append(item)
    return deduplicate_news(news)


def _make_item(title, url, date="", summary=""):
    if len(title) < 10 or not _is_article_url(url) or is_junk(title):
        return None
    item = {
        "source": SOURCE_NAME,
        "title": title,
        "url": url,
        "date": date,
    }
    if date:
        item["edition_date"] = date
    if summary:
        item["summary"] = summary
    return item


def _is_article_url(url):
    parts = urlsplit(str(url or ""))
    hostname = (parts.hostname or "").casefold()
    path_parts = [part.casefold() for part in parts.path.split("/") if part]
    return (
        (hostname == "redstar.ru" or hostname.endswith(".redstar.ru"))
        and len(path_parts) == 1
        and path_parts[0] not in NON_ARTICLE_PATHS
    )


def _card_date(card):
    time_tag = card.select_one("time[datetime]")
    if time_tag:
        value = str(time_tag.get("datetime", "")).strip()[:10]
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass

    match = DATE_RE.search(_text(card))
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _card_summary(card):
    node = card.select_one(".entry-summary, .entry-content, .post-excerpt, p")
    text = _text(node)
    return text if len(text) >= 45 else ""


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
