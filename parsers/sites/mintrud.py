import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from utils.filters import is_junk
from datetime import datetime, timedelta
import re

urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0"}

MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://mintrud.gov.ru/news/news/list?PAGEN_1={p + 1}" if p else "https://mintrud.gov.ru/news/news/list"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for a in s.find_all('a'):
                t = a.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t):
                    continue

                # Парсим дату из начала текста: "13 июля 2026Заголовок..."
                date_str = ""
                match = re.match(
                    r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
                    t)
                if match:
                    day, month_name, year = match.groups()
                    month = MONTHS[month_name]
                    date_str = f"{year}-{month:02d}-{int(day):02d}"
                    try:
                        news_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if news_date < cutoff:
                            continue
                    except:
                        pass
                    # Убираем дату из заголовка
                    t = re.sub(
                        r'^\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}',
                        '', t).strip()

                seen.add(t)
                news.append({
                    'source': 'Минтруд',
                    'title': t,
                    'url': urljoin(u, a.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news