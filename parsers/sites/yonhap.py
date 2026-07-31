"""Парсер официальной RSS-ленты Yonhap о Северной Корее."""

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Yonhap"
FEED_URL = "https://www.yna.co.kr/rss/northkorea.xml"
MAX_ITEMS = 60
MAX_AGE_DAYS = 30


def parse():
    soup = fetch_soup(
        FEED_URL,
        SOURCE_NAME,
        timeout=30,
        verify=True,
        parser="xml",
    )
    if soup is None:
        print("  ✅ 0")
        return []

    news = _parse_yonhap_feed(soup)
    print(f"  ✅ {len(news)}")
    return news


def _parse_yonhap_feed(soup, now=None):
    """Преобразует корейский RSS Yonhap в общий формат проекта."""
    now = now or datetime.now().astimezone()
    cutoff = now.date() - timedelta(days=MAX_AGE_DAYS)
    news = []

    for entry in soup.find_all("item")[:MAX_ITEMS]:
        title = _tag_text(entry, "title")
        url = _tag_text(entry, "link") or _tag_text(entry, "guid")
        publication_date = _parse_yonhap_date(_tag_text(entry, "pubDate"))

        if (
            len(title) < 5
            or not _is_yonhap_article_url(url)
            or is_junk(title)
        ):
            continue

        if publication_date:
            parsed_date = datetime.strptime(
                publication_date,
                "%Y-%m-%d",
            ).date()
            if parsed_date < cutoff:
                continue

        summary = _clean_summary(_tag_text(entry, "description"))
        creator = _tag_text(entry, "creator")
        image = _media_url(entry)

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
            "section": "Северная Корея",
        }
        if summary:
            item["summary"] = summary
        if creator:
            item["author"] = creator
        if image:
            item["image"] = image
        news.append(item)

    return deduplicate_news(news)


def _parse_yonhap_date(raw_date):
    """Читает RSS-дату Yonhap с корейским часовым поясом +09:00."""
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed.date().isoformat() if parsed else ""


def _is_yonhap_article_url(url):
    parts = urlsplit(str(url))
    hostname = (parts.hostname or "").casefold()
    path_parts = [part for part in parts.path.split("/") if part]
    return (
        hostname in {"yna.co.kr", "www.yna.co.kr"}
        and len(path_parts) == 2
        and path_parts[0] == "view"
        and path_parts[1].startswith("AKR")
        and path_parts[1][3:].isdigit()
    )


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_summary(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())


def _media_url(entry):
    media = entry.find("media:content") or entry.find("content")
    return str(media.get("url", "")).strip() if media else ""
