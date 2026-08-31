"""SQLite-хранилище новостей и безопасные JSON-помощники."""

import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock

from utils.dates import parse_date
from utils.logger import get_logger
from utils.news import deduplicate_news, merge_news, normalize_url
from utils.storage_collections import CollectionStorage
from utils.storage_monitoring import MonitoringStorage
from utils.storage_news import NewsStorage
from utils.storage_schema import create_schema as _create_schema
from utils.storage_source_control import SourceControlStorage
from utils.storage_users import UserStorage
from utils.storage_workspace import PersonalWorkspaceStorage
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
_COLLECTION_CACHE = {}


def _database_change_signature():
    """Отслеживает изменения основной SQLite-базы и её WAL-журнала."""
    signature = [str(DATABASE_FILE.resolve())]
    for path in (DATABASE_FILE, Path(f"{DATABASE_FILE}-wal")):
        try:
            stat = path.stat()
            signature.extend((stat.st_size, stat.st_mtime_ns))
        except OSError:
            signature.extend((0, 0))
    return tuple(signature)


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
    connection.create_function(
        "CASEFOLD",
        1,
        lambda value: str(value or "").casefold(),
        deterministic=True,
    )
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _connection():
    """Завершает транзакцию и обязательно закрывает SQLite-соединение."""
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


_USER_STORAGE = UserStorage(
    initialize_database=lambda: initialize_database(),
    connection_factory=lambda: _connection(),
    lock=STORAGE_LOCK,
)


def count_users():
    """Возвращает число учётных записей, включая отключённые."""
    return _USER_STORAGE.count_users()


def create_user(username, password, role="user"):
    """Создаёт пользователя с хешем пароля; открытый пароль не хранится."""
    return _USER_STORAGE.create_user(username, password, role)


def load_user(user_id):
    """Возвращает безопасные поля пользователя без хеша пароля."""
    return _USER_STORAGE.load_user(user_id)


def list_users():
    """Возвращает безопасный список пользователей без хешей паролей."""
    return _USER_STORAGE.list_users()


def set_user_password(user_id, password):
    """Заменяет пароль пользователя новым защищённым хешем."""
    return _USER_STORAGE.set_user_password(user_id, password)


def set_user_role(user_id, role):
    """Меняет роль, не позволяя убрать последнего активного администратора."""
    return _USER_STORAGE.set_user_role(user_id, role)


def set_user_active(user_id, is_active):
    """Включает или отключает вход, сохраняя все данные пользователя."""
    return _USER_STORAGE.set_user_active(user_id, is_active)


def delete_user(user_id):
    """Удаляет аккаунт и связанные личные данные, сохраняя последнего администратора."""
    return _USER_STORAGE.delete_user(user_id)


def authenticate_user(username, password):
    """Проверяет пароль и возвращает активного пользователя."""
    return _USER_STORAGE.authenticate_user(username, password)


_WORKSPACE_STORAGE = PersonalWorkspaceStorage(
    initialize_database=lambda: initialize_database(),
    connection_factory=lambda: _connection(),
    lock=STORAGE_LOCK,
    validate_user_id=lambda value: _validated_user_id(value),
)


def save_personal_note(user_id, folder, title, body, visibility="private",
                       shared_user_ids=None, note_id=None):
    """Создаёт или обновляет рабочую запись владельца."""
    return _WORKSPACE_STORAGE.save_personal_note(
        user_id, folder, title, body, visibility, shared_user_ids, note_id
    )


def list_personal_notes(user_id):
    """Возвращает личные записи владельца с настройкой доступа."""
    return _WORKSPACE_STORAGE.list_personal_notes(user_id)


def delete_personal_note(user_id, note_id):
    return _WORKSPACE_STORAGE.delete_personal_note(user_id, note_id)


def save_calendar_event(user_id, title, event_date, event_time="", place="",
                        description="", visibility="private",
                        shared_user_ids=None, event_id=None):
    """Создаёт или обновляет событие календаря владельца."""
    return _WORKSPACE_STORAGE.save_calendar_event(
        user_id, title, event_date, event_time, place, description,
        visibility, shared_user_ids, event_id
    )


def list_calendar_events(user_id, date_from, date_to):
    """Возвращает события владельца за включительный диапазон дат."""
    return _WORKSPACE_STORAGE.list_calendar_events(user_id, date_from, date_to)


def delete_calendar_event(user_id, event_id):
    return _WORKSPACE_STORAGE.delete_calendar_event(user_id, event_id)


def create_dictionary_deck(user_id, name):
    return _WORKSPACE_STORAGE.create_dictionary_deck(user_id, name)


def list_dictionary_decks(user_id):
    return _WORKSPACE_STORAGE.list_dictionary_decks(user_id)


def save_dictionary_card(user_id, deck_id, term, reading, translation):
    return _WORKSPACE_STORAGE.save_dictionary_card(
        user_id, deck_id, term, reading, translation
    )


def list_dictionary_cards(user_id, deck_id, due_only=False):
    return _WORKSPACE_STORAGE.list_dictionary_cards(user_id, deck_id, due_only)


def review_dictionary_card(user_id, card_id, rating):
    """Применяет простой интервальный повтор для ответа в квизе."""
    return _WORKSPACE_STORAGE.review_dictionary_card(user_id, card_id, rating)


_SOURCE_CONTROL_STORAGE = SourceControlStorage(
    initialize_database=lambda: initialize_database(),
    connection_factory=lambda: _connection(),
    lock=STORAGE_LOCK,
    validate_user_id=lambda value: _validated_user_id(value),
    validate_source_group=lambda value: _validated_source_group(value),
)


def load_source_order(user_id, source_group):
    """Возвращает личный порядок источников для одного раздела."""
    return _SOURCE_CONTROL_STORAGE.load_source_order(user_id, source_group)


def save_source_order(user_id, source_group, sources):
    """Сохраняет личный порядок источников, не затрагивая других пользователей."""
    return _SOURCE_CONTROL_STORAGE.save_source_order(
        user_id, source_group, sources
    )


def source_is_enabled(source):
    """По умолчанию источник включён; администратор может поставить его на паузу."""
    return _SOURCE_CONTROL_STORAGE.source_is_enabled(source)


def load_source_settings():
    """Возвращает сохранённые администратором состояния источников."""
    return _SOURCE_CONTROL_STORAGE.load_source_settings()


def set_source_enabled(source, enabled):
    """Включает источник или временно исключает его из расписания."""
    return _SOURCE_CONTROL_STORAGE.set_source_enabled(source, enabled)


def enqueue_parser_job(source, requested_by=None):
    """Ставит одиночную проверку в очередь, не создавая повторных заданий."""
    return _SOURCE_CONTROL_STORAGE.enqueue_parser_job(source, requested_by)


def claim_next_parser_job():
    """Атомарно забирает одно ожидающее задание для процесса main.py."""
    return _SOURCE_CONTROL_STORAGE.claim_next_parser_job()


def finish_parser_job(job_id, success, error=""):
    """Фиксирует результат ручной проверки источника."""
    return _SOURCE_CONTROL_STORAGE.finish_parser_job(job_id, success, error)


def list_parser_jobs(limit=50):
    """Возвращает последние ручные проверки для администраторской панели."""
    return _SOURCE_CONTROL_STORAGE.list_parser_jobs(limit)


def source_news_statistics():
    """Считает накопленные новости и дату последнего нового материала."""
    return _SOURCE_CONTROL_STORAGE.source_news_statistics()


_NEWS_STORAGE = NewsStorage(
    initialize_database=lambda: initialize_database(),
    connection_factory=lambda: _connection(),
    lock=STORAGE_LOCK,
    normalize_url=normalize_url,
    decode_item=lambda payload: _decode_item(payload),
    attach_display_fields=lambda item, parsed_date, first_seen_at:
        _attach_news_display_fields(item, parsed_date, first_seen_at),
)


def _news_group_condition(source_group, source_column="n.source"):
    """Строит параметризованное SQL-условие для одного раздела ленты."""
    return _NEWS_STORAGE.news_group_condition(source_group, source_column)


def news_group_counts(source_group):
    """Считает все материалы и совпадения раздела без загрузки JSON."""
    return _NEWS_STORAGE.news_group_counts(source_group)


def news_source_counts(source_group):
    """Возвращает размеры источников раздела одним SQL GROUP BY."""
    return _NEWS_STORAGE.news_source_counts(source_group)


def list_news_page(source_group, *, found_only=False, sources=None,
                   search_query="", keyword="", limit=20, offset=0):
    """Читает одну страницу новостей и считает результат средствами SQLite."""
    return _NEWS_STORAGE.list_news_page(
        source_group,
        found_only=found_only,
        sources=sources,
        search_query=search_query,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )


def list_news_index(source_group, limit=2000):
    """Возвращает лёгкий индекс ленты без чтения payload_json."""
    return _NEWS_STORAGE.list_news_index(source_group, limit)


def list_unread_news(user_id, source_group, limit=2000):
    """Совместимый список непрочитанных материалов без полного JSON базы."""
    return _NEWS_STORAGE.list_unread_news(user_id, source_group, limit)


def _unread_news_context(user_id, source_group):
    return _NEWS_STORAGE._unread_news_context(user_id, source_group)


def _unread_news_select(condition):
    return _NEWS_STORAGE._unread_news_select(condition)


def _unread_news_parameters(context):
    return _NEWS_STORAGE._unread_news_parameters(context)


def list_unread_news_index(user_id, source_group, limit=2000):
    """Возвращает лёгкий индекс непрочитанных новостей пользователя."""
    return _NEWS_STORAGE.list_unread_news_index(user_id, source_group, limit)


def news_unread_summary(user_id, source_group, visible_urls=None):
    """Одним SQL-запросом считает новые новости и состояние видимых карточек."""
    return _NEWS_STORAGE.news_unread_summary(
        user_id, source_group, visible_urls
    )


def mark_news_read(user_id, url):
    """Отмечает одну новость прочитанной для конкретного пользователя."""
    return _NEWS_STORAGE.mark_news_read(user_id, url)


def migrate_legacy_unread(user_id, unread_urls):
    """Один раз переносит старый список непрочитанного из localStorage."""
    return _NEWS_STORAGE.migrate_legacy_unread(user_id, unread_urls)


def mark_news_group_read(user_id, source_group):
    """Отмечает прочитанными все новости выбранного раздела."""
    return _NEWS_STORAGE.mark_news_group_read(user_id, source_group)

_MONITORING_STORAGE = MonitoringStorage(
    initialize_database=lambda: initialize_database(),
    connection_factory=lambda: _connection(),
    lock=STORAGE_LOCK,
)


def sync_source_incidents(statuses, now=None):
    """Открывает и закрывает инциденты по результатам реальных проверок."""
    return _MONITORING_STORAGE.sync_source_incidents(statuses, now)


def list_source_incidents(state="all", limit=200):
    """Возвращает последние инциденты для администраторского журнала."""
    return _MONITORING_STORAGE.list_source_incidents(state, limit)


def source_incident_statistics(now=None):
    """Считает активные, критические и недавно закрытые инциденты."""
    return _MONITORING_STORAGE.source_incident_statistics(now)


def source_reliability_statistics(days=7, now=None, sources=None):
    """Считает доступность источников по времени записанных инцидентов."""
    return _MONITORING_STORAGE.source_reliability_statistics(
        days, now, sources
    )


_COLLECTION_STORAGE = CollectionStorage(
    initialize_database=lambda: initialize_database(),
    connection_factory=lambda: _connection(),
    lock=STORAGE_LOCK,
    normalize_url=normalize_url,
    validate_user_id=lambda value: _validated_user_id(value),
)


def list_bookmark_folders(user_id):
    """Возвращает только папки указанного пользователя и число материалов."""
    return _COLLECTION_STORAGE.list_bookmark_folders(user_id)


def ensure_favorites_folder(user_id):
    """Возвращает системную папку избранного и переносит старые сердечки."""
    return _COLLECTION_STORAGE.ensure_favorites_folder(user_id)


def create_bookmark_folder(user_id, name):
    """Создаёт личную папку с уникальным для пользователя названием."""
    return _COLLECTION_STORAGE.create_bookmark_folder(user_id, name)


def rename_bookmark_folder(user_id, folder_id, name):
    """Переименовывает только принадлежащую пользователю папку."""
    return _COLLECTION_STORAGE.rename_bookmark_folder(user_id, folder_id, name)


def delete_bookmark_folder(user_id, folder_id):
    """Удаляет папку; её закладки остаются в разделе «Без папки»."""
    return _COLLECTION_STORAGE.delete_bookmark_folder(user_id, folder_id)


def save_bookmark_folder_order(user_id, folder_ids):
    """Сохраняет полный личный порядок подборок после перетаскивания."""
    return _COLLECTION_STORAGE.save_bookmark_folder_order(user_id, folder_ids)


def update_collection(user_id, folder_id, name, description="",
                      visibility="private", shared_user_ids=None):
    """Обновляет подборку и её наследуемый доступ от имени владельца."""
    return _COLLECTION_STORAGE.update_collection(
        user_id, folder_id, name, description, visibility, shared_user_ids
    )


def load_collection(user_id, folder_id):
    """Возвращает доступную подборку и права текущего пользователя."""
    return _COLLECTION_STORAGE.load_collection(user_id, folder_id)


def list_shared_collections(user_id):
    """Показывает подборки других владельцев, доступные пользователю."""
    return _COLLECTION_STORAGE.list_shared_collections(user_id)


def list_collection_bookmarks(user_id, folder_id):
    return _COLLECTION_STORAGE.list_collection_bookmarks(user_id, folder_id)


def save_external_bookmark(user_id, folder_id, url, title, note=""):
    """Добавляет в собственную подборку ссылку, которой нет в ленте."""
    return _COLLECTION_STORAGE.save_external_bookmark(
        user_id, folder_id, url, title, note
    )


def _validated_collection_note_fields(title, body, url="", source="",
                                      publication_date="", comment=""):
    return _COLLECTION_STORAGE._validated_collection_note_fields(
        title, body, url, source, publication_date, comment
    )


def save_collection_note(user_id, folder_id, title, body, url="", source="",
                         publication_date="", comment=""):
    """Добавляет в подборку заметку или вручную сохранённую статью."""
    return _COLLECTION_STORAGE.save_collection_note(
        user_id, folder_id, title, body, url, source, publication_date, comment
    )


def update_collection_note(user_id, folder_id, note_id, title, body, url="",
                           source="", publication_date="", comment=""):
    """Обновляет существующую заметку владельца без создания дубликата."""
    return _COLLECTION_STORAGE.update_collection_note(
        user_id, folder_id, note_id, title, body, url, source,
        publication_date, comment
    )


def list_collection_notes(user_id, folder_id):
    return _COLLECTION_STORAGE.list_collection_notes(user_id, folder_id)


def list_collection_note_read_ids(user_id, folder_id):
    """Возвращает статьи подборки, прочитанные именно этим пользователем."""
    return _COLLECTION_STORAGE.list_collection_note_read_ids(user_id, folder_id)


def set_collection_note_read(user_id, folder_id, note_id, is_read):
    """Меняет личную отметку чтения статьи в доступной подборке."""
    return _COLLECTION_STORAGE.set_collection_note_read(
        user_id, folder_id, note_id, is_read
    )


def delete_collection_note(user_id, folder_id, note_id):
    return _COLLECTION_STORAGE.delete_collection_note(
        user_id, folder_id, note_id
    )


def save_bookmark(user_id, item, folder_id=None, note=""):
    """Сохраняет снимок новости в личных закладках пользователя."""
    return _COLLECTION_STORAGE.save_bookmark(user_id, item, folder_id, note)


def update_bookmark(user_id, url, folder_id=None, note=""):
    """Перемещает личную закладку и сохраняет заметку пользователя."""
    return _COLLECTION_STORAGE.update_bookmark(user_id, url, folder_id, note)


def remove_bookmark(user_id, url):
    """Удаляет личную закладку, не затрагивая новость в общей базе."""
    return _COLLECTION_STORAGE.remove_bookmark(user_id, url)


def load_bookmark(user_id, url):
    return _COLLECTION_STORAGE.load_bookmark(user_id, url)


def list_bookmarks(user_id, folder_id="all"):
    """Возвращает личные закладки с необязательным фильтром по папке."""
    return _COLLECTION_STORAGE.list_bookmarks(user_id, folder_id)


def bookmarked_urls(user_id):
    """Возвращает URL личных закладок для подсветки сердечек в ленте."""
    return _COLLECTION_STORAGE.bookmarked_urls(user_id)


def count_bookmarks(user_id):
    return _COLLECTION_STORAGE.count_bookmarks(user_id)

def _validated_user_id(value):
    try:
        user_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Пользователь не найден") from error
    if user_id < 1 or load_user(user_id) is None:
        raise ValueError("Пользователь не найден")
    return user_id


def _validated_source_group(value):
    source_group = str(value or "").strip().casefold()
    if source_group not in {"government", "agencies", "newspapers"}:
        raise ValueError("Неизвестный раздел источников")
    return source_group


def _validated_folder_id(value):
    return _COLLECTION_STORAGE._validated_folder_id(value)


def _owned_folder_id(user_id, value):
    return _COLLECTION_STORAGE._owned_folder_id(user_id, value)


def _validated_folder_name(value):
    return _COLLECTION_STORAGE._validated_folder_name(value)


def _validated_bookmark_note(value):
    return _COLLECTION_STORAGE._validated_bookmark_note(value)


def _bookmark_from_row(row):
    return _COLLECTION_STORAGE._bookmark_from_row(row)

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

        with _connection() as connection:
            _create_schema(connection)
            # ALTER TABLE при обновлении старой базы открывает транзакцию.
            # Фиксируем только изменение схемы до BEGIN IMMEDIATE ниже.
            connection.commit()
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
    return _load_collection_cached("news_items")


def load_found_news():
    initialize_database()
    return _load_collection_cached("found_items")


def _load_collection_cached(table):
    """Не разбирает десятки тысяч JSON-записей заново на каждой странице."""
    if table not in {"news_items", "found_items"}:
        raise ValueError("неизвестная таблица новостей")
    signature = _database_change_signature()
    cache_key = (signature[0], table)
    with STORAGE_LOCK:
        cached = _COLLECTION_CACHE.get(cache_key)
        if cached and cached["signature"] == signature:
            return list(cached["items"])

    connection = _connect()
    try:
        items = deduplicate_news(_load_collection(connection, table))
    finally:
        connection.close()

    final_signature = _database_change_signature()
    # Если запись шла одновременно с чтением, не закрепляем снимок под новой
    # сигнатурой: следующий запрос безопасно перечитает актуальную коллекцию.
    if final_signature == signature:
        with STORAGE_LOCK:
            _COLLECTION_CACHE[cache_key] = {
                "signature": signature,
                "items": tuple(items),
            }
    return list(items)


def find_news_by_url(url):
    """Находит одну публикацию без загрузки всей базы в веб-приложение."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT payload_json, parsed_date, first_seen_at
            FROM news_items
            WHERE normalized_url = ?
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    if row is None:
        return None
    item = _decode_item(row["payload_json"])
    if item is not None:
        _attach_news_display_fields(
            item, row["parsed_date"], row["first_seen_at"],
        )
    return item


def load_cached_article(url):
    """Возвращает сохранённый текст статьи, если её уже открывали."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    initialize_database()
    with _connection() as connection:
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
    with STORAGE_LOCK, _connection() as connection:
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
    with _connection() as connection:
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

    with _connection() as connection:
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
        with _connection() as connection:
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


def create_manual_backup(retention=10, now=None):
    """Создаёт подписанную ручную копию и оставляет последние снимки."""
    moment = now or datetime.now()
    destination = BACKUP_DIR / (
        f"{DATABASE_FILE.stem}-manual-{moment:%Y-%m-%d_%H-%M-%S-%f}.db"
    )
    backup_database(destination)
    removed = _remove_old_manual_backups(retention)
    logger.info(f"Создана ручная резервная копия SQLite: {destination.name}")
    return {
        "path": str(destination),
        "name": destination.name,
        "removed": [str(path) for path in removed],
    }


def list_database_backups():
    """Перечисляет автоматические и ручные резервные копии базы."""
    if not BACKUP_DIR.exists():
        return []
    result = []
    for path in BACKUP_DIR.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".db":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append({
            "name": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
                timespec="seconds"
            ),
            "kind": "manual" if "-manual-" in path.name else "automatic",
        })
    return sorted(result, key=lambda item: item["modified_at"], reverse=True)


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


def _remove_old_manual_backups(retention):
    try:
        retention = max(1, int(retention))
    except (TypeError, ValueError):
        retention = 10
    if not BACKUP_DIR.exists():
        return []
    backups = sorted(
        (
            path for path in BACKUP_DIR.iterdir()
            if path.is_file()
            and path.suffix.casefold() == ".db"
            and "-manual-" in path.name
        ),
        key=lambda path: path.name,
    )
    removed = []
    for path in backups[:-retention]:
        path.unlink()
        removed.append(path)
        logger.info(f"Удалена старая ручная копия SQLite: {path.name}")
    return removed


def _replace_collections(connection, all_news, found_news):
    """Заменяет обе коллекции в одной транзакции: либо всё, либо ничего."""
    first_seen_by_key = {
        row["news_key"]: row["first_seen_at"]
        for row in connection.execute(
            "SELECT news_key, first_seen_at FROM news_items"
        ).fetchall()
    }
    connection.execute("DELETE FROM found_items")
    connection.execute("DELETE FROM news_items")
    _insert_news_items(connection, all_news, first_seen_by_key=first_seen_by_key)

    available = {_news_key(item) for item in all_news}
    safe_found = [item for item in found_news if _news_key(item) in available]
    _insert_found_items(connection, safe_found)


def _insert_news_items(connection, items, first_seen_by_key=None):
    updated_at = datetime.now().isoformat(timespec="seconds")
    first_seen_at = datetime.now().isoformat(timespec="microseconds")
    first_seen_by_key = first_seen_by_key or {}
    rows = []
    for item in deduplicate_news(items):
        news_key = _news_key(item)
        rows.append(
            (
                news_key,
                normalize_url(item.get("url", "")),
                str(item.get("source", "")),
                str(item.get("title", "")),
                str(item.get("date", "")),
                str(item.get("parsed_date", "")),
                _encode_item(item),
                updated_at,
                first_seen_by_key.get(news_key) or first_seen_at,
            )
        )
    connection.executemany(
        """
        INSERT INTO news_items(
            news_key, normalized_url, source, title,
            publication_date, parsed_date, payload_json, updated_at,
            first_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _attach_news_display_fields(item, parsed_date, first_seen_at):
    """Добавляет готовые дату публикации и время первого получения."""
    publication_date = parse_date(item.get("date", ""))
    item["publication_date_display"] = (
        datetime.strptime(publication_date, "%Y-%m-%d").strftime("%d.%m.%Y")
        if publication_date
        else str(item.get("date", ""))
    )
    item["parser_added_time"] = ""
    for value in (parsed_date, first_seen_at):
        match = re.search(
            r"(?:^|[T\s])(\d{2}:\d{2})(?::\d{2})?",
            str(value or ""),
        )
        if match:
            item["parser_added_time"] = match.group(1)
            break


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
