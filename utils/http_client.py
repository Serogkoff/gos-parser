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


def fetch_soup(url, source_name, timeout=30, verify=False, parser="html.parser"):
    """
    Скачивает страницу по url и возвращает объект BeautifulSoup.

    Если что-то пошло не так (таймаут, сайт недоступен, ошибка 404/500 и т.д.),
    возвращает None и пишет ПРИЧИНУ в лог (в консоль и в parser_errors.log) -
    вместо того чтобы молча проглотить ошибку через except: pass.

    source_name нужен просто для того, чтобы в логе было понятно,
    какой именно сайт не ответил.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, verify=verify)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning(f"[{source_name}] Таймаут при запросе {url}")
        return None
    except requests.exceptions.ConnectionError as error:
        logger.warning(f"[{source_name}] Ошибка соединения с {url}: {error}")
        return None
    except requests.exceptions.HTTPError:
        logger.warning(
            f"[{source_name}] Сайт ответил ошибкой "
            f"{response.status_code} на {url}"
        )
        return None
    except requests.exceptions.RequestException as error:
        logger.warning(f"[{source_name}] Неизвестная ошибка запроса к {url}: {error}")
        return None

    return BeautifulSoup(response.content, parser)
