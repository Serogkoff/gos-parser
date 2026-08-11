import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "Минпромторг"
NEWS_URL = "https://minpromtorg.gov.ru/press-centre/news"
DATE_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{4})\s*")


def parse():
    cutoff = datetime.now() - timedelta(days=30)
    news = []

    # Старый HTML сайта по-прежнему иногда содержит готовые карточки.
    # Сначала пробуем дешёвый вариант без запуска Chromium.
    for page in range(1, 3):
        url = NEWS_URL if page == 1 else f"{NEWS_URL}/?PAGEN_1={page}"
        soup = fetch_soup(url, SOURCE_NAME)
        if soup is not None:
            news.extend(_parse_news_page(soup, url, cutoff))

    # После обновления сайта обычный ответ часто представляет собой пустой
    # JavaScript-каркас. Одного браузерного открытия первой страницы достаточно,
    # чтобы получить самые свежие материалы, не замедляя цикл второй страницей.
    if not news:
        print("  ℹ️ Карточки Минпромторга подгружаются JavaScript — открываю браузером")
        soup = fetch_soup_js(
            NEWS_URL,
            SOURCE_NAME,
            wait_ms=5000,
            timeout_ms=60000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )
        if soup is not None:
            news.extend(_parse_news_page(soup, NEWS_URL, cutoff))

    news = deduplicate_news(news)
    print(f"  ✅ {len(news)}")
    return news


def _parse_news_page(soup, base_url, cutoff):
    result = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/press-centre/news/" not in href:
            continue

        raw_text = " ".join(link.get_text(" ", strip=True).split())
        date_match = DATE_RE.match(raw_text)
        if not date_match:
            continue

        try:
            publication_date = datetime.strptime(
                date_match.group(1),
                "%d.%m.%Y",
            )
        except ValueError:
            continue
        if publication_date < cutoff:
            continue

        title = DATE_RE.sub("", raw_text).strip()
        if len(title) < 20 or is_junk(title):
            continue

        result.append(
            {
                "source": SOURCE_NAME,
                "title": title,
                "url": urljoin(base_url, href),
                "date": publication_date.strftime("%Y-%m-%d"),
            }
        )
    return result
