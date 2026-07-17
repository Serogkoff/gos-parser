import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.filters import is_junk

HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse():
    news, seen_urls = [], set()

    for p in range(2):
        u = f"http://government.ru/rugovclassifier/726/events/?page={p + 1}" if p else "http://government.ru/rugovclassifier/726/events/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30)
            s = BeautifulSoup(r.text, 'html.parser')

            for a in s.find_all('a'):
                t = a.get_text(strip=True)
                href = a.get('href', '')
                full_url = urljoin(u, href)

                if '/rugovclassifier/726' in href and '/news/' not in href:
                    continue
                if '/news/' not in href:
                    continue
                if len(t) < 20 or is_junk(t) or full_url in seen_urls:
                    continue

                seen_urls.add(full_url)
                news.append({
                    'source': 'Развитие Курил',
                    'title': t,
                    'url': full_url,
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news