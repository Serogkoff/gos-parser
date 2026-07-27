from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минюст"

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minjust.gov.ru/ru/events/list/?PAGEN_1={p + 1}" if p else "https://minjust.gov.ru/ru/events/list/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for block in soup.select('.news-day-block'):
            date_tag = block.select_one('.news-day-block-date .day')
            year_tag = block.select_one('.news-day-block-date .year')

            for li in block.select('.news-day-block-events li'):
                a = li.find('a')
                if not a:
                    continue

                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t):
                    continue

                date_str = ""
                if date_tag and year_tag:
                    try:
                        day, month_name = date_tag.get_text(strip=True).split()
                        year = year_tag.get_text(strip=True).split()[0]
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
                    'url': urljoin(u, a.get('href', '')),
                    'date': date_str
                })

    print(f"  ✅ {len(news)}")
    return news
