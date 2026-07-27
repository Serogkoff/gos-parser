"""Безопасное извлечение текста публикации для локальной страницы просмотра."""

from bs4 import BeautifulSoup

from utils.http_client import fetch_soup


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
    "адрес", "наверх", "наверх", "навигац",
)


def extract_article(url, fallback_title=""):
    soup = fetch_soup(url, "Просмотр новости", timeout=25, verify=False)
    if soup is None:
        return {
            "title": fallback_title,
            "paragraphs": [],
            "error": "Сайт ведомства сейчас не отдал текст публикации.",
        }

    for tag in soup(["script", "style", "noscript", "nav", "footer", "form", "aside"]):
        tag.decompose()

    title = _first_text(
        soup.select_one("h1"),
        soup.select_one("[itemprop='headline']"),
        soup.select_one("meta[property='og:title']"),
    ) or fallback_title

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
