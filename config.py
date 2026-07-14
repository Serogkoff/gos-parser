import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

KEYWORDS = [
    "Курил", "Сахалин", "Владивосток", "Хабаровск", "Камчатка", "Дальний Восток",
    "Арктика", "Калининград", "Крым", "Севастополь",
    "Япония", "Китай", "Индия", "Турция", "Иран", "Бразилия", "ЮАР",
    "КНДР", "Белорусси", "Казахстан", "Вьетнам",
    "БРИКС", "ШОС", "санкци", "нефть", "газ", "СПГ", "импортозамещение",
]

HTML_SOURCES = [
    {"name": "Правительство РФ", "url": "http://government.ru/news/"},
    {"name": "Трутнев", "url": "http://government.ru/gov/persons/21/events/"},
    {"name": "Минпромторг", "url": "https://minpromtorg.gov.ru/press-centre/news/"},
    {"name": "Минприроды", "url": "https://www.mnr.gov.ru/press/news/"},
    {"name": "МВД РФ", "url": "https://мвд.рф/news"},
    {"name": "МЧС", "url": "https://mchs.gov.ru/deyatelnost/press-centr/novosti"},
    {"name": "Минкульт", "url": "https://culture.gov.ru/press/news/"},
    {"name": "Минздрав", "url": "https://minzdrav.gov.ru/news"},
    {"name": "Минтранс", "url": "https://mintrans.gov.ru/press-center/news"},
    {"name": "Минэкономразвития", "url": "https://www.economy.gov.ru/material/news/"},
    {"name": "Минфин", "url": "https://minfin.gov.ru/ru/press-center/"},
    {"name": "Минстрой", "url": "https://www.minstroyrf.gov.ru/press/"},
    {"name": "Минвостокразвития", "url": "https://minvr.gov.ru/press-center/news/"},
    {"name": "Минюст", "url": "https://minjust.gov.ru/ru/events/list/"},
    {"name": "СК РФ", "url": "https://sledcom.ru/news/"},
    {"name": "Развитие Курил", "url": "http://government.ru/rugovclassifier/726/events/"},
]

PROBLEM_SOURCES = [
    {"name": "Минспорт", "url": "https://minsport.gov.ru/press-center/"},
    {"name": "Минтруд", "url": "https://mintrud.gov.ru/news/news/list"},
    {"name": "Минпросвещения", "url": "https://edu.gov.ru/press/news/"},
    {"name": "Минсельхоз", "url": "https://mcx.gov.ru/press-service/news/"},
    {"name": "Минобрнауки", "url": "https://www.minobrnauki.gov.ru/press-center/news/novosti-ministerstva/"},
    {"name": "Администрация Владивостока", "url": "https://www.vlc.ru/event/news/"},
]

JS_SOURCES = [
    {"name": "Минэнерго", "url": "https://minenergo.gov.ru/press-center/news-and-events"},
    {"name": "Минцифры", "url": "https://digital.gov.ru/news-feed"},
    {"name": "Сахалинская область", "url": "https://sakhalin.gov.ru/news"},
]

PAUSE_BETWEEN_REQUESTS = 2
NEWS_PER_SOURCE = 20
PAGES_PER_SOURCE = 3  # Сколько страниц назад смотреть
UPDATE_INTERVAL = 300  # 5 минут в секундах