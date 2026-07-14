import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from utils.filters import is_junk
from datetime import datetime, timedelta

urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minzdrav.gov.ru/news?page={p + 1}" if p else "https://minzdrav.gov.ru/news"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for item in s.select('.media-news-item'):
                title_tag = item.select_one('.media-body a')
                time_tag = item.select_one('time')

                if not title_tag:
                    continue

                t = title_tag.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t):
                    continue

                date_str = ""
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
                    'source': 'Минздрав',
                    'title': t,
                    'url': urljoin(u, title_tag.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news