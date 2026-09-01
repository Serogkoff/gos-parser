"""Сохранение новостей, дедупликация и кеш открытых статей."""

import json
import re
from datetime import datetime
from pathlib import Path

from utils.dates import parse_date
from utils.news import deduplicate_news, merge_news, normalize_url


class NewsPersistenceStorage:
    """Изолирует запись и полную загрузку новостных коллекций SQLite."""

    def __init__(
        self, initialize_database, connect, connection_factory, lock,
        database_file, logger, load_all_news, load_found_news,
        load_collection, max_cached_article_chars=100_000, now=None,
    ):
        self._initialize_database = initialize_database
        self._connect = connect
        self._connection_factory = connection_factory
        self._lock = lock
        self._database_file = database_file
        self._logger = logger
        self._load_all_news = load_all_news
        self._load_found_news = load_found_news
        self._load_collection_callback = load_collection
        self._max_cached_article_chars = max_cached_article_chars
        self._now = now or datetime.now
        self._collection_cache = {}

    def database_change_signature(self):
        """Отслеживает изменения основной SQLite-базы и её WAL-журнала."""
        database_file = Path(self._database_file())
        signature = [str(database_file.resolve())]
        for path in (database_file, Path(f"{database_file}-wal")):
            try:
                stat = path.stat()
                signature.extend((stat.st_size, stat.st_mtime_ns))
            except OSError:
                signature.extend((0, 0))
        return tuple(signature)

    def load_all_news(self):
        self._initialize_database()
        return self.load_collection_cached("news_items")

    def load_found_news(self):
        self._initialize_database()
        return self.load_collection_cached("found_items")

    def load_collection_cached(self, table):
        """Не разбирает десятки тысяч JSON-записей заново на каждой странице."""
        if table not in {"news_items", "found_items"}:
            raise ValueError("неизвестная таблица новостей")
        signature = self.database_change_signature()
        cache_key = (signature[0], table)
        with self._lock:
            cached = self._collection_cache.get(cache_key)
            if cached and cached["signature"] == signature:
                return list(cached["items"])

        connection = self._connect()
        try:
            items = deduplicate_news(
                self._load_collection_callback(connection, table)
            )
        finally:
            connection.close()

        final_signature = self.database_change_signature()
        # Если запись шла одновременно с чтением, не закрепляем снимок под
        # новой сигнатурой: следующий запрос перечитает актуальную коллекцию.
        if final_signature == signature:
            with self._lock:
                self._collection_cache[cache_key] = {
                    "signature": signature,
                    "items": tuple(items),
                }
        return list(items)

    def find_news_by_url(self, url):
        """Находит одну публикацию без загрузки всей базы."""
        normalized = normalize_url(url)
        if not normalized:
            return None
        self._initialize_database()
        with self._connection_factory() as connection:
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
        item = self.decode_item(row["payload_json"])
        if item is not None:
            self.attach_news_display_fields(
                item, row["parsed_date"], row["first_seen_at"],
            )
        return item

    def load_cached_article(self, url):
        """Возвращает сохранённый текст статьи, если её уже открывали."""
        normalized = normalize_url(url)
        if not normalized:
            return None
        self._initialize_database()
        with self._connection_factory() as connection:
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
            self._logger.warning(
                "В SQLite обнаружён повреждённый кеш статьи"
            )
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

    def save_cached_article(self, url, article, source=""):
        """Сохраняет только успешный очищенный текст открытой статьи."""
        normalized = normalize_url(url)
        if not normalized or not isinstance(article, dict) or article.get("error"):
            return None
        paragraphs = self.clean_cached_paragraphs(
            article.get("paragraphs", [])
        )
        if not paragraphs:
            return None
        title = " ".join(str(article.get("title", "")).split())[:500]
        fetched_at = self._now().isoformat(timespec="seconds")
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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
                    json.dumps(
                        paragraphs,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    fetched_at,
                ),
            )
        return self.load_cached_article(normalized)

    def load_existing_urls(self):
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                "SELECT normalized_url FROM news_items "
                "WHERE normalized_url != ''"
            ).fetchall()
        return {row["normalized_url"] for row in rows}

    def save_results(self, all_news, found_news, existing_urls):
        with self._lock:
            return self._save_results(all_news, found_news, existing_urls)

    def _save_results(self, all_news, found_news, existing_urls):
        self._initialize_database()
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

        parsed_at = self._now().strftime("%Y-%m-%d %H:%M")
        for item in new_all:
            if not item.get("parsed_date"):
                item["parsed_date"] = parsed_at
        for item in new_found:
            if not item.get("parsed_date"):
                item["parsed_date"] = parsed_at

        old_all = self._load_all_news()
        old_found = self._load_found_news()

        # Передаём все свежие записи, а не только новые: уже сохранённые
        # материалы смогут получить исправленную дату, ссылку или анонс.
        merged_all = self.sort_items(merge_news(old_all, all_news))
        merged_found = self.sort_items(merge_news(old_found, found_news))

        with self._connection_factory() as connection:
            self.replace_collections(connection, merged_all, merged_found)

        print(f"✅ Новых: {len(new_all)} | Всего: {len(merged_all)}")
        print(
            f"🔴 Новых совпадений: {len(new_found)} | "
            f"Всего: {len(merged_found)}"
        )
        return new_found

    def replace_found_news(self, items):
        """Полностью пересобирает совпадения после изменения слов."""
        with self._lock:
            self._initialize_database()
            all_news = self._load_all_news()
            found_news = deduplicate_news(items)
            available = {self.news_key(item) for item in all_news}
            found_news = [
                item
                for item in found_news
                if self.news_key(item) in available
            ]
            with self._connection_factory() as connection:
                connection.execute("DELETE FROM found_items")
                self.insert_found_items(connection, found_news)
            return self.sort_items(found_news)

    def replace_collections(self, connection, all_news, found_news):
        """Заменяет обе коллекции в одной транзакции: либо всё, либо ничего."""
        first_seen_by_key = {
            row["news_key"]: row["first_seen_at"]
            for row in connection.execute(
                "SELECT news_key, first_seen_at FROM news_items"
            ).fetchall()
        }
        connection.execute("DELETE FROM found_items")
        connection.execute("DELETE FROM news_items")
        self.insert_news_items(
            connection,
            all_news,
            first_seen_by_key=first_seen_by_key,
        )

        available = {self.news_key(item) for item in all_news}
        safe_found = [
            item for item in found_news if self.news_key(item) in available
        ]
        self.insert_found_items(connection, safe_found)

    def insert_news_items(self, connection, items, first_seen_by_key=None):
        updated_at = self._now().isoformat(timespec="seconds")
        first_seen_at = self._now().isoformat(timespec="microseconds")
        first_seen_by_key = first_seen_by_key or {}
        rows = []
        for item in deduplicate_news(items):
            news_key = self.news_key(item)
            rows.append(
                (
                    news_key,
                    normalize_url(item.get("url", "")),
                    str(item.get("source", "")),
                    str(item.get("title", "")),
                    str(item.get("date", "")),
                    str(item.get("parsed_date", "")),
                    self.encode_item(item),
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

    def insert_found_items(self, connection, items):
        updated_at = self._now().isoformat(timespec="seconds")
        connection.executemany(
            """
            INSERT INTO found_items(news_key, payload_json, updated_at)
            VALUES (?, ?, ?)
            """,
            [
                (self.news_key(item), self.encode_item(item), updated_at)
                for item in deduplicate_news(items)
            ],
        )

    def load_collection(self, connection, table):
        if table not in {"news_items", "found_items"}:
            raise ValueError("неизвестная таблица новостей")
        rows = connection.execute(
            f"SELECT payload_json FROM {table}"
        ).fetchall()
        return self.sort_items(
            item
            for item in (
                self.decode_item(row["payload_json"]) for row in rows
            )
            if item is not None
        )

    @staticmethod
    def encode_item(item):
        return json.dumps(
            dict(item), ensure_ascii=False, separators=(",", ":")
        )

    def decode_item(self, payload):
        try:
            item = json.loads(payload)
            return item if isinstance(item, dict) else None
        except (TypeError, json.JSONDecodeError):
            self._logger.warning(
                "В SQLite обнаружена повреждённая запись новости"
            )
            return None

    @staticmethod
    def attach_news_display_fields(item, parsed_date, first_seen_at):
        """Добавляет готовые дату публикации и время первого получения."""
        publication_date = parse_date(item.get("date", ""))
        item["publication_date_display"] = (
            datetime.strptime(publication_date, "%Y-%m-%d").strftime(
                "%d.%m.%Y"
            )
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

    def clean_cached_paragraphs(self, paragraphs):
        if not isinstance(paragraphs, (list, tuple)):
            return []
        result = []
        seen = set()
        remaining = self._max_cached_article_chars
        for paragraph in paragraphs:
            text = " ".join(str(paragraph or "").split())
            if not text or text in seen or remaining <= 0:
                continue
            text = text[:remaining]
            result.append(text)
            seen.add(text)
            remaining -= len(text)
        return result

    @staticmethod
    def news_key(item):
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

    @staticmethod
    def sort_items(items):
        return sorted(
            items,
            key=lambda item: (
                str(item.get("date", "")),
                str(item.get("parsed_date", "")),
            ),
            reverse=True,
        )
