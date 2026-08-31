"""Порядок источников, паузы и очередь ручных проверок."""

import json
from datetime import datetime, timedelta


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


class SourceControlStorage:
    def __init__(
        self, initialize_database, connection_factory, lock,
        validate_user_id, validate_source_group,
    ):
        self._initialize_database = initialize_database
        self._connection_factory = connection_factory
        self._lock = lock
        self._validate_user_id = validate_user_id
        self._validate_source_group = validate_source_group

    def load_source_order(self, user_id, source_group):
        """Возвращает личный порядок источников для одного раздела."""
        user_id = self._validate_user_id(user_id)
        source_group = self._validate_source_group(source_group)
        self._initialize_database()
        with self._connection_factory() as connection:
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

    def save_source_order(self, user_id, source_group, sources):
        """Сохраняет личный порядок источников, не затрагивая других пользователей."""
        user_id = self._validate_user_id(user_id)
        source_group = self._validate_source_group(source_group)
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
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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

    def source_is_enabled(self, source):
        """По умолчанию источник включён; администратор может поставить его на паузу."""
        source = _validated_source_name(source)
        self._initialize_database()
        with self._connection_factory() as connection:
            row = connection.execute(
                "SELECT enabled FROM source_settings WHERE source = ? COLLATE NOCASE",
                (source,),
            ).fetchone()
        return True if row is None else bool(row["enabled"])

    def load_source_settings(self):
        """Возвращает сохранённые администратором состояния источников."""
        self._initialize_database()
        with self._connection_factory() as connection:
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

    def set_source_enabled(self, source, enabled):
        """Включает источник или временно исключает его из расписания."""
        source = _validated_source_name(source)
        enabled = bool(enabled)
        updated_at = datetime.now().isoformat(timespec="seconds")
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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

    def enqueue_parser_job(self, source, requested_by=None):
        """Ставит одиночную проверку в очередь, не создавая повторных заданий."""
        source = _validated_source_name(source)
        requested_by = _validated_optional_user_id(requested_by)
        requested_at = datetime.now().isoformat(timespec="seconds")
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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

    def claim_next_parser_job(self):
        """Атомарно забирает одно ожидающее задание для процесса main.py."""
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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

    def finish_parser_job(self, job_id, success, error=""):
        """Фиксирует результат ручной проверки источника."""
        try:
            job_id = int(job_id)
        except (TypeError, ValueError) as validation_error:
            raise ValueError("Задание не найдено") from validation_error
        status = "success" if success else "error"
        finished_at = datetime.now().isoformat(timespec="seconds")
        error = " ".join(str(error or "").split())[:1000]
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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

    def list_parser_jobs(self, limit=50):
        """Возвращает последние ручные проверки для администраторской панели."""
        try:
            limit = min(200, max(1, int(limit)))
        except (TypeError, ValueError):
            limit = 50
        self._initialize_database()
        with self._connection_factory() as connection:
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

    def source_news_statistics(self):
        """Считает накопленные новости и дату последнего нового материала."""
        self._initialize_database()
        with self._connection_factory() as connection:
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
