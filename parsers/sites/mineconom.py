from urllib.parse import urljoin

from utils.dates import date_from_element
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минэкономразвития"


def parse():
    news, seen = [], set()
    for p in range(3):
        u = f"https://www.economy.gov.ru/material/news/?PAGEN_1={p + 1}" if p else "https://www.economy.gov.ru/material/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.select('a[href*="/material/news/"][href$=".html"]'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = urljoin(u, href)
            if full_url.rstrip('/') == u.rstrip('/'):
                continue
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue
            seen.add(full_url)
            card = a.find_parent(['article', 'li']) or a.find_parent(
                'div', class_=lambda value: value and 'news' in str(value).lower()
            )
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_from_element(card),
            })

    print(f"  ✅ {len(news)}")
    return news
