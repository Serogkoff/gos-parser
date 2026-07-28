from utils.filters import is_junk
"""
ПАРСЕР МИД РФ
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

def parse():
    url = "https://www.mid.ru/ru/rss"
    news = []

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)

        if response.status_code != 200:
            print(f"  ⚠ Статус: {response.status_code}")
            return news

        # BeautifulSoup вместо xml.etree — терпимее к битому XML
        soup = BeautifulSoup(response.content, 'xml')
        entries = soup.find_all('entry')

        for entry in entries[:60]:
            title = entry.find('title')
            link = entry.find('link')

            title_text = title.text.strip() if title and title.text else ''
            link_text = link.get('href', '') if link else ''

            if title_text:
                news.append({
                    'source': 'МИД РФ',
                    'title': title_text,
                    'url': link_text,
                })

        print(f"  ✅ {len(news)}")

    except Exception as e:
        print(f"  ❌ {str(e)[:60]}")

    return news

