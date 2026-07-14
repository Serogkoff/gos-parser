"""
ПОИСК КЛЮЧЕВЫХ СЛОВ
"""

from config import KEYWORDS


def search_keywords(news_list):
    """Ищет ключевые слова в заголовках новостей"""
    found = []
    for item in news_list:
        text = item['title'].lower()
        matched = [kw for kw in KEYWORDS if kw.lower() in text]
        if matched:
            item['keywords'] = matched
            found.append(item)
    return found