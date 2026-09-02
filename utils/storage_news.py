"""Лента новостей и персональные отметки прочитанного."""

from datetime import datetime

from utils.source_groups import (
    AGENCIES_GROUP,
    AGENCY_SOURCES,
    GOVERNMENT_GROUP,
    NEWSPAPERS_GROUP,
    NEWSPAPER_SOURCES,
    source_group as get_source_group,
)


class NewsStorage:
    def __init__(
        self, initialize_database, connection_factory, lock,
        normalize_url, decode_item, attach_display_fields,
        database_change_signature,
    ):
        self._initialize_database = initialize_database
        self._connection_factory = connection_factory
        self._lock = lock
        self._normalize_url = normalize_url
        self._decode_item = decode_item
        self._attach_display_fields = attach_display_fields
        self._database_change_signature = database_change_signature
        self._overview_cache = None

    @staticmethod
    def news_group_condition(source_group, source_column="n.source"):
        """Строит параметризованное SQL-условие для раздела ленты."""
        source_group = str(source_group or "").strip().casefold()
        if source_group not in {
            GOVERNMENT_GROUP,
            AGENCIES_GROUP,
            NEWSPAPERS_GROUP,
        }:
            raise ValueError("Неизвестный раздел источников")

        agency_sources = tuple(sorted(AGENCY_SOURCES))
        newspaper_sources = tuple(sorted(NEWSPAPER_SOURCES))
        agency_placeholders = ", ".join("?" for _ in agency_sources)
        newspaper_placeholders = ", ".join("?" for _ in newspaper_sources)
        agency_condition = (
            f"({source_column} IN ({agency_placeholders}) "
            f"OR {source_column} LIKE ? COLLATE NOCASE)"
        )
        agency_parameters = [*agency_sources, "Yahoo! JAPAN%"]

        if source_group == AGENCIES_GROUP:
            return agency_condition, agency_parameters
        if source_group == NEWSPAPERS_GROUP:
            return (
                f"{source_column} IN ({newspaper_placeholders})",
                list(newspaper_sources),
            )
        return (
            f"NOT {agency_condition} "
            f"AND {source_column} NOT IN ({newspaper_placeholders})",
            [*agency_parameters, *newspaper_sources],
        )

    def news_group_counts(self, source_group):
        """Считает все материалы и совпадения раздела без загрузки JSON."""
        overview = self._news_group_overview(source_group)
        return overview["total"], overview["found"]

    def news_source_counts(self, source_group):
        """Возвращает размеры источников раздела одним SQL GROUP BY."""
        return dict(self._news_group_overview(source_group)["by_source"])

    def _news_group_overview(self, source_group):
        """Переиспользует агрегаты до следующего изменения SQLite/WAL."""
        source_group = str(source_group or "").strip().casefold()
        self.news_group_condition(source_group)
        self._initialize_database()
        signature = self._database_change_signature()
        with self._lock:
            cached = self._overview_cache
            if cached and cached["signature"] == signature:
                return cached["groups"][source_group]

        groups = self._query_news_overview()
        final_signature = self._database_change_signature()
        if final_signature == signature:
            with self._lock:
                self._overview_cache = {
                    "signature": signature,
                    "groups": groups,
                }
        return groups[source_group]

    def _query_news_overview(self):
        groups = {
            group: {"total": 0, "found": 0, "by_source": {}}
            for group in (
                GOVERNMENT_GROUP,
                AGENCIES_GROUP,
                NEWSPAPERS_GROUP,
            )
        }
        with self._connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT n.source,
                       COUNT(*) AS news_count,
                       COUNT(f.news_key) AS found_count
                FROM news_items AS n
                LEFT JOIN found_items AS f ON f.news_key = n.news_key
                GROUP BY n.source
                """
            ).fetchall()
        for row in rows:
            source = row["source"] or "Неизвестный источник"
            group = get_source_group(source)
            news_count = int(row["news_count"])
            found_count = int(row["found_count"])
            groups[group]["total"] += news_count
            groups[group]["found"] += found_count
            groups[group]["by_source"][source] = news_count
        return groups

    def list_news_page(
        self, source_group, *, found_only=False, sources=None,
        search_query="", keyword="", limit=20, offset=0,
    ):
        """Читает одну страницу новостей и считает результат средствами SQLite."""
        try:
            limit = min(100, max(1, int(limit)))
            offset = max(0, int(offset))
        except (TypeError, ValueError) as error:
            raise ValueError("Некорректная страница новостей") from error

        condition, parameters = self.news_group_condition(source_group)
        conditions = [condition]
        selected_sources = []
        for source in sources or []:
            source = str(source or "").strip()
            if source and source not in selected_sources:
                selected_sources.append(source)
        if selected_sources:
            placeholders = ", ".join("?" for _ in selected_sources)
            conditions.append(f"n.source IN ({placeholders})")
            parameters.extend(selected_sources)

        search_query = " ".join(str(search_query or "").split())
        if search_query:
            escaped = (
                search_query.casefold().replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            payload_column = "f.payload_json" if found_only else "n.payload_json"
            conditions.append(
                "(CASEFOLD(n.title) LIKE ? ESCAPE '\\' "
                "OR CASEFOLD(n.source) LIKE ? ESCAPE '\\' "
                f"OR CASEFOLD({payload_column}) LIKE ? ESCAPE '\\')"
            )
            parameters.extend((pattern, pattern, pattern))

        keyword = " ".join(str(keyword or "").split())
        if found_only and keyword:
            conditions.append(
                "EXISTS ("
                "SELECT 1 FROM json_each(f.payload_json, '$.keywords') "
                "AS matched_keyword "
                "WHERE CASEFOLD(matched_keyword.value) = ?"
                ")"
            )
            parameters.append(keyword.casefold())

        join = (
            "JOIN found_items AS f ON f.news_key = n.news_key"
            if found_only else ""
        )
        payload_column = "f.payload_json" if found_only else "n.payload_json"
        where_clause = " AND ".join(conditions)
        cached_total = None
        if not selected_sources and not search_query and not keyword:
            overview = self._news_group_overview(source_group)
            cached_total = overview["found" if found_only else "total"]
        self._initialize_database()
        with self._connection_factory() as connection:
            total = cached_total
            if total is None:
                total = int(
                    connection.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM news_items AS n
                        {join}
                        WHERE {where_clause}
                        """,
                        parameters,
                    ).fetchone()[0]
                )
            rows = connection.execute(
                f"""
                SELECT {payload_column} AS payload_json,
                       n.parsed_date, n.first_seen_at
                FROM news_items AS n
                {join}
                WHERE {where_clause}
                ORDER BY n.publication_date DESC,
                         n.parsed_date DESC,
                         n.news_key DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        items = []
        for row in rows:
            item = self._decode_item(row["payload_json"])
            if item is not None:
                self._attach_display_fields(
                    item, row["parsed_date"], row["first_seen_at"],
                )
                items.append(item)
        return items, total

    def list_news_index(self, source_group, limit=2000):
        """Возвращает лёгкий индекс URL для счётчиков непрочитанного."""
        try:
            limit = min(5000, max(1, int(limit)))
        except (TypeError, ValueError):
            limit = 2000
        condition, parameters = self.news_group_condition(source_group)
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT n.normalized_url AS url, n.source
                FROM news_items AS n
                WHERE {condition} AND n.normalized_url != ''
                ORDER BY n.publication_date DESC,
                         n.parsed_date DESC,
                         n.news_key DESC
                LIMIT ?
                """,
                [*parameters, limit],
            ).fetchall()
        return [
            {
                "url": row["url"],
                "source": row["source"] or "Неизвестный источник",
            }
            for row in rows
        ]

    def list_unread_news(self, user_id, source_group, limit=2000):
        """Возвращает непрочитанные URL пользователя в одном разделе."""
        return [
            item["url"]
            for item in self.list_unread_news_index(
                user_id, source_group, limit
            )
        ]

    def _unread_news_context(self, user_id, source_group):
        try:
            user_id = int(user_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Пользователь не найден") from error
        if user_id <= 0:
            return None

        source_group = str(source_group or "").strip().casefold()
        condition, parameters = self.news_group_condition(source_group)
        self._initialize_database()
        with self._connection_factory() as connection:
            state = connection.execute(
                """SELECT read_all_before
                   FROM user_news_read_state
                   WHERE user_id = ? AND source_group = ?""",
                (user_id, source_group),
            ).fetchone()

        if state is None:
            moment = datetime.now().isoformat(timespec="microseconds")
            with self._lock, self._connection_factory() as connection:
                inserted = connection.execute(
                    """INSERT OR IGNORE INTO user_news_read_state(
                           user_id, source_group, read_all_before, initialized_at
                       ) VALUES (?, ?, ?, ?)""",
                    (user_id, source_group, moment, moment),
                ).rowcount
                state = connection.execute(
                    """SELECT read_all_before
                       FROM user_news_read_state
                       WHERE user_id = ? AND source_group = ?""",
                    (user_id, source_group),
                ).fetchone()
            if inserted:
                return None

        return {
            "user_id": user_id,
            "condition": condition,
            "parameters": parameters,
            "read_all_before": state["read_all_before"],
        }

    @staticmethod
    def _unread_news_select(condition):
        return f"""
            SELECT n.normalized_url AS url,
                   n.source AS source,
                   n.first_seen_at AS first_seen_at,
                   n.news_key AS news_key
            FROM news_items AS n
            LEFT JOIN news_item_reads AS r
              ON r.user_id = ? AND r.normalized_url = n.normalized_url
            WHERE {condition}
              AND n.normalized_url != ''
              AND n.first_seen_at > ?
              AND r.normalized_url IS NULL

            UNION

            SELECT n.normalized_url AS url,
                   n.source AS source,
                   n.first_seen_at AS first_seen_at,
                   n.news_key AS news_key
            FROM news_item_reads AS r
            JOIN news_items AS n
              ON n.normalized_url = r.normalized_url
            WHERE r.user_id = ?
              AND r.is_read = 0
              AND {condition}
              AND n.normalized_url != ''
        """

    @staticmethod
    def _unread_news_parameters(context):
        parameters = context["parameters"]
        return [
            context["user_id"],
            *parameters,
            context["read_all_before"],
            context["user_id"],
            *parameters,
        ]

    def list_unread_news_index(self, user_id, source_group, limit=2000):
        """Возвращает компактный индекс только непрочитанных новостей."""
        try:
            limit = min(5000, max(1, int(limit)))
        except (TypeError, ValueError):
            limit = 2000
        context = self._unread_news_context(user_id, source_group)
        if context is None:
            return []
        unread_select = self._unread_news_select(context["condition"])

        with self._connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT unread.url, unread.source
                FROM ({unread_select}) AS unread
                ORDER BY unread.first_seen_at DESC, unread.news_key DESC
                LIMIT ?
                """,
                [*self._unread_news_parameters(context), limit],
            ).fetchall()
        return [
            {
                "url": row["url"],
                "source": row["source"] or "Неизвестный источник",
            }
            for row in rows
        ]

    def news_unread_summary(self, user_id, source_group, visible_urls=None):
        """Считает непрочитанное и возвращает только видимые отметки."""
        empty = {"total": 0, "by_source": {}, "visible_urls": []}
        context = self._unread_news_context(user_id, source_group)
        if context is None:
            return empty

        visible_candidates = []
        seen_normalized = set()
        for url in visible_urls or []:
            original = str(url or "").strip()
            normalized = self._normalize_url(original)
            if not normalized or normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)
            visible_candidates.append((original, normalized))

        unread_select = self._unread_news_select(context["condition"])
        with self._connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT unread.source, COUNT(*) AS unread_count
                FROM ({unread_select}) AS unread
                GROUP BY unread.source
                """,
                self._unread_news_parameters(context),
            ).fetchall()
            visible_unread = set()
            if visible_candidates:
                placeholders = ", ".join("?" for _ in visible_candidates)
                visible_rows = connection.execute(
                    f"""
                    SELECT DISTINCT n.normalized_url AS url
                    FROM news_items AS n
                    LEFT JOIN news_item_reads AS r
                      ON r.user_id = ? AND r.normalized_url = n.normalized_url
                    WHERE n.normalized_url IN ({placeholders})
                      AND (
                          (n.first_seen_at > ? AND r.normalized_url IS NULL)
                          OR r.is_read = 0
                      )
                    """,
                    [
                        context["user_id"],
                        *(normalized for _, normalized in visible_candidates),
                        context["read_all_before"],
                    ],
                ).fetchall()
                visible_unread = {row["url"] for row in visible_rows}

        by_source = {
            (row["source"] or "Неизвестный источник"):
                int(row["unread_count"])
            for row in rows
        }
        return {
            "total": sum(by_source.values()),
            "by_source": by_source,
            "visible_urls": [
                original
                for original, normalized in visible_candidates
                if normalized in visible_unread
            ],
        }

    def mark_news_read(self, user_id, url):
        """Сохраняет личную отметку чтения одной новости."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Пользователь не найден") from error
        normalized = self._normalize_url(url)
        if user_id <= 0 or not normalized:
            raise ValueError("Новость не найдена")

        self._initialize_database()
        read_at = datetime.now().isoformat(timespec="microseconds")
        with self._lock, self._connection_factory() as connection:
            item = connection.execute(
                "SELECT 1 FROM news_items WHERE normalized_url = ? LIMIT 1",
                (normalized,),
            ).fetchone()
            if item is None:
                raise ValueError("Новость не найдена")
            connection.execute(
                """INSERT INTO news_item_reads(
                       user_id, normalized_url, is_read, read_at
                   ) VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id, normalized_url) DO UPDATE SET
                       is_read = 1,
                       read_at = excluded.read_at""",
                (user_id, normalized, read_at),
            )
        return normalized

    def migrate_legacy_unread(self, user_id, unread_urls):
        """Один раз переносит непрочитанные ссылки из localStorage."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Пользователь не найден") from error
        if user_id <= 0 or not isinstance(unread_urls, list):
            raise ValueError("Некорректные отметки чтения")

        normalized_urls = []
        for url in unread_urls[:5000]:
            normalized = self._normalize_url(url)
            if normalized and normalized not in normalized_urls:
                normalized_urls.append(normalized)

        self._initialize_database()
        moment = datetime.now().isoformat(timespec="microseconds")
        with self._lock, self._connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            initialized = connection.execute(
                "SELECT 1 FROM user_news_read_state WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
            if initialized is not None:
                return False

            connection.executemany(
                """INSERT INTO user_news_read_state(
                       user_id, source_group, read_all_before, initialized_at
                   ) VALUES (?, ?, ?, ?)""",
                [
                    (user_id, source_group, moment, moment)
                    for source_group in (
                        GOVERNMENT_GROUP,
                        AGENCIES_GROUP,
                        NEWSPAPERS_GROUP,
                    )
                ],
            )
            if normalized_urls:
                placeholders = ", ".join("?" for _ in normalized_urls)
                existing = connection.execute(
                    f"""SELECT normalized_url FROM news_items
                        WHERE normalized_url IN ({placeholders})""",
                    normalized_urls,
                ).fetchall()
                connection.executemany(
                    """INSERT INTO news_item_reads(
                           user_id, normalized_url, is_read, read_at
                       ) VALUES (?, ?, 0, ?)""",
                    [
                        (user_id, row["normalized_url"], moment)
                        for row in existing
                    ],
                )
        return True

    def mark_news_group_read(self, user_id, source_group):
        """Отмечает прочитанными все новости выбранного раздела."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Пользователь не найден") from error
        if user_id <= 0:
            raise ValueError("Пользователь не найден")

        source_group = str(source_group or "").strip().casefold()
        condition, parameters = self.news_group_condition(source_group)
        self._initialize_database()
        moment = datetime.now().isoformat(timespec="microseconds")
        with self._lock, self._connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO user_news_read_state(
                       user_id, source_group, read_all_before, initialized_at
                   ) VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, source_group) DO UPDATE SET
                       read_all_before = excluded.read_all_before""",
                (user_id, source_group, moment, moment),
            )
            connection.execute(
                f"""DELETE FROM news_item_reads
                    WHERE user_id = ? AND normalized_url IN (
                        SELECT n.normalized_url FROM news_items AS n
                        WHERE {condition}
                    )""",
                [user_id, *parameters],
            )
        return True
