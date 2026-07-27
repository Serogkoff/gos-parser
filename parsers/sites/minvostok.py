from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минвостокразвития"


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minvr.gov.ru/press-center/news/?PAGEN_1={p + 1}" if p else "https://minvr.gov.ru/press-center/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for item in soup.select('.article__header'):
            title_tag = item.find_next('a', class_='article__link')
            if not title_tag:
                title_tag = item.find_next('a')
            date_tag = item.select_one('.article__time')

            if not title_tag:
                continue

            t = title_tag.get_text(strip=True)
            if len(t) < 20 or t in seen or is_junk(t):
                continue

            date_str = ""
            if date_tag:
                try:
                    parts = date_tag.get_text(strip=True).split()[0].split('.')  # "14.07.2026"
                    day, month, year = parts
                    date_str = f"{year}-{month}-{day}"
                    news_date = datetime.strptime(date_str, '%Y-%m-%d')
                    if news_date < cutoff:
                        continue
                except:
                    pass

            seen.add(t)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': urljoin(u, title_tag.get('href', '')),
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
