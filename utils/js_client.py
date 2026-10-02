from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from bs4 import BeautifulSoup

from utils.logger import get_logger
from utils.proxy import playwright_proxy

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
    proxy_url="",
    parser="html.parser",
    warmup_url="",
    browser_like=False,
    reject_http_errors=False,
):
    """
    Открывает страницу в headless-браузере (для сайтов, которые
    подгружают новости через JS) и возвращает BeautifulSoup-объект.

    Возвращает None при ошибке - и пишет причину в лог, вместо
    того чтобы молча проглотить исключение.
    """
    try:
        with sync_playwright() as p:
            launch_options = {"headless": True}
            if browser_like:
                launch_options["args"] = [
                    "--disable-blink-features=AutomationControlled",
                ]
            proxy = playwright_proxy(proxy_url)
            if proxy:
                launch_options["proxy"] = proxy
            browser = p.chromium.launch(**launch_options)
            context_options = {"ignore_https_errors": True}
            if browser_like:
                context_options.update({
                    "locale": "ru-RU",
                    "timezone_id": "Europe/Moscow",
                    "user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/140.0.0.0 Safari/537.36"
                    ),
                    "viewport": {"width": 1440, "height": 900},
                    "extra_http_headers": {
                        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
                    },
                })
            context = browser.new_context(**context_options)
            page = context.new_page()

            if warmup_url:
                try:
                    warmup_response = page.goto(
                        warmup_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    if (
                        reject_http_errors
                        and warmup_response is not None
                        and warmup_response.status >= 400
                    ):
                        logger.info(
                            f"[{source_name}] Подготовительная страница "
                            f"ответила HTTP {warmup_response.status}"
                        )
                    page.wait_for_timeout(min(wait_ms, 2500))
                except (PlaywrightError, PlaywrightTimeoutError) as error:
                    # Основной запрос остаётся решающим: прогрев нужен только
                    # для cookies и не должен сам по себе отменять загрузку.
                    logger.info(
                        f"[{source_name}] Не удалось подготовить сессию: "
                        f"{type(error).__name__}"
                    )

            html = None
            for attempt in range(2):
                try:
                    navigation_options = {
                        "wait_until": wait_until,
                        "timeout": timeout_ms,
                    }
                    if warmup_url:
                        navigation_options["referer"] = warmup_url
                    response = page.goto(url, **navigation_options)
                    page.wait_for_timeout(wait_ms)
                    if (
                        reject_http_errors
                        and response is not None
                        and response.status >= 400
                    ):
                        logger.warning(
                            f"[{source_name}] Браузер получил HTTP "
                            f"{response.status} на {url}"
                        )
                        html = None
                        break
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

    return BeautifulSoup(html, parser)


def fetch_response_soup_js(
    url,
    source_name,
    timeout_ms=45000,
    wait_ms=2500,
    proxy_url="",
    parser="html.parser",
    warmup_url="",
):
    """Loads a response in Chromium and parses its original response body.

    This is intentionally separate from ``fetch_soup_js``: XML feeds need the
    network response, not Chromium's HTML XML-viewer representation.  It is a
    narrow fallback for public sites that reject the requests client while
    still serving a normal browser through the same configured proxy.
    """
    try:
        with sync_playwright() as p:
            launch_options = {
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            proxy = playwright_proxy(proxy_url)
            if proxy:
                launch_options["proxy"] = proxy
            browser = p.chromium.launch(**launch_options)
            context = browser.new_context(
                ignore_https_errors=True,
                locale="ru-RU",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            if warmup_url:
                try:
                    page.goto(
                        warmup_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    page.wait_for_timeout(wait_ms)
                except (PlaywrightError, PlaywrightTimeoutError):
                    # The target request below is authoritative.  A failed
                    # warm-up should not suppress it.
                    pass

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            page.wait_for_timeout(wait_ms)
            if response is None:
                raise PlaywrightError("navigation returned no response")
            if response.status >= 400:
                logger.warning(
                    f"[{source_name}] Браузер получил HTTP {response.status} "
                    f"на {url}"
                )
                context.close()
                browser.close()
                return None
            body = response.body()
            context.close()
            browser.close()
    except Exception as error:
        logger.warning(
            f"[{source_name}] Ошибка браузерной загрузки ответа {url}: "
            f"{type(error).__name__}: {error}"
        )
        return None

    if not body:
        logger.warning(f"[{source_name}] Браузер вернул пустой ответ: {url}")
        return None
    return BeautifulSoup(body, parser)


def _is_transient_browser_error(error):
    return any(
        marker in str(error)
        for marker in TRANSIENT_BROWSER_ERRORS
    )
