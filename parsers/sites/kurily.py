from urllib.parse import urljoin

from utils.dates import date_from_ancestors
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Развитие Курил"


def parse():
    news, seen_urls = [], set()

    for p in range(2):
        u = f"http://government.ru/rugovclassifier/726/events/?page={p + 1}" if p else "http://government.ru/rugovclassifier/726/events/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.find_all('a'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = urljoin(u, href)

            if '/rugovclassifier/726' in href and '/news/' not in href:
                continue
            if '/news/' not in href:
                continue
            if len(t) < 20 or is_junk(t) or full_url in seen_urls:
                continue

            date_str = date_from_ancestors(a)

            seen_urls.add(full_url)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str,
            })

    with_date = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {with_date})")
    return news
