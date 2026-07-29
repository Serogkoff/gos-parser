import re
from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.dates import (
    date_from_document,
    date_from_news_card,
    validate_publication_date,
)
from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js

SOURCE_NAME = "Минцифры"

def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for pg in range(2):
        u = f"https://digital.gov.ru/news-feed?page={pg + 1}" if pg else "https://digital.gov.ru/news-feed"

        soup = fetch_soup_js(
            u,
            SOURCE_NAME,
            wait_ms=4000,
            timeout_ms=60000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )
        if soup is None:
            soup = fetch_soup(
                u,
                SOURCE_NAME,
                timeout=30,
            )
        if soup is None:
            continue

        for item in soup.select('.main__container a'):
            raw_text = item.get_text(" ", strip=True)
            t = raw_text
            t = re.sub(r'\d+$', '', t).strip()
            t = re.sub(
                r'^\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s*\d{0,4}',
                '', t).strip()
            t = re.sub(r'^(Новость Минцифры|Медиаконтент)\s*', '', t).strip()

            if len(t) < 20 or t in seen or is_junk(t):
                continue

            full_url = urljoin(u, item.get('href', ''))
            # На карточках Минцифры дата ("24 июля") часто находится
            # внутри самой ссылки перед заголовком. Поэтому сначала читаем
            # текст конкретной карточки, не поднимаясь к общей ленте.
            date_str = validate_publication_date(raw_text)
            if not date_str:
                date_str = date_from_news_card(
                    item,
                    r"/news(?:-projects)?/",
                )

            if not date_str:
                detail = fetch_soup(
                    full_url,
                    SOURCE_NAME,
                    timeout=15,
                )
                date_str = date_from_document(
                    detail,
                    prefer_visible=True,
                )
            if not date_str:
                continue
            if datetime.strptime(date_str, "%Y-%m-%d") < cutoff:
                continue

            seen.add(t)
            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str
            })

    print(f"  ✅ {len(news)}")
    return news
