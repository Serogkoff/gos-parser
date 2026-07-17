from utils.filters import is_junk
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
from datetime import datetime, timedelta

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for pg in range(2):
                u = f"https://digital.gov.ru/news-feed?page={pg + 1}" if pg else "https://digital.gov.ru/news-feed"
                try:
                    page.goto(u, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    s = BeautifulSoup(page.content(), 'html.parser')

                    for item in s.select('.main__container a'):
                        t = item.get_text(strip=True)
                        t = re.sub(r'\d+$', '', t).strip()
                        t = re.sub(
                            r'^\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s*\d{0,4}',
                            '', t).strip()
                        t = re.sub(r'^(Новость Минцифры|Медиаконтент)\s*', '', t).strip()

                        if len(t) < 20 or t in seen or is_junk(t):
                            continue

                        date_str = ""
                        parent = item.find_parent('div')
                        if parent:
                            date_el = parent.select_one('.date, [class*=date]')
                            if date_el:
                                try:
                                    text = date_el.get_text(strip=True).lower()
                                    parts = text.split()
                                    if len(parts) >= 2:
                                        day = int(parts[0])
                                        month_name = parts[1]
                                        month = MONTHS.get(month_name, 1)
                                        year = datetime.now().year
                                        news_date = datetime(year, month, day)
                                        if news_date > datetime.now():
                                            year -= 1
                                            news_date = datetime(year, month, day)
                                        if news_date < cutoff:
                                            continue
                                        date_str = news_date.strftime("%Y-%m-%d")
                                except:
                                    pass

                        if not date_str:
                            continue

                        seen.add(t)
                        news.append({
                            'source': 'Минцифры',
                            'title': t,
                            'url': urljoin(u, item.get('href', '')),
                            'date': date_str
                        })
                except:
                    pass
            browser.close()
    except:
        pass
    print(f"  ✅ {len(news)}")
    return news