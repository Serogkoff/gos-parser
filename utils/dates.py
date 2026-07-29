import re
from datetime import datetime, timedelta


MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def parse_date(value, now=None):
    """Возвращает дату в формате YYYY-MM-DD из распространённых форматов."""
    if not value:
        return ""

    now = now or datetime.now()
    text = " ".join(str(value).lower().replace("\xa0", " ").split())

    match = re.search(
        r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)",
        text,
    )
    if match:
        year, month, day = map(int, match.groups())
        return _safe_date(year, month, day)

    match = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", text)
    if match:
        day, month, year = map(int, match.groups())
        return _safe_date(year, month, day)

    months_pattern = "|".join(MONTHS)
    match = re.search(
        rf"\b(\d{{1,2}})\s+({months_pattern})(?:\s+(20\d{{2}}))?\b",
        text,
    )
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2)]
        explicit_year = match.group(3)
        year = int(explicit_year) if explicit_year else now.year
        parsed = _safe_date(year, month, day)
        if (
            not explicit_year
            and parsed
            and datetime.strptime(parsed, "%Y-%m-%d") > now
        ):
            parsed = _safe_date(year - 1, month, day)
        return parsed

    return ""


def date_from_element(element):
    """Ищет дату в time/date-элементах и затем в тексте карточки."""
    return _date_from_element(element, strict=False)


def strict_date_from_element(element, now=None):
    """Ищет только явно размеченную дату публикации."""
    return _date_from_element(element, strict=True, now=now)


def _date_from_element(element, strict=False, now=None):
    if element is None:
        return ""

    candidates = _date_candidates(element, now=now)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return ""

    if strict:
        return ""

    return validate_publication_date(
        element.get_text(" ", strip=True),
        now=now,
    )


def date_from_ancestors(element, max_levels=8, strict=False, now=None):
    """Поднимается от ссылки вверх, пока не найдёт дату карточки."""
    current = element
    for _ in range(max_levels):
        current = getattr(current, "parent", None)
        if current is None:
            break
        parsed = _date_from_element(
            current,
            strict=strict,
            now=now,
        )
        if parsed:
            return parsed
    return ""


def date_from_news_card(
    element,
    article_url_pattern,
    max_levels=8,
    now=None,
):
    """
    Ищет дату только внутри карточки одной новости.

    Поиск прекращается, как только родитель начинает содержать ссылки
    на несколько разных публикаций. Так дата соседней карточки или общий
    день в заголовке ленты не назначаются всем материалам страницы.
    """
    current = element
    article_pattern = re.compile(article_url_pattern, re.IGNORECASE)

    for _ in range(max_levels):
        current = getattr(current, "parent", None)
        if current is None:
            break

        article_urls = {
            str(link.get("href", "")).split("?", 1)[0].rstrip("/")
            for link in current.select("a[href]")
            if article_pattern.search(str(link.get("href", "")))
        }
        if len(article_urls) > 1:
            break

        candidates = _date_candidates(
            current,
            now=now,
            excluded=element,
        )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            return ""

    return ""


def date_from_document(document, now=None, prefer_visible=False):
    """Читает дату публикации из метаданных или рядом с заголовком статьи."""
    if document is None:
        return ""

    heading = document.select_one("h1, [itemprop='headline']")
    if prefer_visible and heading is not None:
        visible_date = _date_near_heading(heading, now=now)
        if visible_date:
            return visible_date

    meta = document.select_one(
        'meta[property="article:published_time"], '
        'meta[name="date"], '
        'meta[itemprop="datePublished"], '
        '[itemprop="datePublished"][content]'
    )
    if meta:
        parsed = validate_publication_date(
            meta.get("content") or meta.get("datetime") or "",
            now=now,
        )
        if parsed:
            return parsed

    if heading is None:
        return ""

    return _date_near_heading(heading, now=now)


def _date_near_heading(heading, now=None):
    """Ищет видимую дату в блоке конкретного заголовка публикации."""
    current = heading
    for _ in range(4):
        current = getattr(current, "parent", None)
        if current is None or getattr(current, "name", "") in {"body", "html"}:
            break

        candidates = _date_candidates(
            current,
            now=now,
            excluded=heading,
        )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            break

    for node in heading.find_all_next(
        ["time", "span", "div"],
        limit=20,
    ):
        value = (
            node.get("datetime")
            or node.get("content")
            or " ".join(node.get_text(" ", strip=True).split())
        )
        classes = " ".join(node.get("class", [])).casefold()
        if (
            not _looks_like_date_only(value)
            and not any(part in classes for part in ("date", "time", "data"))
        ):
            continue
        parsed = validate_publication_date(value, now=now)
        if parsed:
            return parsed

    return ""


def validate_publication_date(value, now=None, max_future_days=1):
    """
    Нормализует дату и отбрасывает явно будущие публикации.

    Один день запаса оставлен из-за разницы часовых поясов источников.
    """
    now = now or datetime.now()
    parsed = parse_date(value, now=now)
    if not parsed:
        return ""

    parsed_date = datetime.strptime(parsed, "%Y-%m-%d")
    if parsed_date.date() > (now + timedelta(days=max_future_days)).date():
        return ""
    return parsed


def _date_candidates(element, now=None, excluded=None):
    values = []
    seen = set()
    selectors = (
        'meta[property="article:published_time"], '
        'meta[name="date"], '
        'meta[itemprop="datePublished"], '
        '[itemprop="datePublished"], '
        'time, '
        '[class*="date"], '
        '[class*="time"], '
        '[class*="data"]'
    )

    for tag in element.select(selectors):
        if _inside(tag, excluded):
            continue
        value = (
            tag.get("content")
            or tag.get("datetime")
            or tag.get_text(" ", strip=True)
        )
        parsed = validate_publication_date(value, now=now)
        if parsed and parsed not in seen:
            seen.add(parsed)
            values.append(parsed)

    # Некоторые карточки не имеют класса date, но помещают дату
    # в отдельный короткий span. Текст заголовка целиком здесь не читается.
    for tag in element.select("span, small"):
        if _inside(tag, excluded):
            continue
        value = " ".join(tag.get_text(" ", strip=True).split())
        if not _looks_like_date_only(value):
            continue
        parsed = validate_publication_date(value, now=now)
        if parsed and parsed not in seen:
            seen.add(parsed)
            values.append(parsed)

    return values


def _inside(tag, ancestor):
    if ancestor is None:
        return False
    current = tag
    while current is not None:
        if current is ancestor:
            return True
        current = getattr(current, "parent", None)
    return False


def _looks_like_date_only(value):
    text = str(value or "").strip().casefold()
    months_pattern = "|".join(MONTHS)
    return bool(
        re.fullmatch(
            rf"\d{{1,2}}\s+({months_pattern})(?:\s+20\d{{2}})?"
            rf"(?:\s*,?\s*\d{{1,2}}:\d{{2}})?",
            text,
        )
        or re.fullmatch(
            r"\d{1,2}[./]\d{1,2}[./]20\d{2}(?:\s+\d{1,2}:\d{2})?",
            text,
        )
        or re.fullmatch(
            r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:[t\s]\d{1,2}:\d{2}.*)?",
            text,
        )
    )


def _safe_date(year, month, day):
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""
