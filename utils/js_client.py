from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from bs4 import BeautifulSoup

from utils.logger import get_logger

logger = get_logger("js_client")
TRANSIENT_BROWSER_ERRORS = (
    "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_RESET",
    "ERR_EMPTY_RESPONSE",
    "ERR_TIMED_OUT",
)


def fetch_soup_js(
    url,
    source_name,
    wait_ms=2000,
    timeout_ms=30000,
    wait_until="networkidle",
    use_partial_on_timeout=False,
):
    """
    Открывает страницу в headless-браузере (для сайтов, которые
    подгружают новости через JS) и возвращает BeautifulSoup-объект.

    Возвращает None при ошибке - и пишет причину в лог, вместо
    того чтобы молча проглотить исключение.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()

            html = None
            for attempt in range(2):
                try:
                    page.goto(
                        url,
                        wait_until=wait_until,
                        timeout=timeout_ms,
                    )
                    page.wait_for_timeout(wait_ms)
                    html = page.content()
                    break
                except PlaywrightTimeoutError:
                    logger.warning(
                        f"[{source_name}] Таймаут загрузки страницы {url}"
                    )
                    if not use_partial_on_timeout:
                        break
                    # Некоторые сайты держат фоновые соединения, хотя
                    # полезная часть страницы уже появилась в DOM.
                    try:
                        page.wait_for_timeout(min(wait_ms, 3000))
                        html = page.content()
                    except Exception:
                        html = None
                    break
                except PlaywrightError as error:
                    transient = _is_transient_browser_error(error)
                    if transient and attempt == 0:
                        logger.info(
                            f"[{source_name}] Временный сетевой сбой; "
                            f"повтор открытия {url}"
                        )
                        page.wait_for_timeout(1500)
                        continue
                    raise

            if html is None:
                context.close()
                browser.close()
                return None

            context.close()
            browser.close()
    except Exception as error:
        logger.warning(
            f"[{source_name}] Ошибка браузера при открытии {url}: "
            f"{type(error).__name__}: {error}"
        )
        return None

    return BeautifulSoup(html, "html.parser")


def _is_transient_browser_error(error):
    return any(
        marker in str(error)
        for marker in TRANSIENT_BROWSER_ERRORS
    )
