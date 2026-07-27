from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минобрнауки"

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://www.minobrnauki.gov.ru/press-center/news/novosti-ministerstva/?PAGEN_1={p + 1}" if p else "https://www.minobrnauki.gov.ru/press-center/news/novosti-ministerstva/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for item in soup.select('.news-item'):
            title_tag = item.select_one('.news-item-title a')
            date_day = item.select_one('.date-day')
            date_month = item.select_one('.day-month')

            if not title_tag:
                continue

            t = title_tag.get_text(strip=True)
            if len(t) < 20 or t in seen or is_junk(t):
                continue

            date_str = ""
            if date_day and date_month:
                try:
                    day = date_day.get_text(strip=True)
                    month_name = date_month.get_text(strip=True).lower()
                    month = MONTHS.get(month_name, 1)
                    year = str(datetime.now().year)
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
                'url': urljoin(u, title_tag.get('href', '')),
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
