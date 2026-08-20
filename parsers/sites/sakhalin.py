"""Парсер официального JSON API новостей Сахалинской области."""

from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from utils.dates import validate_publication_date
from utils.filters import is_junk
from utils.http_client import fetch_json

SOURCE_NAME = "Сахалинская обл."
SITE_URL = "https://sakhalin.gov.ru"
API_URL = f"{SITE_URL}/api/news"
API_HOST = "sakhalin.gov.ru"
MAX_AGE_DAYS = 30
MAX_PAGES = 25


def parse(now=None):
    now = now or datetime.now()
    cutoff = now.date() - timedelta(days=MAX_AGE_DAYS)
    news = []
    seen_articles = set()
    seen_pages = set()
    page_url = API_URL

    for _ in range(MAX_PAGES):
        if page_url in seen_pages:
            break
        seen_pages.add(page_url)

        payload = fetch_json(
            page_url,
            SOURCE_NAME,
            timeout=20,
            # У API не отдается полная цепочка сертификатов для requests.
            # Исключение ограничено одним публичным новостным источником.
            verify=False,
        )
        if not isinstance(payload, dict):
            break

        page_news, reached_old_news = _parse_api_page(
            payload,
            now=now,
            cutoff=cutoff,
            seen_articles=seen_articles,
        )
        news.extend(page_news)
        if reached_old_news:
            break

        page_url = _safe_next_url(
            (payload.get("links") or {}).get("next")
        )
        if not page_url:
            break

    print(f"  ✅ {len(news)}")
    return news


def _parse_api_page(payload, now, cutoff, seen_articles):
    result = []

    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue

        publication_date = validate_publication_date(
            item.get("date", ""),
            now=now,
        )
        if not publication_date:
            continue
        if datetime.strptime(publication_date, "%Y-%m-%d").date() < cutoff:
            return result, True

        title = " ".join(str(item.get("name", "")).split())
        article_url = _article_url(item.get("slug", ""))
        if (
            len(title) < 5
            or not article_url
            or article_url in seen_articles
            or is_junk(title)
        ):
            continue

        seen_articles.add(article_url)
        news_item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": article_url,
            "date": publication_date,
        }
        article_paragraphs = _article_paragraphs(item)
        if article_paragraphs:
            news_item["article_paragraphs"] = article_paragraphs
        result.append(news_item)

    return result, False


def _article_paragraphs(item):
    """Извлекает официальный анонс и текст из полей JSON API."""
    paragraphs = []
    seen = set()

    for field in ("caption", "text"):
        raw_text = str(item.get(field, "") or "").strip()
        if not raw_text:
            continue

        soup = BeautifulSoup(raw_text, "html.parser")
        nodes = soup.select("p, li")
        values = (
            [node.get_text(" ", strip=True) for node in nodes]
            if nodes
            else [soup.get_text(" ", strip=True)]
        )
        for value in values:
            paragraph = " ".join(value.split())
            normalized = paragraph.casefold()
            if len(paragraph) < 15 or normalized in seen:
                continue
            seen.add(normalized)
            paragraphs.append(paragraph)

    return paragraphs[:100]


def _article_url(slug):
    value = str(slug or "").strip()
    if not value:
        return ""

    candidate = urljoin(f"{SITE_URL}/", value)
    parts = urlsplit(candidate)
    if not _is_allowed_host(parts):
        return ""

    return urlunsplit(("https", API_HOST, parts.path, parts.query, ""))


def _safe_next_url(value):
    value = str(value or "").strip()
    if not value:
        return ""

    candidate = urljoin(API_URL, value)
    parts = urlsplit(candidate)
    if not _is_allowed_host(parts):
        return ""
    if parts.path.rstrip("/") != "/api/news":
        return ""

    return urlunsplit(("https", API_HOST, "/api/news", parts.query, ""))


def _is_allowed_host(parts):
    try:
        port = parts.port
    except ValueError:
        return False

    return (
        parts.scheme.casefold() in {"http", "https"}
        and (parts.hostname or "").casefold() == API_HOST
        and not parts.username
        and not parts.password
        and port in {None, 80, 443}
    )
