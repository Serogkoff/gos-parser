from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.filters import is_junk
from datetime import datetime, timedelta
import re

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen_urls = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for pg in range(3):
                u = f"https://minsport.gov.ru/press-center/?page={pg + 1}" if pg else "https://minsport.gov.ru/press-center/"
                try:
                    page.goto(u, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    s = BeautifulSoup(page.content(), 'html.parser')

                    for a in s.find_all('a'):
                        t = a.get_text(strip=True)
                        href = a.get('href', '')
                        full_url = urljoin(u, href)

                        if len(t) < 30 or is_junk(t) or full_url in seen_urls:
                            continue

                        date_str = ""
                        match = re.match(
                            r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
                            t.lower())
                        if match:
                            try:
                                day, month_name, year = int(match.group(1)), match.group(2), int(match.group(3))
                                month = MONTHS[month_name]
                                news_date = datetime(year, month, day)
                                if news_date < cutoff:
                                    continue
                                date_str = news_date.strftime("%Y-%m-%d")
                                t = re.sub(
                                    r'^\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}',
                                    '', t, flags=re.IGNORECASE).strip()
                            except:
                                pass

                        if not date_str:
                            continue

                        seen_urls.add(full_url)
                        news.append({
                            'source': 'Минспорт',
                            'title': t,
                            'url': full_url,
                            'date': date_str
                        })
                except:
                    pass
            browser.close()
    except:
        pass

    print(f"  ✅ {len(news)}")
    return news