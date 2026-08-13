import time
import multiprocessing
from datetime import datetime, timedelta
from threading import Event, Thread

from config import (
    AGENCY_UPDATE_INTERVAL,
    DATABASE_BACKUP_RETENTION,
    GOVERNMENT_UPDATE_INTERVAL,
    KYODO_UPDATE_INTERVAL,
    KYODO_MAX_BACKOFF_SECONDS,
    MAX_RETRIES,
    NEWSPAPER_UPDATE_HOUR,
    PAUSE_BETWEEN_REQUESTS,
    PROJECT_VERSION,
    SOURCE_TIMEOUT_OVERRIDES,
    SOURCE_TIMEOUT_SECONDS,
)
from utils.parser_runner import ParserTimeoutError, run_parser_with_timeout
from utils.news import deduplicate_news
from utils.status import print_status_table, save_parser_status
from utils.storage import (
    ensure_daily_backup,
    load_existing_urls,
    prepare_database,
    save_results,
)
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
from parsers.sites.interfax import parse as interfax
from parsers.sites.yonhap import parse as yonhap
from parsers.sites.kyodo import parse as kyodo
from parsers.sites.minoborony import parse as minoborony
from parsers.sites.ng import parse as ng
from parsers.sites.kommersant import parse as kommersant
from parsers.sites.izvestia import parse as izvestia
from parsers.sites.rg import parse as rg
from parsers.sites.vedomosti import parse as vedomosti
from parsers.sites.redstar import parse as redstar
from parsers.sites.kp import parse as kp
from parsers.sites.kremlin import parse as kremlin


GOVERNMENT_SITES = [
    ("Президент России", kremlin),
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
    ("Минобороны РФ", minoborony),
]

AGENCY_SITES = [
    ("РИА Новости", ria),
    ("ТАСС", tass),
    ("Интерфакс", interfax),
    ("Yonhap", yonhap),
]

KYODO_SITES = [
    ("Киодо (共同通信)", kyodo),
]

NEWSPAPER_SITES = [
    ("Независимая газета", ng),
    ("Коммерсантъ", kommersant),
    ("Известия", izvestia),
    ("Российская газета", rg),
    ("Ведомости", vedomosti),
    ("Красная звезда", redstar),
    ("Комсомольская правда", kp),
]

SITES = [
    *GOVERNMENT_SITES,
    *AGENCY_SITES,
    *KYODO_SITES,
    *NEWSPAPER_SITES,
]


def safe_parse(parser_func, max_retries=2, timeout_seconds=SOURCE_TIMEOUT_SECONDS):
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            news = run_parser_with_timeout(parser_func, timeout_seconds)
            if news is None:
                raise ValueError("Парсер вернул None")
            if not isinstance(news, list):
                raise TypeError(f"Парсер вернул {type(news).__name__}, ожидался list")
            return news, ""
        except Exception as error:
            last_error = f"{type(error).__name__}: {str(error)[:200]}"
            print(f"  ❌ попытка {attempt}/{max_retries}: {type(error).__name__}: {str(error)[:100]}")
            if isinstance(error, ParserTimeoutError):
                print("  ℹ️ Источник остановлен, остальные продолжают работу")
                break
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
        news, error = safe_parse(
            parser_func,
            max_retries=MAX_RETRIES,
            timeout_seconds=SOURCE_TIMEOUT_OVERRIDES.get(
                name,
                SOURCE_TIMEOUT_SECONDS,
            ),
        )
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
    try:
        ensure_daily_backup(retention=DATABASE_BACKUP_RETENTION)
    except Exception as error:
        print(
            "⚠️ Не удалось создать резервную копию SQLite: "
            f"{type(error).__name__}: {error}"
        )

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

    return parser_statuses


def run_schedule(
    sites,
    group_name,
    interval,
    stop_event,
    failure_backoff=False,
    max_backoff_seconds=None,
):
    consecutive_failures = 0
    while not stop_event.is_set():
        statuses = []
        try:
            statuses = run_once(
                sites,
                group_name=group_name,
                merge_status=True,
            )
        except Exception as error:
            print(
                f"\n❌ Ошибка цикла «{group_name}»: "
                f"{type(error).__name__}: {error}"
            )

        group_worked = any(
            item.get("status") == "ok"
            for item in statuses
        )
        consecutive_failures = (
            0 if group_worked else consecutive_failures + 1
        )
        wait_seconds = _schedule_delay(
            interval,
            consecutive_failures,
            failure_backoff=failure_backoff,
            max_backoff_seconds=max_backoff_seconds,
        )

        if not stop_event.is_set():
            print(
                f"\n⏳ {group_name}: следующая проверка "
                f"через {wait_seconds // 60} мин."
            )
        stop_event.wait(wait_seconds)


def _schedule_delay(
    interval,
    consecutive_failures,
    failure_backoff=False,
    max_backoff_seconds=None,
):
    """Увеличивает паузу только для полностью неработающей группы."""
    if not failure_backoff or consecutive_failures <= 0:
        return interval
    maximum = max_backoff_seconds or interval * 8
    return min(interval * (2 ** min(consecutive_failures, 3)), maximum)


def run_daily_schedule(sites, group_name, hour, stop_event):
    """Проверяет группу строго раз в сутки в заданный час."""
    while not stop_event.is_set():
        now = datetime.now()
        next_run = now.replace(
            hour=hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        wait_seconds = max(1, int((next_run - now).total_seconds()))
        if not stop_event.is_set():
            print(
                f"\n⏳ {group_name}: следующая проверка "
                f"{next_run:%d.%m.%Y в %H:%M}."
            )
        stop_event.wait(wait_seconds)
        if stop_event.is_set():
            break

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


def main():
    database = prepare_database(retention=DATABASE_BACKUP_RETENTION)
    size_mb = database["size_bytes"] / 1024 / 1024
    backup_state = (
        "создана сегодня" if database["backup_created"] else "уже существует"
    )
    print(
        "🗄️ SQLite: "
        f"{database['news_count']} новостей, "
        f"{database['cached_articles']} текстов сохранено, "
        f"целостность {database['integrity']}, "
        f"{size_mb:.1f} МБ"
    )
    print(f"💾 Резервная копия: {backup_state}")

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

    kyodo_thread = Thread(
        target=run_schedule,
        args=(
            KYODO_SITES,
            "Киодо",
            KYODO_UPDATE_INTERVAL,
            stop_event,
            True,
            KYODO_MAX_BACKOFF_SECONDS,
        ),
        name="kyodo-parser",
        daemon=True,
    )
    kyodo_thread.start()

    newspaper_thread = Thread(
        target=run_daily_schedule,
        args=(
            NEWSPAPER_SITES,
            "Газеты",
            NEWSPAPER_UPDATE_HOUR,
            stop_event,
        ),
        name="newspaper-parser",
        daemon=True,
    )
    newspaper_thread.start()

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
        kyodo_thread.join(timeout=2)
        newspaper_thread.join(timeout=2)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
