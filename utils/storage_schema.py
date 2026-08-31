"""Создание и совместимые миграции схемы SQLite."""

from datetime import datetime


def create_schema(connection):
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
            updated_at TEXT NOT NULL,
            first_seen_at TEXT NOT NULL DEFAULT ''
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
            system_key TEXT NOT NULL DEFAULT '',
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

        CREATE TABLE IF NOT EXISTS collection_note_reads (
            user_id INTEGER NOT NULL,
            note_id INTEGER NOT NULL,
            read_at TEXT NOT NULL,
            PRIMARY KEY(user_id, note_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(note_id) REFERENCES collection_notes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS personal_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            folder TEXT NOT NULL DEFAULT 'Без папки',
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private'
                CHECK(visibility IN ('private', 'selected', 'all')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS personal_note_shares (
            note_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(note_id, user_id),
            FOREIGN KEY(note_id) REFERENCES personal_notes(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_time TEXT NOT NULL DEFAULT '',
            place TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private'
                CHECK(visibility IN ('private', 'selected', 'all')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS calendar_event_shares (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(event_id, user_id),
            FOREIGN KEY(event_id) REFERENCES calendar_events(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dictionary_decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dictionary_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            term TEXT NOT NULL,
            reading TEXT NOT NULL DEFAULT '',
            translation TEXT NOT NULL,
            repetitions INTEGER NOT NULL DEFAULT 0,
            interval_days INTEGER NOT NULL DEFAULT 0,
            next_review TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(deck_id) REFERENCES dictionary_decks(id) ON DELETE CASCADE,
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

        CREATE TABLE IF NOT EXISTS user_news_read_state (
            user_id INTEGER NOT NULL,
            source_group TEXT NOT NULL,
            read_all_before TEXT NOT NULL,
            initialized_at TEXT NOT NULL,
            PRIMARY KEY(user_id, source_group),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS news_item_reads (
            user_id INTEGER NOT NULL,
            normalized_url TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 1 CHECK(is_read IN (0, 1)),
            read_at TEXT NOT NULL,
            PRIMARY KEY(user_id, normalized_url),
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
        CREATE INDEX IF NOT EXISTS idx_news_source_publication
            ON news_items(source, publication_date DESC, parsed_date DESC);
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
        CREATE INDEX IF NOT EXISTS idx_collection_note_reads_note
            ON collection_note_reads(note_id);
        CREATE INDEX IF NOT EXISTS idx_personal_notes_user
            ON personal_notes(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_personal_note_shares_user
            ON personal_note_shares(user_id, note_id);
        CREATE INDEX IF NOT EXISTS idx_calendar_events_user_date
            ON calendar_events(user_id, event_date, event_time);
        CREATE INDEX IF NOT EXISTS idx_calendar_event_shares_user
            ON calendar_event_shares(user_id, event_id);
        CREATE INDEX IF NOT EXISTS idx_dictionary_decks_user
            ON dictionary_decks(user_id, name);
        CREATE INDEX IF NOT EXISTS idx_dictionary_cards_due
            ON dictionary_cards(user_id, deck_id, next_review);
        CREATE INDEX IF NOT EXISTS idx_user_source_orders_user
            ON user_source_orders(user_id, source_group);
        CREATE INDEX IF NOT EXISTS idx_news_item_reads_user
            ON news_item_reads(user_id, read_at DESC);
        CREATE INDEX IF NOT EXISTS idx_news_item_reads_unread
            ON news_item_reads(user_id, is_read, normalized_url);
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

    news_columns = {
        row["name"] for row in connection.execute(
            "PRAGMA table_info(news_items)"
        ).fetchall()
    }
    if "first_seen_at" not in news_columns:
        connection.execute(
            "ALTER TABLE news_items ADD COLUMN first_seen_at TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        """UPDATE news_items
           SET first_seen_at = CASE
               WHEN updated_at != '' THEN updated_at
               ELSE ?
           END
           WHERE first_seen_at = ''""",
        (datetime.now().isoformat(timespec="microseconds"),),
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_news_first_seen
           ON news_items(first_seen_at DESC)"""
    )

    read_columns = {
        row["name"] for row in connection.execute(
            "PRAGMA table_info(news_item_reads)"
        ).fetchall()
    }
    if "is_read" not in read_columns:
        connection.execute(
            "ALTER TABLE news_item_reads ADD COLUMN is_read INTEGER NOT NULL DEFAULT 1"
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
    if "system_key" not in columns:
        connection.execute(
            "ALTER TABLE bookmark_folders ADD COLUMN system_key TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_bookmark_folders_system
           ON bookmark_folders(user_id, system_key) WHERE system_key != ''"""
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
