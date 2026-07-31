"""Парсер официальной ленты Министерства обороны России."""

import json
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.dates import date_from_news_card, validate_publication_date
from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "Минобороны РФ"
NEWS_URL = "https://z.mil.ru/news"
MAX_AGE_DAYS = 30
MAX_ITEMS = 60
ARTICLE_PATH = re.compile(
    r"^/news/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?$",
    re.IGNORECASE,
)


def parse():
    soup = fetch_soup(
        NEWS_URL,
        SOURCE_NAME,
        timeout=45,
        verify=False,
    )
    news = _parse_news_page(soup) if soup is not None else []

    # Новый сайт Минобороны может отдавать обычному запросу только оболочку,
    # а карточки добавлять JavaScript. В таком случае открываем страницу
    # браузером и разбираем уже готовый DOM.
    if not news:
        print("  ℹ️ Обычная страница пуста — пробую Минобороны через браузер")
        soup = fetch_soup_js(
            NEWS_URL,
            SOURCE_NAME,
            wait_ms=2500,
            timeout_ms=60000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )
        news = _parse_news_page(soup) if soup is not None else []

    print(f"  ✅ {len(news)}")
    return news


def _parse_news_page(soup, now=None):
    if soup is None:
        return []

    now = now or datetime.now()
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    items = []

    for link in soup.select("a[href]"):
        full_url = urljoin(NEWS_URL, link.get("href", ""))
        if not _is_article_url(full_url):
            continue

        title = _title_from_link(link)
        if len(title) < 15 or is_junk(title):
            continue

        publication_date = _date_from_minoborony_card(link, now=now)
        if not publication_date:
            publication_date = date_from_news_card(
                link,
                r"/news/[0-9a-f-]{36}/?",
                max_levels=7,
                now=now,
            )
        if publication_date:
            parsed = datetime.strptime(publication_date, "%Y-%m-%d")
            if parsed < cutoff:
                continue

        summary = _summary_from_minoborony_card(link, title)

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": full_url,
            "date": publication_date,
        }
        if summary:
            item["summary"] = summary
        items.append(item)

    # Некоторые сборки сайта хранят карточки в JSON-состоянии страницы.
    # Этот путь помогает, даже если ссылки ещё не появились в DOM.
    items.extend(_news_from_embedded_json(soup, cutoff, now))
    return deduplicate_news(items)[:MAX_ITEMS]


def _title_from_link(link):
    candidates = [
        link.get("title", ""),
        link.get("aria-label", ""),
        link.get_text(" ", strip=True),
    ]
    image = link.select_one("img[alt]")
    if image is not None:
        candidates.append(image.get("alt", ""))

    current = link
    for _ in range(5):
        current = getattr(current, "parent", None)
        if current is None:
            break
        heading = current.select_one(
            "h1, h2, h3, h4, h5, "
            "[class*='title'], [class*='headline'], [class*='name']"
        )
        if heading is not None:
            candidates.append(heading.get_text(" ", strip=True))

    cleaned = [" ".join(str(value or "").split()) for value in candidates]
    cleaned = [value for value in cleaned if 15 <= len(value) <= 500]
    return max(cleaned, key=len, default="")


def _date_from_minoborony_card(link, now=None):
    """Читает дату из безымянного CSS-блока карточки нового сайта mil.ru."""
    date_line = re.compile(
        r"^\s*\d{1,2}\s+"
        r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)\s+20\d{2}"
        r"(?:\s*(?:г\.)?)?(?:\s*,?\s*\d{1,2}:\d{2})?\s*$",
        re.IGNORECASE,
    )
    current = link

    for _ in range(7):
        current = getattr(current, "parent", None)
        if current is None:
            break

        article_urls = {
            urljoin(NEWS_URL, node.get("href", ""))
            for node in current.select("a[href]")
            if _is_article_url(urljoin(NEWS_URL, node.get("href", "")))
        }
        if len(article_urls) > 1:
            break

        candidates = []
        for node in current.select("time, span, p, div"):
            value = " ".join(node.get_text(" ", strip=True).split())
            if date_line.fullmatch(value):
                parsed = validate_publication_date(value, now=now)
                if parsed and parsed not in candidates:
                    candidates.append(parsed)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            return ""

    return ""


def _summary_from_minoborony_card(link, title):
    """Берёт анонс из карточки, если отдельная страница не содержит текста."""
    current = link

    for _ in range(7):
        current = getattr(current, "parent", None)
        if current is None:
            break

        article_urls = {
            urljoin(NEWS_URL, node.get("href", ""))
            for node in current.select("a[href]")
            if _is_article_url(urljoin(NEWS_URL, node.get("href", "")))
        }
        if len(article_urls) > 1:
            break

        candidates = []
        for node in current.select("p, span, div"):
            text = " ".join(node.get_text(" ", strip=True).split())
            if not 45 <= len(text) <= 1500:
                continue
            if title and (text == title or text.startswith(title)):
                continue
            if validate_publication_date(text):
                continue

            long_children = [
                child
                for child in node.find_all(["p", "span", "div"], recursive=False)
                if len(" ".join(child.get_text(" ", strip=True).split())) >= 45
            ]
            if long_children:
                continue
            candidates.append(text)

        if candidates:
            return max(candidates, key=len)

    return ""


def _news_from_embedded_json(soup, cutoff, now):
    result = []
    selectors = (
        "script[type='application/json'], "
        "script[type='application/ld+json'], "
        "script[id*='state'], script[id*='data']"
    )

    for script in soup.select(selectors):
        raw = script.string or script.get_text("", strip=True)
        if not raw or len(raw) > 8_000_000:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        for value in _walk_json(payload):
            raw_url = value.get("url") or value.get("href") or ""
            full_url = urljoin(NEWS_URL, str(raw_url))
            if not _is_article_url(full_url):
                continue

            title = " ".join(str(
                value.get("headline")
                or value.get("title")
                or value.get("name")
                or ""
            ).split())
            if len(title) < 15 or is_junk(title):
                continue

            raw_date = (
                value.get("datePublished")
                or value.get("publishedAt")
                or value.get("publicationDate")
                or value.get("createdAt")
                or value.get("date")
                or ""
            )
            publication_date = validate_publication_date(raw_date, now=now)
            if publication_date:
                parsed = datetime.strptime(publication_date, "%Y-%m-%d")
                if parsed < cutoff:
                    continue

            raw_summary = (
                value.get("description")
                or value.get("summary")
                or value.get("lead")
                or ""
            )
            summary = " ".join(
                BeautifulSoup(str(raw_summary), "html.parser")
                .get_text(" ", strip=True)
                .split()
            )

            item = {
                "source": SOURCE_NAME,
                "title": title,
                "url": full_url,
                "date": publication_date,
            }
            if len(summary) >= 45:
                item["summary"] = summary
            result.append(item)

    return result


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)


def _is_article_url(url):
    parts = urlsplit(str(url))
    hostname = (parts.hostname or "").casefold()
    return (
        (hostname == "z.mil.ru" or hostname.endswith(".z.mil.ru"))
        and ARTICLE_PATH.fullmatch(parts.path) is not None
    )
