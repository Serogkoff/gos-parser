from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.js_client import fetch_soup_js

SOURCE_NAME = "Минэнерго"


def parse():
    news, seen_titles = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for pg in range(3):
        url = (
            f"https://minenergo.gov.ru/press-center/news-and-events?page={pg + 1}"
            if pg
            else "https://minenergo.gov.ru/press-center/news-and-events"
        )

        soup = fetch_soup_js(url, SOURCE_NAME)
        if soup is None:
            continue

        for time_tag in soup.find_all('time', attrs={'datetime': True}):
            date_str = time_tag['datetime'][:10]
            try:
                news_date = datetime.strptime(date_str, '%Y-%m-%d')
                if news_date < cutoff:
                    continue
            except ValueError:
                continue

            container = time_tag.find_parent('div')
            if not container:
                continue
            a = container.find('a', href=True)
            if not a:
                continue

            t = a.get_text(strip=True)
            if len(t) < 20 or is_junk(t) or t in seen_titles:
                continue

            seen_titles.add(t)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': urljoin(url, a['href']),
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
