"""Meduza через RSS с независимым HTTPS-reader как последним резервом."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_json, fetch_soup
from utils.logger import get_logger
from utils.news import deduplicate_news

from parsers.sites.vpn_rss import VpnRssSource, parse_feed, parse_source

SOURCE_NAME = "Meduza"
READER_SCREEN_URL = "https://r.jina.ai/http://meduza.io/api/w5/screens/news"
MIRROR_INDEX_URL = "https://storage.googleapis.com/meduza-alive/mirror.html"
READER_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}
logger = get_logger("meduza")
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://meduza.io/rss2/all",
    domains=("meduza.io",),
    article_selectors=("[class*='GeneralMaterial-module-article']", "main"),
    rss_full_text_fallback=True,
    direct_feed_fallback_urls=("https://meduza.io/rss2/all",),
    feed_timeout=12,
    feed_attempts=1,
)


def parse():
    items = parse_source(CONFIG, print_empty=False)
    if items:
        return items

    items = _official_mirror_items()
    if items:
        print(f"  ✅ {len(items)}")
        return items

    items = _reader_items()
    print(f"  ✅ {len(items)}")
    return items


def _reader_items(now=None):
    """Читает публичный экран Meduza, если оба RSS-маршрута недоступны."""
    payload = fetch_json(
        READER_SCREEN_URL,
        f"{SOURCE_NAME} · резервный reader",
        timeout=45,
        attempts=1,
        request_headers=READER_HEADERS,
    )
    try:
        content = payload["data"]["content"]
        screen = json.loads(content)
        documents = screen["documents"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning(
            f"[{SOURCE_NAME}] Резервный reader вернул некорректный ответ"
        )
        return []

    if not isinstance(documents, dict):
        return []

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    items = []
    for document in documents.values():
        if not isinstance(document, dict):
            continue
        path = str(document.get("url", "")).strip().lstrip("/")
        title = " ".join(str(document.get("title", "")).split())
        if (
            not path.startswith(("news/", "feature/", "cards/"))
            or len(title) < 5
            or is_junk(title)
        ):
            continue
        try:
            published = datetime.fromtimestamp(
                int(document["datetime"]),
                tz=timezone.utc,
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if published > now:
            continue

        section = {
            "news": "Новости",
            "feature": "Истории",
            "cards": "Карточки",
        }.get(path.split("/", 1)[0], "Новости")
        items.append({
            "source": SOURCE_NAME,
            "title": title,
            "url": f"https://meduza.io/{path}",
            "rss_url": f"https://meduza.io/{path}",
            "date": published.date().isoformat(),
            "published_at": published.isoformat(timespec="seconds"),
            "section": section,
            "article_fetch_pending": True,
        })

    items.sort(key=lambda item: item["published_at"], reverse=True)
    return deduplicate_news(items[: CONFIG.max_items])


def _official_mirror_items():
    """Разрешает постоянно меняющееся официальное зеркало Meduza."""
    index = fetch_soup(
        MIRROR_INDEX_URL,
        f"{SOURCE_NAME} · адрес зеркала",
        timeout=12,
        verify=True,
        attempts=1,
    )
    mirror_url = _mirror_url(index)
    if not mirror_url:
        return []

    feed_url = urljoin(mirror_url.rstrip("/") + "/", "rss2/all")
    feed = fetch_soup(
        feed_url,
        f"{SOURCE_NAME} · официальное зеркало RSS",
        timeout=12,
        verify=True,
        parser="xml",
        attempts=1,
    )
    if feed is None or feed.find("item") is None:
        return []

    hostname = (urlsplit(mirror_url).hostname or "").casefold()
    mirror_config = replace(
        CONFIG,
        feed_url=feed_url,
        domains=CONFIG.domains,
        feed_fallback_urls=(),
        direct_feed_fallback_urls=(),
        feed_url_rewrites=((hostname, "meduza.io"),),
    )
    items = parse_feed(feed, mirror_config)
    for item in items:
        item["article_fetch_pending"] = True
    return items


def _mirror_url(index):
    if not isinstance(index, BeautifulSoup):
        return ""
    link = index.select_one("a[href]")
    value = str(link.get("href", "")).strip() if link else ""
    parts = urlsplit(value)
    hostname = (parts.hostname or "").casefold()
    if (
        parts.scheme != "https"
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or hostname == "localhost"
        or hostname.endswith(".localhost")
    ):
        return ""
    return f"https://{hostname}"
