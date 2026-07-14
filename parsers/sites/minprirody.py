import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0"}

def parse():
    news, seen = [], set()
    for p in range(3):
        u = f"https://www.mnr.gov.ru/press/news/?PAGEN_1={p+1}" if p else "https://www.mnr.gov.ru/press/news/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')
            for a in s.find_all('a'):
                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen: continue
                seen.add(t)
                news.append({'source': 'Минприроды', 'title': t, 'url': urljoin(u, a.get('href',''))})
        except: pass
    print(f"  ✅ {len(news)}")
    return news