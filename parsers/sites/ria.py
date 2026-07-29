"""Парсер свежей ленты РИА Новости."""

import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

from utils.dates import validate_publication_date
from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "РИА Новости"
FEED_URL = "https://ria.ru/lenta/"
RIA_URL_DATE = re.compile(r"/(20\d{2})(\d{2})(\d{2})/")


def parse():
    soup = fetch_soup(FEED_URL, SOURCE_NAME, timeout=30)
    if soup is None:
        print("  ✅ 0")
        return []

    news = _parse_ria_cards(soup)
    print(f"  ✅ {len(news)}")
    return news


def _parse_ria_cards(soup, now=None):
    """Преобразует карточки ленты РИА в общий формат проекта."""
    now = now or datetime.now()
    news = []

    for card in soup.select(".list-item"):
        if card.get("data-type") not in (None, "", "article"):
            continue

        link = card.select_one("a.list-item__title[href]")
        if link is None:
            continue

        title = " ".join(link.get_text(" ", strip=True).split())
        url = urljoin(FEED_URL, link.get("href", ""))
        if (
            len(title) < 10
            or not url.startswith(("https://ria.ru/", "http://ria.ru/"))
            or is_junk(title)
        ):
            continue

        date_node = card.select_one(
            ".list-item__info-item[data-type='date'], "
            ".list-item__date, time"
        )
        raw_date = date_node.get_text(" ", strip=True) if date_node else ""

        news.append({
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": _parse_ria_date(url, raw_date, now=now),
        })

    return deduplicate_news(news)


def _parse_ria_date(url, raw_date="", now=None):
    """
    Читает дату из адреса статьи РИА.

    В адресах РИА дата имеет устойчивый вид /20260729/. Время в карточке
    используется только как запасной вариант.
    """
    now = now or datetime.now()
    match = RIA_URL_DATE.search(str(url))
    if match:
        year, month, day = map(int, match.groups())
        parsed = validate_publication_date(
            f"{year:04d}-{month:02d}-{day:02d}",
            now=now,
        )
        if parsed:
            return parsed

    text = " ".join(str(raw_date).lower().replace("\xa0", " ").split())
    if text.startswith("вчера"):
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if text.startswith("сегодня") or re.fullmatch(r"\d{1,2}:\d{2}", text):
        return now.strftime("%Y-%m-%d")

    return validate_publication_date(text, now=now)
