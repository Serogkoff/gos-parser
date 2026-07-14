from utils.filters import is_junk
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

def parse():
    news, seen = [], set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for pg in range(3):
                u = f"https://digital.gov.ru/news-feed?page={pg + 1}" if pg else "https://digital.gov.ru/news-feed"
                try:
                    page.goto(u, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    s = BeautifulSoup(page.content(), 'html.parser')
                    for a in s.find_all('a'):
                        t = a.get_text(strip=True)
                        # Убираем цифры в конце
                        t = re.sub(r'\d+$', '', t).strip()
                        # Убираем даты в начале: "20 июня", "12 апреля", "18 декабря 2025"
                        t = re.sub(r'^\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s*\d{0,4}', '', t).strip()
                        # Убираем "Новость Минцифры", "Медиаконтент"
                        t = re.sub(r'^(Новость Минцифры|Медиаконтент)\s*', '', t).strip()
                        if len(t) < 20 or t in seen or is_junk(t):
                            continue
                        seen.add(t)
                        news.append({'source': 'Минцифры', 'title': t, 'url': urljoin(u, a.get('href', ''))})
                except:
                    pass
            browser.close()
    except:
        pass
    print(f"  ✅ {len(news)}")
    return news