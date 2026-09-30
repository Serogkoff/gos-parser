"""Экспериментальный парсер русского раздела Берлинского центра Карнеги."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.logger import get_logger
from utils.news import deduplicate_news
from utils.proxy import kyodo_proxy_url


SOURCE_NAME = "Берлинский центр Карнеги"
LISTING_URL = "https://carnegieendowment.org/ru/russia-eurasia"
ARTICLE_PATH_RE = re.compile(
    r"^/ru/russia-eurasia/(?P<section>politika|research)/"
    r"(?P<year>20\d{2})/(?P<month>\d{2})/(?P<slug>[^/]+)/?$",
    re.IGNORECASE,
)
MAX_ARTICLES = 20
logger = get_logger("carnegie")


def _proxy_url():
    """Использует настроенный VPN-канал Киодо только для Carnegie."""
    try:
        return kyodo_proxy_url()
    except ValueError as error:
        logger.warning(f"[{SOURCE_NAME}] Настройка VPN некорректна: {error}")
        return ""


def parse():
    proxy_url = _proxy_url()
    listing = fetch_soup(
        LISTING_URL,
        SOURCE_NAME,
        timeout=30,
        verify=True,
        attempts=2,
        proxy_url=proxy_url,
    )
    if listing is None:
        print("  ✅ 0")
        return []

    news = _parse_listing(listing)
    if not news:
        print("  ℹ️ Карточки Carnegie подгружаются JavaScript — открываю браузером")
        rendered_listing = fetch_soup_js(
            LISTING_URL,
            SOURCE_NAME,
            wait_ms=2500,
            timeout_ms=45000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
            proxy_url=proxy_url,
        )
        news = _parse_listing(rendered_listing)
    news = news[:MAX_ARTICLES]
    if news:
        workers = min(4, len(news))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            metadata = list(
                pool.map(lambda item: _load_article_metadata(item, proxy_url), news)
            )
        for item, details in zip(news, metadata):
            item.update(details)

    news = deduplicate_news(news)
    print(f"  ✅ {len(news)}")
    return news


def _parse_listing(soup):
    """Берёт уникальные русские публикации в порядке страницы центра."""
    if soup is None:
        return []

    by_url = {}
    ordered_urls = []
    for link in soup.select("a[href]"):
        url = _clean_article_url(link.get("href"))
        match = ARTICLE_PATH_RE.fullmatch(urlsplit(url).path)
        if not match:
            continue
        title = " ".join(link.get_text(" ", strip=True).split())
        if len(title) < 10 or is_junk(title):
            continue
        if url not in by_url:
            ordered_urls.append(url)
        previous = by_url.get(url)
        if previous is not None and len(previous["title"]) >= len(title):
            continue
        by_url[url] = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": f"{match.group('year')}-{match.group('month')}-01",
            "section": (
                "Carnegie Politika"
                if match.group("section").casefold() == "politika"
                else "Исследования"
            ),
        }
    return [by_url[url] for url in ordered_urls if url in by_url]


def _load_article_metadata(item, proxy_url=""):
    soup = fetch_soup(
        item["url"],
        f"{SOURCE_NAME} · публикация",
        timeout=20,
        verify=True,
        attempts=1,
        proxy_url=proxy_url,
    )
    return _parse_article_metadata(soup)


def _parse_article_metadata(soup):
    """Читает точную дату и анонс из Open Graph отдельной публикации."""
    if soup is None:
        return {}

    details = {}
    published = soup.select_one('meta[property="article:published_time"]')
    publication_date = _parse_iso_date(
        published.get("content") if published else ""
    )
    if publication_date:
        details["date"] = publication_date

    description = (
        soup.select_one('meta[property="og:description"]')
        or soup.select_one('meta[name="description"]')
    )
    summary = " ".join(
        str(description.get("content", "") if description else "").split()
    )
    if summary:
        details["summary"] = summary
    return details


def _parse_iso_date(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _clean_article_url(value):
    parts = urlsplit(urljoin(LISTING_URL, str(value or "").strip()))
    hostname = (parts.hostname or "").casefold()
    if hostname not in {"carnegieendowment.org", "www.carnegieendowment.org"}:
        return ""
    return urlunsplit(("https", "carnegieendowment.org", parts.path.rstrip("/"), "", ""))
