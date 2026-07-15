import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from utils.filters import is_junk

urllib3.disable_warnings()
HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse():
    news, seen = [], set()

    for p in range(3):
        u = f"https://мвд.рф/news/{p + 1}/" if p else "https://мвд.рф/news"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for item in s.select('.news-inner__item'):
                a = item.select_one('a.news-inner__link')
                date_div = item.select_one('.news-inner__data-time')

                if not a or not date_div: continue
                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t): continue

                seen.add(t)
                news.append({
                    'source': 'МВД РФ',
                    'title': t,
                    'url': urljoin(u, a.get('href', '')),
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news