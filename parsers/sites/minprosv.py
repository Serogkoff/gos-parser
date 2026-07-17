from utils.filters import is_junk
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timedelta
import re

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
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()

            for pg in range(5):
                u = f"https://edu.gov.ru/press/news/?page={pg + 1}" if pg else "https://edu.gov.ru/press/news/"
                try:
                    page.goto(u, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    s = BeautifulSoup(page.content(), 'html.parser')

                    for a in s.find_all('a'):
                        t = a.get_text(strip=True)
                        href = a.get('href', '')

                        if '/press/' not in href or len(t) < 30 or t in seen or is_junk(t):
                            continue

                        news_url = urljoin(u, href)
                        date_str = ""

                        # Заходим на страницу новости за датой
                        try:
                            page.goto(news_url, wait_until="networkidle", timeout=15000)
                            page.wait_for_timeout(1000)
                            s2 = BeautifulSoup(page.content(), 'html.parser')
                            date_el = s2.select_one('.date, [class*=date], time, .published')
                            if date_el:
                                raw = date_el.get_text(strip=True)
                                match = re.search(
                                    r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
                                    raw.lower())
                                if match:
                                    day, month_name, year = int(match.group(1)), match.group(2), int(match.group(3))
                                    month = MONTHS[month_name]
                                    news_date = datetime(year, month, day)
                                    if news_date < cutoff:
                                        continue
                                    date_str = news_date.strftime("%Y-%m-%d")
                        except:
                            pass

                        seen.add(t)
                        news.append({
                            'source': 'Минпросвещения',
                            'title': t,
                            'url': news_url,
                            'date': date_str
                        })
                except:
                    pass
            browser.close()
    except:
        pass

    print(f"  ✅ {len(news)}")
    return news