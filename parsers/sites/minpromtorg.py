import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from utils.filters import is_junk
from datetime import datetime, timedelta
import re

urllib3.disable_warnings()
HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse():
    news, seen_urls = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minpromtorg.gov.ru/press-centre/news/?PAGEN_1={p + 1}" if p else "https://minpromtorg.gov.ru/press-centre/news/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for a in s.find_all('a'):
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
                    'source': 'Минпромторг',
                    'title': t,
                    'url': full_url,
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news