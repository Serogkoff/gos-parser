import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.filters import is_junk
from datetime import datetime, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"http://government.ru/rugovclassifier/726/events/?page={p + 1}" if p else "http://government.ru/rugovclassifier/726/events/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30)
            s = BeautifulSoup(r.text, 'html.parser')

            for a in s.find_all('a'):
                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t):
                    continue

                date_str = ""
                parent = a.find_parent('div') or a.find_parent('li')
                if parent:
                    time_tag = parent.find('time')
                    if time_tag and time_tag.get('datetime'):
                        date_str = time_tag['datetime'][:10]
                        try:
                            news_date = datetime.strptime(date_str, '%Y-%m-%d')
                            if news_date < cutoff:
                                continue
                        except:
                            pass

                seen.add(t)
                news.append({
                    'source': 'Развитие Курил',
                    'title': t,
                    'url': urljoin(u, a.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news