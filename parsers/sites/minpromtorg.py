import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from utils.filters import is_junk
from datetime import datetime, timedelta

urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse():
    news, seen = [], set()
    cutoff = datetime.now() - timedelta(days=30)

    for p in range(2):
        u = f"https://minpromtorg.gov.ru/press-centre/news/?PAGEN_1={p + 1}" if p else "https://minpromtorg.gov.ru/press-centre/news/"
        try:
            r = requests.get(u, headers=HEADERS, timeout=30, verify=False)
            s = BeautifulSoup(r.text, 'html.parser')

            for announce in s.select('.announce'):
                title_tag = announce.select_one('.announce__title')
                link_tag = announce.select_one('a')
                date_tag = announce.select_one('.announce__date')

                if not title_tag:
                    continue

                t = title_tag.get_text(strip=True)
                if len(t) < 20 or t in seen or is_junk(t):
                    continue

                date_str = ""
                if date_tag:
                    try:
                        date_str = datetime.strptime(date_tag.get_text(strip=True), '%d.%m.%Y').strftime('%Y-%m-%d')
                        news_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if news_date < cutoff:
                            continue
                    except:
                        pass

                seen.add(t)
                news.append({
                    'source': 'Минпромторг',
                    'title': t,
                    'url': urljoin(u, link_tag.get('href', '')),
                    'date': date_str
                })
        except:
            pass

    print(f"  ✅ {len(news)}")
    return news