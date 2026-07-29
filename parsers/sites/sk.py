import re
from urllib.parse import urljoin

from utils.dates import (
    date_from_document,
    date_from_news_card,
    validate_publication_date,
)
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "СК РФ"
OFFICIAL_CHANNEL_URL = "https://t.me/s/rusledcom"
ARTICLE_ID_PATTERN = re.compile(
    r"/news/(?:item|detail)/(\d+)",
    re.IGNORECASE,
)


def parse():
    news, seen = [], set()
    channel_dates = _official_channel_dates()

    for p in range(3):
        u = f"https://sledcom.ru/news/?PAGEN_1={p + 1}" if p else "https://sledcom.ru/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.select('a[href*="/news/item/"], a[href*="/news/detail/"]'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = urljoin(u, href).split('?', 1)[0]
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue
            seen.add(full_url)
            card_date = date_from_news_card(
                a,
                r"/news/(?:item|detail)/",
            )
            date_str = channel_dates.get(_article_id(full_url), "")
            if not date_str:
                detail = fetch_soup(full_url, SOURCE_NAME, timeout=15)
                date_str = date_from_document(
                    detail,
                    prefer_visible=True,
                )
            if not date_str:
                date_str = card_date
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str,
            })

    with_date = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {with_date})")
    return news


def _official_channel_dates():
    """
    Возвращает даты публикаций из официального канала СК.

    На странице sledcom.ru дата общего блока иногда назначается всем
    карточкам подряд. В канале каждая ссылка находится внутри отдельного
    сообщения с точным временем публикации, поэтому используем его дату
    как основной источник и оставляем сайт резервным.
    """
    soup = fetch_soup(
        OFFICIAL_CHANNEL_URL,
        f"{SOURCE_NAME}: даты",
        timeout=15,
    )
    return _channel_dates_from_soup(soup)


def _channel_dates_from_soup(soup):
    dates = {}
    if soup is None:
        return dates

    selector = (
        'a[href*="sledcom.ru/news/item/"], '
        'a[href*="sledcom.ru/news/detail/"]'
    )
    for link in soup.select(selector):
        article_id = _article_id(link.get("href", ""))
        if not article_id:
            continue

        message = link.find_parent(class_="tgme_widget_message")
        if message is None:
            continue

        time_tag = message.select_one("time[datetime]")
        if time_tag is None:
            continue

        date_str = validate_publication_date(
            time_tag.get("datetime", ""),
        )
        if date_str:
            dates[article_id] = date_str

    return dates


def _article_id(url):
    match = ARTICLE_ID_PATTERN.search(str(url or ""))
    return match.group(1) if match else ""
