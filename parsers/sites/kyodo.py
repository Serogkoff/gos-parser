"""Парсер японских материалов Kyodo с главной страницы 47NEWS."""

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import HEADERS
from utils.js_client import fetch_soup_js
from utils.logger import get_logger
from utils.news import deduplicate_news


SOURCE_NAME = "Киодо (共同通信)"
HOME_URL = "https://www.47news.jp/"
NEWS_URL = "https://www.47news.jp/news"
PUBLISHER_NAME = "共同通信"
MAX_AGE_DAYS = 30
NEXT_BUILD_ID = "uFzqY36IiFlXsPPmSxzhK"

logger = get_logger("kyodo")
_next_build_id = NEXT_BUILD_ID

# На главной странице 47NEWS каждая рубрика содержит шесть самых свежих
# материалов. Поэтому один лёгкий запрос заменяет обход множества страниц.
SECTION_KEYS = (
    ("topNews", "Главное"),
    ("nationalNews", "Общество"),
    ("politicsNews", "Политика"),
    ("economicsNews", "Экономика"),
    ("worldNews", "Международные новости"),
    ("sportsNews", "Спорт"),
    ("cultural", "Культура"),
    ("medical", "Медицина"),
    ("scienceEnvironment", "Наука и экология"),
    ("entertainment", "Развлечения"),
    ("opnion", "Мнения"),
    ("obituary", "Некрологи"),
)


def parse():
    page_props = _fetch_page_props()
    if not page_props:
        print("  ✅ 0")
        return []

    news = _parse_47news_page(page_props)
    print(f"  ✅ {len(news)}")
    return news


def _fetch_page_props():
    """Получает компактные данные Next.js, не скачивая тяжёлую главную."""
    global _next_build_id

    data_url = f"{HOME_URL}_next/data/{_next_build_id}/news.json"
    try:
        response = requests.get(
            data_url,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=(10, 45),
        )
        response.raise_for_status()
        payload = response.json()
        page_props = payload.get("pageProps", {})
        if page_props:
            return page_props
    except (requests.RequestException, ValueError) as error:
        logger.warning(
            f"[{SOURCE_NAME}] Компактная лента 47NEWS недоступна: "
            f"{type(error).__name__}: {error}"
        )

    # На некоторых российских маршрутах CloudFront зависает именно для
    # requests (HTTP/1.1), хотя браузер открывает сайт. Системный curl умеет
    # HTTP/2 и обычно проходит тем же путём, что и обычный браузер.
    page_props = _fetch_page_props_with_curl(data_url)
    if page_props:
        return page_props

    # После обновления 47NEWS меняется buildId. Браузерный резерв получает
    # новый идентификатор и одновременно возвращает данные текущей страницы.
    print("  ℹ️ JSON-лента недоступна — пробую 47NEWS через браузер")
    soup = fetch_soup_js(
        NEWS_URL,
        SOURCE_NAME,
        wait_ms=1200,
        timeout_ms=60000,
        wait_until="domcontentloaded",
        use_partial_on_timeout=True,
    )
    if soup is None:
        return {}

    payload = _next_payload(soup)
    build_id = str(payload.get("buildId", "")).strip()
    if build_id:
        _next_build_id = build_id
    return payload.get("props", {}).get("pageProps", {})


def _fetch_page_props_with_curl(data_url):
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return {}

    try:
        completed = subprocess.run(
            [
                curl,
                "--location",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "10",
                "--max-time",
                "60",
                "--header",
                f"User-Agent: {HEADERS['User-Agent']}",
                "--header",
                "Accept: application/json",
                data_url,
            ],
            capture_output=True,
            check=True,
            timeout=70,
        )
        payload = json.loads(completed.stdout.decode("utf-8"))
        return payload.get("pageProps", {})
    except (subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.warning(
            f"[{SOURCE_NAME}] Системный curl не получил ленту: "
            f"{type(error).__name__}: {error}"
        )
        return {}


def _parse_47news_page(page, now=None):
    """Читает JSON страницы и оставляет только публикации 共同通信."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    page_props = _coerce_page_props(page)
    news = []

    # /news — отдельная и существенно более лёгкая страница共同通信.
    direct_entries = (
        page_props.get("data", {}).get("categoryNewsList", [])
        if isinstance(page_props.get("data"), dict)
        else []
    )
    sections = (
        (("categoryNewsList", "Все новости", direct_entries),)
        if direct_entries
        else tuple((key, section, _section_entries(page_props.get(key))) for key, section in SECTION_KEYS)
    )

    for _key, section, entries in sections:
        for entry in entries:
            publisher = (entry.get("user") or {}).get("title", "")
            if publisher != PUBLISHER_NAME:
                continue

            title = " ".join(str(entry.get("title", "")).split())
            url = urljoin(HOME_URL, str(entry.get("url", "")))
            publication_date = _parse_47news_date(entry.get("startDate", ""))

            if (
                len(title) < 5
                or is_junk(title)
                or not _is_47news_article_url(url)
            ):
                continue

            if publication_date:
                parsed = datetime.strptime(publication_date, "%Y-%m-%d")
                if parsed < cutoff:
                    continue

            summary = _clean_summary(entry.get("body", ""))
            image = entry.get("image") or {}

            item = {
                "source": SOURCE_NAME,
                "title": title,
                "url": url,
                "date": publication_date,
                "section": section,
                "source_id": str(entry.get("id", "")),
            }
            if summary:
                item["summary"] = summary
            if image.get("url"):
                item["image"] = str(image["url"])
            news.append(item)

    return deduplicate_news(news)


def _next_payload(soup):
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None:
        return {}
    try:
        return json.loads(script.string or script.get_text())
    except (TypeError, json.JSONDecodeError):
        return {}


def _coerce_page_props(page):
    if isinstance(page, dict):
        return page
    return _next_payload(page).get("props", {}).get("pageProps", {})


def _section_entries(value):
    # topNews хранит список в поле Article; остальные рубрики — напрямую.
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        entries = value.get("Article", [])
        return entries if isinstance(entries, list) else []
    return []


def _parse_47news_date(raw_date):
    try:
        return datetime.strptime(
            str(raw_date).strip(),
            "%Y-%m-%d %H:%M:%S",
        ).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _is_47news_article_url(url):
    parts = urlsplit(str(url))
    hostname = (parts.hostname or "").casefold()
    path = parts.path.strip("/")
    return (
        hostname in {"47news.jp", "www.47news.jp"}
        and path.endswith(".html")
        and path[:-5].isdigit()
    )


def _clean_summary(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.replace("...", "").split())
