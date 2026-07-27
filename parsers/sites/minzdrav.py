from urllib.parse import urljoin
import re
from datetime import datetime, timedelta

from utils.dates import parse_date
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минздрав"


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minzdrav.gov.ru/news?page={p + 1}" if p else "https://minzdrav.gov.ru/news"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for title_tag in soup.select('a[href*="/news/"]'):
            href = title_tag.get('href', '')
            match = re.search(r"/news/(20\d{2})/(\d{1,2})/(\d{1,2})/", href)
            if not match:
                continue
            t = title_tag.get_text(" ", strip=True)
            full_url = urljoin(u, href)
            date_str = parse_date("-".join(match.groups()))
            if not date_str or datetime.strptime(date_str, "%Y-%m-%d") < cutoff:
                continue
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue
            seen.add(full_url)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
