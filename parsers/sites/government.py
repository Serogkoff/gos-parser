import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def parse():
    news = []
    seen = set()
    for page in range(3):
        url = "http://government.ru/news/" if page == 0 else f"http://government.ru/news/?page={page+1}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            soup = BeautifulSoup(resp.text, 'html.parser')
            for a in soup.find_all('a'):
                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen: continue
                seen.add(t)
                news.append({'source': 'Правительство РФ', 'title': t, 'url': urljoin(url, a.get('href',''))})
        except: pass
    print(f"  ✅ {len(news)}")
    return news