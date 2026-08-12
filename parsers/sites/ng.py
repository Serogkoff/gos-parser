"""Бережный парсер статей свежего номера «Независимой газеты»."""

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Независимая газета"
FRESH_ISSUE_URL = "https://www.ng.ru/gazeta/"
RSS_URL = "https://www.ng.ru/rss/"
ARTICLE_DATE_RE = re.compile(r"/(20\d{2}-\d{2}-\d{2})/")
ISSUE_NUMBER_RE = re.compile(r"\((\d+)\)")
PAGE_SUFFIX_RE = re.compile(r"\s*\(\d+\s+полоса\)\s*$", re.IGNORECASE)


def parse():
    # У НГ агрессивная защита по IP. Здесь намеренно нет резервного URL,
    # повторов и Playwright: один запрос к номеру и при неудаче один запрос
    # к официальному RSS безопаснее серии обращений к одному серверу.
    soup = fetch_soup(
        FRESH_ISSUE_URL,
        SOURCE_NAME,
        timeout=25,
        verify=True,
        attempts=1,
    )
    news = _parse_fresh_issue(soup) if soup else []
    if not news:
        print("  ℹ️ Свежий номер НГ недоступен — пробую официальный RSS")
        rss = fetch_soup(
            RSS_URL,
            f"{SOURCE_NAME} · RSS",
            timeout=25,
            verify=True,
            parser="xml",
            attempts=1,
        )
        news = _parse_rss(rss) if rss else []
        if not news:
            print("  ℹ️ НГ заблокировала и номер, и RSS — повтор завтра в 08:00")

    print(f"  ✅ {len(news)}")
    return news


def _parse_rss(soup):
    """Возвращает материалы только самого свежего дня из резервной ленты."""
    parsed = []
    for entry in soup.find_all("item"):
        title_tag = entry.find("title")
        link_tag = entry.find("link")
        date_tag = entry.find("pubDate") or entry.find("pubdate")
        title = (
            " ".join(title_tag.get_text(" ", strip=True).split())
            if title_tag
            else ""
        )
        url = link_tag.get_text(strip=True) if link_tag else ""
        publication_date = _rss_date(
            date_tag.get_text(" ", strip=True) if date_tag else ""
        )
        if len(title) < 15 or not url or not publication_date or is_junk(title):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
            "section": "Онлайн НГ · резерв",
        }
        description = entry.find("description")
        if description:
            summary_soup = BeautifulSoup(
                description.get_text(),
                "html.parser",
            )
            summary = " ".join(
                summary_soup.get_text(" ", strip=True).split()
            )
            if len(summary) >= 30:
                item["summary"] = summary
        parsed.append(item)

    if not parsed:
        return []
    newest_date = max(item["date"] for item in parsed)
    return deduplicate_news([
        item for item in parsed if item["date"] == newest_date
    ])


def _rss_date(value):
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _parse_fresh_issue(soup, base_url=FRESH_ISSUE_URL):
    """Берёт только статьи номера, указанного в заголовке «Газета»."""
    issue_node = soup.select_one("h1.htitle .num, h1 .num, .htitle .num")
    issue_text = (
        " ".join(issue_node.get_text(" ", strip=True).split())
        if issue_node
        else ""
    )
    issue_number_match = ISSUE_NUMBER_RE.search(issue_text)
    issue_number = issue_number_match.group(1) if issue_number_match else ""
    edition_date_match = re.search(r"20\d{2}-\d{2}-\d{2}", issue_text)
    edition_date = edition_date_match.group(0) if edition_date_match else ""

    if not issue_number:
        return []

    news = []
    for link in soup.select(
        'div[role="main"] .anonce h3 a[href], '
        'main .anonce h3 a[href], .anonce h3 a[href]'
    ):
        url = urljoin(base_url, link.get("href", ""))
        path = urlsplit(url).path
        if (
            not path.endswith(".html")
            or f"_{issue_number}_" not in path
            or "/news/" in path
        ):
            continue

        date_match = ARTICLE_DATE_RE.search(path)
        publication_date = date_match.group(1) if date_match else edition_date
        title = PAGE_SUFFIX_RE.sub(
            "",
            " ".join(link.get_text(" ", strip=True).split()),
        ).strip()

        if len(title) < 15 or is_junk(title):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
        }
        if edition_date:
            item["edition_date"] = edition_date
        news.append(item)

    return deduplicate_news(news)
