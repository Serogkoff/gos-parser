"""SQLite-хранилище новостей и безопасные JSON-помощники."""

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from threading import RLock

from utils.logger import get_logger
from utils.news import deduplicate_news, merge_news, normalize_url


PROJECT_DIR = Path(__file__).resolve().parent.parent
ALL_NEWS_FILE = PROJECT_DIR / "all_news.json"
FOUND_NEWS_FILE = PROJECT_DIR / "found_news.json"
DATABASE_FILE = Path(
    os.environ.get("NEWS_DATABASE_PATH", PROJECT_DIR / "news.db")
)
BACKUP_DIR = Path(
    os.environ.get("NEWS_BACKUP_DIR", PROJECT_DIR / "backups")
)
logger = get_logger("storage")
STORAGE_LOCK = RLock()
JSON_MIGRATION_KEY = "json_migration_v1"
MAX_CACHED_ARTICLE_CHARS = 100_000
_INITIALIZED_DATABASES = set()
_INITIALIZATION_RESULTS = {}


def _load_json(path):
    """Читает служебный JSON. Оставлен для настроек, статуса и миграции."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError("ожидался JSON-массив")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as error:
        logger.error(f"Не удалось прочитать {path.name}: {error}")
        return []


def _write_json_atomic(path, data):
    """Записывает небольшой JSON через временный файл без риска обрыва."""
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
            temp_name = file.name
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _connect():
    """Создаёт отдельное SQLite-соединение для текущей операции."""
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _create_schema(connection):
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS news_items (
            news_key TEXT PRIMARY KEY,
            normalized_url TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            publication_date TEXT NOT NULL DEFAULT '',
            parsed_date TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS found_items (
            news_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(news_key) REFERENCES news_items(news_key)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS article_cache (
            normalized_url TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            paragraphs_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_news_source
            ON news_items(source);
        CREATE INDEX IF NOT EXISTS idx_news_publication_date
            ON news_items(publication_date DESC, parsed_date DESC);
        CREATE INDEX IF NOT EXISTS idx_news_normalized_url
            ON news_items(normalized_url);
        """
    )


def initialize_database():
    """
    Создаёт базу и один раз переносит старые JSON-файлы.

    Исходные JSON не удаляются: они остаются резервным снимком на случай,
    если пользователь захочет проверить миграцию или откатиться.
    """
    database_id = str(DATABASE_FILE.resolve())
    with STORAGE_LOCK:
        if database_id in _INITIALIZED_DATABASES and DATABASE_FILE.exists():
            return dict(_INITIALIZATION_RESULTS[database_id])

        with _connect() as connection:
            _create_schema(connection)
            completed = connection.execute(
                "SELECT 1 FROM metadata WHERE key = ?",
                (JSON_MIGRATION_KEY,),
            ).fetchone()
            if completed:
                stats = database_stats(connection=connection)
                _INITIALIZED_DATABASES.add(database_id)
                _INITIALIZATION_RESULTS[database_id] = dict(stats)
                return stats

            # Блокирует только конкурирующую первую миграцию. Обычные чтения
            # продолжают работать благодаря WAL, а второй процесс дождётся
            # завершения и повторно проверит metadata.
            connection.execute("BEGIN IMMEDIATE")
            completed = connection.execute(
                "SELECT 1 FROM metadata WHERE key = ?",
                (JSON_MIGRATION_KEY,),
            ).fetchone()
            if completed:
                stats = database_stats(connection=connection)
                _INITIALIZED_DATABASES.add(database_id)
                _INITIALIZATION_RESULTS[database_id] = dict(stats)
                return stats

            all_news = deduplicate_news(_load_json(ALL_NEWS_FILE))
            found_news = deduplicate_news(_load_json(FOUND_NEWS_FILE))
            if all_news or found_news:
                # Гарантируем, что каждая найденная запись существует в
                # news_items, но не переносим поле keywords в общую ленту.
                available = {_news_key(item) for item in all_news}
                missing = []
                for item in found_news:
                    if _news_key(item) in available:
                        continue
                    clean_item = dict(item)
                    clean_item.pop("keywords", None)
                    missing.append(clean_item)
                all_news = [*all_news, *missing]
                _replace_collections(
                    connection,
                    all_news,
                    found_news,
                )
                logger.info(
                    "Миграция JSON → SQLite завершена: "
                    f"{len(all_news)} новостей, {len(found_news)} совпадений"
                )

            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                (
                    JSON_MIGRATION_KEY,
                    json.dumps(
                        {
                            "completed_at": datetime.now().isoformat(timespec="seconds"),
                            "all_news": len(all_news),
                            "found_news": len(found_news),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            stats = database_stats(connection=connection)
            _INITIALIZED_DATABASES.add(database_id)
            _INITIALIZATION_RESULTS[database_id] = dict(stats)
            return stats


def load_all_news():
    initialize_database()
    with _connect() as connection:
        # Правила очистки развиваются вместе с парсерами. Применяем их и к
        # уже накопленной SQLite-базе, чтобы старые служебные карточки не
        # оставались в интерфейсе до следующего запуска своего источника.
        return deduplicate_news(_load_collection(connection, "news_items"))


def load_found_news():
    initialize_database()
    with _connect() as connection:
        return deduplicate_news(_load_collection(connection, "found_items"))


def find_news_by_url(url):
    """Находит одну публикацию без загрузки всей базы в веб-приложение."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT payload_json
            FROM news_items
            WHERE normalized_url = ?
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    return _decode_item(row["payload_json"]) if row else None


def load_cached_article(url):
    """Возвращает сохранённый текст статьи, если её уже открывали."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT source, title, paragraphs_json, fetched_at
            FROM article_cache
            WHERE normalized_url = ?
            """,
            (normalized,),
        ).fetchone()
    if row is None:
        return None
    try:
        paragraphs = json.loads(row["paragraphs_json"])
    except (TypeError, json.JSONDecodeError):
        logger.warning("В SQLite обнаружён повреждённый кеш статьи")
        return None
    if not isinstance(paragraphs, list) or not paragraphs:
        return None
    return {
        "title": row["title"],
        "paragraphs": paragraphs,
        "error": "",
        "source": row["source"],
        "cached": True,
        "cached_at": row["fetched_at"],
    }


def save_cached_article(url, article, source=""):
    """Сохраняет только успешный очищенный текст открытой статьи."""
    normalized = normalize_url(url)
    if not normalized or not isinstance(article, dict) or article.get("error"):
        return None
    paragraphs = _clean_cached_paragraphs(article.get("paragraphs", []))
    if not paragraphs:
        return None
    title = " ".join(str(article.get("title", "")).split())[:500]
    fetched_at = datetime.now().isoformat(timespec="seconds")
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO article_cache(
                normalized_url, source, title, paragraphs_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(normalized_url) DO UPDATE SET
                source = excluded.source,
                title = excluded.title,
                paragraphs_json = excluded.paragraphs_json,
                fetched_at = excluded.fetched_at
            """,
            (
                normalized,
                str(source),
                title,
                json.dumps(paragraphs, ensure_ascii=False, separators=(",", ":")),
                fetched_at,
            ),
        )
    return load_cached_article(normalized)


def load_existing_urls():
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT normalized_url FROM news_items WHERE normalized_url != ''"
        ).fetchall()
    return {row["normalized_url"] for row in rows}


def save_results(all_news, found_news, existing_urls):
    with STORAGE_LOCK:
        return _save_results(all_news, found_news, existing_urls)


def _save_results(all_news, found_news, existing_urls):
    initialize_database()
    all_news = deduplicate_news(all_news)
    found_news = deduplicate_news(found_news)
    new_all = [
        item
        for item in all_news
        if normalize_url(item.get("url", "")) not in existing_urls
    ]
    new_found = [
        item
        for item in found_news
        if normalize_url(item.get("url", "")) not in existing_urls
    ]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for item in new_all:
        if not item.get("parsed_date"):
            item["parsed_date"] = now
    for item in new_found:
        if not item.get("parsed_date"):
            item["parsed_date"] = now

    old_all = load_all_news()
    old_found = load_found_news()

    # Передаём все свежие записи, а не только новые: уже сохранённые
    # материалы смогут получить исправленную дату, ссылку или анонс.
    merged_all = merge_news(old_all, all_news)
    merged_found = merge_news(old_found, found_news)
    merged_all = _sort_items(merged_all)
    merged_found = _sort_items(merged_found)

    with _connect() as connection:
        _replace_collections(connection, merged_all, merged_found)

    print(f"✅ Новых: {len(new_all)} | Всего: {len(merged_all)}")
    print(
        f"🔴 Новых совпадений: {len(new_found)} | "
        f"Всего: {len(merged_found)}"
    )
    return new_found


def replace_found_news(items):
    """Полностью пересобирает таблицу совпадений после изменения слов."""
    with STORAGE_LOCK:
        initialize_database()
        all_news = load_all_news()
        found_news = deduplicate_news(items)
        available = {_news_key(item) for item in all_news}
        found_news = [
            item for item in found_news if _news_key(item) in available
        ]
        with _connect() as connection:
            connection.execute("DELETE FROM found_items")
            _insert_found_items(connection, found_news)
        return _sort_items(found_news)


def database_stats(connection=None):
    """Возвращает краткую статистику и результат проверки целостности."""
    owns_connection = connection is None
    if owns_connection:
        initialize_database()
        connection = _connect()
    try:
        news_count = connection.execute(
            "SELECT COUNT(*) FROM news_items"
        ).fetchone()[0]
        found_count = connection.execute(
            "SELECT COUNT(*) FROM found_items"
        ).fetchone()[0]
        cached_articles = connection.execute(
            "SELECT COUNT(*) FROM article_cache"
        ).fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        backups = _list_automatic_backups()
        migration = connection.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (JSON_MIGRATION_KEY,),
        ).fetchone()
        return {
            "news_count": news_count,
            "found_count": found_count,
            "cached_articles": cached_articles,
            "integrity": integrity,
            "path": str(DATABASE_FILE),
            "size_bytes": (
                DATABASE_FILE.stat().st_size if DATABASE_FILE.exists() else 0
            ),
            "journal_mode": connection.execute(
                "PRAGMA journal_mode"
            ).fetchone()[0],
            "json_migrated": migration is not None,
            "backup_count": len(backups),
            "last_backup": str(backups[-1]) if backups else "",
        }
    finally:
        if owns_connection:
            connection.close()


def backup_database(destination=None):
    """Атомарно создаёт и проверяет копию работающей SQLite-базы."""
    initialize_database()
    destination = Path(destination or DATABASE_FILE.with_suffix(".backup.db"))
    if destination.resolve() == DATABASE_FILE.resolve():
        raise ValueError("резервная копия не может заменять рабочую базу")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        if temporary.exists():
            temporary.unlink()
        with STORAGE_LOCK:
            source = _connect()
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(
                        f"проверка резервной копии завершилась: {result}"
                    )
            finally:
                # Контекстный менеджер sqlite3 завершает транзакцию, но не
                # закрывает соединение. На Windows открытый дескриптор не даёт
                # атомарно переименовать временную базу.
                target.close()
                source.close()
            os.replace(temporary, destination)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError as error:
                logger.warning(
                    f"Не удалось удалить временную копию SQLite: {error}"
                )
    return destination


def ensure_daily_backup(retention=7, now=None):
    """
    Создаёт не больше одной автоматической копии в день.

    Функцию безопасно вызывать после каждого цикла парсинга: если сегодняшний
    снимок уже существует, повторного копирования базы не будет.
    """
    initialize_database()
    moment = now or datetime.now()
    destination = BACKUP_DIR / (
        f"{DATABASE_FILE.stem}-{moment:%Y-%m-%d}.db"
    )
    created = False
    with STORAGE_LOCK:
        if not destination.exists():
            backup_database(destination)
            created = True
            logger.info(f"Создана резервная копия SQLite: {destination.name}")
        removed = _remove_old_backups(retention)
    return {
        "created": created,
        "path": str(destination),
        "removed": [str(path) for path in removed],
    }


def prepare_database(retention=7):
    """Проверяет рабочую базу и создаёт ежедневную резервную копию."""
    stats = database_stats()
    if stats["integrity"] != "ok":
        raise sqlite3.DatabaseError(
            f"проверка целостности SQLite завершилась: {stats['integrity']}"
        )
    backup = ensure_daily_backup(retention=retention)
    stats = database_stats()
    stats["backup_created"] = backup["created"]
    return stats


def _automatic_backup_pattern():
    return re.compile(
        rf"^{re.escape(DATABASE_FILE.stem)}-\d{{4}}-\d{{2}}-\d{{2}}\.db$"
    )


def _list_automatic_backups():
    if not BACKUP_DIR.exists():
        return []
    pattern = _automatic_backup_pattern()
    return sorted(
        path
        for path in BACKUP_DIR.iterdir()
        if path.is_file() and pattern.fullmatch(path.name)
    )


def _remove_old_backups(retention):
    try:
        retention = max(1, int(retention))
    except (TypeError, ValueError):
        retention = 7
    backups = _list_automatic_backups()
    removed = []
    for path in backups[:-retention]:
        path.unlink()
        removed.append(path)
        logger.info(f"Удалена старая резервная копия SQLite: {path.name}")
    return removed


def _replace_collections(connection, all_news, found_news):
    """Заменяет обе коллекции в одной транзакции: либо всё, либо ничего."""
    connection.execute("DELETE FROM found_items")
    connection.execute("DELETE FROM news_items")
    _insert_news_items(connection, all_news)

    available = {_news_key(item) for item in all_news}
    safe_found = [item for item in found_news if _news_key(item) in available]
    _insert_found_items(connection, safe_found)


def _insert_news_items(connection, items):
    updated_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for item in deduplicate_news(items):
        rows.append(
            (
                _news_key(item),
                normalize_url(item.get("url", "")),
                str(item.get("source", "")),
                str(item.get("title", "")),
                str(item.get("date", "")),
                str(item.get("parsed_date", "")),
                _encode_item(item),
                updated_at,
            )
        )
    connection.executemany(
        """
        INSERT INTO news_items(
            news_key, normalized_url, source, title,
            publication_date, parsed_date, payload_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _insert_found_items(connection, items):
    updated_at = datetime.now().isoformat(timespec="seconds")
    connection.executemany(
        """
        INSERT INTO found_items(news_key, payload_json, updated_at)
        VALUES (?, ?, ?)
        """,
        [
            (_news_key(item), _encode_item(item), updated_at)
            for item in deduplicate_news(items)
        ],
    )


def _load_collection(connection, table):
    if table not in {"news_items", "found_items"}:
        raise ValueError("неизвестная таблица новостей")
    rows = connection.execute(
        f"SELECT payload_json FROM {table}"
    ).fetchall()
    return _sort_items(
        item
        for item in (_decode_item(row["payload_json"]) for row in rows)
        if item is not None
    )


def _encode_item(item):
    return json.dumps(dict(item), ensure_ascii=False, separators=(",", ":"))


def _decode_item(payload):
    try:
        item = json.loads(payload)
        return item if isinstance(item, dict) else None
    except (TypeError, json.JSONDecodeError):
        logger.warning("В SQLite обнаружена повреждённая запись новости")
        return None


def _clean_cached_paragraphs(paragraphs):
    if not isinstance(paragraphs, (list, tuple)):
        return []
    result = []
    seen = set()
    remaining = MAX_CACHED_ARTICLE_CHARS
    for paragraph in paragraphs:
        text = " ".join(str(paragraph or "").split())
        if not text or text in seen or remaining <= 0:
            continue
        text = text[:remaining]
        result.append(text)
        seen.add(text)
        remaining -= len(text)
    return result


def _news_key(item):
    normalized = normalize_url(item.get("url", ""))
    if normalized:
        return f"url:{normalized}"
    source = " ".join(str(item.get("source", "")).casefold().split())
    title = re.sub(
        r"[^\wа-яё]+",
        " ",
        str(item.get("title", "")).casefold(),
        flags=re.IGNORECASE,
    )
    return f"title:{source}:{' '.join(title.split())}"


def _sort_items(items):
    return sorted(
        items,
        key=lambda item: (
            str(item.get("date", "")),
            str(item.get("parsed_date", "")),
        ),
        reverse=True,
    )
