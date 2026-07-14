import time
from datetime import datetime

from utils.storage import save_results, load_existing_urls
from utils.keywords import search_keywords

from parsers.sites.mid import parse as mid
from parsers.sites.government import parse as gov
from parsers.sites.trutnev import parse as trutnev
from parsers.sites.minpromtorg import parse as prom
from parsers.sites.minprirody import parse as priroda
from parsers.sites.mvd import parse as mvd
from parsers.sites.mchs import parse as mchs
from parsers.sites.minkult import parse as kult
from parsers.sites.minzdrav import parse as zdrav
from parsers.sites.mintrans import parse as trans
from parsers.sites.mineconom import parse as econom
from parsers.sites.minfin import parse as fin
from parsers.sites.minstroy import parse as stroy
from parsers.sites.minvostok import parse as vostok
from parsers.sites.minyust import parse as yust
from parsers.sites.sk import parse as sk
from parsers.sites.kurily import parse as kurily
from parsers.sites.minsport import parse as sport
from parsers.sites.mintrud import parse as trud
from parsers.sites.minprosv import parse as prosv
from parsers.sites.minselkhoz import parse as selkhoz
from parsers.sites.minobrnauki import parse as obrnauki
from parsers.sites.vladivostok import parse as vlad
from parsers.sites.minenergo import parse as energo
from parsers.sites.mintsifry import parse as tsifry
from parsers.sites.sakhalin import parse as sakh


SITES = [
    ("МИД РФ", mid),
    ("Правительство РФ", gov),
    ("Трутнев", trutnev),
    ("Минпромторг", prom),
    ("Минприроды", priroda),
    ("МВД РФ", mvd),
    ("МЧС", mchs),
    ("Минкульт", kult),
    ("Минздрав", zdrav),
    ("Минтранс", trans),
    ("Минэкономразвития", econom),
    ("Минфин", fin),
    ("Минстрой", stroy),
    ("Минвостокразвития", vostok),
    ("Минюст", yust),
    ("СК РФ", sk),
    ("Развитие Курил", kurily),
    ("Минспорт", sport),
    ("Минтруд", trud),
    ("Минпросвещения", prosv),
    ("Минсельхоз", selkhoz),
    ("Минобрнауки", obrnauki),
    ("Владивосток", vlad),
    ("Минэнерго", energo),
    ("Минцифры", tsifry),
    ("Сахалин", sakh),
]


def safe_parse(parser_func, max_retries=2):
    for attempt in range(1, max_retries + 1):
        try:
            news = parser_func()
            if news is None:
                raise ValueError("Парсер вернул None")
            if not isinstance(news, list):
                raise TypeError(f"Парсер вернул {type(news).__name__}, ожидался list")
            return news
        except Exception as error:
            print(f"  ❌ попытка {attempt}/{max_retries}: {type(error).__name__}: {str(error)[:100]}")
            if attempt < max_retries:
                time.sleep(3)
    return []


def run_once():
    existing_urls = load_existing_urls()

    print("=" * 70)
    print(f"🚀 Парсер | {datetime.now():%Y-%m-%d %H:%M:%S} | В базе: {len(existing_urls)}")
    print("=" * 70)

    all_news = []
    found_news = []

    for name, parser_func in SITES:
        print(f"\n{name}:")
        news = safe_parse(parser_func, max_retries=2)
        all_news.extend(news)
        matches = search_keywords(news)
        print(f"  📰 Новостей: {len(news)}")
        if matches:
            found_news.extend(matches)
            print(f"  🎯 Совпадений: {len(matches)}")
        else:
            print("  Совпадений нет")
        time.sleep(2)

    new_found = save_results(all_news, found_news, existing_urls)

    print("\n" + "=" * 70)
    print(f"📊 Получено новостей: {len(all_news)}")
    print(f"🎯 Всего совпадений: {len(found_news)}")
    print(f"🔴 Новых совпадений: {len(new_found)}")

    if new_found:
        print("\n🔴 НОВЫЕ МАТЕРИАЛЫ:")
        for index, item in enumerate(new_found, start=1):
            source = item.get("source", "Неизвестный источник")
            title = item.get("title", "Без заголовка")
            url = item.get("url", "")
            print(f"  {index}. [{source}] {title[:100]}")
            if url:
                print(f"     🔗 {url}")


def main():
    while True:
        try:
            run_once()
            print("\n⏳ Следующая проверка через 5 минут...")
            time.sleep(300)
        except KeyboardInterrupt:
            print("\n🛑 Парсер остановлен пользователем")
            break
        except Exception as error:
            print(f"\n❌ Критическая ошибка: {type(error).__name__}: {error}")
            print("🔄 Новый запуск через 60 секунд...")
            time.sleep(60)


if __name__ == "__main__":
    main()