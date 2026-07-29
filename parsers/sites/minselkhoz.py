from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.parser_links import find_article_url

SOURCE_NAME = "Минсельхоз"

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}

ARTICLE_PATH = re.compile(
    r"^/press-service/news/[^/]+/?$",
    re.IGNORECASE,
)


def _is_article_url(url):
    parts = urlsplit(url)
    hostname = (parts.hostname or "").casefold()
    return (
        (hostname == "mcx.gov.ru" or hostname.endswith(".mcx.gov.ru"))
        and ARTICLE_PATH.fullmatch(parts.path) is not None
    )


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://mcx.gov.ru/press-service/news/?PAGEN_1={p + 1}" if p else "https://mcx.gov.ru/press-service/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for item in soup.select('.newsList__wrapContent'):
            title_tag = item.select_one('.newsList__title')
            date_tag = item.select_one('.b-date')

            if not title_tag:
                continue

            t = title_tag.get_text(strip=True)
            if len(t) < 20 or t in seen or is_junk(t):
                continue

            article_url = find_article_url(item, u, _is_article_url)
            if not article_url:
                continue

            date_str = ""
            if date_tag:
                try:
                    parts = date_tag.get_text(strip=True).split()  # "14 июля 2026"
                    day, month_name, year = parts
                    month = MONTHS[month_name.lower()]
                    date_str = f"{year}-{month:02d}-{int(day):02d}"
                    news_date = datetime.strptime(date_str, '%Y-%m-%d')
                    if news_date < cutoff:
                        continue
                except:
                    pass

            seen.add(t)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': article_url,
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
