from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup

from utils.logger import get_logger

logger = get_logger("js_client")


def fetch_soup_js(url, source_name, wait_ms=2000, timeout_ms=30000):
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

            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                page.wait_for_timeout(wait_ms)
                html = page.content()
            except PlaywrightTimeoutError:
                logger.warning(f"[{source_name}] Таймаут загрузки страницы {url}")
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
