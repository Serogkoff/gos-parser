from urllib.parse import urljoin
from datetime import datetime, timedelta

from utils.filters import is_junk
from utils.http_client import fetch_soup

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

            link_tag = (
                title_tag
                if title_tag.name == "a"
                else title_tag.find("a")
            )

            href = (
                link_tag.get("href", "")
                if link_tag
                else ""
            )

            seen.add(title)

            news.append({
                "source": SOURCE_NAME,
                "title": title,
                "url": urljoin(url, href),
                "date": date_str,
            })

    print(f"  ✅ {len(news)}")
    return news
