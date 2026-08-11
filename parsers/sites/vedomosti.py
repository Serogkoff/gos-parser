"""Парсер официальной RSS-ленты последнего номера «Ведомостей»."""

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Ведомости"
ISSUE_RSS_URL = "https://www.vedomosti.ru/rss/issue"
URL_DATE_RE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})(?:/|$)")


def parse():
    soup = fetch_soup(
        ISSUE_RSS_URL,
        SOURCE_NAME,
        timeout=30,
        verify=True,
        parser="xml",
        attempts=1,
    )
    if soup is None:
        soup = fetch_soup(
            ISSUE_RSS_URL,
            SOURCE_NAME,
            timeout=30,
            verify=False,
            parser="xml",
            attempts=1,
        )
    news = _parse_issue_rss(soup) if soup else []
    print(f"  ✅ {len(news)}")
    return news


def _parse_issue_rss(soup):
    if soup is None:
        return []

    news = []
    for entry in soup.find_all(["item", "entry"]):
        title = _tag_text(entry, "title")
        url = _entry_url(entry)
        if len(title) < 10 or not _is_article_url(url) or is_junk(title):
            continue

        date = (
            _date_from_url(url)
            or _parse_rss_date(
                _tag_text(entry, "pubDate")
                or _tag_text(entry, "published")
                or _tag_text(entry, "updated")
            )
        )
        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": date,
        }
        if date:
            item["edition_date"] = date

        description = _clean_html(
            _tag_text(entry, "description") or _tag_text(entry, "summary")
        )
        if description:
            item["summary"] = description
        news.append(item)

    return deduplicate_news(news)


def _entry_url(entry):
    link = entry.find("link")
    if link:
        return str(link.get("href", "")).strip() or _tag_text(entry, "link")
    return _tag_text(entry, "guid") or _tag_text(entry, "id")


def _is_article_url(url):
    parts = urlsplit(str(url or ""))
    hostname = (parts.hostname or "").casefold()
    return (
        (hostname == "vedomosti.ru" or hostname.endswith(".vedomosti.ru"))
        and URL_DATE_RE.search(parts.path) is not None
        and any(part in parts.path.casefold() for part in ("/articles/", "/news/"))
    )


def _date_from_url(url):
    match = URL_DATE_RE.search(urlsplit(str(url or "")).path)
    return "-".join(match.groups()) if match else ""


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
