"""Операции с пользователями и проверка учётных данных."""

import sqlite3
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash


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


class UserStorage:
    def __init__(self, initialize_database, connection_factory, lock):
        self._initialize_database = initialize_database
        self._connection_factory = connection_factory
        self._lock = lock

    def count_users(self):
        """Возвращает число учётных записей, включая отключённые."""
        self._initialize_database()
        with self._connection_factory() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, username, password, role="user"):
        """Создаёт пользователя с хешем пароля; открытый пароль не хранится."""
        username = _validate_username(username)
        password = _validate_password(password)
        role = str(role or "user").strip().casefold()
        if role not in {"admin", "user"}:
            raise ValueError("Неизвестная роль пользователя")

        self._initialize_database()
        created_at = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock, self._connection_factory() as connection:
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
        return self.load_user(user_id)

    def load_user(self, user_id):
        """Возвращает безопасные поля пользователя без хеша пароля."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None
        self._initialize_database()
        with self._connection_factory() as connection:
            row = connection.execute(
                """
                SELECT id, username, role, is_active, created_at, last_login_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return _user_from_row(row)

    def list_users(self):
        """Возвращает безопасный список пользователей без хешей паролей."""
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT id, username, role, is_active, created_at, last_login_at
                FROM users
                ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END,
                         username COLLATE NOCASE
                """
            ).fetchall()
        return [_user_from_row(row) for row in rows]

    def set_user_password(self, user_id, password):
        """Заменяет пароль пользователя новым защищённым хешем."""
        password = _validate_password(password)
        user = self.load_user(user_id)
        if user is None:
            raise ValueError("Пользователь не найден")
        with self._lock, self._connection_factory() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), user["id"]),
            )
        return self.load_user(user["id"])

    def set_user_role(self, user_id, role):
        """Меняет роль, не позволяя убрать последнего активного администратора."""
        role = str(role or "").strip().casefold()
        if role not in {"admin", "user"}:
            raise ValueError("Неизвестная роль пользователя")
        try:
            user_id = int(user_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Пользователь не найден") from error

        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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
        return self.load_user(user_id)

    def set_user_active(self, user_id, is_active):
        """Включает или отключает вход, сохраняя все данные пользователя."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Пользователь не найден") from error
        is_active = bool(is_active)

        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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
        return self.load_user(user_id)

    def delete_user(self, user_id):
        """Удаляет аккаунт и связанные личные данные, сохраняя последнего администратора."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Пользователь не найден") from error

        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT username, role, is_active FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Пользователь не найден")
            if row["role"] == "admin" and row["is_active"]:
                active_admins = connection.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
                ).fetchone()[0]
                if active_admins <= 1:
                    raise ValueError("Нельзя удалить последнего активного администратора")
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return row["username"]

    def authenticate_user(self, username, password):
        """Проверяет пароль и возвращает активного пользователя."""
        username = " ".join(str(username or "").split())
        password = str(password or "")
        if not username or not password:
            return None
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
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
