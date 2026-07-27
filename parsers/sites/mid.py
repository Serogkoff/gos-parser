from utils.http_client import fetch_soup
from utils.news import deduplicate_news

SOURCE_NAME = "МИД РФ"


def parse():
    url = "https://www.mid.ru/ru/rss"
    news = []

    # Встроенный parser не требует отдельной установки lxml.
    # Для поиска простых тегов entry/item его возможностей достаточно.
    soup = fetch_soup(url, SOURCE_NAME, parser="html.parser")
    if soup is None:
        return news

    entries = soup.find_all('entry') or soup.find_all('item')

    for entry in entries[:60]:
        title = entry.find('title')
        link = entry.find('link')
        published = entry.find('published') or entry.find('pubdate') or entry.find('updated')

        title_text = title.text.strip() if title and title.text else ''
        link_text = ""
        if link:
            link_text = link.get('href', '') or link.get_text(strip=True)
        date_text = published.get_text(strip=True) if published else ""

        if title_text and link_text:
            news.append({
                'source': SOURCE_NAME,
                'title': title_text,
                'url': link_text,
                'date': date_text[:10] if date_text[:4].isdigit() else "",
            })

    news = deduplicate_news(news)
    print(f"  ✅ {len(news)}")
    return news
