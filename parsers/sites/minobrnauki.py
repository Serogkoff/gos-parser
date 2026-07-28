import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin, urlsplit

from utils.filters import is_junk
from utils.http_client import fetch_soup


SOURCE_NAME = "Минобрнауки"
BASE_URL = "https://www.minobrnauki.gov.ru/press-center/news/"
MAX_PAGES = 6

ARTICLE_PATH = re.compile(
    r"^/press-center/news/[^/]+/\d+/?$",
    re.IGNORECASE,
)
DATE_DMY = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
DATE_TEXT = re.compile(
    r"\b(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)"
    r"(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)

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


def parse():
    news = []
    seen_urls = set()
    now = datetime.now()
    cutoff = now - timedelta(days=30)

    for page in range(1, MAX_PAGES + 1):
        query = urlencode({"PAGEN_1": page, "SIZEN_1": 20})
        page_url = f"{BASE_URL}?{query}"
        soup = fetch_soup(page_url, SOURCE_NAME)
        if soup is None:
            continue

        page_items = 0
        page_dates = []

        # Ищем не конкретный CSS-класс карточки, а реальные адреса статей.
        # Так изменение оформления списка не превращает URL в адрес раздела.
        for link in soup.select("a[href]"):
            article_url = _article_url(link.get("href", ""))
            if not article_url or article_url in seen_urls:
                continue

            title = _extract_title(link)
            if len(title) < 20 or is_junk(title):
                continue

            date_str = _extract_date(link, now)
            if date_str:
                try:
                    news_date = datetime.strptime(date_str, "%Y-%m-%d")
                    page_dates.append(news_date)
                    if news_date < cutoff:
                        continue
                except ValueError:
                    date_str = ""

            seen_urls.add(article_url)
            page_items += 1
            news.append(
                {
                    "source": SOURCE_NAME,
                    "title": title,
                    "url": article_url,
                    "date": date_str,
                }
            )

        # Если следующая страница не содержит статей, дальше идти незачем.
        if page > 1 and page_items == 0:
            break

        # Останавливаемся, когда вся распознанная страница уже старше 30 дней.
        if page_dates and max(page_dates) < cutoff:
            break

    news.sort(
        key=lambda item: (item.get("date", ""), item.get("url", "")),
        reverse=True,
    )
    with_date = sum(bool(item.get("date")) for item in news)
    print(f"  ✅ {len(news)} (с датой: {with_date})")
    return news


def _article_url(href):
    absolute = urljoin(BASE_URL, str(href).strip())
    parts = urlsplit(absolute)

    if parts.scheme not in {"http", "https"}:
        return ""
    if parts.hostname not in {
        "minobrnauki.gov.ru",
        "www.minobrnauki.gov.ru",
        "m.minobrnauki.gov.ru",
    }:
        return ""
    if not ARTICLE_PATH.fullmatch(parts.path):
        return ""

    return urljoin(BASE_URL, parts.path.rstrip("/") + "/")


def _extract_title(link):
    candidates = [
        link.get_text(" ", strip=True),
        link.get("title", ""),
        link.get("aria-label", ""),
    ]

    # Иногда кликабельна картинка или кнопка «Подробнее», а заголовок
    # находится рядом внутри той же карточки.
    container = link.find_parent(
        ["article", "li", "div"],
        class_=re.compile(r"(news|item|card)", re.IGNORECASE),
    )
    if container:
        for selector in (
            ".news-item-title",
            ".news-item__title",
            ".news__title",
            ".card__title",
            "h2",
            "h3",
        ):
            tag = container.select_one(selector)
            if tag:
                candidates.append(tag.get_text(" ", strip=True))

    for value in candidates:
        title = " ".join(str(value).split())
        if len(title) >= 20 and title.casefold() not in {
            "читать далее",
            "подробнее",
        }:
            return title
    return ""


def _extract_date(link, now):
    nodes = [link]
    parent = link.parent
    for _ in range(6):
        if parent is None or getattr(parent, "name", "") in {"main", "body", "html"}:
            break
        nodes.append(parent)
        parent = parent.parent

    for node in nodes:
        time_tag = node.select_one("time[datetime]") if hasattr(node, "select_one") else None
        if time_tag:
            value = time_tag.get("datetime", "").strip()[:10]
            try:
                return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                pass

        text = " ".join(node.get_text(" ", strip=True).split())

        match = DATE_DMY.search(text)
        if match:
            day, month, year = map(int, match.groups())
            return _safe_date(year, month, day)

        match = DATE_TEXT.search(text)
        if match:
            day = int(match.group(1))
            month = MONTHS[match.group(2).casefold()]
            year = int(match.group(3) or now.year)

            # В январе декабрьская публикация без указанного года относится
            # к предыдущему календарному году.
            if not match.group(3) and month > now.month + 1:
                year -= 1
            return _safe_date(year, month, day)

    return ""


def _safe_date(year, month, day):
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""