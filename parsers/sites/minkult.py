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
    r"^(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+"
    r"(\d{4})",
    re.IGNORECASE,
)

DATE_TIME_PREFIX_PATTERN = re.compile(
    r"^\d{1,2}\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+"
    r"\d{4}\s*/\s*\d{1,2}:\d{2}",
    re.IGNORECASE,
)


def parse():
    news = []
    seen = set()
    cutoff = datetime.now() - timedelta(days=30)

    for page in range(1, 4):
        if page == 1:
            url = "https://culture.gov.ru/press/news/"
        else:
            url = (
                "https://culture.gov.ru/press/news/"
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

            for link_tag in soup.find_all("a", href=True):
                raw_text = link_tag.get_text(
                    " ",
                    strip=True,
                )

                if len(raw_text) < 30 or is_junk(raw_text):
                    continue

                date_str = ""
                title = raw_text

                match = DATE_PATTERN.match(raw_text)

                if match:
                    day, month_name, year = match.groups()

                    news_date = datetime(
                        year=int(year),
                        month=MONTHS[month_name.lower()],
                        day=int(day),
                    )

                    if news_date < cutoff:
                        continue

                    date_str = news_date.strftime("%Y-%m-%d")

                    title = DATE_TIME_PREFIX_PATTERN.sub(
                        "",
                        raw_text,
                    ).strip()

                # Повторная проверка уже очищенного заголовка
                if (
                    len(title) < 20
                    or title in seen
                    or is_junk(title)
                ):
                    continue

                href = link_tag.get("href", "")

                # Желательно оставить только ссылки на новости
                if "/press/news/" not in href:
                    continue

                seen.add(title)

                news.append({
                    "source": "Минкульт",
                    "title": title,
                    "url": urljoin(url, href),
                    "date": date_str,
                })

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