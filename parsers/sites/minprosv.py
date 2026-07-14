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
                        if len(t) < 30 or t in seen or is_junk(t):
                            continue

                        # Ищем дату — проверяем начало текста на "DD месяц YYYY"
                        date_str = ""
                        match = re.match(
                            r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
                            t)
                        if match:
                            day, month_name, year = match.groups()
                            month = MONTHS.get(month_name, 1)
                            date_str = f"{year}-{month:02d}-{int(day):02d}"
                            try:
                                news_date = datetime.strptime(date_str, '%Y-%m-%d')
                                if news_date < cutoff:
                                    continue
                            except:
                                pass
                            # Убираем дату из заголовка
                            t = re.sub(
                                r'^\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}\s*',
                                '', t).strip()

                        seen.add(t)
                        news.append({
                            'source': 'Минпросвещения',
                            'title': t,
                            'url': urljoin(u, a.get('href', '')),
                            'date': date_str
                        })
                except:
                    pass
            browser.close()
    except:
        pass

    print(f"  ✅ {len(news)}")
    return news