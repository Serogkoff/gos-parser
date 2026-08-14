"""Парсер японских материалов Kyodo с главной страницы 47NEWS."""

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import HEADERS
from utils.js_client import fetch_soup_js
from utils.logger import get_logger
from utils.news import deduplicate_news
from utils.proxy import kyodo_proxy_url, proxy_environment, requests_proxies


SOURCE_NAME = "Киодо (共同通信)"
HOME_URL = "https://www.47news.jp/"
NEWS_URL = "https://www.47news.jp/news"
PUBLISHER_NAME = "共同通信"
MAX_AGE_DAYS = 30
BUILD_ID_FILE = Path(__file__).resolve().parents[2] / "kyodo_build_id.txt"

logger = get_logger("kyodo")
_next_build_id = ""


def _proxy_url():
    """Отдельный голландский маршрут; остальные источники его не используют."""
    try:
        return kyodo_proxy_url()
    except ValueError as error:
        logger.warning(f"[{SOURCE_NAME}] Настройка прокси некорректна: {error}")
        return ""

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

# Официальные тематические разделы共同通信 на 47NEWS. Общая страница
# возвращает только двадцать материалов и игнорирует обычный ?page=N,
# поэтому собираем первые двадцать публикаций каждой рубрики отдельно.
CATEGORY_ROUTES = (
    ("Общество", "/news/national/"),
    ("Политика", "/news/politics/"),
    ("Экономика", "/news/economics/"),
    ("Спорт", "/news/sports/"),
    ("Культура", "/news/culture/"),
)


def parse():
    first_page = _fetch_page_props()
    if not first_page:
        print("  ✅ 0")
        return []

    news = _parse_47news_page(first_page)
    known_urls = {item.get("url") for item in news}

    for section, route in CATEGORY_ROUTES:
        page_props = _fetch_category_page_props(route)
        if not page_props:
            continue
        page_news = _parse_47news_page(page_props, direct_section=section)
        fresh = [item for item in page_news if item.get("url") not in known_urls]
        news.extend(fresh)
        known_urls.update(item.get("url") for item in fresh)

    news = deduplicate_news(news)
    print(f"  ✅ {len(news)}")
    return news


def _fetch_page_props():
    """Получает данные Next.js и обновляет изменившийся buildId."""
    global _next_build_id

    if not _next_build_id:
        _next_build_id = _load_build_id()

    data_url = ""
    stale_build = not bool(_next_build_id)
    if _next_build_id:
        data_url = f"{HOME_URL}_next/data/{_next_build_id}/news.json"
        try:
            response = requests.get(
                data_url,
                headers={**HEADERS, "Accept": "application/json"},
                timeout=(4, 8),
                proxies=requests_proxies(_proxy_url()),
            )
            response.raise_for_status()
            payload = response.json()
            page_props = payload.get("pageProps", {})
            if page_props:
                return page_props
        except (requests.RequestException, ValueError) as error:
            stale_build = getattr(getattr(error, "response", None), "status_code", None) == 404
            logger.warning(
                f"[{SOURCE_NAME}] Компактная лента 47NEWS недоступна: "
                f"{type(error).__name__}: {error}"
            )

    # При сетевом сбое curl иногда проходит по HTTP/2. При 404 повторять
    # заведомо устаревший JSON бессмысленно — сразу узнаём новый buildId.
    if not stale_build:
        page_props = _fetch_page_props_with_curl(data_url)
        if page_props:
            return page_props

    payload = _fetch_news_payload_http()
    if not payload:
        payload = _fetch_news_payload_with_curl()

    if not payload:
        print("  ℹ️ JSON-лента недоступна — пробую 47NEWS через браузер")
        soup = fetch_soup_js(
            NEWS_URL,
            SOURCE_NAME,
            wait_ms=800,
            timeout_ms=18000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
            proxy_url=_proxy_url(),
        )
        payload = _next_payload(soup) if soup else {}

    build_id = str(payload.get("buildId", "")).strip()
    if build_id:
        _next_build_id = build_id
        _save_build_id(build_id)
    return payload.get("props", {}).get("pageProps", {})


def _load_build_id():
    try:
        return BUILD_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _save_build_id(build_id):
    try:
        BUILD_ID_FILE.write_text(str(build_id).strip(), encoding="utf-8")
    except OSError as error:
        logger.warning(f"[{SOURCE_NAME}] Не удалось сохранить buildId: {error}")


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
                "4",
                "--max-time",
                "10",
                "--header",
                f"User-Agent: {HEADERS['User-Agent']}",
                "--header",
                "Accept: application/json",
                data_url,
            ],
            capture_output=True,
            check=True,
            timeout=12,
            env=proxy_environment(_proxy_url()),
        )
        payload = json.loads(completed.stdout.decode("utf-8"))
        return payload.get("pageProps", {})
    except (subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.warning(
            f"[{SOURCE_NAME}] Системный curl не получил ленту: "
            f"{type(error).__name__}: {error}"
        )
        return {}


def _fetch_news_payload_http():
    """Пытается прочитать HTML /news без запуска Chromium."""
    try:
        response = requests.get(
            NEWS_URL,
            headers={**HEADERS, "Accept": "text/html,*/*;q=0.8"},
            timeout=(4, 8),
            proxies=requests_proxies(_proxy_url()),
        )
        response.raise_for_status()
        return _next_payload(BeautifulSoup(response.content, "html.parser"))
    except requests.RequestException:
        return {}


def _fetch_news_payload_with_curl():
    """HTTP/2-резерв для получения нового buildId без браузера."""
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
                "4",
                "--max-time",
                "10",
                "--header",
                f"User-Agent: {HEADERS['User-Agent']}",
                NEWS_URL,
            ],
            capture_output=True,
            check=True,
            timeout=12,
            env=proxy_environment(_proxy_url()),
        )
        soup = BeautifulSoup(completed.stdout, "html.parser")
        return _next_payload(soup)
    except subprocess.SubprocessError:
        return {}


def _fetch_category_page_props(route):
    """Читает отдельную рубрику共同通信 без запуска браузера."""
    route = "/" + str(route).strip("/") + "/"
    route_json = route.strip("/") + ".json"
    if _next_build_id:
        data_url = f"{HOME_URL}_next/data/{_next_build_id}/{route_json}"
        try:
            response = requests.get(
                data_url,
                headers={**HEADERS, "Accept": "application/json"},
                timeout=(4, 8),
                proxies=requests_proxies(_proxy_url()),
            )
            response.raise_for_status()
            page_props = response.json().get("pageProps", {})
            if page_props:
                return page_props
        except (requests.RequestException, ValueError):
            pass

    try:
        response = requests.get(
            urljoin(HOME_URL, route),
            headers={**HEADERS, "Accept": "text/html,*/*;q=0.8"},
            timeout=(4, 8),
            proxies=requests_proxies(_proxy_url()),
        )
        response.raise_for_status()
        payload = _next_payload(BeautifulSoup(response.content, "html.parser"))
        return payload.get("props", {}).get("pageProps", {})
    except requests.RequestException:
        payload = _fetch_url_payload_with_curl(urljoin(HOME_URL, route))
        return payload.get("props", {}).get("pageProps", {})


def _fetch_url_payload_with_curl(url):
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
                "4",
                "--max-time",
                "10",
                "--header",
                f"User-Agent: {HEADERS['User-Agent']}",
                url,
            ],
            capture_output=True,
            check=True,
            timeout=12,
            env=proxy_environment(_proxy_url()),
        )
        return _next_payload(BeautifulSoup(completed.stdout, "html.parser"))
    except subprocess.SubprocessError:
        return {}


def _parse_47news_page(page, now=None, direct_section="Все новости"):
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
        (("categoryNewsList", direct_section, direct_entries),)
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
