"""Бережный парсер статей свежего номера «Независимой газеты»."""

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import HEADERS, fetch_soup
from utils.logger import get_logger
from utils.news import deduplicate_news


SOURCE_NAME = "Независимая газета"
FRESH_ISSUE_URL = "https://www.ng.ru/gazeta/"
RSS_URL = "https://www.ng.ru/rss/"
ISSUE_READER_URL = "https://r.jina.ai/https://www.ng.ru/gazeta/"
RSS_PROXY_URL = (
    "https://api.rss2json.com/v1/api.json"
    "?rss_url=https%3A%2F%2Fwww.ng.ru%2Frss%2F"
)
ARTICLE_DATE_RE = re.compile(r"/(20\d{2}-\d{2}-\d{2})/")
ISSUE_NUMBER_RE = re.compile(r"\((\d+)\)")
PAGE_SUFFIX_RE = re.compile(r"\s*\(\d+\s+полоса\)\s*$", re.IGNORECASE)
logger = get_logger("ng")


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
        print("  ℹ️ НГ заблокировала IP — пробую свежий номер через шлюз")
        proxy_issue = _fetch_issue_proxy()
        news = _parse_markdown_issue(proxy_issue) if proxy_issue else []
    if not news:
        print("  ℹ️ Страница номера недоступна — пробую официальный RSS")
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
            print("  ℹ️ Прямой RSS недоступен — пробую его через шлюз")
            news = _parse_proxy_feed(_fetch_rss_proxy())
        if not news:
            print("  ℹ️ Все способы НГ недоступны — повтор завтра в 08:00")

    print(f"  ✅ {len(news)}")
    return news


def _fetch_issue_proxy():
    """Получает Markdown свежего номера через внешний IP один раз в сутки."""
    try:
        response = requests.get(
            ISSUE_READER_URL,
            # Jina Reader — API, а не обычная веб-страница. Браузерный
            # User-Agent вызывает у его Cloudflare лишнюю HTML-проверку.
            headers={
                "User-Agent": "gos-parser/1.0",
                "Accept": "text/plain",
            },
            timeout=40,
        )
        response.raise_for_status()
        if not response.text.strip():
            raise ValueError("получен пустой ответ")
        return response.text
    except (requests.RequestException, ValueError) as error:
        logger.warning(f"[{SOURCE_NAME} · шлюз номера] Ошибка: {error}")
        return None


def _parse_markdown_issue(markdown):
    """Извлекает статьи самого частого номера из Markdown-копии страницы."""
    if not isinstance(markdown, str) or not markdown.strip():
        return []
    markdown = "\n".join(line.strip() for line in markdown.splitlines())

    candidates = []
    pattern = re.compile(
        r"(?m)^(?:#{1,6}\s+)?\[([^\]\n]{15,})\]"
        r"\((https?://(?:www\.)?ng\.ru/[^\s)]+/"
        r"20\d{2}-\d{2}-\d{2}/[^\s)]+_\d+_[^\s)]+\.html)\)\s*$"
    )
    for title, url in pattern.findall(markdown):
        issue_match = re.search(r"_(\d+)_", url)
        date_match = ARTICLE_DATE_RE.search(urlsplit(url).path)
        if not issue_match or not date_match:
            continue
        candidates.append({
            "title": " ".join(title.split()),
            "url": url,
            "issue_number": issue_match.group(1),
            "date": date_match.group(1),
        })
    if not candidates:
        return []

    issue_counts = {}
    for item in candidates:
        number = item["issue_number"]
        issue_counts[number] = issue_counts.get(number, 0) + 1
    current_issue = max(issue_counts, key=issue_counts.get)

    edition_match = re.search(r"\b(\d{2})\.(\d{2})\.(20\d{2})\b", markdown)
    edition_date = (
        f"{edition_match.group(3)}-{edition_match.group(2)}-{edition_match.group(1)}"
        if edition_match
        else ""
    )
    news = []
    for item in candidates:
        title = PAGE_SUFFIX_RE.sub("", item["title"]).strip()
        if (
            item["issue_number"] != current_issue
            or len(title) < 15
            or is_junk(title)
        ):
            continue
        news_item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": item["url"],
            "date": item["date"],
        }
        if edition_date:
            news_item["edition_date"] = edition_date
        news.append(news_item)
    return deduplicate_news(news)


def _fetch_rss_proxy():
    """Один раз получает публичный RSS через внешний IP без API-ключа."""
    try:
        response = requests.get(
            RSS_PROXY_URL,
            headers=HEADERS,
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "ok":
            raise ValueError(payload.get("message") or "неизвестный ответ")
        return payload
    except (requests.RequestException, ValueError) as error:
        logger.warning(f"[{SOURCE_NAME} · RSS-шлюз] Ошибка: {error}")
        return None


def _parse_proxy_feed(payload):
    if not isinstance(payload, dict):
        return []
    parsed = []
    for entry in payload.get("items", []):
        if not isinstance(entry, dict):
            continue
        publication_date = str(entry.get("pubDate", ""))[:10]
        item = _rss_item(
            entry.get("title", ""),
            entry.get("link", ""),
            publication_date,
            entry.get("description", ""),
        )
        if item:
            parsed.append(item)
    return _latest_rss_day(parsed)


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
        description = entry.find("description")
        item = _rss_item(
            title,
            url,
            publication_date,
            description.get_text() if description else "",
        )
        if item:
            parsed.append(item)

    return _latest_rss_day(parsed)


def _rss_item(title, url, publication_date, description=""):
    title = " ".join(str(title).split())
    url = str(url).strip()
    if len(title) < 15 or not url or not publication_date or is_junk(title):
        return None
    item = {
        "source": SOURCE_NAME,
        "title": title,
        "url": url,
        "date": publication_date,
        "section": "Онлайн НГ · резерв",
    }
    summary = " ".join(
        BeautifulSoup(str(description), "html.parser")
        .get_text(" ", strip=True)
        .split()
    )
    if len(summary) >= 30:
        item["summary"] = summary
    return item


def _latest_rss_day(items):
    if not items:
        return []
    newest_date = max(item["date"] for item in items)
    return deduplicate_news([
        item for item in items if item["date"] == newest_date
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
