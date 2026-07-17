import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from utils.filters import is_junk
from datetime import datetime, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for page in range(2):
        url = "http://government.ru/news/" if page == 0 else f"http://government.ru/news/?page={page + 1}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            soup = BeautifulSoup(resp.text, 'html.parser')

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
                        except:
                            pass

                seen.add(t)
                news.append({
                    'source': 'Правительство РФ',
                    'title': t,
                    'url': urljoin(url, href),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news