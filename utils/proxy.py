"""Изолированные настройки прокси для источников с региональным доступом."""

import os
import time
from pathlib import Path
from threading import Lock
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import requests


PROJECT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_DIR / ".env"
SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}
KYODO_CHECK_URL = "https://www.47news.jp/news"
_kyodo_status_cache = {
    "checked_monotonic": 0.0,
    "value": None,
    "proxy_url": "",
    "candidate_index": None,
}
_kyodo_status_lock = Lock()


def kyodo_proxy_url():
    """Возвращает доступный маршрут, предпочитая основной SOCKS5."""
    candidates = _configured_proxy_urls()
    if len(candidates) <= 1:
        return candidates[0] if candidates else ""
    selected, _index = _select_proxy_route(candidates)
    # Если обе проверки временно не прошли, сохраняем прежнее поведение:
    # конкретный парсер сам выполнит запрос и запишет содержательную ошибку.
    return selected or candidates[0]


def kyodo_proxy_candidates():
    """Возвращает маршруты для запроса: рабочий первым, остальные резервом."""
    candidates = _configured_proxy_urls()
    if len(candidates) <= 1:
        return tuple(candidates)
    selected, _index = _select_proxy_route(candidates)
    if not selected:
        return tuple(candidates)
    return tuple([selected, *(item for item in candidates if item != selected)])


def kyodo_proxy_status(force=False):
    """Проверяет реальный доступ к 47NEWS через выделенный маршрут Киодо."""
    try:
        candidates = _configured_proxy_urls()
    except ValueError:
        result = {
            "ok": False,
            "state": "invalid",
            "label": "VPN недоступен",
            "detail": "Проверьте настройки канала Киодо",
        }
    else:
        if not candidates:
            result = {
                "ok": False,
                "state": "missing",
                "label": "VPN недоступен",
                "detail": "Канал Киодо не настроен",
            }
        else:
            proxy_url, candidate_index = _select_proxy_route(
                candidates,
                force=force,
            )
            if proxy_url:
                if candidate_index == 0:
                    detail = "47NEWS доступен через основной канал"
                    state = "ok"
                    label = "VPN работает"
                else:
                    detail = "Основной канал недоступен; включён резервный SOCKS5"
                    state = "backup"
                    label = "Резервный VPN"
                result = {
                    "ok": True,
                    "state": state,
                    "label": label,
                    "detail": detail,
                }
            else:
                result = {
                    "ok": False,
                    "state": "unavailable",
                    "label": "VPN недоступен",
                    "detail": "47NEWS не отвечает через основной и резервный каналы",
                }
    return result


def _configured_proxy_urls():
    primary = _setting("KYODO_PROXY_URL") or _proxy_url_from_separate_settings()
    backup = (
        _setting("KYODO_PROXY_BACKUP_URL")
        or _proxy_url_from_separate_settings("KYODO_PROXY_BACKUP")
    )
    result = []
    for value in (primary, backup):
        value = _validate_proxy_url(value)
        if value and value not in result:
            result.append(value)
    return result


def _select_proxy_route(candidates, force=False):
    """Проверяет маршруты по порядку и кэширует выбор на одну минуту."""
    now = time.monotonic()
    with _kyodo_status_lock:
        cached_value = _kyodo_status_cache["value"]
        cached_url = _kyodo_status_cache["proxy_url"]
        if (
            not force
            and cached_value is not None
            and now - _kyodo_status_cache["checked_monotonic"] < 60
            and (not cached_url or cached_url in candidates)
        ):
            return cached_url, _kyodo_status_cache["candidate_index"]

        selected = ""
        selected_index = None
        for index, proxy_url in enumerate(candidates):
            if _proxy_is_available(proxy_url):
                selected = proxy_url
                selected_index = index
                break

        _kyodo_status_cache.update({
            "checked_monotonic": now,
            "value": bool(selected),
            "proxy_url": selected,
            "candidate_index": selected_index,
        })
        return selected, selected_index


def _proxy_is_available(proxy_url):
    try:
        response = requests.get(
            KYODO_CHECK_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=(3, 6),
            proxies=requests_proxies(proxy_url),
            stream=True,
        )
        response.raise_for_status()
        response.close()
        return True
    except requests.RequestException:
        return False


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


def _proxy_url_from_separate_settings(prefix="KYODO_PROXY"):
    host = _setting(f"{prefix}_HOST")
    port = _setting(f"{prefix}_PORT")
    username = _setting(f"{prefix}_USERNAME")
    password = _setting(f"{prefix}_PASSWORD")
    if not any((host, port, username, password)):
        return ""
    if not host or not port:
        raise ValueError("для VPN-маршрута требуются адрес и порт")

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
