from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Трутнев"


def parse():
    news, seen_urls = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"http://government.ru/gov/persons/21/events/?page={p + 1}" if p else "http://government.ru/gov/persons/21/events/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.find_all('a'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = urljoin(u, href)

            if '/news/' not in href:
                continue
            if len(t) < 20 or is_junk(t) or full_url in seen_urls:
                continue

            date_str = ""
            parent = a.find_parent('div') or a.find_parent('li')
            if parent:
                time_tag = parent.find('time')
                if time_tag and time_tag.get('datetime'):
                    date_str = time_tag['datetime'][:10]
                    try:
                        news_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if news_date < cutoff:
                            continue
                    except:
                        pass

            seen_urls.add(full_url)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
