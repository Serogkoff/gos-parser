from utils.filters import is_junk
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0"}

def parse():
    news, seen = [], set()
    for p in range(3):
        u = f"http://government.ru/rugovclassifier/726/events/?page={p+1}" if p else "http://government.ru/rugovclassifier/726/events/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30)
            s = BeautifulSoup(r.text, 'html.parser')
            for a in s.find_all('a'):
                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t): continue
                seen.add(t)
                news.append({'source': 'Развитие Курил', 'title': t, 'url': urljoin(u, a.get('href',''))})
        except: pass
    print(f"  ✅ {len(news)}")
    return news