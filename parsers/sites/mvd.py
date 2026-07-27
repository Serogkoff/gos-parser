from urllib.parse import urljoin

from utils.dates import date_from_element
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "МВД РФ"


def parse():
    news, seen = [], set()

    for p in range(3):
        u = f"https://мвд.рф/news/{p + 1}/" if p else "https://мвд.рф/news"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for item in soup.select('.news-inner__item'):
            a = item.select_one('a.news-inner__link')
            date_div = item.select_one('.news-inner__data-time')

            if not a or not date_div:
                continue
            t = a.get_text(strip=True)
            full_url = urljoin(u, a.get('href', ''))
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue

            seen.add(full_url)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_from_element(date_div),
            })

    print(f"  ✅ {len(news)}")
    return news
