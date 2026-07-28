"""Безопасное извлечение текста публикации для локальной страницы просмотра."""

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js


CONTAINER_SELECTORS = (
    "article",
    "[itemprop='articleBody']",
    ".article-content",
    ".article__content",
    ".news-detail",
    ".news__content",
    ".detail-text",
    ".content",
    "main",
)

SKIP_PARTS = (
    "cookie", "подпис", "социальн", "поделиться", "обратн", "телефон",
    "адрес", "наверх", "навигац", "все материалы сайта доступны по лицензии",
    "creative commons",
)

GENERIC_TITLES = {
    "новости",
    "публикации пресс-центра",
    "пресс-центр",
    "новости и пресс-релизы",
}


def extract_article(url, fallback_title=""):
    fetch_url = url
    if _is_minobrnauki_url(url) or _is_mnr_url(url):
        fetch_url = url.rstrip("/") + "/"

    if _is_mnr_url(url):
        soup = fetch_soup_js(
            fetch_url,
            "Просмотр Минприроды",
            wait_ms=2500,
            timeout_ms=45000,
        )
        if soup is None:
            soup = fetch_soup(
                fetch_url,
                "Просмотр Минприроды",
                timeout=30,
                verify=False,
            )
    else:
        soup = fetch_soup(fetch_url, "Просмотр новости", timeout=25, verify=False)

    if soup is None:
        return {
            "title": fallback_title,
            "paragraphs": [],
            "error": "Сайт ведомства сейчас не отдал текст публикации.",
        }

    if _is_minobrnauki_url(url):
        article = _extract_minobrnauki_card(soup, fetch_url, fallback_title)
        if article:
            return article

    if _is_mnr_url(url):
        article = _extract_mnr_article(soup, fallback_title)
        if article:
            return article

    for tag in soup(["script", "style", "noscript", "nav", "footer", "form", "aside"]):
        tag.decompose()

    title = _first_text(
        soup.select_one("h1"),
        soup.select_one("[itemprop='headline']"),
        soup.select_one("meta[property='og:title']"),
    ) or fallback_title
    if fallback_title and title.casefold().strip() in GENERIC_TITLES:
        title = fallback_title

    best = []
    for selector in CONTAINER_SELECTORS:
        for container in soup.select(selector):
            paragraphs = _paragraphs(container)
            if sum(map(len, paragraphs)) > sum(map(len, best)):
                best = paragraphs

    if not best:
        best = _paragraphs(soup)

    return {
        "title": title,
        "paragraphs": best[:100],
        "error": "" if best else "Не удалось выделить текст публикации автоматически.",
    }


def _is_minobrnauki_url(url):
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname == "minobrnauki.gov.ru" or hostname.endswith(".minobrnauki.gov.ru")


def _is_mnr_url(url):
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname == "mnr.gov.ru" or hostname.endswith(".mnr.gov.ru")


def _extract_mnr_article(soup, fallback_title):
    """Извлекает публикацию Минприроды без списка соседних новостей."""
    for selector in (
        "header",
        "nav",
        "footer",
        "aside",
        "form",
        ".breadcrumbs",
        ".breadcrumb",
        ".pagination",
        ".pager",
        ".news-list",
        ".news-listing",
        ".news-items",
        ".sidebar",
        ".side-menu",
        ".menu",
    ):
        for node in soup.select(selector):
            node.decompose()

    title = fallback_title or _first_text(
        soup.select_one("meta[property='og:title']"),
        soup.select_one("h1"),
        soup.select_one("[itemprop='headline']"),
    )

    best = []
    for selector in (
        "[itemprop='articleBody']",
        ".news-detail__content",
        ".news-detail__text",
        ".news-detail",
        ".detail-text",
        ".article__content",
        ".article-content",
        "article",
    ):
        for container in soup.select(selector):
            paragraphs = _clean_mnr_paragraphs(container, title)
            if sum(map(len, paragraphs)) > sum(map(len, best)):
                best = paragraphs

    if best:
        return {
            "title": title,
            "paragraphs": best[:100],
            "error": "",
        }

    description_tag = soup.select_one("meta[property='og:description']")
    description = (
        " ".join(description_tag.get("content", "").split())
        if description_tag
        else ""
    )
    if len(description) >= 45:
        return {
            "title": title,
            "paragraphs": [description],
            "error": "",
        }

    return None


def _clean_mnr_paragraphs(container, title):
    paragraphs = []
    seen = set()
    title_key = " ".join(title.casefold().split()) if title else ""

    for node in container.select("p, li"):
        text = " ".join(node.get_text(" ", strip=True).split())
        folded = text.casefold()

        if len(text) < 45:
            continue
        if title_key and folded == title_key:
            continue
        if any(part in folded for part in SKIP_PARTS):
            continue
        if "новости и пресс-релизы" in folded:
            continue
        if folded not in seen:
            seen.add(folded)
            paragraphs.append(text)

    return paragraphs


def _extract_minobrnauki_card(soup, url, fallback_title):
    """
    У Минобрнауки адрес с ID публикации открывает общий список новостей.
    Поэтому ищем на странице только карточку с тем же числовым ID.
    """
    target_path = urlsplit(url).path.rstrip("/")
    target_id = target_path.rsplit("/", 1)[-1]
    if not target_id.isdigit():
        return None

    # Страница Минобрнауки визуально похожа на общий список, но сведения
    # выбранной публикации сервер помещает в Open Graph-метаданные.
    og_url = soup.select_one("meta[property='og:url']")
    og_title = soup.select_one("meta[property='og:title']")
    og_description = soup.select_one("meta[property='og:description']")
    metadata_url = og_url.get("content", "") if og_url else ""
    metadata_path = urlsplit(metadata_url).path.rstrip("/")
    description = (
        " ".join(og_description.get("content", "").split())
        if og_description
        else ""
    )

    if (
        metadata_path.rsplit("/", 1)[-1] == target_id
        and len(description) >= 45
    ):
        title = fallback_title
        if not title and og_title:
            title = " ".join(og_title.get("content", "").split())
        return {
            "title": title,
            "paragraphs": [description],
            "error": "",
        }

    target_link = None
    for link in soup.select("a[href]"):
        link_path = urlsplit(urljoin(url, link.get("href", ""))).path.rstrip("/")
        if link_path.rsplit("/", 1)[-1] == target_id:
            target_link = link
            break

    if target_link is None:
        return None

    card = target_link.find_parent(class_="news-item")
    if card is None:
        card = _nearest_news_container(target_link, fallback_title)
    if card is None:
        return None

    for tag in card(["script", "style", "noscript", "nav", "form", "button"]):
        tag.decompose()

    paragraphs = []
    seen = set()
    selectors = (
        ".news-item-text",
        ".news-item__text",
        ".news-item-description",
        ".news-item__description",
        ".news-item-preview",
        ".news-item__preview",
        ".news-list__text",
        ".preview-text",
        ".description",
        "p",
    )
    for selector in selectors:
        found_for_selector = []
        for node in card.select(selector):
            text = _clean_minobrnauki_text(
                node.get_text(" ", strip=True),
                fallback_title,
            )
            folded = text.casefold()
            if len(text) >= 45 and folded not in seen:
                seen.add(folded)
                found_for_selector.append(text)
        if found_for_selector:
            paragraphs.extend(found_for_selector)
            break

    if not paragraphs:
        text = _clean_minobrnauki_text(
            card.get_text(" ", strip=True),
            fallback_title,
        )
        if len(text) >= 45:
            paragraphs.append(text)

    if not paragraphs:
        return None

    return {
        "title": fallback_title,
        "paragraphs": paragraphs[:20],
        "error": "",
    }


def _nearest_news_container(link, fallback_title):
    title_key = " ".join(fallback_title.casefold().split())[:60]
    parent = link.parent

    for _ in range(7):
        if parent is None or getattr(parent, "name", "") in {"main", "body", "html"}:
            break
        classes = " ".join(parent.get("class", [])).casefold()
        text = " ".join(parent.get_text(" ", strip=True).casefold().split())
        if (
            any(part in classes for part in ("news", "item", "card"))
            and (not title_key or title_key in text)
        ):
            return parent
        parent = parent.parent
    return None


def _clean_minobrnauki_text(value, fallback_title):
    text = " ".join(str(value).split())
    if fallback_title:
        text = text.replace(fallback_title, " ")
    text = re.sub(
        r"^\s*\d{1,2}\s+"
        r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip(" —|")
    if text.casefold() in {
        "наука",
        "образование",
        "молодежная политика",
        "новости министерства",
    }:
        return ""
    return text


def _first_text(*tags):
    for tag in tags:
        if not tag:
            continue
        if tag.name == "meta":
            value = tag.get("content", "").strip()
        else:
            value = tag.get_text(" ", strip=True)
        if value:
            return value
    return ""


def _paragraphs(container):
    result = []
    seen = set()
    candidates = container.select("p, li") or [container]
    for node in candidates:
        text = " ".join(node.get_text(" ", strip=True).split())
        folded = text.casefold()
        if len(text) < 45 or any(part in folded for part in SKIP_PARTS):
            continue
        if folded not in seen:
            seen.add(folded)
            result.append(text)
    return result
