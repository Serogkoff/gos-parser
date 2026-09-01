import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import web_app
from utils import storage


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database = directory / "news.db"
        self.patchers = (
            patch.object(storage, "DATABASE_FILE", self.database),
            patch.object(storage, "ALL_NEWS_FILE", directory / "all_news.json"),
            patch.object(storage, "FOUND_NEWS_FILE", directory / "found_news.json"),
            patch.object(storage, "BACKUP_DIR", directory / "backups"),
        )
        for patcher in self.patchers:
            patcher.start()
        self.previous_auth_disabled = web_app.app.config["AUTH_DISABLED"]
        self.previous_allowed_hosts = web_app.app.config["ALLOWED_HOSTS"]
        self.previous_cookie_secure = web_app.app.config["SESSION_COOKIE_SECURE"]
        web_app.app.config["AUTH_DISABLED"] = False
        web_app.app.config["ALLOWED_HOSTS"] = set()
        web_app.app.config["SESSION_COOKIE_SECURE"] = False
        web_app.app.config["TESTING"] = True
        web_app.LOGIN_PAIR_LIMITER.reset()
        web_app.LOGIN_ACCOUNT_LIMITER.reset()
        web_app.LOGIN_IP_LIMITER.reset()
        self.client = web_app.app.test_client()

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled
        web_app.app.config["ALLOWED_HOSTS"] = self.previous_allowed_hosts
        web_app.app.config["SESSION_COOKIE_SECURE"] = self.previous_cookie_secure
        web_app.app.config["TESTING"] = False
        web_app.LOGIN_PAIR_LIMITER.reset()
        web_app.LOGIN_ACCOUNT_LIMITER.reset()
        web_app.LOGIN_IP_LIMITER.reset()
        self.client = None
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    @staticmethod
    def _csrf(response):
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        if not match:
            raise AssertionError("На странице отсутствует CSRF-токен")
        return match.group(1)

    def _create_first_admin(self):
        setup_page = self.client.get("/setup")
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": self._csrf(setup_page),
                "username": "owner",
                "password": "super-secret-2026",
                "password_confirm": "super-secret-2026",
            },
        )
        self.assertEqual(response.status_code, 302)
        return response

    @staticmethod
    def _empty_app_data(filename, default):
        if filename == "parser_status.json":
            return {"sources": [], "generated_at": ""}
        return []

    def test_first_launch_creates_admin_and_never_stores_plain_password(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/setup"))

        self._create_first_admin()
        user = storage.authenticate_user("owner", "super-secret-2026")
        self.assertEqual(user["role"], "admin")

        with closing(sqlite3.connect(self.database)) as connection:
            password_hash = connection.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("owner",),
            ).fetchone()[0]
        self.assertNotEqual(password_hash, "super-secret-2026")
        self.assertNotIn("super-secret-2026", password_hash)

    def test_health_check_is_available_without_login(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        self.assertNotIn("version", response.get_json())
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_feed_uses_short_private_cache_but_account_stays_no_store(self):
        self._create_first_admin()
        with patch.object(
            web_app,
            "load_json",
            side_effect=self._empty_app_data,
        ):
            feed = self.client.get("/")
        account = self.client.get("/account")

        self.assertEqual(
            feed.headers["Cache-Control"],
            "private, max-age=30, must-revalidate",
        )
        self.assertIn("Cookie", feed.headers["Vary"])
        self.assertEqual(account.headers["Cache-Control"], "no-store")

    def test_public_mode_rejects_unknown_host_and_remote_setup(self):
        web_app.app.config["ALLOWED_HOSTS"] = {"news-monitor.ru"}

        unknown = self.client.get(
            "/healthz", headers={"Host": "untrusted.example"}
        )
        known = self.client.get(
            "/healthz", headers={"Host": "news-monitor.ru"}
        )
        setup = self.client.get(
            "/setup", headers={"Host": "news-monitor.ru"}
        )

        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(known.status_code, 200)
        self.assertEqual(setup.status_code, 403)

    def test_server_host_defaults_to_loopback_and_allows_lan_opt_in(self):
        with patch.object(web_app, "environment_value", return_value=""):
            self.assertEqual(web_app._server_host(), "127.0.0.1")
        with patch.object(
            web_app,
            "environment_value",
            return_value=" 0.0.0.0 ",
        ):
            self.assertEqual(web_app._server_host(), "0.0.0.0")

    def test_repeated_bad_password_temporarily_blocks_login(self):
        storage.create_user("limited-user", "limited-secret-2026", role="user")
        login_page = self.client.get("/login")
        token = self._csrf(login_page)

        for attempt in range(5):
            response = self.client.post(
                "/login",
                data={
                    "csrf_token": token,
                    "username": "limited-user",
                    "password": "wrong-password",
                },
            )
            expected = 429 if attempt == 4 else 200
            self.assertEqual(response.status_code, expected)

        blocked = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": "limited-user",
                "password": "limited-secret-2026",
            },
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)

    def test_login_logout_and_protected_pages(self):
        self._create_first_admin()
        with patch.object(
            web_app,
            "load_json",
            side_effect=self._empty_app_data,
        ):
            page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("owner", page.get_data(as_text=True))
        self.assertIn("Ключевые слова", page.get_data(as_text=True))

        logout = self.client.post(
            "/logout",
            data={"csrf_token": self._csrf(page)},
        )
        self.assertEqual(logout.status_code, 302)
        self.assertTrue(logout.headers["Location"].endswith("/login"))
        self.assertEqual(logout.headers["Clear-Site-Data"], '"cache"')
        self.assertTrue(self.client.get("/").headers["Location"].startswith("/login"))

        login_page = self.client.get("/login?next=/newspapers")
        bad_login = self.client.post(
            "/login",
            data={
                "csrf_token": self._csrf(login_page),
                "next": "/newspapers",
                "username": "owner",
                "password": "wrong-password",
            },
        )
        self.assertEqual(bad_login.status_code, 200)
        self.assertIn("Неверный логин", bad_login.get_data(as_text=True))

        good_login = self.client.post(
            "/login",
            data={
                "csrf_token": self._csrf(bad_login),
                "next": "/newspapers",
                "username": "owner",
                "password": "super-secret-2026",
            },
        )
        self.assertEqual(good_login.status_code, 302)
        self.assertTrue(good_login.headers["Location"].endswith("/newspapers"))

    def test_regular_user_cannot_change_admin_settings(self):
        storage.create_user("owner", "super-secret-2026", role="admin")
        storage.create_user("reader", "reader-secret-2026", role="user")
        login_page = self.client.get("/login")
        logged_in = self.client.post(
            "/login",
            data={
                "csrf_token": self._csrf(login_page),
                "username": "reader",
                "password": "reader-secret-2026",
            },
        )
        self.assertEqual(logged_in.status_code, 302)

        with patch.object(
            web_app,
            "load_json",
            side_effect=self._empty_app_data,
        ):
            page = self.client.get("/")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("reader", html)
        self.assertIn('id="keywords-open"', html)
        self.assertNotIn("Сводка покрытия", html)

        with (
            patch.object(web_app, "add_keyword", return_value=["Япония"]),
            patch.object(web_app, "rebuild_found_news", return_value=[]),
        ):
            allowed = self.client.post(
                "/api/keywords",
                json={"keyword": "Япония"},
                headers={"X-CSRF-Token": self._csrf(page)},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/admin/sources").status_code, 403)
        self.assertEqual(self.client.get("/admin/system").status_code, 403)
        self.assertEqual(self.client.get("/admin/incidents").status_code, 403)
        self.assertEqual(self.client.get("/admin/reliability").status_code, 403)

    def test_admin_creates_manages_and_reactivates_user(self):
        self._create_first_admin()
        page = self.client.get("/admin/users")
        token = self._csrf(page)
        created = self.client.post(
            "/admin/users",
            data={
                "csrf_token": token,
                "action": "create",
                "username": "journalist",
                "role": "user",
                "password": "temporary-2026",
                "password_confirm": "temporary-2026",
            },
        )
        self.assertEqual(created.status_code, 302)
        user = next(
            item for item in storage.list_users() if item["username"] == "journalist"
        )
        self.assertEqual(user["role"], "user")

        promoted = self.client.post(
            "/admin/users",
            data={
                "csrf_token": token,
                "action": "role",
                "user_id": user["id"],
                "role": "admin",
            },
        )
        self.assertEqual(promoted.status_code, 302)
        self.assertEqual(storage.load_user(user["id"])["role"], "admin")

        disabled = self.client.post(
            "/admin/users",
            data={
                "csrf_token": token,
                "action": "toggle",
                "user_id": user["id"],
            },
        )
        self.assertEqual(disabled.status_code, 302)
        self.assertFalse(storage.load_user(user["id"])["is_active"])
        self.assertIsNone(storage.authenticate_user("journalist", "temporary-2026"))

        self.client.post(
            "/admin/users",
            data={
                "csrf_token": token,
                "action": "toggle",
                "user_id": user["id"],
            },
        )
        self.client.post(
            "/admin/users",
            data={
                "csrf_token": token,
                "action": "password",
                "user_id": user["id"],
                "password": "replacement-2026",
            },
        )
        self.assertIsNotNone(
            storage.authenticate_user("journalist", "replacement-2026")
        )

        users_page = self.client.get("/admin/users").get_data(as_text=True)
        self.assertIn("Удалить пользователя", users_page)
        self.assertIn("password-toggle", users_page)
        deleted = self.client.post(
            "/admin/users",
            data={
                "csrf_token": token,
                "action": "delete",
                "user_id": user["id"],
            },
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertIsNone(storage.load_user(user["id"]))

    def test_admin_can_open_source_panel_queue_refresh_and_pause_source(self):
        self._create_first_admin()
        with patch.object(
            web_app,
            "load_json",
            side_effect=self._empty_app_data,
        ), patch.object(
            web_app,
            "kyodo_proxy_status",
            return_value={
                "ok": True,
                "label": "VPN работает",
                "detail": "47NEWS доступен через отдельный канал",
            },
        ):
            page = self.client.get("/admin/sources")

        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Центр управления", html)
        self.assertIn("Автоматическая диагностика", html)
        self.assertIn("VPN работает", html)
        self.assertIn("МЧС", html)
        token = self._csrf(page)

        queued = self.client.post(
            "/admin/sources",
            data={
                "csrf_token": token,
                "action": "refresh",
                "source": "МЧС",
            },
        )
        self.assertEqual(queued.status_code, 302)
        self.assertEqual(storage.list_parser_jobs()[0]["source"], "МЧС")
        self.assertEqual(storage.list_parser_jobs()[0]["status"], "pending")

        paused = self.client.post(
            "/admin/sources",
            data={
                "csrf_token": token,
                "action": "toggle",
                "source": "МЧС",
            },
        )
        self.assertEqual(paused.status_code, 302)
        self.assertFalse(storage.source_is_enabled("МЧС"))

    def test_admin_can_inspect_system_and_create_backup(self):
        self._create_first_admin()
        with (
            patch.object(web_app, "read_recent_errors", return_value=[
                "2026-08-13 10:00:00 | WARNING | test | Сайт не ответил"
            ]),
            patch.object(web_app, "error_log_stats", return_value={
                "path": "parser_errors.log",
                "size_bytes": 128,
                "modified_at": "2026-08-13T10:00:00",
            }),
        ):
            page = self.client.get("/admin/system")

        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Целостность SQLite", html)
        self.assertIn("Автоматическая диагностика", html)
        self.assertIn("Сайт не ответил", html)
        token = self._csrf(page)

        with patch.object(
            web_app,
            "create_manual_backup",
            return_value={"name": "news-manual-test.db", "removed": []},
        ) as create_backup:
            response = self.client.post(
                "/admin/system",
                data={"csrf_token": token, "action": "backup"},
            )

        self.assertEqual(response.status_code, 302)
        create_backup.assert_called_once_with(retention=10)
        self.assertIn("news-manual-test.db", response.headers["Location"])

    def test_admin_can_open_incident_history(self):
        self._create_first_admin()
        storage.sync_source_incidents([{
            "source": "МЧС",
            "status": "error",
            "failure_streak": 3,
            "error": "HTTP 503",
        }])

        page = self.client.get("/admin/incidents?state=active")

        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("История сбоев", html)
        self.assertIn("МЧС", html)
        self.assertIn("Критично", html)
        self.assertIn("HTTP 503", html)

    def test_admin_can_open_reliability_report(self):
        self._create_first_admin()
        storage.sync_source_incidents([{
            "source": "МЧС",
            "status": "error",
            "failure_streak": 1,
            "error": "Timeout",
        }])

        page = self.client.get("/admin/reliability?days=30")

        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Надёжность", html)
        self.assertIn("30 дней", html)
        self.assertIn("МЧС", html)

    def test_user_can_change_own_password(self):
        self._create_first_admin()
        page = self.client.get("/account")
        changed = self.client.post(
            "/account",
            data={
                "csrf_token": self._csrf(page),
                "current_password": "super-secret-2026",
                "new_password": "new-owner-secret-2026",
                "password_confirm": "new-owner-secret-2026",
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.assertIsNone(storage.authenticate_user("owner", "super-secret-2026"))
        self.assertIsNotNone(
            storage.authenticate_user("owner", "new-owner-secret-2026")
        )

    def test_last_active_admin_cannot_be_disabled_or_demoted(self):
        admin = storage.create_user("owner", "super-secret-2026", role="admin")
        with self.assertRaisesRegex(ValueError, "последнего активного"):
            storage.set_user_active(admin["id"], False)
        with self.assertRaisesRegex(ValueError, "последнего активного"):
            storage.set_user_role(admin["id"], "user")
        self.assertTrue(storage.load_user(admin["id"])["is_active"])
        self.assertEqual(storage.load_user(admin["id"])["role"], "admin")
        with self.assertRaisesRegex(ValueError, "последнего активного"):
            storage.delete_user(admin["id"])

    def test_login_page_has_show_password_control(self):
        page = self.client.get("/setup").get_data(as_text=True)
        self.assertIn("password-toggle", page)
        self.assertIn("Показать пароль", page)

    def test_external_next_url_is_not_accepted(self):
        self.assertEqual(web_app.safe_next_url("https://example.com"), "/")
        self.assertEqual(web_app.safe_next_url("//example.com"), "/")
        self.assertEqual(web_app.safe_next_url("/agencies?page=2"), "/agencies?page=2")


if __name__ == "__main__":
    unittest.main()
