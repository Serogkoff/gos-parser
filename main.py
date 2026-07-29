import time
from datetime import datetime
from threading import Event, Thread

from config import (
    AGENCY_UPDATE_INTERVAL,
    GOVERNMENT_UPDATE_INTERVAL,
    MAX_RETRIES,
    PAUSE_BETWEEN_REQUESTS,
    PROJECT_VERSION,
)
from utils.news import deduplicate_news
from utils.status import print_status_table, save_parser_status
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
from parsers.sites.ria import parse as ria
from parsers.sites.tass import parse as tass


GOVERNMENT_SITES = [
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

AGENCY_SITES = [
    ("РИА Новости", ria),
    ("ТАСС", tass),
]

SITES = [*GOVERNMENT_SITES, *AGENCY_SITES]


def safe_parse(parser_func, max_retries=2):
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            news = parser_func()
            if news is None:
                raise ValueError("Парсер вернул None")
            if not isinstance(news, list):
                raise TypeError(f"Парсер вернул {type(news).__name__}, ожидался list")
            return news, ""
        except Exception as error:
            last_error = f"{type(error).__name__}: {str(error)[:200]}"
            print(f"  ❌ попытка {attempt}/{max_retries}: {type(error).__name__}: {str(error)[:100]}")
            if attempt < max_retries:
                time.sleep(3)
    return [], last_error


def run_once(sites=None, group_name="Все источники", merge_status=False):
    sites = SITES if sites is None else sites
    existing_urls = load_existing_urls()

    print("=" * 70)
    print(
        f"🚀 {group_name} · v{PROJECT_VERSION} | "
        f"{datetime.now():%Y-%m-%d %H:%M:%S} | В базе: {len(existing_urls)}"
    )
    print("=" * 70)

    all_news = []
    found_news = []
    parser_statuses = []

    for name, parser_func in sites:
        print(f"\n{name}:")
        started = time.perf_counter()
        news, error = safe_parse(parser_func, max_retries=MAX_RETRIES)
        duration = time.perf_counter() - started
        all_news.extend(news)
        matches = search_keywords(news)
        print(f"  📰 Новостей: {len(news)}")
        if matches:
            found_news.extend(matches)
            print(f"  🎯 Совпадений: {len(matches)}")
        else:
            print("  Совпадений нет")

        parser_statuses.append({
            "source": name,
            "status": "error" if error else ("ok" if news else "empty"),
            "news_count": len(news),
            "with_date": sum(bool(item.get("date")) for item in news),
            "matches_count": len(matches),
            "duration_seconds": round(duration, 2),
            "error": error,
        })
        time.sleep(PAUSE_BETWEEN_REQUESTS)

    all_news = deduplicate_news(all_news)
    found_news = deduplicate_news(found_news)
    save_parser_status(
        parser_statuses,
        PROJECT_VERSION,
        merge=merge_status,
    )
    print_status_table(parser_statuses)
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


def run_schedule(sites, group_name, interval, stop_event):
    while not stop_event.is_set():
        try:
            run_once(
                sites,
                group_name=group_name,
                merge_status=True,
            )
        except Exception as error:
            print(
                f"\n❌ Ошибка цикла «{group_name}»: "
                f"{type(error).__name__}: {error}"
            )

        if not stop_event.is_set():
            print(
                f"\n⏳ {group_name}: следующая проверка "
                f"через {interval // 60} мин."
            )
        stop_event.wait(interval)


def main():
    stop_event = Event()
    agency_thread = Thread(
        target=run_schedule,
        args=(
            AGENCY_SITES,
            "Информагентства",
            AGENCY_UPDATE_INTERVAL,
            stop_event,
        ),
        name="agency-parser",
        daemon=True,
    )
    agency_thread.start()

    try:
        run_schedule(
            GOVERNMENT_SITES,
            "Госструктуры",
            GOVERNMENT_UPDATE_INTERVAL,
            stop_event,
        )
    except KeyboardInterrupt:
        print("\n🛑 Парсер остановлен пользователем")
    finally:
        stop_event.set()
        agency_thread.join(timeout=2)


if __name__ == "__main__":
    main()
