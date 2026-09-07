"""Проверка, резервное копирование и обслуживание SQLite-базы."""

import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

class DatabaseMaintenance:
    _BACKUP_FREE_SPACE_RESERVE = 1024 ** 3

    def __init__(
        self, initialize_database, connect, lock, database_file,
        backup_dir, json_migration_key, logger,
    ):
        self._initialize_database = initialize_database
        self._connect = connect
        self._lock = lock
        self._database_file = database_file
        self._backup_dir = backup_dir
        self._json_migration_key = json_migration_key
        self._logger = logger

    def database_stats(self, connection=None):
        """Возвращает краткую статистику и результат проверки целостности."""
        owns_connection = connection is None
        if owns_connection:
            self._initialize_database()
            connection = self._connect()
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
            backups = self._list_managed_backups()
            migration = connection.execute(
                "SELECT value FROM metadata WHERE key = ?",
                (self._json_migration_key,),
            ).fetchone()
            return {
                "news_count": news_count,
                "found_count": found_count,
                "cached_articles": cached_articles,
                "integrity": integrity,
                "path": str(self._database_file()),
                "size_bytes": self._database_storage_size(),
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

    def backup_database(self, destination=None):
        """Атомарно создаёт и проверяет копию работающей SQLite-базы."""
        self._initialize_database()
        destination = Path(destination or self._database_file().with_suffix(".backup.db"))
        if destination.resolve() == self._database_file().resolve():
            raise ValueError("резервная копия не может заменять рабочую базу")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            if temporary.exists():
                temporary.unlink()
            with self._lock:
                source = self._connect()
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
                    self._logger.warning(
                        f"Не удалось удалить временную копию SQLite: {error}"
                    )
        return destination

    def ensure_daily_backup(self, retention=3, now=None):
        """
        Создаёт не больше одной автоматической копии в день.

        Функцию безопасно вызывать после каждого цикла парсинга: если сегодняшний
        снимок уже существует, повторного копирования базы не будет.
        """
        self._initialize_database()
        moment = now or datetime.now()
        destination = self._backup_dir() / (
            f"{self._database_file().stem}-{moment:%Y-%m-%d}.db"
        )
        created = False
        with self._lock:
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                removed = self._remove_old_managed_backups(
                    self._validated_retention(retention) - 1
                )
                self._ensure_backup_space(destination.parent)
                self.backup_database(destination)
                created = True
                self._logger.info(f"Создана резервная копия SQLite: {destination.name}")
            else:
                removed = []
            removed.extend(self._remove_old_managed_backups(retention))
        return {
            "created": created,
            "path": str(destination),
            "removed": [str(path) for path in removed],
        }

    def create_manual_backup(self, retention=3, now=None):
        """Создаёт ручную копию в пределах общего лимита снимков."""
        moment = now or datetime.now()
        destination = self._backup_dir() / (
            f"{self._database_file().stem}-manual-{moment:%Y-%m-%d_%H-%M-%S-%f}.db"
        )
        with self._lock:
            self._initialize_database()
            destination.parent.mkdir(parents=True, exist_ok=True)
            removed = self._remove_old_managed_backups(
                self._validated_retention(retention) - 1
            )
            self._ensure_backup_space(destination.parent)
            self.backup_database(destination)
            removed.extend(self._remove_old_managed_backups(retention))
        self._logger.info(f"Создана ручная резервная копия SQLite: {destination.name}")
        return {
            "path": str(destination),
            "name": destination.name,
            "removed": [str(path) for path in removed],
        }

    def list_database_backups(self):
        """Перечисляет автоматические и ручные резервные копии базы."""
        if not self._backup_dir().exists():
            return []
        result = []
        for path in self._backup_dir().iterdir():
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

    def prepare_database(self, retention=3):
        """Проверяет рабочую базу и создаёт ежедневную резервную копию."""
        stats = self.database_stats()
        if stats["integrity"] != "ok":
            raise sqlite3.DatabaseError(
                f"проверка целостности SQLite завершилась: {stats['integrity']}"
            )
        backup = self.ensure_daily_backup(retention=retention)
        stats = self.database_stats()
        stats["backup_created"] = backup["created"]
        return stats

    def purge_news_archive(self, backup_retention=3, now=None):
        """Создаёт проверенную копию, удаляет только новости и сжимает базу."""
        self._initialize_database()
        size_before = self._database_storage_size()
        backup = self.create_manual_backup(
            retention=backup_retention,
            now=now,
        )
        tables = ("found_items", "news_items", "article_cache", "news_item_reads")
        removed = {}
        compaction_error = ""
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                for table in tables:
                    removed[table] = connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                for table in tables:
                    connection.execute(f"DELETE FROM {table}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as error:
                compaction_error = str(error)
                self._logger.warning(
                    "Новостной архив удалён, но SQLite не удалось сжать: "
                    f"{error}"
                )
            finally:
                connection.close()
        size_after = self._database_storage_size()
        return {
            "backup": backup,
            "removed": removed,
            "size_before": size_before,
            "size_after": size_after,
            "freed_bytes": max(0, size_before - size_after),
            "compaction_error": compaction_error,
        }

    def _automatic_backup_pattern(self):
        return re.compile(
            rf"^{re.escape(self._database_file().stem)}-\d{{4}}-\d{{2}}-\d{{2}}\.db$"
        )

    def _list_automatic_backups(self):
        if not self._backup_dir().exists():
            return []
        pattern = self._automatic_backup_pattern()
        return sorted(
            path
            for path in self._backup_dir().iterdir()
            if path.is_file() and pattern.fullmatch(path.name)
        )

    def _list_managed_backups(self):
        """Возвращает снимки этой базы в фактическом порядке создания."""
        if not self._backup_dir().exists():
            return []
        automatic = self._automatic_backup_pattern()
        manual = re.compile(
            rf"^{re.escape(self._database_file().stem)}-manual-.*\.db$"
        )
        backups = [
            path for path in self._backup_dir().iterdir()
            if path.is_file()
            and (automatic.fullmatch(path.name) or manual.fullmatch(path.name))
        ]
        return sorted(backups, key=lambda path: (path.stat().st_mtime_ns, path.name))

    @staticmethod
    def _validated_retention(retention):
        try:
            return max(1, int(retention))
        except (TypeError, ValueError):
            return 3

    def _remove_old_managed_backups(self, retention):
        try:
            retention = max(0, int(retention))
        except (TypeError, ValueError):
            retention = 3
        backups = self._list_managed_backups()
        excess = max(0, len(backups) - retention)
        removed = []
        for path in backups[:excess]:
            path.unlink()
            removed.append(path)
            self._logger.info(f"Удалена старая резервная копия SQLite: {path.name}")
        return removed

    def _database_storage_size(self):
        database = self._database_file()
        candidates = (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
        )
        return sum(path.stat().st_size for path in candidates if path.exists())

    def _ensure_backup_space(self, destination_parent):
        free = shutil.disk_usage(destination_parent).free
        required = self._database_storage_size() + self._BACKUP_FREE_SPACE_RESERVE
        if free < required:
            raise OSError(
                "недостаточно свободного места для проверенной резервной копии "
                f"(нужно не менее {required} байт, свободно {free})"
            )

    def _remove_old_backups(self, retention):
        try:
            retention = max(1, int(retention))
        except (TypeError, ValueError):
            retention = 3
        backups = self._list_automatic_backups()
        removed = []
        for path in backups[:-retention]:
            path.unlink()
            removed.append(path)
            self._logger.info(f"Удалена старая резервная копия SQLite: {path.name}")
        return removed

    def _remove_old_manual_backups(self, retention):
        try:
            retention = max(1, int(retention))
        except (TypeError, ValueError):
            retention = 3
        if not self._backup_dir().exists():
            return []
        backups = sorted(
            (
                path for path in self._backup_dir().iterdir()
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
            self._logger.info(f"Удалена старая ручная копия SQLite: {path.name}")
        return removed
