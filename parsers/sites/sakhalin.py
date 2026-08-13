import re
from urllib.parse import urljoin, urlsplit
from datetime import datetime, timedelta

from utils.dates import date_from_document, date_from_news_card
from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js

SOURCE_NAME = "Сахалинская обл."

def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)
    detail_checks = 0

    for pg in range(2):
        u = f"https://sakhalin.gov.ru/news?page={pg + 1}" if pg else "https://sakhalin.gov.ru/news"

        soup = fetch_soup_js(
            u,
            SOURCE_NAME,
            wait_ms=1200,
            timeout_ms=25000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )
        if soup is None:
            continue

        for a in soup.find_all('a'):
            t = a.get_text(strip=True)
            full_url = urljoin(u, a.get('href', ''))
            path = urlsplit(full_url).path.rstrip("/")
            if not path.startswith("/news/"):
                continue
            if len(t) < 20 or t in seen or is_junk(t):
                continue

            date_str = date_from_news_card(
                a,
                r"/news/",
            )
            if not date_str and detail_checks < 8:
                detail_checks += 1
                detail = fetch_soup(
                    full_url,
                    SOURCE_NAME,
                    timeout=8,
                    attempts=1,
                )
                date_str = date_from_document(detail)

            if date_str:
                news_date = datetime.strptime(date_str, "%Y-%m-%d")
                if news_date < cutoff:
                    continue

            # Убираем только служебную дату в начале карточки. Даты внутри
            # заголовка ("завершить к 1 сентября") должны сохраниться.
            t = re.sub(
                r'^\s*\d{1,2}\s+'
                r'(января|февраля|марта|апреля|мая|июня|июля|августа|'
                r'сентября|октября|ноября|декабря)\s*\d{0,4}\s*',
                '',
                t,
                flags=re.IGNORECASE,
            ).strip()

            seen.add(t)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
