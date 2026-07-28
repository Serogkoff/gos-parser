import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js


SOURCE_NAME = "Минприроды"
BASE_URL = "https://www.mnr.gov.ru"
NEWS_URL = f"{BASE_URL}/press/news/"

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _fetch_page(url):
    """
    Сначала пробует обычный HTTP-запрос с двумя вариантами домена.
    Браузер используется только как запасной вариант.
    """
    candidates = [
        url,
        url.replace("https://www.mnr.gov.ru", "https://mnr.gov.ru", 1),
    ]

    for attempt, candidate in enumerate(candidates, start=1):
        soup = fetch_soup(candidate, SOURCE_NAME, timeout=40)
        if soup is not None:
            return soup

        if attempt < len(candidates):
            print("  ℹ️ Минприроды сбросило соединение — повтор через 4 секунды")
            time.sleep(4)

    print("  ℹ️ Обычные запросы отклонены — пробую открыть страницу браузером")
    return fetch_soup_js(url, SOURCE_NAME, wait_ms=2500, timeout_ms=45000)


def _article_url(href):
    """Возвращает только ссылку на конкретную публикацию Минприроды."""
    if not href:
        return ""

    url = urljoin(BASE_URL, href.strip())
    parts = urlsplit(url)
    hostname = (parts.hostname or "").casefold()
    path = parts.path.rstrip("/")

    if hostname not in {"mnr.gov.ru", "www.mnr.gov.ru"}:
        return ""
    if not path.startswith("/press/news/") or path == "/press/news":
        return ""

    # Для Bitrix-страниц завершающий слеш важен.
    return urljoin(BASE_URL, path + "/")


def _parse_date(raw):
    try:
        parts = raw.replace(",", " ").split()
        day = int(parts[0])
        month = MONTHS[parts[1].casefold()]
        year = int(parts[2][:4])
        return datetime(year, month, day)
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for page in range(1, 3):
        if page > 1:
            # Не отправляем сайту два запроса подряд.
            time.sleep(4)

        url = NEWS_URL if page == 1 else f"{NEWS_URL}?PAGEN_1={page}"
        soup = _fetch_page(url)

        # Если не открылась даже первая страница, вторую не атакуем.
        if soup is None:
            if page == 1:
                break
            continue

        for item in soup.select(".news-item"):
            title_tag = item.select_one(".news-item__title a")
            date_tag = item.select_one(".news-item__date")

            if not title_tag:
                continue

            title = title_tag.get_text(" ", strip=True)
            article_url = _article_url(title_tag.get("href", ""))

            if (
                len(title) < 20
                or title in seen
                or is_junk(title)
                or not article_url
            ):
                continue

            publication_date = (
                _parse_date(date_tag.get_text(" ", strip=True))
                if date_tag
                else None
            )
            if publication_date and publication_date < cutoff:
                continue

            seen.add(title)
            news.append(
                {
                    "source": SOURCE_NAME,
                    "title": title,
                    "url": article_url,
                    "date": (
                        publication_date.strftime("%Y-%m-%d")
                        if publication_date
                        else ""
                    ),
                }
            )

    dated_count = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {dated_count})")
    return news