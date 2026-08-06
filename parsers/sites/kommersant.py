"""Парсер полной версии свежего номера газеты «Коммерсантъ»."""

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Коммерсантъ"
DAILY_URL = "https://www.kommersant.ru/daily"
DAILY_RSS_URL = "https://www.kommersant.ru/RSS/daily.xml"
ISSUE_PATH_RE = re.compile(r"^/daily/(\d+)/?$", re.IGNORECASE)
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
    """Берёт свежий выпуск из официальной полной RSS-ленты газеты."""
    issue_soup = fetch_soup(
        DAILY_URL,
        f"{SOURCE_NAME} · свежий номер",
        timeout=30,
        verify=True,
    )
    issue = _extract_latest_issue(issue_soup) if issue_soup else {}

    rss = fetch_soup(
        DAILY_RSS_URL,
        f"{SOURCE_NAME} · RSS",
        timeout=30,
        verify=True,
        parser="xml",
    )
    if rss is None:
        print("  ✅ 0")
        return []

    news = _parse_daily_rss(rss, issue=issue)
    print(f"  ✅ {len(news)}")
    return news


def _extract_latest_issue(soup):
    """Находит первый выпуск /daily/ID и его дату, не вычисляя ID вручную."""
    if soup is None:
        return {}

    for link in soup.select("a[href]"):
        href = str(link.get("href", "")).strip()
        path = urlsplit(urljoin(DAILY_URL, href)).path
        match = ISSUE_PATH_RE.fullmatch(path)
        if not match:
            continue

        issue = {"id": match.group(1), "url": urljoin(DAILY_URL, href)}
        label = " ".join(link.get_text(" ", strip=True).split())
        if label:
            issue["number"] = label.lstrip("№").strip()

        node = link
        for _ in range(5):
            node = node.parent
            if node is None:
                break
            edition_date = _parse_russian_date(node.get_text(" ", strip=True))
            if edition_date:
                issue["date"] = edition_date
                break
        return issue

    return {}


def _parse_daily_rss(soup, issue=None):
    """Преобразует полную RSS-ленту текущего номера в формат проекта."""
    issue = issue or {}
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
            "date": _parse_rss_date(_tag_text(entry, "pubDate"))
            or issue.get("date", ""),
        }
        if issue.get("date"):
            item["edition_date"] = issue["date"]
        if issue.get("id"):
            item["edition_id"] = issue["id"]

        description = _clean_html(_tag_text(entry, "description"))
        if description:
            item["summary"] = description
        news.append(item)

    return deduplicate_news(news)


def _parse_russian_date(value):
    match = RUSSIAN_DATE_RE.search(
        " ".join(str(value or "").replace("\xa0", " ").split())
    )
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name.casefold())
    if not month:
        return ""
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def _parse_rss_date(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed.date().isoformat() if parsed else ""


def _is_article_url(url):
    parts = urlsplit(str(url or ""))
    hostname = (parts.hostname or "").casefold()
    path = parts.path.rstrip("/")
    return (
        hostname in {"kommersant.ru", "www.kommersant.ru"}
        and re.fullmatch(r"/doc/\d+", path, re.IGNORECASE) is not None
    )


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_html(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())
