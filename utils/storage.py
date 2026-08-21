"""SQLite-хранилище новостей и безопасные JSON-помощники."""

import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock

from werkzeug.security import check_password_hash, generate_password_hash

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

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
                CHECK(role IN ('admin', 'user')),
            is_active INTEGER NOT NULL DEFAULT 1
                CHECK(is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            last_login_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS bookmark_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT '',
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookmark_folder_shares (
            folder_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(folder_id, user_id),
            FOREIGN KEY(folder_id) REFERENCES bookmark_folders(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS collection_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            publication_date TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(folder_id) REFERENCES bookmark_folders(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            folder_id INTEGER,
            normalized_url TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            publication_date TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_url),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(folder_id) REFERENCES bookmark_folders(id)
                ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS user_source_orders (
            user_id INTEGER NOT NULL,
            source_group TEXT NOT NULL,
            source_order_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, source_group),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS source_settings (
            source TEXT PRIMARY KEY COLLATE NOCASE,
            enabled INTEGER NOT NULL DEFAULT 1
                CHECK(enabled IN (0, 1)),
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS parser_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'running', 'success', 'error')),
            requested_by INTEGER,
            requested_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS source_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_key TEXT NOT NULL,
            source TEXT NOT NULL,
            code TEXT NOT NULL CHECK(code IN ('error', 'empty')),
            level TEXT NOT NULL CHECK(level IN ('warning', 'critical')),
            title TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            resolved_at TEXT NOT NULL DEFAULT '',
            resolution TEXT NOT NULL DEFAULT '',
            checks_count INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_news_source
            ON news_items(source);
        CREATE INDEX IF NOT EXISTS idx_news_publication_date
            ON news_items(publication_date DESC, parsed_date DESC);
        CREATE INDEX IF NOT EXISTS idx_news_normalized_url
            ON news_items(normalized_url);
        CREATE INDEX IF NOT EXISTS idx_users_role
            ON users(role, is_active);
        CREATE INDEX IF NOT EXISTS idx_bookmark_folders_user
            ON bookmark_folders(user_id, name);
        CREATE INDEX IF NOT EXISTS idx_bookmarks_user
            ON bookmarks(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_bookmarks_folder
            ON bookmarks(user_id, folder_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_bookmark_folder_shares_user
            ON bookmark_folder_shares(user_id, folder_id);
        CREATE INDEX IF NOT EXISTS idx_collection_notes_folder
            ON collection_notes(folder_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_user_source_orders_user
            ON user_source_orders(user_id, source_group);
        CREATE INDEX IF NOT EXISTS idx_parser_jobs_status
            ON parser_jobs(status, requested_at);
        CREATE INDEX IF NOT EXISTS idx_parser_jobs_source
            ON parser_jobs(source, id DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_source_incidents_active
            ON source_incidents(incident_key) WHERE resolved_at = '';
        CREATE INDEX IF NOT EXISTS idx_source_incidents_history
            ON source_incidents(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_source_incidents_source
            ON source_incidents(source, started_at DESC);
        """
    )

    columns = {
        row["name"] for row in connection.execute(
            "PRAGMA table_info(bookmark_folders)"
        ).fetchall()
    }
    if "description" not in columns:
        connection.execute(
            "ALTER TABLE bookmark_folders ADD COLUMN description TEXT NOT NULL DEFAULT ''"
        )
    if "visibility" not in columns:
        connection.execute(
            "ALTER TABLE bookmark_folders ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'"
        )
    if "updated_at" not in columns:
        connection.execute(
            "ALTER TABLE bookmark_folders ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )
    if "sort_order" not in columns:
        connection.execute(
            "ALTER TABLE bookmark_folders ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
        )
        users = connection.execute(
            "SELECT DISTINCT user_id FROM bookmark_folders"
        ).fetchall()
        for user in users:
            folders = connection.execute(
                """SELECT id FROM bookmark_folders WHERE user_id = ?
                   ORDER BY name COLLATE NOCASE, id""",
                (user["user_id"],),
            ).fetchall()
            connection.executemany(
                "UPDATE bookmark_folders SET sort_order = ? WHERE id = ?",
                [(position, folder["id"]) for position, folder in enumerate(folders)],
            )

    note_columns = {
        row["name"] for row in connection.execute(
            "PRAGMA table_info(collection_notes)"
        ).fetchall()
    }
    for name in ("url", "source", "publication_date", "comment"):
        if name not in note_columns:
            connection.execute(
                f"ALTER TABLE collection_notes ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
            )


def count_users():
    """Возвращает число учётных записей, включая отключённые."""
    initialize_database()
    with _connection() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def create_user(username, password, role="user"):
    """Создаёт пользователя с хешем пароля; открытый пароль не хранится."""
    username = _validate_username(username)
    password = _validate_password(password)
    role = str(role or "user").strip().casefold()
    if role not in {"admin", "user"}:
        raise ValueError("Неизвестная роль пользователя")

    initialize_database()
    created_at = datetime.now().isoformat(timespec="seconds")
    try:
        with STORAGE_LOCK, _connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(
                    username, password_hash, role, is_active, created_at
                ) VALUES (?, ?, ?, 1, ?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    created_at,
                ),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Пользователь с таким именем уже существует") from error
    return load_user(user_id)


def load_user(user_id):
    """Возвращает безопасные поля пользователя без хеша пароля."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT id, username, role, is_active, created_at, last_login_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return _user_from_row(row)


def list_users():
    """Возвращает безопасный список пользователей без хешей паролей."""
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, username, role, is_active, created_at, last_login_at
            FROM users
            ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END,
                     username COLLATE NOCASE
            """
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def set_user_password(user_id, password):
    """Заменяет пароль пользователя новым защищённым хешем."""
    password = _validate_password(password)
    user = load_user(user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    with STORAGE_LOCK, _connection() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user["id"]),
        )
    return load_user(user["id"])


def set_user_role(user_id, role):
    """Меняет роль, не позволяя убрать последнего активного администратора."""
    role = str(role or "").strip().casefold()
    if role not in {"admin", "user"}:
        raise ValueError("Неизвестная роль пользователя")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Пользователь не найден") from error

    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT role, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Пользователь не найден")
        if row["role"] == "admin" and role != "admin" and row["is_active"]:
            active_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError("Нельзя понизить последнего активного администратора")
        connection.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (role, user_id),
        )
    return load_user(user_id)


def set_user_active(user_id, is_active):
    """Включает или отключает вход, сохраняя все данные пользователя."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Пользователь не найден") from error
    is_active = bool(is_active)

    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT role, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Пользователь не найден")
        if row["role"] == "admin" and row["is_active"] and not is_active:
            active_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError("Нельзя отключить последнего активного администратора")
        connection.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (int(is_active), user_id),
        )
    return load_user(user_id)


def authenticate_user(username, password):
    """Проверяет пароль и возвращает активного пользователя."""
    username = " ".join(str(username or "").split())
    password = str(password or "")
    if not username or not password:
        return None
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, role, is_active,
                   created_at, last_login_at
            FROM users WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()
        if (
            row is None
            or not bool(row["is_active"])
            or not check_password_hash(row["password_hash"], password)
        ):
            return None
        logged_at = datetime.now().isoformat(timespec="seconds")
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (logged_at, row["id"]),
        )
    user = _user_from_row(row)
    user["last_login_at"] = logged_at
    return user


def load_source_order(user_id, source_group):
    """Возвращает личный порядок источников для одного раздела."""
    user_id = _validated_user_id(user_id)
    source_group = _validated_source_group(source_group)
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT source_order_json
            FROM user_source_orders
            WHERE user_id = ? AND source_group = ?
            """,
            (user_id, source_group),
        ).fetchone()
    if row is None:
        return []
    try:
        values = json.loads(row["source_order_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    for value in values:
        source = " ".join(str(value or "").split())[:300]
        if source and source.casefold() not in seen:
            seen.add(source.casefold())
            result.append(source)
    return result


def save_source_order(user_id, source_group, sources):
    """Сохраняет личный порядок источников, не затрагивая других пользователей."""
    user_id = _validated_user_id(user_id)
    source_group = _validated_source_group(source_group)
    if not isinstance(sources, list) or len(sources) > 500:
        raise ValueError("Некорректный список источников")
    order = []
    seen = set()
    for value in sources:
        source = " ".join(str(value or "").split())
        key = source.casefold()
        if not source or len(source) > 300 or key in seen:
            continue
        seen.add(key)
        order.append(source)
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        connection.execute(
            """
            INSERT INTO user_source_orders(
                user_id, source_group, source_order_json, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, source_group) DO UPDATE SET
                source_order_json = excluded.source_order_json,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                source_group,
                json.dumps(order, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    return order


def source_is_enabled(source):
    """По умолчанию источник включён; администратор может поставить его на паузу."""
    source = _validated_source_name(source)
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            "SELECT enabled FROM source_settings WHERE source = ? COLLATE NOCASE",
            (source,),
        ).fetchone()
    return True if row is None else bool(row["enabled"])


def load_source_settings():
    """Возвращает сохранённые администратором состояния источников."""
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            "SELECT source, enabled, updated_at FROM source_settings"
        ).fetchall()
    return {
        row["source"]: {
            "enabled": bool(row["enabled"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    }


def set_source_enabled(source, enabled):
    """Включает источник или временно исключает его из расписания."""
    source = _validated_source_name(source)
    enabled = bool(enabled)
    updated_at = datetime.now().isoformat(timespec="seconds")
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        connection.execute(
            """
            INSERT INTO source_settings(source, enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (source, int(enabled), updated_at),
        )
    return {"source": source, "enabled": enabled, "updated_at": updated_at}


def enqueue_parser_job(source, requested_by=None):
    """Ставит одиночную проверку в очередь, не создавая повторных заданий."""
    source = _validated_source_name(source)
    requested_by = _validated_optional_user_id(requested_by)
    requested_at = datetime.now().isoformat(timespec="seconds")
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            """
            SELECT * FROM parser_jobs
            WHERE source = ? COLLATE NOCASE
              AND status IN ('pending', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (source,),
        ).fetchone()
        if existing is not None:
            return _parser_job_from_row(existing)
        cursor = connection.execute(
            """
            INSERT INTO parser_jobs(source, status, requested_by, requested_at)
            VALUES (?, 'pending', ?, ?)
            """,
            (source, requested_by, requested_at),
        )
        row = connection.execute(
            "SELECT * FROM parser_jobs WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _parser_job_from_row(row)


def claim_next_parser_job():
    """Атомарно забирает одно ожидающее задание для процесса main.py."""
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        now = datetime.now()
        stale_before = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        finished_at = now.isoformat(timespec="seconds")
        connection.execute(
            """
            UPDATE parser_jobs
            SET status = 'error', finished_at = ?,
                error = 'Задание прервано: основной процесс был перезапущен'
            WHERE status = 'running'
              AND started_at != ''
              AND started_at < ?
            """,
            (finished_at, stale_before),
        )
        row = connection.execute(
            """
            SELECT * FROM parser_jobs
            WHERE status = 'pending'
            ORDER BY id LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        started_at = now.isoformat(timespec="seconds")
        connection.execute(
            "UPDATE parser_jobs SET status = 'running', started_at = ? WHERE id = ?",
            (started_at, row["id"]),
        )
        row = connection.execute(
            "SELECT * FROM parser_jobs WHERE id = ?",
            (row["id"],),
        ).fetchone()
    return _parser_job_from_row(row)


def finish_parser_job(job_id, success, error=""):
    """Фиксирует результат ручной проверки источника."""
    try:
        job_id = int(job_id)
    except (TypeError, ValueError) as validation_error:
        raise ValueError("Задание не найдено") from validation_error
    status = "success" if success else "error"
    finished_at = datetime.now().isoformat(timespec="seconds")
    error = " ".join(str(error or "").split())[:1000]
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE parser_jobs
            SET status = ?, finished_at = ?, error = ?
            WHERE id = ? AND status = 'running'
            """,
            (status, finished_at, error, job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Задание не найдено или уже завершено")


def list_parser_jobs(limit=50):
    """Возвращает последние ручные проверки для администраторской панели."""
    try:
        limit = min(200, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT j.*, u.username AS requested_by_name
            FROM parser_jobs AS j
            LEFT JOIN users AS u ON u.id = j.requested_by
            ORDER BY j.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_parser_job_from_row(row) for row in rows]


def source_news_statistics():
    """Считает накопленные новости и дату последнего нового материала."""
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT source, COUNT(*) AS news_count,
                   MAX(publication_date) AS newest_publication,
                   MAX(parsed_date) AS last_received
            FROM news_items
            GROUP BY source
            """
        ).fetchall()
    return {
        row["source"]: {
            "news_count": int(row["news_count"]),
            "newest_publication": row["newest_publication"] or "",
            "last_received": row["last_received"] or "",
        }
        for row in rows
    }


def sync_source_incidents(statuses, now=None):
    """Открывает и закрывает инциденты по результатам реальных проверок."""
    moment = now or datetime.now()
    checked_at = moment.isoformat(timespec="seconds")
    changes = {"opened": 0, "updated": 0, "resolved": 0}
    initialize_database()

    with STORAGE_LOCK, _connection() as connection:
        for raw_item in statuses:
            if not isinstance(raw_item, dict):
                continue
            source = " ".join(str(raw_item.get("source", "")).split())
            if not source:
                continue
            status = str(raw_item.get("status", "")).strip().casefold()
            active_rows = connection.execute(
                """
                SELECT * FROM source_incidents
                WHERE source = ? AND resolved_at = ''
                ORDER BY id
                """,
                (source,),
            ).fetchall()

            active_code = status if status in {"error", "empty"} else ""
            incident_key = f"{source}:{active_code}" if active_code else ""
            current = next(
                (row for row in active_rows if row["incident_key"] == incident_key),
                None,
            )

            for row in active_rows:
                if current is not None and row["id"] == current["id"]:
                    continue
                resolution = "Источник отключён" if status == "disabled" else "Работа восстановлена"
                connection.execute(
                    """
                    UPDATE source_incidents
                    SET resolved_at = ?, resolution = ?
                    WHERE id = ?
                    """,
                    (checked_at, resolution, row["id"]),
                )
                changes["resolved"] += 1

            if not active_code:
                continue

            failure_streak = _non_negative_int(raw_item.get("failure_streak"))
            level = "critical" if failure_streak >= 3 else "warning"
            title = (
                f"{source}: ошибка парсинга"
                if active_code == "error"
                else f"{source}: пустая выдача"
            )
            message = str(raw_item.get("error", "")).strip()
            if not message and active_code == "empty":
                message = "Парсер вернул 0 материалов"

            if current is None:
                connection.execute(
                    """
                    INSERT INTO source_incidents(
                        incident_key, source, code, level, title, message,
                        started_at, last_seen_at, checks_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        incident_key,
                        source,
                        active_code,
                        level,
                        title,
                        message,
                        checked_at,
                        checked_at,
                    ),
                )
                changes["opened"] += 1
            else:
                connection.execute(
                    """
                    UPDATE source_incidents
                    SET level = ?, title = ?, message = ?, last_seen_at = ?,
                        checks_count = checks_count + 1
                    WHERE id = ?
                    """,
                    (level, title, message, checked_at, current["id"]),
                )
                changes["updated"] += 1

    return changes


def list_source_incidents(state="all", limit=200):
    """Возвращает последние инциденты для администраторского журнала."""
    state = str(state or "all").strip().casefold()
    if state not in {"all", "active", "resolved"}:
        raise ValueError("Неизвестный фильтр инцидентов")
    try:
        limit = min(500, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = 200
    where = {
        "all": "",
        "active": "WHERE resolved_at = ''",
        "resolved": "WHERE resolved_at != ''",
    }[state]
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM source_incidents
            {where}
            ORDER BY CASE WHEN resolved_at = '' THEN 0 ELSE 1 END,
                     started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_incident_from_row(row) for row in rows]


def source_incident_statistics(now=None):
    """Считает активные, критические и недавно закрытые инциденты."""
    moment = now or datetime.now()
    since = (moment - timedelta(hours=24)).isoformat(timespec="seconds")
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN resolved_at = '' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN resolved_at = '' AND level = 'critical' THEN 1 ELSE 0 END) AS critical,
                SUM(CASE WHEN resolved_at >= ? THEN 1 ELSE 0 END) AS resolved_24h
            FROM source_incidents
            """,
            (since,),
        ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "active": int(row["active"] or 0),
        "critical": int(row["critical"] or 0),
        "resolved_24h": int(row["resolved_24h"] or 0),
    }


def source_reliability_statistics(days=7, now=None, sources=None):
    """Считает доступность источников по времени записанных инцидентов."""
    try:
        days = min(365, max(1, int(days)))
    except (TypeError, ValueError):
        days = 7
    moment = now or datetime.now()
    period_start = moment - timedelta(days=days)
    period_seconds = max(1, int((moment - period_start).total_seconds()))
    start_text = period_start.isoformat(timespec="seconds")
    end_text = moment.isoformat(timespec="seconds")
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM source_incidents
            WHERE started_at < ?
              AND (resolved_at = '' OR resolved_at > ?)
            ORDER BY source COLLATE NOCASE, started_at
            """,
            (end_text, start_text),
        ).fetchall()

    by_source = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(dict(row))
    names = {
        " ".join(str(source or "").split())
        for source in (sources or ())
        if " ".join(str(source or "").split())
    }
    names.update(by_source)

    result = []
    for source in names:
        incidents = by_source.get(source, [])
        intervals = []
        critical_count = 0
        active_count = 0
        checks_count = 0
        for incident in incidents:
            started = _storage_datetime(incident.get("started_at"))
            resolved = _storage_datetime(incident.get("resolved_at"))
            if started is None:
                continue
            interval_start = max(period_start, started)
            interval_end = min(moment, resolved or moment)
            if interval_end <= interval_start:
                continue
            intervals.append((interval_start, interval_end))
            critical_count += incident.get("level") == "critical"
            active_count += not bool(incident.get("resolved_at"))
            checks_count += _non_negative_int(incident.get("checks_count"))

        merged = []
        for interval_start, interval_end in sorted(intervals):
            if not merged or interval_start > merged[-1][1]:
                merged.append([interval_start, interval_end])
            elif interval_end > merged[-1][1]:
                merged[-1][1] = interval_end
        downtime = sum(
            max(0, int((interval_end - interval_start).total_seconds()))
            for interval_start, interval_end in merged
        )
        uptime = max(0.0, 100.0 * (period_seconds - downtime) / period_seconds)
        result.append({
            "source": source,
            "uptime_percent": round(uptime, 3),
            "downtime_seconds": downtime,
            "incident_count": len(intervals),
            "critical_count": critical_count,
            "active_count": active_count,
            "checks_count": checks_count,
            "average_incident_seconds": (
                int(downtime / len(intervals)) if intervals else 0
            ),
        })

    return sorted(
        result,
        key=lambda item: (
            item["uptime_percent"],
            -item["downtime_seconds"],
            item["source"].casefold(),
        ),
    )


def _incident_from_row(row, now=None):
    item = dict(row)
    moment = now or datetime.now()
    started = _storage_datetime(item.get("started_at"))
    finished = _storage_datetime(item.get("resolved_at")) or moment
    seconds = max(0, int((finished - started).total_seconds())) if started else 0
    item["is_active"] = not bool(item.get("resolved_at"))
    item["duration_seconds"] = seconds
    return item


def _storage_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or ""))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _non_negative_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def list_bookmark_folders(user_id):
    """Возвращает только папки указанного пользователя и число материалов."""
    user_id = _validated_user_id(user_id)
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT f.id, f.name, f.description, f.visibility,
                   f.sort_order, f.created_at, f.updated_at,
                   COUNT(DISTINCT b.id) AS bookmark_count,
                   COUNT(DISTINCT n.id) AS note_count
            FROM bookmark_folders AS f
            LEFT JOIN bookmarks AS b
              ON b.folder_id = f.id AND b.user_id = f.user_id
            LEFT JOIN collection_notes AS n ON n.folder_id = f.id
            WHERE f.user_id = ?
            GROUP BY f.id
            ORDER BY f.sort_order, f.name COLLATE NOCASE, f.id
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "visibility": row["visibility"],
            "sort_order": int(row["sort_order"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "bookmark_count": int(row["bookmark_count"]),
            "note_count": int(row["note_count"]),
        }
        for row in rows
    ]


def create_bookmark_folder(user_id, name):
    """Создаёт личную папку с уникальным для пользователя названием."""
    user_id = _validated_user_id(user_id)
    name = _validated_folder_name(name)
    initialize_database()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with STORAGE_LOCK, _connection() as connection:
            sort_order = int(
                connection.execute(
                    """SELECT COALESCE(MAX(sort_order), -1) + 1
                       FROM bookmark_folders WHERE user_id = ?""",
                    (user_id,),
                ).fetchone()[0]
            )
            cursor = connection.execute(
                """INSERT INTO bookmark_folders(
                       user_id, name, sort_order, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (user_id, name, sort_order, now, now),
            )
            folder_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Папка с таким названием уже существует") from error
    return next(
        folder for folder in list_bookmark_folders(user_id)
        if folder["id"] == folder_id
    )


def rename_bookmark_folder(user_id, folder_id, name):
    """Переименовывает только принадлежащую пользователю папку."""
    user_id = _validated_user_id(user_id)
    folder_id = _validated_folder_id(folder_id)
    name = _validated_folder_name(name)
    initialize_database()
    try:
        with STORAGE_LOCK, _connection() as connection:
            cursor = connection.execute(
                "UPDATE bookmark_folders SET name = ? WHERE id = ? AND user_id = ?",
                (name, folder_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Папка не найдена")
    except sqlite3.IntegrityError as error:
        raise ValueError("Папка с таким названием уже существует") from error
    return next(
        folder for folder in list_bookmark_folders(user_id)
        if folder["id"] == folder_id
    )


def delete_bookmark_folder(user_id, folder_id):
    """Удаляет папку; её закладки остаются в разделе «Без папки»."""
    user_id = _validated_user_id(user_id)
    folder_id = _validated_folder_id(folder_id)
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM bookmark_folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Папка не найдена")


def save_bookmark_folder_order(user_id, folder_ids):
    """Сохраняет полный личный порядок подборок после перетаскивания."""
    user_id = _validated_user_id(user_id)
    if not isinstance(folder_ids, list):
        raise ValueError("Некорректный порядок подборок")
    requested = []
    for value in folder_ids:
        try:
            folder_id = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Некорректный порядок подборок") from error
        if folder_id < 1 or folder_id in requested:
            raise ValueError("Некорректный порядок подборок")
        requested.append(folder_id)
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        owned = {
            int(row["id"]) for row in connection.execute(
                "SELECT id FROM bookmark_folders WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        }
        if set(requested) != owned:
            raise ValueError("Список подборок изменился. Обнови страницу")
        connection.executemany(
            "UPDATE bookmark_folders SET sort_order = ? WHERE id = ? AND user_id = ?",
            [(position, folder_id, user_id) for position, folder_id in enumerate(requested)],
        )
    return list_bookmark_folders(user_id)


def update_collection(user_id, folder_id, name, description="", visibility="private",
                      shared_user_ids=None):
    """Обновляет подборку и её наследуемый доступ только от имени владельца."""
    user_id = _validated_user_id(user_id)
    folder_id = _owned_folder_id(user_id, folder_id)
    name = _validated_folder_name(name)
    description = str(description or "").strip()
    if len(description) > 1000:
        raise ValueError("Описание не должно превышать 1000 символов")
    visibility = str(visibility or "private").strip().casefold()
    if visibility not in {"private", "all", "selected"}:
        raise ValueError("Неизвестный режим доступа")
    requested_ids = set()
    for value in shared_user_ids or []:
        shared_id = _validated_user_id(value)
        if shared_id != user_id:
            requested_ids.add(shared_id)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with STORAGE_LOCK, _connection() as connection:
            connection.execute(
                """UPDATE bookmark_folders
                   SET name = ?, description = ?, visibility = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (name, description, visibility, now, folder_id, user_id),
            )
            connection.execute(
                "DELETE FROM bookmark_folder_shares WHERE folder_id = ?",
                (folder_id,),
            )
            if visibility == "selected":
                connection.executemany(
                    """INSERT INTO bookmark_folder_shares(folder_id, user_id, created_at)
                       VALUES (?, ?, ?)""",
                    [(folder_id, shared_id, now) for shared_id in sorted(requested_ids)],
                )
    except sqlite3.IntegrityError as error:
        raise ValueError("Подборка с таким названием уже существует") from error
    return load_collection(user_id, folder_id)


def load_collection(user_id, folder_id):
    """Возвращает доступную подборку и отмечает права текущего пользователя."""
    user_id = _validated_user_id(user_id)
    folder_id = _validated_folder_id(folder_id)
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """SELECT f.*, u.username AS owner_name,
                      CASE WHEN f.user_id = ? THEN 1 ELSE 0 END AS can_edit
               FROM bookmark_folders AS f
               JOIN users AS u ON u.id = f.user_id
               WHERE f.id = ? AND (
                   f.user_id = ? OR f.visibility = 'all' OR EXISTS(
                       SELECT 1 FROM bookmark_folder_shares AS s
                       WHERE s.folder_id = f.id AND s.user_id = ?
                   )
               )""",
            (user_id, folder_id, user_id, user_id),
        ).fetchone()
        if row is None:
            return None
        shared_rows = connection.execute(
            """SELECT u.id, u.username FROM bookmark_folder_shares AS s
               JOIN users AS u ON u.id = s.user_id
               WHERE s.folder_id = ? ORDER BY u.username COLLATE NOCASE""",
            (folder_id,),
        ).fetchall()
    return {
        "id": int(row["id"]), "user_id": int(row["user_id"]),
        "name": row["name"], "description": row["description"],
        "visibility": row["visibility"], "owner_name": row["owner_name"],
        "sort_order": int(row["sort_order"]),
        "can_edit": bool(row["can_edit"]),
        "shared_users": [dict(id=int(item["id"]), username=item["username"])
                         for item in shared_rows],
    }


def list_shared_collections(user_id):
    """Показывает подборки других владельцев, доступные пользователю."""
    user_id = _validated_user_id(user_id)
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """SELECT f.id, f.name, f.description, f.visibility,
                      u.username AS owner_name,
                      COUNT(DISTINCT b.id) AS bookmark_count,
                      COUNT(DISTINCT n.id) AS note_count
               FROM bookmark_folders AS f
               JOIN users AS u ON u.id = f.user_id
               LEFT JOIN bookmarks AS b ON b.folder_id = f.id
               LEFT JOIN collection_notes AS n ON n.folder_id = f.id
               WHERE f.user_id != ? AND (f.visibility = 'all' OR EXISTS(
                   SELECT 1 FROM bookmark_folder_shares AS s
                   WHERE s.folder_id = f.id AND s.user_id = ?
               ))
               GROUP BY f.id ORDER BY f.sort_order, f.name COLLATE NOCASE, f.id""",
            (user_id, user_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_collection_bookmarks(user_id, folder_id):
    collection = load_collection(user_id, folder_id)
    if collection is None:
        raise ValueError("Подборка не найдена")
    with _connection() as connection:
        rows = connection.execute(
            """SELECT b.*, f.name AS folder_name FROM bookmarks AS b
               JOIN bookmark_folders AS f ON f.id = b.folder_id
               WHERE b.folder_id = ? ORDER BY b.updated_at DESC, b.id DESC""",
            (collection["id"],),
        ).fetchall()
    return [_bookmark_from_row(row) for row in rows]


def save_external_bookmark(user_id, folder_id, url, title, note=""):
    """Добавляет в собственную подборку ссылку, которой нет в ленте."""
    normalized = normalize_url(str(url or "").strip())
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("Укажи полный адрес, начинающийся с http:// или https://")
    title = " ".join(str(title or "").split())[:1000]
    if not title:
        raise ValueError("Укажи название материала")
    return save_bookmark(
        user_id,
        {"url": normalized, "title": title, "source": "Внешний источник", "date": ""},
        folder_id,
        note,
    )


def _validated_collection_note_fields(title, body, url="", source="",
                                      publication_date="", comment=""):
    """Проверяет и нормализует редактируемые поля заметки."""
    title = " ".join(str(title or "").split())
    body = str(body or "").strip()
    raw_url = str(url or "").strip()
    normalized_url = normalize_url(raw_url) if raw_url else ""
    if raw_url and not normalized_url.startswith(("http://", "https://")):
        raise ValueError("Укажи полный адрес, начинающийся с http:// или https://")
    source = " ".join(str(source or "").split())
    if len(source) > 300:
        raise ValueError("Источник не должен превышать 300 символов")
    publication_date = str(publication_date or "").strip()
    if publication_date:
        try:
            datetime.strptime(publication_date, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("Дата публикации указана неверно") from error
    comment = _validated_bookmark_note(comment)
    if not 1 <= len(title) <= 200:
        raise ValueError("Заголовок заметки должен содержать от 1 до 200 символов")
    if len(body) > 20_000:
        raise ValueError("Текст заметки не должен превышать 20000 символов")
    return title, body, normalized_url, source, publication_date, comment


def save_collection_note(user_id, folder_id, title, body, url="", source="",
                         publication_date="", comment=""):
    """Добавляет в подборку заметку или вручную сохранённую статью."""
    user_id = _validated_user_id(user_id)
    folder_id = _owned_folder_id(user_id, folder_id)
    fields = _validated_collection_note_fields(
        title, body, url, source, publication_date, comment,
    )
    now = datetime.now().isoformat(timespec="seconds")
    with STORAGE_LOCK, _connection() as connection:
        cursor = connection.execute(
            """INSERT INTO collection_notes(
                   folder_id, user_id, title, body, url, source,
                   publication_date, comment, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (folder_id, user_id, *fields, now, now),
        )
    return cursor.lastrowid


def update_collection_note(user_id, folder_id, note_id, title, body, url="",
                           source="", publication_date="", comment=""):
    """Обновляет существующую заметку владельца без создания дубликата."""
    user_id = _validated_user_id(user_id)
    folder_id = _owned_folder_id(user_id, folder_id)
    try:
        note_id = int(note_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Заметка не найдена") from error
    fields = _validated_collection_note_fields(
        title, body, url, source, publication_date, comment,
    )
    now = datetime.now().isoformat(timespec="seconds")
    with STORAGE_LOCK, _connection() as connection:
        cursor = connection.execute(
            """UPDATE collection_notes
               SET title = ?, body = ?, url = ?, source = ?,
                   publication_date = ?, comment = ?, updated_at = ?
               WHERE id = ? AND folder_id = ? AND user_id = ?""",
            (*fields, now, note_id, folder_id, user_id),
        )
    if cursor.rowcount != 1:
        raise ValueError("Заметка не найдена")
    return note_id


def list_collection_notes(user_id, folder_id):
    collection = load_collection(user_id, folder_id)
    if collection is None:
        raise ValueError("Подборка не найдена")
    with _connection() as connection:
        rows = connection.execute(
            """SELECT id, title, body, url, source, publication_date, comment,
                      created_at, updated_at
               FROM collection_notes WHERE folder_id = ?
               ORDER BY updated_at DESC, id DESC""",
            (collection["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_collection_note(user_id, folder_id, note_id):
    user_id = _validated_user_id(user_id)
    folder_id = _owned_folder_id(user_id, folder_id)
    with STORAGE_LOCK, _connection() as connection:
        cursor = connection.execute(
            """DELETE FROM collection_notes
               WHERE id = ? AND folder_id = ? AND user_id = ?""",
            (int(note_id), folder_id, user_id),
        )
    if cursor.rowcount != 1:
        raise ValueError("Заметка не найдена")


def save_bookmark(user_id, item, folder_id=None, note=""):
    """Сохраняет снимок новости в личных закладках пользователя."""
    user_id = _validated_user_id(user_id)
    if not isinstance(item, dict):
        raise ValueError("Новость не найдена")
    normalized = normalize_url(item.get("url", ""))
    title = " ".join(str(item.get("title", "")).split())[:1000]
    if not normalized or not title:
        raise ValueError("Новость не найдена")
    folder_id = _owned_folder_id(user_id, folder_id)
    note = _validated_bookmark_note(note)
    now = datetime.now().isoformat(timespec="seconds")
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        connection.execute(
            """
            INSERT INTO bookmarks(
                user_id, folder_id, normalized_url, url, source, title,
                publication_date, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, normalized_url) DO UPDATE SET
                folder_id = COALESCE(excluded.folder_id, bookmarks.folder_id),
                url = excluded.url,
                source = excluded.source,
                title = excluded.title,
                publication_date = excluded.publication_date,
                note = CASE WHEN excluded.note != '' THEN excluded.note ELSE bookmarks.note END,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                folder_id,
                normalized,
                item.get("url", ""),
                str(item.get("source", ""))[:300],
                title,
                str(item.get("date", ""))[:50],
                note,
                now,
                now,
            ),
        )
    return load_bookmark(user_id, normalized)


def update_bookmark(user_id, url, folder_id=None, note=""):
    """Перемещает личную закладку и сохраняет заметку пользователя."""
    user_id = _validated_user_id(user_id)
    normalized = normalize_url(url)
    folder_id = _owned_folder_id(user_id, folder_id)
    note = _validated_bookmark_note(note)
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE bookmarks
            SET folder_id = ?, note = ?, updated_at = ?
            WHERE user_id = ? AND normalized_url = ?
            """,
            (
                folder_id,
                note,
                datetime.now().isoformat(timespec="seconds"),
                user_id,
                normalized,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Закладка не найдена")
    return load_bookmark(user_id, normalized)


def remove_bookmark(user_id, url):
    """Удаляет одну личную закладку, не затрагивая новость в общей базе."""
    user_id = _validated_user_id(user_id)
    normalized = normalize_url(url)
    initialize_database()
    with STORAGE_LOCK, _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM bookmarks WHERE user_id = ? AND normalized_url = ?",
            (user_id, normalized),
        )
    return cursor.rowcount == 1


def load_bookmark(user_id, url):
    user_id = _validated_user_id(user_id)
    normalized = normalize_url(url)
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT b.*, f.name AS folder_name
            FROM bookmarks AS b
            LEFT JOIN bookmark_folders AS f
              ON f.id = b.folder_id AND f.user_id = b.user_id
            WHERE b.user_id = ? AND b.normalized_url = ?
            """,
            (user_id, normalized),
        ).fetchone()
    return _bookmark_from_row(row)


def list_bookmarks(user_id, folder_id="all"):
    """Возвращает личные закладки, при необходимости фильтруя по папке."""
    user_id = _validated_user_id(user_id)
    initialize_database()
    parameters = [user_id]
    condition = ""
    if folder_id == "unfiled":
        condition = " AND b.folder_id IS NULL"
    elif folder_id not in {"all", None, ""}:
        owned_id = _owned_folder_id(user_id, folder_id)
        condition = " AND b.folder_id = ?"
        parameters.append(owned_id)
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT b.*, f.name AS folder_name
            FROM bookmarks AS b
            LEFT JOIN bookmark_folders AS f
              ON f.id = b.folder_id AND f.user_id = b.user_id
            WHERE b.user_id = ?
            """ + condition + " ORDER BY b.updated_at DESC, b.id DESC",
            parameters,
        ).fetchall()
    return [_bookmark_from_row(row) for row in rows]


def bookmarked_urls(user_id):
    """Возвращает URL личных закладок для подсветки сердечек в ленте."""
    return [item["url"] for item in list_bookmarks(user_id)]


def count_bookmarks(user_id):
    user_id = _validated_user_id(user_id)
    initialize_database()
    with _connection() as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM bookmarks WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )


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
    try:
        folder_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Папка не найдена") from error
    if folder_id < 1:
        raise ValueError("Папка не найдена")
    return folder_id


def _owned_folder_id(user_id, value):
    if value in {None, "", "unfiled"}:
        return None
    folder_id = _validated_folder_id(value)
    initialize_database()
    with _connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM bookmark_folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        ).fetchone()
    if exists is None:
        raise ValueError("Папка не найдена")
    return folder_id


def _validated_folder_name(value):
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= 80:
        raise ValueError("Название папки должно содержать от 1 до 80 символов")
    return name


def _validated_bookmark_note(value):
    note = str(value or "").strip()
    if len(note) > 5000:
        raise ValueError("Заметка не должна превышать 5000 символов")
    return note


def _bookmark_from_row(row):
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "folder_id": int(row["folder_id"]) if row["folder_id"] else None,
        "folder_name": row["folder_name"] or "",
        "normalized_url": row["normalized_url"],
        "url": row["url"],
        "source": row["source"],
        "title": row["title"],
        "date": row["publication_date"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_username(value):
    username = " ".join(str(value or "").split())
    if not 3 <= len(username) <= 50:
        raise ValueError("Логин должен содержать от 3 до 50 символов")
    if not all(character.isalnum() or character in "._-" for character in username):
        raise ValueError("В логине разрешены буквы, цифры, точка, дефис и подчёркивание")
    return username


def _validate_password(value):
    password = str(value or "")
    if not 10 <= len(password) <= 256:
        raise ValueError("Пароль должен содержать не менее 10 символов")
    return password


def _validated_source_name(value):
    source = " ".join(str(value or "").split())
    if not 1 <= len(source) <= 300:
        raise ValueError("Источник не найден")
    return source


def _validated_optional_user_id(value):
    if value in {None, ""}:
        return None
    try:
        user_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Пользователь не найден") from error
    return user_id if user_id > 0 else None


def _parser_job_from_row(row):
    if row is None:
        return None
    keys = set(row.keys())
    return {
        "id": int(row["id"]),
        "source": row["source"],
        "status": row["status"],
        "requested_by": (
            int(row["requested_by"]) if row["requested_by"] is not None else None
        ),
        "requested_by_name": (
            row["requested_by_name"] if "requested_by_name" in keys else ""
        ) or "",
        "requested_at": row["requested_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
    }


def _user_from_row(row):
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


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
