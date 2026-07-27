import re
from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "Минпромторг"


def parse():
    news, seen_urls = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minpromtorg.gov.ru/press-centre/news/?PAGEN_1={p + 1}" if p else "https://minpromtorg.gov.ru/press-centre/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.find_all('a'):
            t = a.get_text(strip=True)
            href = a.get('href', '')

            # Только ссылки на новости
            if '/press-centre/news/' not in href:
                continue
            if len(t) < 30 or is_junk(t):
                continue

            # Парсим дату из начала текста
            match = re.match(r'(\d{2}\.\d{2}\.\d{4})', t)
            if not match:
                continue  # Без даты — пропускаем

            date_str = ""
            try:
                date_str = datetime.strptime(match.group(1), '%d.%m.%Y').strftime('%Y-%m-%d')
                if datetime.strptime(date_str, '%Y-%m-%d') < cutoff:
                    continue
            except:
                pass

            # Убираем дату из заголовка
            t = re.sub(r'^\d{2}\.\d{2}\.\d{4}', '', t).strip()

            full_url = urljoin(u, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
