"""Первый запуск SQLite и однократная миграция старых JSON-файлов."""

import json
from datetime import datetime


def load_json_list(path, logger):
    """Читает служебный JSON-массив или возвращает пустой список."""
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


class DatabaseInitializer:
    def __init__(
        self,
        database_file,
        all_news_file,
        found_news_file,
        connection_factory,
        create_schema,
        database_stats,
        replace_collections,
        deduplicate_news,
        news_key,
        lock,
        migration_key,
        logger,
        now=None,
    ):
        self._database_file = database_file
        self._all_news_file = all_news_file
        self._found_news_file = found_news_file
        self._connection_factory = connection_factory
        self._create_schema = create_schema
        self._database_stats = database_stats
        self._replace_collections = replace_collections
        self._deduplicate_news = deduplicate_news
        self._news_key = news_key
        self._lock = lock
        self._migration_key = migration_key
        self._logger = logger
        self._now = now or datetime.now
        self._initialized_databases = set()
        self._initialization_results = {}

    def initialize_database(self):
        """
        Создаёт базу и один раз переносит старые JSON-файлы.

        Исходные JSON не удаляются: они остаются резервным снимком на случай,
        если пользователь захочет проверить миграцию или откатиться.
        """
        database_file = self._database_file()
        database_id = str(database_file.resolve())
        with self._lock:
            if (
                database_id in self._initialized_databases
                and database_file.exists()
            ):
                return dict(self._initialization_results[database_id])

            with self._connection_factory() as connection:
                self._create_schema(connection)
                # ALTER TABLE при обновлении старой базы открывает транзакцию.
                # Фиксируем только изменение схемы до BEGIN IMMEDIATE ниже.
                connection.commit()
                if self._migration_completed(connection):
                    return self._remember_result(database_id, connection)

                # Блокирует только конкурирующую первую миграцию. Обычные
                # чтения продолжают работать благодаря WAL, а второй процесс
                # дождётся завершения и повторно проверит metadata.
                connection.execute("BEGIN IMMEDIATE")
                if self._migration_completed(connection):
                    return self._remember_result(database_id, connection)

                all_news = self._deduplicate_news(
                    self._load_json(self._all_news_file())
                )
                found_news = self._deduplicate_news(
                    self._load_json(self._found_news_file())
                )
                if all_news or found_news:
                    all_news = self._include_missing_found_items(
                        all_news,
                        found_news,
                    )
                    self._replace_collections(
                        connection,
                        all_news,
                        found_news,
                    )
                    self._logger.info(
                        "Миграция JSON → SQLite завершена: "
                        f"{len(all_news)} новостей, "
                        f"{len(found_news)} совпадений"
                    )

                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                    (
                        self._migration_key,
                        json.dumps(
                            {
                                "completed_at": self._now().isoformat(
                                    timespec="seconds"
                                ),
                                "all_news": len(all_news),
                                "found_news": len(found_news),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                return self._remember_result(database_id, connection)

    def _migration_completed(self, connection):
        return connection.execute(
            "SELECT 1 FROM metadata WHERE key = ?",
            (self._migration_key,),
        ).fetchone() is not None

    def _remember_result(self, database_id, connection):
        stats = self._database_stats(connection)
        self._initialized_databases.add(database_id)
        self._initialization_results[database_id] = dict(stats)
        return stats

    def _include_missing_found_items(self, all_news, found_news):
        """Добавляет найденные записи, отсутствующие в общей старой ленте."""
        available = {self._news_key(item) for item in all_news}
        missing = []
        for item in found_news:
            if self._news_key(item) in available:
                continue
            clean_item = dict(item)
            clean_item.pop("keywords", None)
            missing.append(clean_item)
        return [*all_news, *missing]

    def _load_json(self, path):
        return load_json_list(path, self._logger)
