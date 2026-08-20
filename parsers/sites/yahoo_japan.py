"""RSS-ленты Yahoo! JAPAN News для личного мониторинга."""

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


MAX_ITEMS = 50
MAX_AGE_DAYS = 30
YAHOO_HOST = "news.yahoo.co.jp"

SOURCE_TOP = "Yahoo! JAPAN · トップ"
SOURCE_DOMESTIC = "Yahoo! JAPAN · 国内"
SOURCE_WORLD = "Yahoo! JAPAN · 国際"
SOURCE_BUSINESS = "Yahoo! JAPAN · 経済"
SOURCE_IT = "Yahoo! JAPAN · IT"
SOURCE_LIFE = "Yahoo! JAPAN · ライフ"
SOURCE_LOCAL = "Yahoo! JAPAN · 地域"
SOURCE_ENTERTAINMENT = "Yahoo! JAPAN · エンタメ"
SOURCE_JIJI = "Yahoo! JAPAN · 時事通信"
SOURCE_AP = "Yahoo! JAPAN · AP通信"
SOURCE_CNN = "Yahoo! JAPAN · CNN"
SOURCE_TEIKOKUDB = "Yahoo! JAPAN · 帝国データバンク"

YAHOO_FEEDS = (
    (
        SOURCE_JIJI,
        "時事通信",
        "https://news.yahoo.co.jp/rss/media/jij/all.xml",
    ),
    (
        SOURCE_AP,
        "AP通信",
        "https://news.yahoo.co.jp/rss/media/aptsushinv/all.xml",
    ),
    (
        SOURCE_CNN,
        "CNN",
        "https://news.yahoo.co.jp/rss/media/cnn/all.xml",
    ),
    (
        SOURCE_TEIKOKUDB,
        "帝国データバンク",
        "https://news.yahoo.co.jp/rss/media/teikokudb/all.xml",
    ),
    (
        SOURCE_TOP,
        "トップ",
        "https://news.yahoo.co.jp/rss/topics/top-picks.xml",
    ),
    (
        SOURCE_DOMESTIC,
        "国内",
        "https://news.yahoo.co.jp/rss/categories/domestic.xml",
    ),
    (
        SOURCE_WORLD,
        "国際",
        "https://news.yahoo.co.jp/rss/categories/world.xml",
    ),
    (
        SOURCE_BUSINESS,
        "経済",
        "https://news.yahoo.co.jp/rss/categories/business.xml",
    ),
    (
        SOURCE_IT,
        "IT",
        "https://news.yahoo.co.jp/rss/categories/it.xml",
    ),
    (
        SOURCE_LIFE,
        "ライフ",
        "https://news.yahoo.co.jp/rss/categories/life.xml",
    ),
    (
        SOURCE_LOCAL,
        "地域",
        "https://news.yahoo.co.jp/rss/categories/local.xml",
    ),
    (
        SOURCE_ENTERTAINMENT,
        "エンタメ",
        "https://news.yahoo.co.jp/rss/categories/entertainment.xml",
    ),
)


def parse_feed(source_name, section, feed_url, now=None):
    """Преобразует одну RSS 2.0 ленту Yahoo в формат проекта."""
    soup = fetch_soup(
        feed_url,
        source_name,
        timeout=30,
        verify=True,
        parser="xml",
    )
    if soup is None:
        print("  ✅ 0")
        return []

    now = now or datetime.now().astimezone()
    cutoff = now.date() - timedelta(days=MAX_AGE_DAYS)
    news = []

    for entry in soup.find_all("item")[:MAX_ITEMS]:
        title = _tag_text(entry, "title")
        url = _article_url(
            _tag_text(entry, "link"),
            _tag_text(entry, "guid"),
        )
        if not url:
            url = _comments_article_url(_tag_text(entry, "comments"))
        publication_date = _parse_rss_date(_tag_text(entry, "pubDate"))

        if len(title) < 4 or not url or is_junk(title):
            continue
        if publication_date:
            parsed_date = datetime.strptime(
                publication_date,
                "%Y-%m-%d",
            ).date()
            if parsed_date < cutoff:
                continue

        item = {
            "source": source_name,
            "title": title,
            "url": url,
            "date": publication_date,
            "section": section,
        }
        summary = _clean_summary(_tag_text(entry, "description"))
        if summary and summary != title:
            item["summary"] = summary
        news.append(item)

    result = deduplicate_news(news)
    print(f"  ✅ {len(result)}")
    return result


def _article_url(*values):
    for value in values:
        parts = urlsplit(str(value or "").strip())
        hostname = (parts.hostname or "").casefold()
        try:
            port = parts.port
        except ValueError:
            continue
        if (
            parts.scheme.casefold() not in {"http", "https"}
            or hostname != YAHOO_HOST
            or parts.username
            or parts.password
            or port not in {None, 80, 443}
            or not parts.path.startswith("/")
        ):
            continue
        return urlunsplit(("https", YAHOO_HOST, parts.path, parts.query, ""))
    return ""


def _comments_article_url(value):
    url = _article_url(value)
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.path.endswith("/comments"):
        return ""
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path[:-9], parts.query, "")
    )


def _parse_rss_date(raw_date):
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed.date().isoformat() if parsed else ""


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_summary(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())


def parse_jiji():
    return parse_feed(*YAHOO_FEEDS[0])


def parse_ap():
    return parse_feed(*YAHOO_FEEDS[1])


def parse_cnn():
    return parse_feed(*YAHOO_FEEDS[2])


def parse_teikokudb():
    return parse_feed(*YAHOO_FEEDS[3])


def parse_top():
    return parse_feed(*YAHOO_FEEDS[4])


def parse_domestic():
    return parse_feed(*YAHOO_FEEDS[5])


def parse_world():
    return parse_feed(*YAHOO_FEEDS[6])


def parse_business():
    return parse_feed(*YAHOO_FEEDS[7])


def parse_it():
    return parse_feed(*YAHOO_FEEDS[8])


def parse_life():
    return parse_feed(*YAHOO_FEEDS[9])


def parse_local():
    return parse_feed(*YAHOO_FEEDS[10])


def parse_entertainment():
    return parse_feed(*YAHOO_FEEDS[11])


YAHOO_SITES = [
    (SOURCE_JIJI, parse_jiji),
    (SOURCE_AP, parse_ap),
    (SOURCE_CNN, parse_cnn),
    (SOURCE_TEIKOKUDB, parse_teikokudb),
    (SOURCE_TOP, parse_top),
    (SOURCE_DOMESTIC, parse_domestic),
    (SOURCE_WORLD, parse_world),
    (SOURCE_BUSINESS, parse_business),
    (SOURCE_IT, parse_it),
    (SOURCE_LIFE, parse_life),
    (SOURCE_LOCAL, parse_local),
    (SOURCE_ENTERTAINMENT, parse_entertainment),
]
