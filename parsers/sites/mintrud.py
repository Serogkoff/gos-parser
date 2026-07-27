import re
from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минтруд"

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen_urls = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://mintrud.gov.ru/news/news/list?PAGEN_1={p + 1}" if p else "https://mintrud.gov.ru/news/news/list"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.find_all('a'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = urljoin(u, href)

            if full_url in seen_urls:
                continue

            # Ищем дату в начале или в конце
            date_str = ""
            match = re.search(
                r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
                t.lower())
            if match:
                try:
                    day, month_name, year = int(match.group(1)), match.group(2), int(match.group(3))
                    month = MONTHS[month_name]
                    news_date = datetime(year, month, day)
                    if news_date < cutoff:
                        continue
                    date_str = news_date.strftime("%Y-%m-%d")
                    # Убираем дату из любого места заголовка
                    t = re.sub(
                        r'\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}',
                        '', t, flags=re.IGNORECASE).strip()
                except:
                    pass

            if not date_str or len(t) < 20 or is_junk(t):
                continue

            seen_urls.add(full_url)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
