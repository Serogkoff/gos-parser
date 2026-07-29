from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit

from utils.filters import is_junk
from utils.http_client import fetch_soup
from utils.parser_links import find_article_url

SOURCE_NAME = "Минтранс"

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

ARTICLE_PATH = re.compile(
    r"^/press-center/news/\d+/?$",
    re.IGNORECASE,
)


def _is_article_url(url):
    parts = urlsplit(url)
    hostname = (parts.hostname or "").casefold()
    return (
        (
            hostname == "mintrans.gov.ru"
            or hostname.endswith(".mintrans.gov.ru")
        )
        and ARTICLE_PATH.fullmatch(parts.path) is not None
    )


def parse():
    news = []
    seen = set()

    cutoff = datetime.now() - timedelta(days=30)

    for page in range(2):
        if page == 0:
            url = "https://mintrans.gov.ru/press-center/news"
        else:
            url = (
                "https://mintrans.gov.ru/press-center/news"
                f"?page={page + 1}"
            )

        soup = fetch_soup(url, SOURCE_NAME)
        if soup is None:
            continue

        for item in soup.select(".news-inf"):
            title_tag = item.select_one(".news-text")
            date_tag = item.select_one(".date-span")

            if not title_tag:
                continue

            title = title_tag.get_text(
                " ",
                strip=True,
            )

            if (
                len(title) < 20
                or title in seen
                or is_junk(title)
            ):
                continue

            article_url = find_article_url(item, url, _is_article_url)
            if not article_url:
                continue

            date_str = ""

            if date_tag:
                try:
                    raw_date = date_tag.get_text(
                        " ",
                        strip=True,
                    ).lower()

                    parts = raw_date.replace(
                        ",",
                        "",
                    ).split()

                    day = int(parts[0])
                    month_name = parts[1]
                    year = int(parts[2])

                    month = MONTHS[month_name]

                    news_date = datetime(
                        year=year,
                        month=month,
                        day=day,
                    )

                    date_str = news_date.strftime(
                        "%Y-%m-%d"
                    )

                    if news_date < cutoff:
                        continue

                except (
                    ValueError,
                    KeyError,
                    IndexError,
                ) as error:
                    print(
                        f"  ⚠ Не удалось разобрать дату "
                        f"'{raw_date}': {error}"
                    )

            seen.add(title)

            news.append({
                "source": SOURCE_NAME,
                "title": title,
                "url": article_url,
                "date": date_str,
            })

    print(f"  ✅ {len(news)}")
    return news
