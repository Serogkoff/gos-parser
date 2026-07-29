from urllib.parse import urljoin, urlsplit
import re

from utils.dates import date_from_document, date_from_news_card
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минпросвещения"


def parse():
    news, seen = [], set()

    for pg in range(3):
        u = f"https://edu.gov.ru/press/news/?page={pg + 1}" if pg else "https://edu.gov.ru/press/news/"

        soup = fetch_soup(u, SOURCE_NAME, timeout=30)
        if soup is None:
            continue

        # Страница списка находится в /press/news/, а сами материалы имеют
        # адреса вида /press/12345/....
        for a in soup.select('a[href]'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            path = urlsplit(urljoin(u, href)).path.rstrip('/')
            if not re.match(r"^/press/\d+", path):
                continue
            full_url = urljoin(u, href)
            if len(t) < 30 or full_url in seen or is_junk(t):
                continue

            date_str = date_from_news_card(
                a,
                r"/press/\d+",
            )
            if not date_str:
                detail = fetch_soup(full_url, SOURCE_NAME, timeout=15)
                date_str = date_from_document(detail)

            seen.add(full_url)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str,
            })

    with_date = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {with_date})")
    return news
