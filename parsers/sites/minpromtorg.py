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
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minpromtorg.gov.ru/press-centre/news/?PAGEN_1={p + 1}" if p else "https://minpromtorg.gov.ru/press-centre/news/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for a in s.find_all('a'):
                t = a.get_text(strip=True)
                if len(t) < 30 or t in seen or is_junk(t):
                    continue

                # Парсим дату из начала: "14.07.2026Название..."
                date_str = ""
                match = re.match(r'(\d{2}\.\d{2}\.\d{4})', t)
                if match:
                    try:
                        date_str = datetime.strptime(match.group(1), '%d.%m.%Y').strftime('%Y-%m-%d')
                        news_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if news_date < cutoff:
                            continue
                    except:
                        pass
                    # Убираем дату из заголовка
                    t = re.sub(r'^\d{2}\.\d{2}\.\d{4}', '', t).strip()

                seen.add(t)
                news.append({
                    'source': 'Минпромторг',
                    'title': t,
                    'url': urljoin(u, a.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news