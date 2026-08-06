"""Парсер статей свежего номера «Независимой газеты»."""

import re
from urllib.parse import urljoin, urlsplit

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Независимая газета"
FRESH_ISSUE_URL = "https://www.ng.ru/gazeta/"
ARTICLE_DATE_RE = re.compile(r"/(20\d{2}-\d{2}-\d{2})/")
ISSUE_NUMBER_RE = re.compile(r"\((\d+)\)")
PAGE_SUFFIX_RE = re.compile(r"\s*\(\d+\s+полоса\)\s*$", re.IGNORECASE)


def parse():
    soup = fetch_soup(
        FRESH_ISSUE_URL,
        SOURCE_NAME,
        timeout=30,
        verify=True,
    )
    if soup is None:
        print("  ✅ 0")
        return []

    news = _parse_fresh_issue(soup)
    print(f"  ✅ {len(news)}")
    return news


def _parse_fresh_issue(soup):
    """Берёт только статьи номера, указанного в заголовке «Газета»."""
    issue_node = soup.select_one("h1.htitle .num")
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
    for link in soup.select('div[role="main"] .anonce h3 a[href]'):
        url = urljoin(FRESH_ISSUE_URL, link.get("href", ""))
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
