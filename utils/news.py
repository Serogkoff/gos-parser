import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utils.dates import validate_publication_date


TRACKING_PARAMETERS = {"fbclid", "gclid", "yclid"}
TITLE_DEDUP_SOURCES = {
    "мчс",
    "минэнерго",
    "минэкономразвития",
    "минюст",
    "минсельхоз",
    "минстрой",
    "минвостокразвития",
    "минтранс",
}

MINOBRNAUKI_ARTICLE_PATH = re.compile(
    r"^/press-center/news/[^/]+/\d+$",
    re.IGNORECASE,
)

MNR_ARTICLE_PATH = re.compile(
    r"^/press/news/[^/]+$",
    re.IGNORECASE,
)

TRAILING_SLASH_ARTICLE_RULES = (
    (
        "mcx.gov.ru",
        re.compile(r"^/press-service/news/[^/]+$", re.IGNORECASE),
    ),
    (
        "minstroyrf.gov.ru",
        re.compile(r"^/press/[^/]+$", re.IGNORECASE),
    ),
    (
        "minvr.gov.ru",
        re.compile(r"^/press-center/news/[^/]+$", re.IGNORECASE),
    ),
)

SOURCE_ARTICLE_RULES = {
    "Минсельхоз": (
        "mcx.gov.ru",
        re.compile(r"^/press-service/news/[^/]+/?$", re.IGNORECASE),
    ),
    "Минстрой": (
        "minstroyrf.gov.ru",
        re.compile(r"^/press/[^/]+/?$", re.IGNORECASE),
    ),
    "Минвостокразвития": (
        "minvr.gov.ru",
        re.compile(r"^/press-center/news/[^/]+/?$", re.IGNORECASE),
    ),
    "Минтранс": (
        "mintrans.gov.ru",
        re.compile(r"^/press-center/news/\d+/?$", re.IGNORECASE),
    ),
}


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

    else:
        for required_host, article_path in TRAILING_SLASH_ARTICLE_RULES:
            if (
                (
                    hostname == required_host
                    or hostname.endswith(f".{required_host}")
                )
                and article_path.fullmatch(path)
            ):
                path += "/"
                break

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

        keys = _identity_keys(item)
        if any(key in seen for key in keys):
            continue

        seen.update(keys)

        copy = dict(item)
        normalized = normalize_url(item.get("url", ""))
        if normalized:
            copy["url"] = normalized
        if copy.get("date"):
            copy["date"] = validate_publication_date(copy["date"])

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

    if source in SOURCE_ARTICLE_RULES:
        required_host, article_path = SOURCE_ARTICLE_RULES[source]
        parts = urlsplit(url)
        hostname = (parts.hostname or "").casefold()
        return (
            (
                hostname == required_host
                or hostname.endswith(f".{required_host}")
            )
            and article_path.fullmatch(parts.path) is not None
        )

    return True


def merge_news(existing, incoming):
    """Обновляет старые записи новыми полями, не создавая повторов."""
    result = deduplicate_news(existing)

    positions = {}
    for index, item in enumerate(result):
        for key in _identity_keys(item):
            positions.setdefault(key, index)

    for item in deduplicate_news(incoming):
        keys = _identity_keys(item)
        existing_index = next(
            (positions[key] for key in keys if key in positions),
            None,
        )

        if existing_index is not None:
            current = result[existing_index]

            for field, value in item.items():
                if value and (
                    field != "parsed_date"
                    or not current.get(field)
                ):
                    current[field] = value

            for key in _identity_keys(current):
                positions[key] = existing_index
        else:
            new_index = len(result)
            result.append(item)
            for key in keys:
                positions[key] = new_index

    return result


def _identity_keys(item):
    """Возвращает все безопасные признаки одной и той же публикации."""
    source = str(item.get("source", "")).strip().casefold()
    title = _normalize_title(item.get("title", ""))
    normalized_url = normalize_url(item.get("url", ""))
    keys = []

    if normalized_url:
        keys.append(("url", normalized_url))

    if source in TITLE_DEDUP_SOURCES and title:
        keys.append(("source-title", source, title))

    if not keys:
        keys.append(("source-title", source, title))

    return keys


def _normalize_title(title):
    value = str(title or "").casefold().replace("ё", "е")
    return " ".join(re.findall(r"[a-zа-я0-9]+", value, flags=re.IGNORECASE))


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
