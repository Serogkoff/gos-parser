from utils.filters import is_junk
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timedelta


def parse():
    news, seen_urls = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for pg in range(3):
                u = f"https://minenergo.gov.ru/press-center/news-and-events?page={pg + 1}" if pg else "https://minenergo.gov.ru/press-center/news-and-events"
                try:
                    page.goto(u, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    s = BeautifulSoup(page.content(), 'html.parser')

                    # Ищем все time с datetime
                    for time_tag in s.find_all('time', attrs={'datetime': True}):
                        date_str = time_tag['datetime'][:10]
                        try:
                            news_date = datetime.strptime(date_str, '%Y-%m-%d')
                            if news_date < cutoff:
                                continue
                        except:
                            continue

                        # Ищем ближайшую ссылку
                        container = time_tag.find_parent('div')
                        if not container:
                            continue
                        a = container.find('a', href=True)
                        if not a:
                            continue

                        t = a.get_text(strip=True)
                        full_url = urljoin(u, a['href'])

                        if len(t) < 20 or is_junk(t) or full_url in seen_urls:
                            continue

                        seen_urls.add(full_url)
                        news.append({
                            'source': 'Минэнерго',
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