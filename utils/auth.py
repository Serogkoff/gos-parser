"""Секреты и небольшие помощники аутентификации Flask."""

import os
import secrets
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
SECRET_FILE = Path(
    os.environ.get("MONITOR_SECRET_FILE", PROJECT_DIR / ".monitor_secret")
)


def load_secret_key():
    """
    Возвращает постоянный секрет сессий.

    На сервере его можно передать через MONITOR_SECRET_KEY. Для локального
    запуска ключ один раз создаётся рядом с проектом и не попадает в Git.
    """
    configured = os.environ.get("MONITOR_SECRET_KEY", "").strip()
    if configured:
        return configured

    try:
        existing = SECRET_FILE.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    except FileNotFoundError:
        pass

    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(48)
    try:
        with SECRET_FILE.open("x", encoding="utf-8") as file:
            file.write(generated)
        try:
            SECRET_FILE.chmod(0o600)
        except OSError:
            pass
        return generated
    except FileExistsError:
        existing = SECRET_FILE.read_text(encoding="utf-8").strip()
        if len(existing) < 32:
            raise RuntimeError("Файл секрета приложения повреждён")
        return existing
