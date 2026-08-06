import json
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

from utils.dates import (
    date_from_ancestors,
    date_from_document,
    date_from_news_card,
    validate_publication_date,
)
from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.js_client import fetch_soup_js
from utils.news import normalize_url
from utils.storage import (
    PROJECT_DIR,
    _load_json,
    _write_json_atomic,
)

SOURCE_NAME = "СК РФ"
# v1 мог сохранить дату соседней карточки, если вместо статьи сайт СК
# возвращал общую страницу «Новости». Новый файл намеренно не подхватывает
# такие уже накопленные значения.
DATE_CACHE_FILE = PROJECT_DIR / "sk_dates_v2.json"
DETAIL_REQUEST_PAUSE = 0.5


def parse():
    news, seen = [], set()
    date_cache = _load_date_cache()
    cache_changed = False

    # Первая страница содержит текущую десятку публикаций.
    # Дополнительные страницы раньше создавали лишнюю нагрузку на сайт.
    for p in range(1):
        u = f"https://sledcom.ru/news/?PAGEN_1={p + 1}" if p else "https://sledcom.ru/news/"

        soup = fetch_soup(u, SOURCE_NAME)
        if soup is None:
            continue

        for a in soup.select('a[href*="/news/item/"], a[href*="/news/detail/"]'):
            t = a.get_text(strip=True)
            href = a.get('href', '')
            full_url = normalize_url(
                urljoin(u, href).split('?', 1)[0]
            )
            if len(t) < 20 or full_url in seen or is_junk(t):
                continue
            seen.add(full_url)
            card_date = date_from_news_card(
                a,
                r"/news/(?:item|detail)/",
            )
            cached_date = date_cache.get(full_url, "")
            date_str = cached_date
            # Даты свежих материалов СК перепроверяем: сайт иногда вместо
            # статьи отдаёт общую страницу новостей, и раньше случайная дата
            # из неё навсегда попадала в кэш.
            if not cached_date or _should_recheck_date(cached_date):
                detail = fetch_soup(
                    full_url,
                    SOURCE_NAME,
                    timeout=15,
                    attempts=1,
                )
                detail_date = _confirmed_date_from_sk_article(
                    detail,
                    expected_title=t,
                )
                if not detail_date:
                    browser_detail = fetch_soup_js(
                        full_url,
                        f"{SOURCE_NAME} — дата статьи",
                        wait_ms=1200,
                        timeout_ms=30000,
                        wait_until="domcontentloaded",
                        use_partial_on_timeout=True,
                    )
                    detail_date = _confirmed_date_from_sk_article(
                        browser_detail,
                        expected_title=t,
                    )
                if detail_date:
                    date_str = detail_date
                    if date_cache.get(full_url) != detail_date:
                        date_cache[full_url] = detail_date
                        cache_changed = True
                elif not cached_date:
                    date_str = card_date
                time.sleep(DETAIL_REQUEST_PAUSE)

            news.append({
                'source': SOURCE_NAME,
                'title': t,
                'url': full_url,
                'date': date_str,
            })

    if cache_changed:
        _save_date_cache(date_cache)

    with_date = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {with_date})")
    return news


def _date_from_sk_article(
    soup,
    expected_title="",
    article_url="",
):
    """
    Читает дату, показанную непосредственно на странице публикации СК.

    Сайт СК иногда отвечает на URL статьи общей страницей «Новости».
    Поэтому дата принимается только после привязки к нужной карточке либо
    после подтверждения, что метаданные страницы относятся к нужной статье.
    """
    if soup is None:
        return ""

    card_date = _date_from_matching_card(
        soup,
        expected_title=expected_title,
        article_url=article_url,
    )
    if card_date:
        return card_date

    if expected_title and not _page_matches_title(soup, expected_title):
        return ""

    return date_from_document(
        soup,
        prefer_visible=True,
    )


def _confirmed_date_from_sk_article(soup, expected_title=""):
    """
    Возвращает дату только когда документ подтверждён как нужная статья.

    В отличие от ``_date_from_sk_article`` эта функция намеренно не читает
    дату карточки с общей страницы «Новости»: именно это было причиной
    сохранения соседней/устаревшей даты в кэш СК.
    """
    if soup is None or not expected_title:
        return ""

    json_date = _date_from_matching_json_ld(soup, expected_title)
    if json_date:
        return json_date

    if not _page_matches_title(soup, expected_title):
        return ""

    return date_from_document(
        soup,
        prefer_visible=True,
    )


def _date_from_matching_json_ld(soup, expected_title):
    """Ищет datePublished только у JSON-LD с заголовком нужной статьи."""
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            document = json.loads(raw)
        except (TypeError, ValueError):
            continue

        for node in _walk_json_ld(document):
            if not isinstance(node, dict):
                continue
            headline = node.get("headline") or node.get("name") or ""
            if not _titles_match(headline, expected_title):
                continue
            parsed = validate_publication_date(
                node.get("datePublished", ""),
            )
            if parsed:
                return parsed
    return ""


def _walk_json_ld(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def _should_recheck_date(date_str, days=2):
    """Свежий кэш СК считаем предварительным и быстро перепроверяем."""
    try:
        cached = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return True
    return cached >= (datetime.now().date() - timedelta(days=days))


def _date_from_matching_card(
    soup,
    expected_title="",
    article_url="",
):
    """Находит дату только рядом с нужной публикацией в общей ленте."""
    if article_url:
        normalized_target = normalize_url(article_url)
        for link in soup.select(
            'a[href*="/news/item/"], a[href*="/news/detail/"]'
        ):
            candidate_url = normalize_url(
                urljoin("https://sledcom.ru/", link.get("href", ""))
            )
            if candidate_url != normalized_target:
                continue
            parsed = date_from_news_card(
                link,
                r"/news/(?:item|detail)/",
            )
            if parsed:
                return parsed

    if expected_title:
        for node in soup.select(
            "a, h1, h2, h3, [class*='title'], [class*='headline']"
        ):
            if not _titles_match(
                node.get_text(" ", strip=True),
                expected_title,
            ):
                continue
            parsed = date_from_ancestors(
                node,
                max_levels=6,
                strict=True,
            )
            if parsed:
                return parsed

    return ""


def _page_matches_title(soup, expected_title):
    """Проверяет, что метаданные действительно принадлежат нужной статье."""
    title_candidates = []
    for selector, attribute in (
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
        ("title", None),
    ):
        node = soup.select_one(selector)
        if node is None:
            continue
        value = (
            node.get(attribute, "")
            if attribute
            else node.get_text(" ", strip=True)
        )
        if value:
            title_candidates.append(value)

    return any(
        _titles_match(candidate, expected_title)
        for candidate in title_candidates
    )


def _titles_match(left, right):
    left = " ".join(str(left or "").casefold().replace("ё", "е").split())
    right = " ".join(str(right or "").casefold().replace("ё", "е").split())
    if not left or not right:
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def _load_date_cache():
    cache = {}
    for item in _load_json(DATE_CACHE_FILE):
        if not isinstance(item, dict):
            continue
        url = normalize_url(item.get("url", ""))
        date_str = validate_publication_date(item.get("date", ""))
        if url and date_str:
            cache[url] = date_str
    return cache


def _save_date_cache(cache):
    document = [
        {
            "url": url,
            "date": date_str,
        }
        for url, date_str in sorted(cache.items())
        if url and date_str
    ]
    _write_json_atomic(DATE_CACHE_FILE, document)
