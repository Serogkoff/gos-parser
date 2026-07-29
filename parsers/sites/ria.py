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
SECTION_URLS = (
    ("Политика", "https://ria.ru/politics/"),
    ("В мире", "https://ria.ru/world/"),
    ("Экономика", "https://ria.ru/economy/"),
    ("Общество", "https://ria.ru/society/"),
    ("Происшествия", "https://ria.ru/incidents/"),
    ("Наука", "https://ria.ru/science/"),
    ("Культура", "https://ria.ru/culture/"),
    ("Туризм", "https://ria.ru/tourism/"),
    ("Спорт", "https://ria.ru/sport/"),
)
SECTIONS_PER_RUN = 3
RIA_URL_DATE = re.compile(r"/(20\d{2})(\d{2})(\d{2})/")
_section_cache = {}
_next_section_index = 0


def parse():
    latest_soup = fetch_soup(FEED_URL, SOURCE_NAME, timeout=30)
    latest_news = (
        _parse_ria_cards(latest_soup, section="Последние новости")
        if latest_soup is not None
        else []
    )

    _refresh_next_sections()

    cached_news = [
        item
        for section_news in _section_cache.values()
        for item in section_news
    ]
    # Кэш рубрик идёт первым, чтобы у совпавшей новости сохранилось точное
    # название раздела, а не общее «Последние новости».
    news = deduplicate_news([*cached_news, *latest_news])

    if not news:
        print("  ✅ 0")
        return []

    print(f"  ✅ {len(news)}")
    return news


def _refresh_next_sections():
    """
    Обновляет за один запуск только часть основных рубрик.

    За три трехминутных цикла парсер обходит все девять разделов.
    Это защищает РИА и сам парсер от серии долгих запросов подряд.
    """
    global _next_section_index

    if not SECTION_URLS:
        return

    for _ in range(min(SECTIONS_PER_RUN, len(SECTION_URLS))):
        section, url = SECTION_URLS[_next_section_index]
        _next_section_index = (_next_section_index + 1) % len(SECTION_URLS)
        soup = fetch_soup(url, f"{SOURCE_NAME} · {section}", timeout=30)
        if soup is not None:
            _section_cache[section] = _parse_ria_cards(
                soup,
                section=section,
            )


def _parse_ria_cards(soup, now=None, section=""):
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

        item = _build_ria_item(
            title,
            url,
            raw_date,
            section=section,
            now=now,
        )
        if item:
            news.append(item)

    # У разделов «Спорт» и «Туризм» другой шаблон карточек.
    for link in soup.select(
        "a.cell-list__item-link[href], "
        "a.cell-list-f__main-link[href], "
        "a.cell-list-f__item-link[href]"
    ):
        title_node = link.select_one(
            ".cell-list__item-title, "
            ".cell-list-f__main-title, "
            ".cell-list-f__item-title"
        )
        title = " ".join(
            (
                title_node.get_text(" ", strip=True)
                if title_node
                else link.get("title", "")
            ).split()
        )
        raw_date_node = link.select_one(".cell-info__date")
        raw_date = (
            raw_date_node.get_text(" ", strip=True)
            if raw_date_node
            else ""
        )
        item = _build_ria_item(
            title,
            urljoin(FEED_URL, link.get("href", "")),
            raw_date,
            section=section,
            now=now,
        )
        if item:
            news.append(item)

    return deduplicate_news(news)


def _build_ria_item(title, url, raw_date, section, now):
    title = " ".join(str(title).split())
    if (
        len(title) < 10
        or not url.startswith(("https://ria.ru/", "http://ria.ru/"))
        or is_junk(title)
    ):
        return None

    publication_date = _parse_ria_date(url, raw_date, now=now)
    if publication_date:
        parsed = datetime.strptime(publication_date, "%Y-%m-%d")
        if parsed < now - timedelta(days=30):
            return None

    return {
        "source": SOURCE_NAME,
        "title": title,
        "url": url,
        "date": publication_date,
        "section": section,
    }


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
