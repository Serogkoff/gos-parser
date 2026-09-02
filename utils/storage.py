"""SQLite-хранилище новостей и безопасные JSON-помощники."""

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock

from utils.logger import get_logger
from utils.news import deduplicate_news, normalize_url
from utils.storage_collections import CollectionStorage
from utils.storage_initialization import DatabaseInitializer, load_json_list
from utils.storage_maintenance import DatabaseMaintenance
from utils.storage_monitoring import MonitoringStorage
from utils.storage_news import NewsStorage
from utils.storage_news_persistence import NewsPersistenceStorage
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


def _load_json(path):
    """Совместимый помощник для небольших служебных JSON-массивов."""
    return load_json_list(path, logger)


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
    database_change_signature=lambda: _database_change_signature(),
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

_DATABASE_INITIALIZER = DatabaseInitializer(
    database_file=lambda: DATABASE_FILE,
    all_news_file=lambda: ALL_NEWS_FILE,
    found_news_file=lambda: FOUND_NEWS_FILE,
    connection_factory=lambda: _connection(),
    create_schema=_create_schema,
    database_stats=lambda connection: database_stats(connection=connection),
    replace_collections=lambda connection, all_news, found_news: (
        _replace_collections(connection, all_news, found_news)
    ),
    deduplicate_news=deduplicate_news,
    news_key=lambda item: _news_key(item),
    lock=STORAGE_LOCK,
    migration_key=JSON_MIGRATION_KEY,
    logger=logger,
    now=lambda: datetime.now(),
)


def initialize_database():
    """Создаёт базу и один раз переносит старые JSON-файлы."""
    return _DATABASE_INITIALIZER.initialize_database()


_NEWS_PERSISTENCE = NewsPersistenceStorage(
    initialize_database=lambda: initialize_database(),
    connect=lambda: _connect(),
    connection_factory=lambda: _connection(),
    lock=STORAGE_LOCK,
    database_file=lambda: DATABASE_FILE,
    logger=logger,
    load_all_news=lambda: load_all_news(),
    load_found_news=lambda: load_found_news(),
    load_collection=lambda connection, table: _load_collection(
        connection, table
    ),
    max_cached_article_chars=MAX_CACHED_ARTICLE_CHARS,
    now=lambda: datetime.now(),
)


def _database_change_signature():
    return _NEWS_PERSISTENCE.database_change_signature()


def load_all_news():
    return _NEWS_PERSISTENCE.load_all_news()


def load_found_news():
    return _NEWS_PERSISTENCE.load_found_news()


def _load_collection_cached(table):
    """Не разбирает десятки тысяч JSON-записей заново на каждой странице."""
    return _NEWS_PERSISTENCE.load_collection_cached(table)


def find_news_by_url(url):
    """Находит одну публикацию без загрузки всей базы в веб-приложение."""
    return _NEWS_PERSISTENCE.find_news_by_url(url)


def load_cached_article(url):
    """Возвращает сохранённый текст статьи, если её уже открывали."""
    return _NEWS_PERSISTENCE.load_cached_article(url)


def save_cached_article(url, article, source=""):
    """Сохраняет только успешный очищенный текст открытой статьи."""
    return _NEWS_PERSISTENCE.save_cached_article(url, article, source)


def load_existing_urls():
    return _NEWS_PERSISTENCE.load_existing_urls()


def save_results(all_news, found_news, existing_urls):
    return _NEWS_PERSISTENCE.save_results(
        all_news, found_news, existing_urls
    )


def _save_results(all_news, found_news, existing_urls):
    return _NEWS_PERSISTENCE._save_results(
        all_news, found_news, existing_urls
    )


def replace_found_news(items):
    """Полностью пересобирает таблицу совпадений после изменения слов."""
    return _NEWS_PERSISTENCE.replace_found_news(items)


_DATABASE_MAINTENANCE = DatabaseMaintenance(
    initialize_database=lambda: initialize_database(),
    connect=lambda: _connect(),
    lock=STORAGE_LOCK,
    database_file=lambda: DATABASE_FILE,
    backup_dir=lambda: BACKUP_DIR,
    json_migration_key=JSON_MIGRATION_KEY,
    logger=logger,
)


def database_stats(connection=None):
    """Возвращает краткую статистику и результат проверки целостности."""
    return _DATABASE_MAINTENANCE.database_stats(connection)


def backup_database(destination=None):
    """Атомарно создаёт и проверяет копию работающей SQLite-базы."""
    return _DATABASE_MAINTENANCE.backup_database(destination)


def ensure_daily_backup(retention=7, now=None):
    """Создаёт не больше одной автоматической копии в день."""
    return _DATABASE_MAINTENANCE.ensure_daily_backup(retention, now)


def create_manual_backup(retention=10, now=None):
    """Создаёт подписанную ручную копию и оставляет последние снимки."""
    return _DATABASE_MAINTENANCE.create_manual_backup(retention, now)


def list_database_backups():
    """Перечисляет автоматические и ручные резервные копии базы."""
    return _DATABASE_MAINTENANCE.list_database_backups()


def prepare_database(retention=7):
    """Проверяет рабочую базу и создаёт ежедневную резервную копию."""
    return _DATABASE_MAINTENANCE.prepare_database(retention)


def _automatic_backup_pattern():
    return _DATABASE_MAINTENANCE._automatic_backup_pattern()


def _list_automatic_backups():
    return _DATABASE_MAINTENANCE._list_automatic_backups()


def _remove_old_backups(retention):
    return _DATABASE_MAINTENANCE._remove_old_backups(retention)


def _remove_old_manual_backups(retention):
    return _DATABASE_MAINTENANCE._remove_old_manual_backups(retention)

def _replace_collections(connection, all_news, found_news):
    """Заменяет обе коллекции в одной транзакции: либо всё, либо ничего."""
    return _NEWS_PERSISTENCE.replace_collections(
        connection, all_news, found_news
    )


def _insert_news_items(connection, items, first_seen_by_key=None):
    return _NEWS_PERSISTENCE.insert_news_items(
        connection, items, first_seen_by_key
    )


def _insert_found_items(connection, items):
    return _NEWS_PERSISTENCE.insert_found_items(connection, items)


def _load_collection(connection, table):
    return _NEWS_PERSISTENCE.load_collection(connection, table)


def _encode_item(item):
    return _NEWS_PERSISTENCE.encode_item(item)


def _decode_item(payload):
    return _NEWS_PERSISTENCE.decode_item(payload)


def _attach_news_display_fields(item, parsed_date, first_seen_at):
    """Добавляет готовые дату публикации и время первого получения."""
    return _NEWS_PERSISTENCE.attach_news_display_fields(
        item, parsed_date, first_seen_at
    )


def _clean_cached_paragraphs(paragraphs):
    return _NEWS_PERSISTENCE.clean_cached_paragraphs(paragraphs)


def _news_key(item):
    return _NEWS_PERSISTENCE.news_key(item)


def _sort_items(items):
    return _NEWS_PERSISTENCE.sort_items(items)
