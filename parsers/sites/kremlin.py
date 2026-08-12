"""Новости Президента России из официального Atom-канала Кремля."""

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.news import deduplicate_news


SOURCE_NAME = "Президент России"
FEED_URL = "http://www.kremlin.ru/events/president/news/feed"
MAX_ARTICLE_CHARS = 95_000


def parse():
    soup = fetch_soup(
        FEED_URL,
        SOURCE_NAME,
        timeout=30,
        verify=True,
        parser="xml",
        attempts=1,
    )
    news = _parse_feed(soup) if soup else []
    print(
        f"  ✅ {len(news)} "
        f"(с текстом: {sum(bool(item.get('article_paragraphs')) for item in news)})"
    )
    return news


def _parse_feed(soup):
    news = []
    for entry in soup.find_all("entry")[:50]:
        title_tag = entry.find("title")
        title = (
            " ".join(title_tag.get_text(" ", strip=True).split())
            if title_tag
            else ""
        )
        link_tag = entry.find("link", attrs={"rel": "alternate"})
        url = link_tag.get("href", "").strip() if link_tag else ""
        if not url:
            id_tag = entry.find("id")
            url = id_tag.get_text(strip=True) if id_tag else ""
        date_tag = entry.find("published") or entry.find("updated")
        publication_date = (
            date_tag.get_text(strip=True)[:10] if date_tag else ""
        )
        if len(title) < 10 or not url or is_junk(title):
            continue

        item = {
            "source": SOURCE_NAME,
            "title": title,
            "url": url,
            "date": publication_date,
        }
        content = entry.find("content")
        if content:
            paragraphs = _extract_feed_paragraphs(content.get_text(), title)
            if paragraphs:
                item["article_paragraphs"] = paragraphs
        summary = entry.find("summary")
        if summary:
            summary_text = _plain_html_text(summary.get_text())
            if len(summary_text) >= 30:
                item["summary"] = summary_text
        news.append(item)

    return deduplicate_news(news)


def _extract_feed_paragraphs(value, title=""):
    content = BeautifulSoup(value or "", "html.parser")
    for tag in content(["script", "style", "noscript", "form", "nav", "footer"]):
        tag.decompose()

    paragraphs = []
    seen = set()
    total = 0
    nodes = content.select("p, li, blockquote")
    if not nodes:
        nodes = [content]
    for node in nodes:
        text = " ".join(node.get_text(" ", strip=True).split())
        key = text.casefold()
        if len(text) < 15 or key == title.casefold() or key in seen:
            continue
        if total + len(text) > MAX_ARTICLE_CHARS:
            break
        seen.add(key)
        paragraphs.append(text)
        total += len(text)
    return paragraphs


def _plain_html_text(value):
    return " ".join(
        BeautifulSoup(value or "", "html.parser")
        .get_text(" ", strip=True)
        .split()
    )
