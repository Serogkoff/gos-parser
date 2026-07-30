"""Парсер открытых официальных RSS-лент Интерфакса."""

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Интерфакс"
FEED_URLS = (
    ("Последние новости", "https://www.interfax.ru/rss.asp"),
    ("Спорт", "https://www.sport-interfax.ru/rss.asp"),
)
MAX_ITEMS_PER_FEED = 50
MAX_AGE_DAYS = 30


def parse():
    news = []

    for default_section, url in FEED_URLS:
        soup = fetch_soup(
            url,
            f"{SOURCE_NAME} · {default_section}",
            timeout=30,
            verify=True,
            parser="xml",
        )
        if soup is not None:
            news.extend(
                _parse_interfax_feed(
                    soup,
                    default_section=default_section,
                )
            )

    news = deduplicate_news(news)
    print(f"  ✅ {len(news)}")
    return news


def _parse_interfax_feed(soup, default_section="", now=None):
    """Преобразует RSS Интерфакса в общий формат проекта."""
    now = now or datetime.now().astimezone()
    cutoff = now.date() - timedelta(days=MAX_AGE_DAYS)
    news = []

    for entry in soup.find_all("item")[:MAX_ITEMS_PER_FEED]:
        title = _tag_text(entry, "title")
        url = _tag_text(entry, "link") or _tag_text(entry, "guid")
        publication_date = _parse_interfax_date(
            _tag_text(entry, "pubDate"),
        )

        if (
            len(title) < 10
            or not _is_interfax_article_url(url)
            or _is_junk_interfax_title(title)
        ):
            continue

        if publication_date:
            parsed_date = datetime.strptime(
                publication_date,
                "%Y-%m-%d",
            ).date()
            if parsed_date < cutoff:
                continue

        categories = [
            " ".join(category.get_text(" ", strip=True).split())
            for category in entry.find_all("category")
            if category.get_text(" ", strip=True)
        ]
        summary = _clean_summary(_tag_text(entry, "description"))

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
            "section": (
                categories[0]
                if categories
                else default_section or "Последние новости"
            ),
        }
        if summary:
            item["summary"] = summary
        news.append(item)

    return deduplicate_news(news)


def _parse_interfax_date(raw_date):
    """Читает стандартную дату RSS вместе с часовым поясом."""
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed.date().isoformat() if parsed else ""


def _is_interfax_article_url(url):
    parts = urlsplit(str(url))
    hostname = (parts.hostname or "").casefold()
    path_parts = [part for part in parts.path.split("/") if part]

    if hostname in {"interfax.ru", "www.interfax.ru"}:
        return (
            len(path_parts) == 2
            and path_parts[0] in {
                "russia",
                "world",
                "business",
                "moscow",
                "culture",
                "digital",
            }
            and path_parts[1].isdigit()
        )

    if hostname in {"sport-interfax.ru", "www.sport-interfax.ru"}:
        return len(path_parts) == 1 and path_parts[0].isdigit()

    return False


def _is_junk_interfax_title(title):
    # Общее правило считает подстроку «факс» служебным контактом.
    # В названии самого агентства это, разумеется, не мусор.
    cleaned = str(title).casefold().replace("интерфакс", "")
    return is_junk(cleaned)


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_summary(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())
