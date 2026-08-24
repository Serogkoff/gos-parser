"""Секреты и небольшие помощники аутентификации Flask."""

import os
import secrets
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"
SECRET_FILE = Path(
    os.environ.get("MONITOR_SECRET_FILE", PROJECT_DIR / ".monitor_secret")
)


def environment_value(name, default=""):
    """Читает настройку из окружения или локального закрытого `.env`."""
    configured = os.environ.get(name)
    if configured is not None:
        return configured.strip()
    try:
        lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return default
    prefix = f"{name}="
    result = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result = value
    return default if result is None else result


def load_secret_key():
    """
    Возвращает постоянный секрет сессий.

    На сервере его можно передать через MONITOR_SECRET_KEY. Для локального
    запуска ключ один раз создаётся рядом с проектом и не попадает в Git.
    """
    configured = environment_value("MONITOR_SECRET_KEY")
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
