"""Безопасное извлечение текста публикации для локальной страницы просмотра."""

import json
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

VERIFIED_ARTICLE_SELECTORS = {
    "interfax.ru": (
        "article[itemprop='articleBody']",
        "[itemprop='articleBody']",
        "article",
    ),
    "sport-interfax.ru": (
        "article[itemprop='articleBody']",
        "[itemprop='articleBody']",
        "article",
    ),
    "ria.ru": (
        "[itemprop='articleBody']",
        ".article__body",
        ".article__text",
        ".article__block",
    ),
    "mcx.gov.ru": (
        "[itemprop='articleBody']",
        ".news-detail__content",
        ".news-detail__text",
        ".news-detail__body",
        ".newsDetail__content",
        ".newsDetail__text",
        ".news-detail",
        ".newsDetail",
        ".detail-text",
        ".article__content",
        "[class*='publication'][class*='body']",
    ),
    "minstroyrf.gov.ru": (
        "[itemprop='articleBody']",
        ".news-detail__content",
        ".news-detail",
        ".detail-new",
        ".detail-text",
        ".article-content",
    ),
    "minvr.gov.ru": (
        "[itemprop='articleBody']",
        ".article__body",
        ".article__content",
        ".news-detail__content",
        ".news-detail",
        ".detail-text",
    ),
    "mintrans.gov.ru": (
        "[itemprop='articleBody']",
        ".news-detail__content",
        ".news-detail__text",
        ".news-detail__body",
        ".news-detail",
        ".news-content",
        ".news-detail-text",
        ".detail-text",
        ".article-content",
        "[class*='article'][class*='body']",
        "article",
    ),
}

ARTICLE_MENU_PARTS = (
    "о министерстве положение руководство",
    "деятельность национальные проекты",
    "пресс-центр все новости",
    "пресс-центр новости",
    "государственные услуги государственные программы",
    "обращения граждан и организаций контакты",
    "онлайн-сервисы все сервисы",
)

MVD_NOISE_PARTS = (
    "график приема граждан руководящим составом мвд россии",
    "о рассмотрении обращений граждан и организаций",
    "поступление на службу в органы внутренних дел российской федерации",
    "мвд россии министр структура министерства руководство",
    "деятельность служба статистика и аналитика мониторинг общественного мнения",
    "для граждан прием обращений граждан и организаций",
    "онлайн-сервисы все сервисы прием обращений граждан и организаций",
    "ваш участковый отдел полиции внимание розыск",
    "мобильное приложение мвд россии детская страница",
    "официальный интернет-сайт мвд россии",
    "при использовании материалов сайта",
    "ссылки на сайты органов государственной власти",
    "версия для слабовидящих",
)

MVD_REMOVABLE_SELECTORS = (
    "header",
    "nav",
    "footer",
    "aside",
    "form",
    ".header",
    ".footer",
    ".breadcrumbs",
    ".breadcrumb",
    ".sidebar",
    ".side-menu",
    ".main-menu",
    ".navigation",
    ".online-services",
    ".social",
    ".share",
    ".related-news",
    ".other-news",
)

MVD_ARTICLE_SELECTORS = (
    "[itemprop='articleBody']",
    ".news-detail__content",
    ".news-detail__text",
    ".news-detail",
    ".article__content",
    ".article__text",
    ".article-content",
    ".content__text",
    ".detail-text",
    "article",
    "main",
)


def extract_article(url, fallback_title=""):
    fetch_url = url
    verified_selectors = _verified_article_selectors(url)
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
        if soup is None and verified_selectors:
            soup = fetch_soup_js(
                fetch_url,
                "Просмотр новости",
                wait_ms=1500,
                timeout_ms=40000,
            )

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

    if _is_mvd_url(url):
        return _extract_mvd_article(soup, fallback_title)

    if _is_interfax_url(url):
        article = _extract_interfax_article(soup, fallback_title)
        if article:
            return article

    if _is_ria_url(url):
        article = _extract_ria_article(soup, fallback_title)
        if article:
            return article

    if verified_selectors:
        return _extract_verified_article(
            soup,
            fallback_title,
            verified_selectors,
        )

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


def _is_mvd_url(url):
    hostname = (urlsplit(url).hostname or "").casefold()
    return (
        hostname in {"мвд.рф", "xn--b1aew.xn--p1ai"}
        or hostname.endswith(".мвд.рф")
        or hostname.endswith(".xn--b1aew.xn--p1ai")
    )


def _is_interfax_url(url):
    hostname = (urlsplit(url).hostname or "").casefold()
    return (
        hostname in {"interfax.ru", "sport-interfax.ru"}
        or hostname.endswith(".interfax.ru")
        or hostname.endswith(".sport-interfax.ru")
    )


def _is_ria_url(url):
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname == "ria.ru" or hostname.endswith(".ria.ru")


def _extract_mvd_article(soup, fallback_title):
    """Извлекает статью МВД без меню, сервисов и нижних блоков сайта."""
    page_title = _first_text(
        soup.select_one("h1"),
        soup.select_one("[itemprop='headline']"),
        soup.select_one("meta[property='og:title']"),
    )
    title = fallback_title or page_title

    if (
        fallback_title
        and page_title
        and page_title.casefold().strip() not in GENERIC_TITLES
        and not _titles_match(fallback_title, page_title)
    ):
        return {
            "title": fallback_title,
            "paragraphs": [],
            "error": (
                "Сайт МВД открыл другую страницу вместо публикации. "
                "Используйте кнопку «Открыть оригинал»."
            ),
        }

    structured_article = _extract_structured_article(soup, fallback_title)
    if structured_article:
        paragraphs = _clean_mvd_texts(
            structured_article["paragraphs"],
            title,
        )
        if paragraphs:
            return {
                "title": title or structured_article["title"],
                "paragraphs": paragraphs[:100],
                "error": "",
            }

    for selector in MVD_REMOVABLE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    best = []
    for selector in MVD_ARTICLE_SELECTORS:
        for container in soup.select(selector):
            paragraphs = _mvd_paragraphs(container, title)
            if sum(map(len, paragraphs)) > sum(map(len, best)):
                best = paragraphs

    if best:
        return {
            "title": title,
            "paragraphs": best[:100],
            "error": "",
        }

    return {
        "title": title,
        "paragraphs": [],
        "error": (
            "Заголовок найден, но сайт МВД не отдал чистый текст "
            "публикации. Используйте кнопку «Открыть оригинал»."
        ),
    }


def _mvd_paragraphs(container, title):
    """Сохраняет абзацы публикации МВД и отбрасывает окружение страницы."""
    nodes = container.select("p, blockquote")
    if not nodes:
        nodes = [
            node
            for node in container.select("div, section")
            if not node.find(["div", "section", "p", "blockquote"])
        ]

    return _clean_mvd_texts(
        (node.get_text(" ", strip=True) for node in nodes),
        title,
    )


def _clean_mvd_texts(values, title):
    result = []
    seen = set()
    title_key = _title_key(title)

    for value in values:
        text = " ".join(str(value or "").split())
        normalized = _title_key(text)
        folded = text.casefold().replace("ё", "е")

        if len(text) < 20:
            continue
        if title_key and normalized == title_key:
            continue
        if any(part in folded for part in MVD_NOISE_PARTS):
            continue
        if any(part in folded for part in SKIP_PARTS):
            continue
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(text)

    return result


def _extract_interfax_article(soup, fallback_title):
    """Берёт полный текст статьи, а не короткое описание из JSON-LD."""
    container = soup.select_one(
        "article[itemprop='articleBody'], [itemprop='articleBody']"
    )
    if container is None:
        return None

    title = fallback_title or _first_text(
        container.select_one("h1"),
        soup.select_one("meta[property='og:title']"),
    )
    page_title = _first_text(
        container.select_one("h1"),
        soup.select_one("meta[property='og:title']"),
    )
    if fallback_title and not _titles_match(fallback_title, page_title):
        return None

    paragraphs = _verified_paragraphs(container, title)
    if not paragraphs:
        return None

    return {
        "title": title,
        "paragraphs": paragraphs[:100],
        "error": "",
    }


def _extract_ria_article(soup, fallback_title):
    """Берёт текстовые блоки РИА, исключая пересказ ИИ и подписи к фото."""
    page_title = _first_text(
        soup.select_one("h1.article__title"),
        soup.select_one("h1"),
        soup.select_one("meta[property='og:title']"),
    )
    if fallback_title and not _titles_match(fallback_title, page_title):
        return None

    body = soup.select_one(".article__body, [itemprop='articleBody']")
    if body is None:
        return None

    paragraphs = _exact_article_paragraphs(
        body.select(".article__block[data-type='text'] .article__text"),
        fallback_title or page_title,
    )

    if not paragraphs:
        return None

    return {
        "title": fallback_title or page_title,
        "paragraphs": paragraphs[:100],
        "error": "",
    }


def _exact_article_paragraphs(nodes, title):
    """Чистит уже найденные точные блоки статьи, сохраняя короткие абзацы."""
    result = []
    seen = set()
    title_key = _title_key(title)

    for node in nodes:
        text = " ".join(node.get_text(" ", strip=True).split())
        normalized = _title_key(text)
        folded = text.casefold()
        if len(text) < 15:
            continue
        if title_key and normalized == title_key:
            continue
        if any(part in folded for part in SKIP_PARTS):
            continue
        if any(part in folded for part in ARTICLE_MENU_PARTS):
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(text)

    return result


def _verified_article_selectors(url):
    hostname = (urlsplit(url).hostname or "").casefold()
    for required_host, selectors in VERIFIED_ARTICLE_SELECTORS.items():
        if hostname == required_host or hostname.endswith(f".{required_host}"):
            return selectors
    return ()


def _extract_verified_article(soup, fallback_title, selectors):
    """
    Извлекает текст только если страница подтверждает заголовок публикации.

    Это не даёт общему разделу новостей или странице ошибки превратиться
    во «внутренний текст» из пунктов меню.
    """
    structured_article = _extract_structured_article(
        soup,
        fallback_title,
    )
    page_titles = [
        _first_text(soup.select_one("h1")),
        _first_text(soup.select_one("[itemprop='headline']")),
        _first_text(soup.select_one("meta[property='og:title']")),
    ]
    if structured_article:
        page_titles.append(structured_article["title"])
    page_titles = [title for title in page_titles if title]

    if fallback_title:
        title_confirmed = any(
            _titles_match(fallback_title, page_title)
            for page_title in page_titles
        )
    else:
        title_confirmed = bool(page_titles)

    title = fallback_title or (page_titles[0] if page_titles else "")
    if not title_confirmed:
        return {
            "title": title,
            "paragraphs": [],
            "error": (
                "Сайт открыл общий раздел вместо публикации. "
                "Используйте кнопку «Открыть оригинал»."
            ),
        }

    if structured_article and structured_article["paragraphs"]:
        return {
            "title": fallback_title or structured_article["title"],
            "paragraphs": structured_article["paragraphs"][:100],
            "error": "",
        }

    for tag in soup(
        ["script", "style", "noscript", "nav", "footer", "form", "aside"]
    ):
        tag.decompose()

    candidates = []
    for selector in selectors:
        candidates.extend(soup.select(selector))

    matching_heading = next(
        (
            heading
            for heading in soup.select("h1, [itemprop='headline']")
            if _titles_match(
                fallback_title or page_titles[0],
                heading.get_text(" ", strip=True),
            )
        ),
        None,
    )
    current = matching_heading.parent if matching_heading else None
    for _ in range(7):
        if current is None or getattr(current, "name", "") in {
            "main",
            "body",
            "html",
        }:
            break
        current_text = " ".join(
            current.get_text(" ", strip=True).split()
        )
        if len(current_text) >= len(title) + 80:
            candidates.append(current)
            break
        current = current.parent

    best = []
    for container in candidates:
        paragraphs = _verified_paragraphs(container, title)
        if sum(map(len, paragraphs)) > sum(map(len, best)):
            best = paragraphs

    if best:
        return {
            "title": title,
            "paragraphs": best[:100],
            "error": "",
        }

    description_tag = (
        soup.select_one("meta[property='og:description']")
        or soup.select_one("meta[name='description']")
    )
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

    return {
        "title": title,
        "paragraphs": [],
        "error": (
            "Заголовок найден, но сайт не отдал текст публикации. "
            "Используйте кнопку «Открыть оригинал»."
        ),
    }


def _extract_structured_article(soup, fallback_title):
    """Читает Schema.org/JSON-LD, если сайт хранит текст новости там."""
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue

        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        for item in _walk_json_objects(payload):
            headline = str(
                item.get("headline")
                or item.get("name")
                or ""
            ).strip()
            if (
                fallback_title
                and headline
                and not _titles_match(fallback_title, headline)
            ):
                continue

            body = item.get("articleBody")
            if isinstance(body, str):
                paragraphs = _structured_paragraphs(body)
                if paragraphs:
                    return {
                        "title": headline or fallback_title,
                        "paragraphs": paragraphs,
                    }

            description = item.get("description")
            if (
                headline
                and isinstance(description, str)
                and len(" ".join(description.split())) >= 80
            ):
                return {
                    "title": headline,
                    "paragraphs": _structured_paragraphs(description),
                }

    return None


def _walk_json_objects(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json_objects(nested)


def _structured_paragraphs(value):
    text = BeautifulSoup(str(value), "html.parser").get_text("\n")
    result = []
    seen = set()

    for part in re.split(r"[\r\n]+", text):
        cleaned = " ".join(part.split())
        normalized = _title_key(cleaned)
        if len(cleaned) >= 45 and normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)

    if not result:
        cleaned = " ".join(text.split())
        if len(cleaned) >= 45:
            result.append(cleaned)

    return result


def _titles_match(expected, actual):
    expected_key = _title_key(expected)
    actual_key = _title_key(actual)
    return (
        len(expected_key) >= 12
        and (
            expected_key in actual_key
            or actual_key in expected_key
        )
    )


def _title_key(value):
    return " ".join(
        re.findall(
            r"[a-zа-я0-9]+",
            str(value or "").casefold().replace("ё", "е"),
            flags=re.IGNORECASE,
        )
    )


def _verified_paragraphs(container, title):
    result = []
    seen = set()
    title_key = _title_key(title)

    def add_node(node):
        text = " ".join(node.get_text(" ", strip=True).split())
        if title and text.startswith(title):
            text = text[len(title):].lstrip(" —:|")
        folded = text.casefold()
        normalized = _title_key(text)

        if len(text) < 45:
            return
        if title_key and normalized == title_key:
            return
        if any(part in folded for part in SKIP_PARTS):
            return
        if any(part in folded for part in ARTICLE_MENU_PARTS):
            return
        if normalized not in seen:
            seen.add(normalized)
            result.append(text)

    for node in container.select("p, li, blockquote"):
        add_node(node)

    if not result:
        for node in container.select("div, section"):
            direct_blocks = node.find_all(
                ["div", "section", "p", "li", "blockquote"],
                recursive=False,
            )
            if any(
                len(" ".join(child.get_text(" ", strip=True).split())) >= 45
                for child in direct_blocks
            ):
                continue
            add_node(node)

    return result


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
