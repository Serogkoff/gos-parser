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
        u = f"https://minfin.gov.ru/ru/press-center/?PAGEN_1={p + 1}" if p else "https://minfin.gov.ru/ru/press-center/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for card in s.select('.news_card_min'):
                title_tag = card.select_one('a[title]')
                date_tag = card.select_one('span')

                if not title_tag:
                    continue

                t = title_tag.get('title', '').strip()
                if not t or len(t) < 20 or t in seen or is_junk(t):
                    continue

                date_str = ""
                if date_tag:
                    try:
                        parts = date_tag.get_text(strip=True).split('.')  # "14.07.26"
                        day, month, year = parts
                        year = '20' + year
                        date_str = f"{year}-{month}-{day}"
                        news_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if news_date < cutoff:
                            continue
                    except:
                        pass

                seen.add(t)
                news.append({
                    'source': 'Минфин',
                    'title': t,
                    'url': urljoin(u, title_tag.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news