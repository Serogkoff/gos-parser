from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Правительство РФ"


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for page in range(2):
        url = "http://government.ru/news/" if page == 0 else f"http://government.ru/news/?page={page + 1}"

        soup = fetch_soup(url, SOURCE_NAME)
        if soup is None:
            # Ошибка уже записана в лог внутри fetch_soup - просто идём дальше
            continue

        for a in soup.find_all('a'):
            t = a.get_text(strip=True)
            href = a.get('href', '')

            # Только ссылки на новости
            if '/news/' not in href:
                continue
            if len(t) < 20 or t in seen or is_junk(t):
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
                    except ValueError:
                        pass

            seen.add(t)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': urljoin(url, href),
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
