from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def parse():
    news, seen = [], set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for pg in range(3):
                u = f"https://sakhalin.gov.ru/news?page={pg+1}" if pg else "https://sakhalin.gov.ru/news"
                try:
                    page.goto(u, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    s = BeautifulSoup(page.content(), 'html.parser')
                    for a in s.find_all('a'):
                        t = a.get_text(strip=True)
                        if len(t) < 20 or t in seen: continue
                        seen.add(t)
                        news.append({'source': 'Сахалинская обл.', 'title': t, 'url': urljoin(u, a.get('href',''))})
                except: pass
            browser.close()
    except: pass
    print(f"  ✅ {len(news)}")
    return news