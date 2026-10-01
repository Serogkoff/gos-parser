"""Общий RSS -> страница статьи конвейер для источников через VPN."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_response_soup_js
from utils.logger import get_logger
from utils.news import deduplicate_news, normalize_url
from utils.proxy import kyodo_proxy_url
from utils.storage import load_source_url_aliases


logger = get_logger("vpn_rss")

REMOVE_SELECTORS = (
    "script", "style", "noscript", "nav", "footer", "form", "aside",
    "iframe", "button", "[role='navigation']", "[aria-label*='соц']",
    "[class*='advert']", "[class*='banner']", "[class*='cookie']",
    "[class*='footer']", "[class*='header']", "[class*='menu']",
    "[class*='recommend']", "[class*='related']", "[class*='share']",
    "[class*='social']", "[class*='subscribe']", "[class*='support']",
)
JUNK_PARTS = (
    "читайте также", "подписывайтесь", "подписаться", "поделиться",
    "реклама", "мы в социальных сетях", "следите за новостями",
    "поддержать редакцию", "поддержите нашу работу",
    "расширение для браузера", "это расширение поможет",
    "конец истории", "скачайте новое приложение",
    "при первом открытии приложения", "новое приложение недоступно",
)


@dataclass(frozen=True)
class VpnRssSource:
    name: str
    feed_url: str
    domains: tuple
    article_selectors: tuple
    default_section: str = "Новости"
    max_items: int = 50
    max_new_articles: int = 8
    rss_full_text_fallback: bool = False
    prefer_rss_full_text: bool = False
    feed_fallback_urls: tuple = ()
    browser_fallback: bool = False
    browser_warmup_url: str = ""


def parse_source(config, now=None):
    """Читает RSS, а полные тексты только новых материалов — через VPN."""
    proxy_url = _proxy_url(config.name)
    feed = _load_feed(config, proxy_url)
    if feed is None:
        print("  ✅ 0")
        return []

    discovered = parse_feed(feed, config, now=now)
    aliases = load_source_url_aliases(config.name)
    result = []
    new_count = 0

    for item in discovered:
        rss_url = normalize_url(item["url"])
        existing = aliases.get(rss_url)
        if existing and existing.get("has_article"):
            item["url"] = existing["url"]
            result.append(item)
            continue

        if not existing and new_count >= config.max_new_articles:
            # Следующий цикл продолжит с оставшимися элементами RSS. Так первый
            # запуск не превращается в сотни запросов к страницам статей.
            continue

        new_count += not bool(existing)
        if config.prefer_rss_full_text:
            rss_enriched = _rss_fallback(dict(item), config)
            if rss_enriched.get("article_paragraphs"):
                result.append(rss_enriched)
                continue
        enriched = load_article(item, config, proxy_url=proxy_url)
        if enriched.get("article_paragraphs"):
            result.append(enriched)
            continue

        # Ошибка одной статьи не останавливает источник. Карточку сохраняем,
        # но помечаем для повторной попытки полного текста в следующем цикле.
        enriched["article_fetch_pending"] = True
        result.append(enriched)

    result = deduplicate_news(result)
    print(f"  ✅ {len(result)}")
    return result


def parse_feed(soup, config, now=None):
    """Преобразует RSS 2.0 в общий формат карточек проекта."""
    now = now or datetime.now().astimezone()
    result = []
    for entry in soup.find_all("item")[: config.max_items]:
        title = _tag_text(entry, "title")
        url = clean_url(
            _tag_text(entry, "link") or _tag_text(entry, "guid"),
            config.domains,
        )
        if not url or len(title) < 5 or is_junk(title):
            continue

        published_at = parse_rss_datetime(_tag_text(entry, "pubDate"))
        categories = [
            _clean_text(tag.get_text(" ", strip=True))
            for tag in entry.find_all("category")
            if _clean_text(tag.get_text(" ", strip=True))
        ]
        summary = html_text(_tag_markup(entry, "description"))
        author = (
            _tag_text(entry, "dc:creator")
            or _tag_text(entry, "creator")
            or _tag_text(entry, "author")
        )
        full_html = (
            _tag_markup(entry, "content:encoded")
            or _tag_markup(entry, "encoded")
        )

        item = {
            "source": config.name,
            "title": title,
            "url": url,
            "rss_url": url,
            "date": published_at[:10],
            "published_at": published_at,
            "section": categories[0] if categories else config.default_section,
        }
        if summary:
            item["summary"] = summary
        if author:
            item["author"] = author
        if full_html:
            item["rss_content_html"] = full_html
        result.append(item)
    return deduplicate_news(result)


def load_article(item, config, proxy_url=""):
    """Загружает страницу и дополняет RSS-карточку чистым полным текстом."""
    result = dict(item)
    soup = fetch_soup(
        item["url"],
        f"{config.name} · полный текст",
        timeout=35,
        verify=True,
        attempts=2,
        proxy_url=proxy_url,
    )
    if soup is None and config.browser_fallback:
        soup = fetch_response_soup_js(
            item["url"],
            f"{config.name} · полный текст · браузер",
            timeout_ms=45000,
            wait_ms=2500,
            proxy_url=proxy_url,
            parser="html.parser",
            warmup_url=config.browser_warmup_url,
        )
    if soup is None:
        return _rss_fallback(result, config)

    canonical = _canonical_url(soup, item["url"], config.domains)
    if canonical:
        result["url"] = canonical

    metadata = extract_metadata(soup)
    for field in ("author", "section", "published_at"):
        if metadata.get(field):
            result[field] = metadata[field]
    if result.get("published_at"):
        result["date"] = result["published_at"][:10]

    paragraphs = extract_paragraphs(soup, config.article_selectors)
    if not paragraphs and metadata.get("article_body"):
        paragraphs = text_to_paragraphs(metadata["article_body"])
    if paragraphs:
        result["article_paragraphs"] = paragraphs
        result.pop("article_fetch_pending", None)
    else:
        logger.warning(
            f"[{config.name}] Не удалось выделить полный текст: {item['url']}"
        )
        result = _rss_fallback(result, config)

    # HTML RSS нужен только как аварийный источник внутри текущего процесса.
    result.pop("rss_content_html", None)
    return result


def extract_paragraphs(soup, selectors):
    """Берёт самый содержательный подтверждённый контейнер без обвязки."""
    for selector in selectors:
        paragraphs = []
        seen = set()
        for original in soup.select(selector):
            container = BeautifulSoup(str(original), "html.parser")
            for removable in container.select(",".join(REMOVE_SELECTORS)):
                removable.decompose()
            for node in container.select("p, h2, blockquote, li"):
                text = _clean_text(node.get_text(" ", strip=True))
                folded = text.casefold()
                if (
                    len(text) < 35
                    or any(part in folded for part in JUNK_PARTS)
                    or folded in seen
                ):
                    continue
                seen.add(folded)
                paragraphs.append(text)
        if sum(map(len, paragraphs)) >= 120:
            # Селекторы заданы от самого точного к резервному. Это не даёт
            # более широкому main победить только за счёт рекомендаций.
            return paragraphs[:150]
    return []


def extract_metadata(soup):
    """Читает автора, рубрику и дату из meta и JSON-LD без обязательности."""
    metadata = {}
    published = _meta_content(
        soup,
        "meta[property='article:published_time'], "
        "meta[itemprop='datePublished'], meta[name='date']",
    )
    section = _meta_content(soup, "meta[property='article:section']")
    author = _meta_content(
        soup,
        "meta[name='author'], meta[property='article:author']",
    )

    for payload in _json_ld_objects(soup):
        for record in _walk_json(payload):
            kind = record.get("@type", "") if isinstance(record, dict) else ""
            kinds = kind if isinstance(kind, list) else [kind]
            if not any("article" in str(value).casefold() for value in kinds):
                continue
            published = published or str(record.get("datePublished", ""))
            section = section or _first_value(record.get("articleSection"))
            author = author or _author_name(record.get("author"))
            body = _clean_text(record.get("articleBody", ""))
            if body:
                metadata["article_body"] = body

    normalized_date = parse_iso_datetime(published)
    if normalized_date:
        metadata["published_at"] = normalized_date
    if _clean_text(section):
        metadata["section"] = _clean_text(section)
    if _clean_text(author):
        metadata["author"] = _clean_text(author)
    return metadata


def clean_url(value, domains):
    value = str(value or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    hostname = (parts.hostname or "").casefold()
    if not _allowed_domain(hostname, domains):
        return ""
    return normalize_url(urlunsplit(("https", hostname, parts.path, parts.query, "")))


def parse_rss_datetime(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
    except (TypeError, ValueError, OverflowError):
        return ""
    if parsed is None:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.isoformat(timespec="seconds")


def parse_iso_datetime(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.isoformat(timespec="seconds")


def html_text(value):
    return _clean_text(BeautifulSoup(str(value or ""), "html.parser").get_text(" "))


def text_to_paragraphs(value):
    return [
        text for text in (_clean_text(part) for part in re.split(r"[\r\n]+", value))
        if len(text) >= 35 and not any(junk in text.casefold() for junk in JUNK_PARTS)
    ][:150]


def _rss_fallback(item, config):
    html = item.pop("rss_content_html", "")
    if config.rss_full_text_fallback and html:
        paragraphs = extract_paragraphs(
            BeautifulSoup(f"<article>{html}</article>", "html.parser"),
            ("article",),
        )
        if sum(map(len, paragraphs)) >= 500:
            item["article_paragraphs"] = paragraphs
    return item


def _load_feed(config, proxy_url):
    """Tries official feed aliases, then the existing browser VPN transport."""
    feed_urls = (config.feed_url, *config.feed_fallback_urls)
    for feed_url in feed_urls:
        feed = fetch_soup(
            feed_url,
            f"{config.name} · RSS",
            timeout=30,
            verify=True,
            parser="xml",
            attempts=2,
            proxy_url=proxy_url,
        )
        if feed is not None and feed.find("item") is not None:
            return feed

    if not config.browser_fallback:
        return None
    for feed_url in feed_urls:
        feed = fetch_response_soup_js(
            feed_url,
            f"{config.name} · RSS · браузер",
            timeout_ms=45000,
            wait_ms=2500,
            proxy_url=proxy_url,
            parser="xml",
            warmup_url=config.browser_warmup_url,
        )
        if feed is not None and feed.find("item") is not None:
            return feed
    return None


def _proxy_url(source_name):
    try:
        proxy_url = kyodo_proxy_url()
    except ValueError as error:
        logger.warning(f"[{source_name}] Настройка VPN некорректна: {error}")
        return ""
    if not proxy_url:
        logger.warning(f"[{source_name}] VPN-канал не настроен")
    return proxy_url


def _canonical_url(soup, base_url, domains):
    tag = soup.select_one("link[rel='canonical'][href]")
    return clean_url(urljoin(base_url, tag.get("href", "")), domains) if tag else ""


def _allowed_domain(hostname, domains):
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def _tag_text(entry, name):
    tag = entry.find(name)
    return _clean_text(tag.get_text(" ", strip=True)) if tag else ""


def _tag_markup(entry, name):
    tag = entry.find(name)
    # В RSS HTML обычно лежит внутри CDATA. decode_contents повторно экранирует
    # его в &lt;p&gt;, тогда как get_text возвращает исходную HTML-строку.
    return str(tag.get_text()) if tag else ""


def _clean_text(value):
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _meta_content(soup, selector):
    tag = soup.select_one(selector)
    return str(tag.get("content", "")).strip() if tag else ""


def _json_ld_objects(soup):
    for script in soup.select("script[type='application/ld+json']"):
        try:
            yield json.loads(script.string or script.get_text() or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _first_value(value):
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _author_name(value):
    if isinstance(value, list):
        return ", ".join(filter(None, (_author_name(item) for item in value)))
    if isinstance(value, dict):
        return _clean_text(value.get("name", ""))
    return _clean_text(value)
