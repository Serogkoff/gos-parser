import time

import requests
from bs4 import BeautifulSoup

from utils.logger import get_logger

logger = get_logger("http_client")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_ATTEMPTS = 2


def fetch_soup(
    url,
    source_name,
    timeout=30,
    verify=False,
    parser="html.parser",
    attempts=DEFAULT_ATTEMPTS,
    proxy_url="",
):
    """
    Скачивает страницу по url и возвращает объект BeautifulSoup.

    Если что-то пошло не так (таймаут, сайт недоступен, ошибка 404/500 и т.д.),
    возвращает None и пишет ПРИЧИНУ в лог (в консоль и в parser_errors.log) -
    вместо того чтобы молча проглотить ошибку через except: pass.

    source_name нужен просто для того, чтобы в логе было понятно,
    какой именно сайт не ответил.
    """
    attempts = max(1, int(attempts))
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                verify=verify,
                proxies=(
                    {"http": proxy_url, "https": proxy_url}
                    if proxy_url else None
                ),
            )
            response.raise_for_status()
            if not response.content:
                raise requests.exceptions.ConnectionError("получен пустой ответ")
            return BeautifulSoup(response.content, parser)

        except requests.exceptions.Timeout:
            if attempt < attempts:
                _wait_before_retry(source_name, url, attempt, "таймаут")
                continue
            logger.warning(f"[{source_name}] Таймаут при запросе {url}")

        except requests.exceptions.ConnectionError as error:
            if attempt < attempts:
                _wait_before_retry(
                    source_name,
                    url,
                    attempt,
                    "сброс соединения",
                )
                continue
            logger.warning(f"[{source_name}] Ошибка соединения с {url}: {error}")

        except requests.exceptions.HTTPError:
            status_code = response.status_code
            if status_code in TRANSIENT_STATUS_CODES and attempt < attempts:
                delay = _retry_after_seconds(response) or min(2 * attempt, 6)
                logger.info(
                    f"[{source_name}] HTTP {status_code}; "
                    f"повтор через {delay} с: {url}"
                )
                time.sleep(delay)
                continue
            logger.warning(
                f"[{source_name}] Сайт ответил ошибкой "
                f"{status_code} на {url}"
            )

        except requests.exceptions.RequestException as error:
            logger.warning(
                f"[{source_name}] Неизвестная ошибка запроса к {url}: {error}"
            )
        return None

    return None


def _wait_before_retry(source_name, url, attempt, reason):
    delay = min(2 * attempt, 6)
    logger.info(
        f"[{source_name}] {reason}; повтор через {delay} с: {url}"
    )
    time.sleep(delay)


def _retry_after_seconds(response):
    value = str(response.headers.get("Retry-After", "")).strip()
    if value.isdigit():
        return min(max(int(value), 1), 30)
    return 0
