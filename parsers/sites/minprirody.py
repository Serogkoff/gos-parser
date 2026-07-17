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
        u = f"https://www.mnr.gov.ru/press/news/?PAGEN_1={p + 1}" if p else "https://www.mnr.gov.ru/press/news/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for item in s.select('.news-item'):
                title_tag = item.select_one('.news-item__title a')
                date_tag = item.select_one('.news-item__date')

                if not title_tag or not date_tag:
                    continue

                t = title_tag.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t):
                    continue

                raw = date_tag.get_text(strip=True)
                date_str = ""
                try:
                    parts = raw.split()
                    day, month_name = int(parts[0]), parts[1].lower()
                    year = int(parts[2][:4])
                    month = MONTHS[month_name]
                    news_date = datetime(year, month, day)
                    if news_date < cutoff:
                        continue
                    date_str = news_date.strftime("%Y-%m-%d")
                except:
                    pass

                seen.add(t)
                news.append({
                    'source': 'Минприроды',
                    'title': t,
                    'url': urljoin(u, title_tag.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news