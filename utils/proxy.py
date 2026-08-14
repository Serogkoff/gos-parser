"""Изолированные настройки прокси для источников с региональным доступом."""

import os
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit


PROJECT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_DIR / ".env"
SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}


def kyodo_proxy_url():
    """Возвращает SOCKS/HTTP-прокси Киодо, не раскрывая его в логах."""
    value = _setting("KYODO_PROXY_URL")
    if not value:
        value = _proxy_url_from_separate_settings()
    return _validate_proxy_url(value)


def requests_proxies(proxy_url):
    """Готовит явный маршрут requests только для конкретного вызова."""
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def playwright_proxy(proxy_url):
    """Преобразует URL с учётными данными в конфигурацию Playwright."""
    if not proxy_url:
        return None

    parts = urlsplit(proxy_url)
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host + (f":{parts.port}" if parts.port else "")
    # requests использует socks5h, чтобы DNS также шёл через прокси.
    # Chromium называет тот же режим просто socks5.
    browser_scheme = "socks5" if parts.scheme.casefold() == "socks5h" else parts.scheme
    result = {
        "server": urlunsplit((browser_scheme, netloc, "", "", "")),
    }
    if parts.username is not None:
        result["username"] = unquote(parts.username)
    if parts.password is not None:
        result["password"] = unquote(parts.password)
    return result


def proxy_environment(proxy_url):
    """Передаёт прокси дочернему curl без пароля в командной строке."""
    environment = os.environ.copy()
    if proxy_url:
        environment["ALL_PROXY"] = proxy_url
        environment["all_proxy"] = proxy_url
    return environment


def _read_env_value(name):
    try:
        lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""

    prefix = f"{name}="
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value.strip()
    return ""


def _setting(name):
    return os.environ.get(name, "").strip() or _read_env_value(name)


def _proxy_url_from_separate_settings():
    host = _setting("KYODO_PROXY_HOST")
    port = _setting("KYODO_PROXY_PORT")
    username = _setting("KYODO_PROXY_USERNAME")
    password = _setting("KYODO_PROXY_PASSWORD")
    if not any((host, port, username, password)):
        return ""
    if not host or not port:
        raise ValueError("для прокси Киодо требуются адрес и порт")

    host = host.removeprefix("[").removesuffix("]")
    if ":" in host:
        host = f"[{host}]"
    credentials = ""
    if username or password:
        credentials = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return f"socks5h://{credentials}{host}:{port}"


def _validate_proxy_url(value):
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme.casefold() not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError("KYODO_PROXY_URL использует неподдерживаемый протокол")
    if not parts.hostname or not parts.port:
        raise ValueError("KYODO_PROXY_URL должен содержать адрес и порт")
    return value
