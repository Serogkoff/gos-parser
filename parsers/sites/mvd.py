import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from utils.dates import date_from_element, date_from_news_card
from utils.filters import is_junk
from utils.http_client import fetch_soup

SOURCE_NAME = "МВД РФ"
NEWS_URL = "https://мвд.рф/news"
ARTICLE_PATH = re.compile(r"^/news/item/\d+/?$", re.IGNORECASE)


def parse(now=None):
    now = now or datetime.now()
    news, seen = [], set()

    for p in range(3):
        u = f"{NEWS_URL}/{p + 1}/" if p else NEWS_URL

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        # Старый сайт использовал news-inner__item, а обновлённая версия
        # меняет имена классов. Адрес публикации /news/item/<id> остаётся
        # стабильным, поэтому опираемся на него и читаем данные из карточки.
        for a in soup.select('a[href*="/news/item/"]'):
            full_url = urljoin(u, a.get("href", ""))
            if not _is_article_url(full_url) or full_url in seen:
                continue
            t = _title_from_link(a)
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue

            publication_date = _date_from_mvd_card(a, now=now)

            seen.add(full_url)
            news.append({
                "source": SOURCE_NAME,
                "title": t,
                "url": full_url,
                "date": publication_date,
            })

    print(f"  ✅ {len(news)}")
    return news


def _is_article_url(value):
    parsed = urlsplit(str(value or ""))
    host = parsed.hostname.encode("idna").decode("ascii") if parsed.hostname else ""
    official_host = "xn--b1aew.xn--p1ai"
    return (
        (host == official_host or host.endswith(f".{official_host}"))
        and bool(ARTICLE_PATH.match(parsed.path))
    )


def _title_from_link(link):
    candidates = [
        link.get("title", ""),
        link.get("aria-label", ""),
        link.get_text(" ", strip=True),
    ]
    current = link
    for _ in range(5):
        current = getattr(current, "parent", None)
        if current is None:
            break
        heading = current.select_one(
            "h1, h2, h3, h4, [class*='title'], [class*='name']"
        )
        if heading is not None:
            candidates.append(heading.get_text(" ", strip=True))
    cleaned = [" ".join(str(value or "").split()) for value in candidates]
    cleaned = [value for value in cleaned if 20 <= len(value) <= 700]
    return max(cleaned, key=len, default="")


def _date_from_mvd_card(link, now=None):
    now = now or datetime.now()
    current = link
    for _ in range(7):
        current = getattr(current, "parent", None)
        if current is None:
            break
        article_urls = {
            urljoin(NEWS_URL, item.get("href", ""))
            for item in current.select('a[href*="/news/item/"]')
            if _is_article_url(urljoin(NEWS_URL, item.get("href", "")))
        }
        if len(article_urls) > 1:
            break
        text = " ".join(current.get_text(" ", strip=True).split())
        if re.search(r"\bсегодня\b", text, re.IGNORECASE):
            return now.strftime("%Y-%m-%d")
        date_node = current.select_one(
            "time, [datetime], .news-inner__data-time, "
            "[class*='date'], [class*='time'], [class*='data']"
        )
        parsed = date_from_element(date_node)
        if parsed:
            return parsed

    return date_from_news_card(
        link,
        r"/news/item/\d+/?",
        max_levels=7,
        now=now,
    )
