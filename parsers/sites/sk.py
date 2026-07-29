import time
from urllib.parse import urljoin

from utils.dates import (
    date_from_document,
    date_from_news_card,
    validate_publication_date,
)
from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import normalize_url
from utils.storage import (
    PROJECT_DIR,
    _load_json,
    _write_json_atomic,
)

SOURCE_NAME = "СК РФ"
DATE_CACHE_FILE = PROJECT_DIR / "sk_dates.json"
DETAIL_REQUEST_PAUSE = 0.5


def parse():
    news, seen = [], set()
    date_cache = _load_date_cache()
    cache_changed = False

    # Первая страница содержит текущую десятку публикаций.
    # Дополнительные страницы раньше создавали лишнюю нагрузку на сайт.
    for p in range(1):
        u = f"https://sledcom.ru/news/?PAGEN_1={p + 1}" if p else "https://sledcom.ru/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.select('a[href*="/news/item/"], a[href*="/news/detail/"]'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = normalize_url(
                urljoin(u, href).split('?', 1)[0]
            )
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue
            seen.add(full_url)
            card_date = date_from_news_card(
                a,
                r"/news/(?:item|detail)/",
            )
            date_str = date_cache.get(full_url, "")
            if not date_str:
                detail = fetch_soup(
                    full_url,
                    SOURCE_NAME,
                    timeout=15,
                )
                detail_date = _date_from_sk_article(detail)
                if detail_date:
                    date_str = detail_date
                    date_cache[full_url] = detail_date
                    cache_changed = True
                else:
                    date_str = card_date
                time.sleep(DETAIL_REQUEST_PAUSE)

            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str,
            })

    if cache_changed:
        _save_date_cache(date_cache)

    with_date = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {with_date})")
    return news


def _date_from_sk_article(soup):
    """
    Читает дату, показанную непосредственно на странице публикации СК.

    Дата общей ленты иногда относится к соседней карточке, поэтому сначала
    используем специальное поле статьи ``news-item__date``. Универсальный
    поиск оставлен только как резерв для другого варианта шаблона сайта.
    """
    if soup is None:
        return ""

    date_tag = soup.select_one(".news-item__date")
    if date_tag is not None:
        date_str = validate_publication_date(
            date_tag.get_text(" ", strip=True),
        )
        if date_str:
            return date_str

    return date_from_document(
        soup,
        prefer_visible=True,
    )


def _load_date_cache():
    cache = {}
    for item in _load_json(DATE_CACHE_FILE):
        if not isinstance(item, dict):
            continue
        url = normalize_url(item.get("url", ""))
        date_str = validate_publication_date(item.get("date", ""))
        if url and date_str:
            cache[url] = date_str
    return cache


def _save_date_cache(cache):
    document = [
        {
            "url": url,
            "date": date_str,
        }
        for url, date_str in sorted(cache.items())
        if url and date_str
    ]
    _write_json_atomic(DATE_CACHE_FILE, document)
