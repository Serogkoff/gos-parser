import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMETERS = {"fbclid", "gclid", "yclid"}

MINOBRNAUKI_ARTICLE_PATH = re.compile(
    r"^/press-center/news/[^/]+/\d+$",
    re.IGNORECASE,
)

MNR_ARTICLE_PATH = re.compile(
    r"^/press/news/[^/]+$",
    re.IGNORECASE,
)


def normalize_url(url):
    """Нормализует URL, чтобы одинаковые новости не сохранялись дважды."""
    if not isinstance(url, str):
        return ""

    url = url.strip()
    if not url:
        return ""

    parts = urlsplit(url)

    if parts.netloc.lower() == "sledcom.ru" and "/news/item/" in parts.path:
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                "",
                "",
            )
        )

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_PARAMETERS
    ]

    path = parts.path.rstrip("/") or "/"
    hostname = (parts.hostname or "").casefold()

    if (
        (
            hostname == "minobrnauki.gov.ru"
            or hostname.endswith(".minobrnauki.gov.ru")
        )
        and MINOBRNAUKI_ARTICLE_PATH.fullmatch(path)
    ):
        # Без завершающего слеша открывается общий список новостей.
        path += "/"

    elif (
        (
            hostname == "mnr.gov.ru"
            or hostname.endswith(".mnr.gov.ru")
        )
        and MNR_ARTICLE_PATH.fullmatch(path)
    ):
        # Минприроды также требует завершающий слеш.
        path += "/"

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(query),
            "",
        )
    )


def deduplicate_news(items):
    """Оставляет одну запись на URL, сохраняя исходный порядок."""
    result = []
    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        if not is_valid_news_item(item):
            continue

        normalized = normalize_url(item.get("url", ""))

        key = normalized or (
            item.get("source", "").strip().lower(),
            item.get("title", "").strip().lower(),
        )

        if key in seen:
            continue

        seen.add(key)

        copy = dict(item)
        if normalized:
            copy["url"] = normalized

        result.append(copy)

    return result


def is_valid_news_item(item):
    """Удаляет известные служебные ссылки из уже накопленной базы."""
    source = item.get("source", "")
    url = normalize_url(item.get("url", ""))

    if source == "Минэкономразвития":
        return "/material/news/" in url and url.endswith(".html")

    if source == "СК РФ":
        return "/news/item/" in url or "/news/detail/" in url

    return True


def merge_news(existing, incoming):
    """Обновляет старые записи новыми полями, не создавая повторов."""
    result = deduplicate_news(existing)

    positions = {
        normalize_url(item.get("url", "")): index
        for index, item in enumerate(result)
        if item.get("url")
    }

    for item in deduplicate_news(incoming):
        key = normalize_url(item.get("url", ""))

        if key and key in positions:
            current = result[positions[key]]

            for field, value in item.items():
                if value and (
                    field != "parsed_date"
                    or not current.get(field)
                ):
                    current[field] = value
        else:
            if key:
                positions[key] = len(result)

            result.append(item)

    return result


def sort_news_by_publication(items):
    """
    Сначала показывает материалы с датой публикации — от новых к старым.
    Записи без неё помещает ниже и сортирует по дате получения парсером.
    """
    return sorted(
        items,
        key=_publication_sort_key,
        reverse=True,
    )


def _publication_sort_key(item):
    publication_date = str(item.get("date", "")).strip()
    parsed_date = str(item.get("parsed_date", "")).strip()

    if publication_date:
        return 1, publication_date, parsed_date

    return 0, parsed_date, ""