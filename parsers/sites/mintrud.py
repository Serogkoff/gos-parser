import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from utils.filters import is_junk

urllib3.disable_warnings()
HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse():
    news, seen_urls = [], set()

    for p in range(2):
        u = f"https://mintrud.gov.ru/news/news/list?PAGEN_1={p + 1}" if p else "https://mintrud.gov.ru/news/news/list"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for a in s.find_all('a'):
                t = a.get_text(strip=True)
                href = a.get('href', '')
                full_url = urljoin(u, href)

                if full_url in seen_urls:
                    continue
                if len(t) < 20 or is_junk(t):
                    continue

                seen_urls.add(full_url)
                news.append({
                    'source': 'Минтруд',
                    'title': t,
                    'url': full_url,
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news