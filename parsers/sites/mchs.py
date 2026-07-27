from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "МЧС"

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://mchs.gov.ru/deyatelnost/press-centr/novosti?page={p + 1}" if p else "https://mchs.gov.ru/deyatelnost/press-centr/novosti"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for item in soup.select('.articles-item'):
            title_tag = item.select_one('.articles-item__title')
            link_tag = item.select_one('a.articles-item__image-wrapper')
            date_tag = item.select_one('.articles-item__date')

            if not title_tag or not link_tag:
                continue

            t = title_tag.get_text(strip=True)
            if len(t) < 20 or t in seen or is_junk(t):
                continue

            # Парсим дату "14 июля 2026, 11:00"
            date_str = ""
            if date_tag:
                try:
                    parts = date_tag.get_text(strip=True).split(',')[0]  # "14 июля 2026"
                    day, month_name, year = parts.split()
                    month = MONTHS[month_name]
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
                'url': urljoin(u, link_tag.get('href', '')),
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
