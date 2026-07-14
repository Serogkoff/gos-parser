import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from utils.filters import is_junk
from datetime import datetime, timedelta

urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0"}

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://mintrans.gov.ru/press-center/news?page={p + 1}" if p else "https://mintrans.gov.ru/press-center/news"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for item in s.select('.news-inf'):
                title_tag = item.select_one('.news-text')
                date_tag = item.select_one('.date-span')

                if not title_tag:
                    continue

                t = title_tag.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t):
                    continue

                date_str = ""
                if date_tag:
                    try:
                        parts = date_tag.get_text(strip()).lower().split()  # "14 июля 2026"
                        day, month_name, year = parts
                        month = MONTHS[month_name]
                        date_str = f"{year}-{month:02d}-{int(day):02d}"
                        news_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if news_date < cutoff:
                            continue
                    except:
                        pass

                seen.add(t)
                news.append({
                    'source': 'Минтранс',
                    'title': t,
                    'url': urljoin(u, title_tag.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news