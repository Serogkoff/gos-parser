from urllib.parse import urljoin

from utils.dates import (
    date_from_document,
    date_from_news_card,
    validate_publication_date,
)
from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import normalize_url

SOURCE_NAME = "СК РФ"


def parse():
    news, seen = [], set()

    for p in range(3):
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
            detail = fetch_soup(full_url, SOURCE_NAME, timeout=15)
            date_str = _date_from_sk_article(detail) or card_date
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str,
            })

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
