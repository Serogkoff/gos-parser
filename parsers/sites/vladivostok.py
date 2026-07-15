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

    for p in range(3):
        u = f"https://www.vlc.ru/event/news/?PAGEN_1={p + 1}" if p else "https://www.vlc.ru/event/news/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')
            for card in s.select('.card-body'):
                a = card.select_one('a[href]')
                date_tag = card.select_one('.card-date')
                if not a: continue
                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t): continue

                date_str = ""
                if date_tag:
                    try:
                        parts = date_tag.get_text(strip=True).split()
                        d, m, y = int(parts[0]), MONTHS[parts[1].lower()], int(parts[2])
                        news_date = datetime(y, m, d)
                        if news_date < cutoff: continue
                        date_str = news_date.strftime("%Y-%m-%d")
                    except:
                        pass

                seen.add(t)
                news.append(
                    {'source': 'Владивосток', 'title': t, 'url': urljoin(u, a.get('href', '')), 'date': date_str})
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news