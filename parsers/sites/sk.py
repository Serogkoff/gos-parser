from urllib.parse import urljoin

from utils.dates import date_from_ancestors, date_from_element, parse_date
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "СК РФ"


def parse():
    news, seen = [], set()
    for p in range(3):
        u = f"https://sledcom.ru/news/?PAGEN_1={p + 1}" if p else "https://sledcom.ru/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.select('a[href*="/news/item/"], a[href*="/news/detail/"]'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = urljoin(u, href).split('?', 1)[0]
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue
            seen.add(full_url)
            date_str = date_from_ancestors(a)
            if not date_str:
                detail = fetch_soup(full_url, SOURCE_NAME, timeout=15)
                if detail is not None:
                    meta = detail.select_one(
                        'meta[property="article:published_time"], '
                        'meta[name="date"], meta[itemprop="datePublished"]'
                    )
                    if meta:
                        date_str = parse_date(meta.get("content", ""))
                    if not date_str:
                        date_str = date_from_element(detail)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str,
            })

    with_date = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {with_date})")
    return news
