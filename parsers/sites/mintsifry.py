from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Служебные слова, которые НЕ являются новостями
SKIP_WORDS = [
    "office@", "статистика", "использование материалов", "сообщить об ошибке",
    "контакты", "пресс-служба", "подписаться", "рассылка","аккредитация", "телефон",
    "факс", "email","реестр", "адрес", "карта сайта", "поиск", "вход", "регистрация",
    "личный кабинет", "чат-бот", "версия для слабовидящих", "старая версия",
    "об организации", "противодействие коррупции", "вакансии", "открытое министерство",
]


def parse():
    news, seen = [], set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for pg in range(3):
                u = f"https://digital.gov.ru/news-feed?page={pg + 1}" if pg else "https://digital.gov.ru/news-feed"
                try:
                    page.goto(u, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    s = BeautifulSoup(page.content(), 'html.parser')
                    for a in s.find_all('a'):
                        t = a.get_text(strip=True)
                        if len(t) < 20 or t in seen: continue

                        # Пропускаем служебные ссылки
                        if any(w in t.lower() for w in SKIP_WORDS):
                            continue
                        # Пропускаем email и телефоны
                        if '@' in t or t.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                            continue

                        seen.add(t)
                        news.append({'source': 'Минцифры', 'title': t, 'url': urljoin(u, a.get('href', ''))})
                except:
                    pass
            browser.close()
    except:
        pass
    print(f"  ✅ {len(news)}")
    return news