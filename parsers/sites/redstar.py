"""Парсер материалов текущего номера газеты «Красная звезда»."""

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.dates import parse_date
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import deduplicate_news


SOURCE_NAME = "Красная звезда"
# На redstar.ru HTTPS периодически отвечает TLSV1_UNRECOGNIZED_NAME.
# Официальная ссылка раздела работает по HTTP, поэтому не форсируем HTTPS.
ISSUE_URL = "http://redstar.ru/category/nomer/"
ISSUE_RSS_URL = "http://redstar.ru/category/nomer/feed/"
SITE_RSS_URL = "http://redstar.ru/feed/"
DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
NON_ARTICLE_PATHS = {
    "", "category", "tag", "author", "page", "feed", "wp-content",
    "wp-admin", "nomer",
}


def parse():
    issue_feed = fetch_soup(
        ISSUE_RSS_URL,
        f"{SOURCE_NAME} · номера",
        timeout=25,
        verify=False,
        parser="xml",
        attempts=1,
    )
    issue = _latest_issue_from_rss(issue_feed)

    # Общий RSS содержит не карточки выпусков, а отдельные статьи со всех
    # полос. Категория с датой номера позволяет оставить только свежий выпуск.
    article_feed = fetch_soup(
        SITE_RSS_URL,
        f"{SOURCE_NAME} · статьи",
        timeout=25,
        verify=False,
        parser="xml",
        attempts=1,
    )
    news = _parse_articles_rss(
        article_feed,
        issue_title=issue.get("title", "") if issue else "",
        issue_date=issue.get("date", "") if issue else "",
    )

    if not news:
        news = _fallback_issue_pages(issue)

    print(f"  ✅ {len(news)}")
    return news


def _latest_issue_from_rss(soup):
    issues = _parse_issue_rss(soup)
    return issues[0] if issues else None


def _parse_articles_rss(soup, issue_title="", issue_date=""):
    """Извлекает отдельные статьи только из последнего газетного номера."""
    if soup is None:
        return []

    news = []
    issue_key = _category_key(issue_title)
    for entry in soup.find_all("item"):
        categories = [
            " ".join(tag.get_text(" ", strip=True).split())
            for tag in entry.find_all("category")
        ]
        category_keys = {_category_key(value) for value in categories}
        if issue_key and issue_key not in category_keys:
            continue

        category_date = ""
        for value in categories:
            category_date = parse_date(value)
            if category_date:
                break
        item = _make_item(
            title=_tag_text(entry, "title"),
            url=_tag_text(entry, "link") or _tag_text(entry, "guid"),
            date=issue_date or category_date or _parse_rss_date(
                _tag_text(entry, "pubDate")
            ),
            summary=_clean_html(_tag_text(entry, "description")),
        )
        if item:
            news.append(item)
    return deduplicate_news(news)


def _fallback_issue_pages(issue=None):
    """Резерв: раскрывает выпуск по полосам, если RSS статей недоступен."""
    if issue is None:
        soup = fetch_soup(
            ISSUE_URL,
            SOURCE_NAME,
            timeout=25,
            verify=False,
            attempts=1,
        )
        if soup is None:
            print("  ℹ️ RSS «Красной звезды» пуст — пробую страницу через браузер")
            soup = fetch_soup_js(
                ISSUE_URL,
                SOURCE_NAME,
                wait_ms=1800,
                timeout_ms=45000,
                wait_until="domcontentloaded",
                use_partial_on_timeout=True,
            )
        issues = _parse_issue_page(soup) if soup else []
        issue = issues[0] if issues else None

    if not issue:
        return []

    page = fetch_soup(
        issue.get("url", ""),
        f"{SOURCE_NAME} · свежий номер",
        timeout=25,
        verify=False,
        attempts=1,
    )
    strips = _parse_issue_strips(page, issue) if page else []
    return strips or [issue]


def _parse_issue_strips(soup, issue):
    if soup is None:
        return []

    news = []
    for figure in soup.select(".entry-content figure"):
        image = figure.select_one("img[src*='_Stranitsa_'], img[src*='_stranitsa_']")
        link = figure.select_one("a[href]")
        if image is None or link is None:
            continue
        caption = _text(figure.select_one("figcaption"))
        if not caption:
            match = re.search(r"_stranitsa_(\d+)", str(image.get("src", "")), re.I)
            caption = f"{match.group(1)} полоса" if match else "Полоса номера"
        item = _make_item(
            title=f"{issue.get('title', 'Свежий номер')} — {caption}",
            url=urljoin(issue.get("url", ISSUE_URL), str(link.get("href", ""))),
            date=issue.get("date", ""),
        )
        if item:
            news.append(item)
    return deduplicate_news(news)


def _deduplicate_issue_records(items):
    """Убирает повторы служебных карточек, не отправляя их в общую базу."""
    result = []
    seen = set()
    for item in items:
        url = str(item.get("url", "")).rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _parse_issue_page(soup):
    if soup is None:
        return []

    news = []
    cards = soup.select("article, .post, .type-post")
    for card in cards:
        link = card.select_one(
            "h1 a[href], h2 a[href], h3 a[href], .entry-title a[href]"
        )
        if link is None:
            continue
        item = _make_item(
            title=_text(link),
            url=urljoin(ISSUE_URL, str(link.get("href", "")).strip()),
            date=_card_date(card),
            summary=_card_summary(card),
        )
        if item:
            news.append(item)

    return _deduplicate_issue_records(news)


def _parse_issue_rss(soup):
    if soup is None:
        return []

    news = []
    for entry in soup.find_all("item"):
        item = _make_item(
            title=_tag_text(entry, "title"),
            url=_tag_text(entry, "link") or _tag_text(entry, "guid"),
            date=parse_date(_tag_text(entry, "title"))
            or _parse_rss_date(_tag_text(entry, "pubDate")),
            summary=_clean_html(_tag_text(entry, "description")),
        )
        if item:
            news.append(item)
    return _deduplicate_issue_records(news)


def _make_item(title, url, date="", summary=""):
    if len(title) < 10 or not _is_article_url(url) or is_junk(title):
        return None
    item = {
        "source": SOURCE_NAME,
        "title": title,
        "url": url,
        "date": date,
    }
    if date:
        item["edition_date"] = date
    if summary:
        item["summary"] = summary
    return item


def _is_article_url(url):
    parts = urlsplit(str(url or ""))
    hostname = (parts.hostname or "").casefold()
    path_parts = [part.casefold() for part in parts.path.split("/") if part]
    attachment_id = parse_qs(parts.query).get("attachment_id", [""])[0]
    return (
        (hostname == "redstar.ru" or hostname.endswith(".redstar.ru"))
        and (
            (
                len(path_parts) == 1
                and path_parts[0] not in NON_ARTICLE_PATHS
            )
            or (not path_parts and attachment_id.isdigit())
        )
    )


def _card_date(card):
    time_tag = card.select_one("time[datetime]")
    if time_tag:
        value = str(time_tag.get("datetime", "")).strip()[:10]
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass

    match = DATE_RE.search(_text(card))
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _card_summary(card):
    node = card.select_one(".entry-summary, .entry-content, .post-excerpt, p")
    text = _text(node)
    return text if len(text) >= 45 else ""


def _parse_rss_date(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
    except (TypeError, ValueError, OverflowError):
        return ""
    if not parsed:
        return ""
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=3)))
    return parsed.date().isoformat()


def _category_key(value):
    normalized = str(value or "").casefold().replace("\xa0", " ")
    return " ".join(normalized.split()).rstrip(".")


def _tag_text(entry, name):
    tag = entry.find(name)
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _clean_html(value):
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
    return " ".join(text.split())


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""
