import re
from datetime import datetime


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

    match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text)
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
        year = int(match.group(3)) if match.group(3) else now.year
        parsed = _safe_date(year, month, day)
        if parsed and datetime.strptime(parsed, "%Y-%m-%d") > now:
            parsed = _safe_date(year - 1, month, day)
        return parsed

    return ""


def date_from_element(element):
    """Ищет дату в time/date-элементах и затем в тексте карточки."""
    if element is None:
        return ""

    for tag in element.select(
        'time, [class*="date"], [class*="time"], [class*="data"]'
    ):
        value = tag.get("datetime") or tag.get_text(" ", strip=True)
        parsed = parse_date(value)
        if parsed:
            return parsed

    return parse_date(element.get_text(" ", strip=True))


def date_from_ancestors(element, max_levels=8):
    """Поднимается от ссылки вверх, пока не найдёт дату карточки."""
    current = element
    for _ in range(max_levels):
        current = getattr(current, "parent", None)
        if current is None:
            break
        parsed = date_from_element(current)
        if parsed:
            return parsed
    return ""


def _safe_date(year, month, day):
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""
