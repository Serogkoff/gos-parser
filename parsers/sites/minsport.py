import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

from utils.filters import is_junk


urllib3.disable_warnings()

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

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

DATE_PATTERN = re.compile(
    r"(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+"
    r"(\d{4})",
    re.IGNORECASE,
)


def parse_date(raw_date):
    """Преобразует русскую дату в YYYY-MM-DD."""

    if not raw_date:
        return ""

    match = DATE_PATTERN.search(raw_date.lower())

    if not match:
        return ""

    day, month_name, year = match.groups()

    try:
        news_date = datetime(
            year=int(year),
            month=MONTHS[month_name.lower()],
            day=int(day),
        )

        return news_date.strftime("%Y-%m-%d")

    except (ValueError, KeyError):
        return ""


def parse():
    news = []
    seen = set()

    cutoff = datetime.now() - timedelta(days=30)

    for page in range(1, 4):
        if page == 1:
            url = "https://minsport.gov.ru/press-center/"
        else:
            url = (
                "https://minsport.gov.ru/press-center/"
                f"?PAGEN_1={page}"
            )

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30,
                verify=False,
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            page_count = 0

            for link_tag in soup.find_all("a", href=True):
                href = link_tag.get("href", "").strip()

                # Берём только ссылки на отдельные новости
                if "/press-center/news/" not in href:
                    continue

                title = link_tag.get_text(
                    " ",
                    strip=True,
                )

                if (
                    len(title) < 20
                    or title in seen
                    or is_junk(title)
                ):
                    continue

                # Ищем общий родительский блок карточки
                card = link_tag.find_parent(
                    ["article", "li", "div"]
                )

                raw_date = ""
                date_str = ""

                if card:
                    # Сначала пробуем отдельный тег даты
                    date_tag = card.select_one(
                        "time, "
                        ".date, "
                        "[class*='date'], "
                        "[class*='time']"
                    )

                    if date_tag:
                        datetime_value = date_tag.get(
                            "datetime",
                            "",
                        )

                        if datetime_value:
                            date_str = datetime_value[:10]

                        raw_date = date_tag.get_text(
                            " ",
                            strip=True,
                        )

                    # Если отдельный тег не найден,
                    # ищем дату во всём тексте карточки
                    if not date_str:
                        card_text = card.get_text(
                            " ",
                            strip=True,
                        )

                        date_str = parse_date(card_text)

                if date_str:
                    try:
                        news_date = datetime.strptime(
                            date_str,
                            "%Y-%m-%d",
                        )

                        if news_date < cutoff:
                            continue

                    except ValueError:
                        date_str = ""

                seen.add(title)
                page_count += 1

                news.append({
                    "source": "Минспорт",
                    "title": title,
                    "url": urljoin(url, href),
                    "date": date_str,
                })

            print(
                f"  Страница {page}: "
                f"{page_count} новостей"
            )

        except requests.RequestException as error:
            print(
                f"  ⚠ Страница {page}: "
                f"{type(error).__name__}: {error}"
            )

        except Exception as error:
            print(
                f"  ⚠ Ошибка разбора страницы {page}: "
                f"{type(error).__name__}: {error}"
            )

    print(f"  ✅ {len(news)}")
    return news