"""Изолированный запуск парсеров с настоящим ограничением времени."""

import multiprocessing
import time


class ParserTimeoutError(TimeoutError):
    """Парсер не успел завершиться за отведённое время."""


class ParserExecutionError(RuntimeError):
    """Парсер завершился исключением в дочернем процессе."""


def run_parser_with_timeout(parser_func, timeout_seconds):
    """
    Запускает один парсер в отдельном процессе.

    Поток невозможно безопасно остановить извне, поэтому ThreadPoolExecutor
    здесь не подходит: зависший Playwright продолжал бы жить после таймаута.
    Дочерний процесс можно завершить, не задерживая остальные источники.
    """
    timeout_seconds = max(1.0, float(timeout_seconds))
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_parser_worker,
        args=(parser_func, child_connection),
        name=f"parser-{getattr(parser_func, '__name__', 'source')}",
        daemon=True,
    )
    process.start()
    child_connection.close()
    deadline = time.monotonic() + timeout_seconds
    message = None

    try:
        while message is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ParserTimeoutError(
                    f"превышен лимит {timeout_seconds:g} с"
                )
            if parent_connection.poll(min(0.25, remaining)):
                try:
                    message = parent_connection.recv()
                except EOFError as error:
                    raise ParserExecutionError(
                        "дочерний процесс закрыл канал без результата"
                    ) from error
            elif not process.is_alive():
                raise ParserExecutionError(
                    f"дочерний процесс завершился с кодом "
                    f"{process.exitcode} без результата"
                )

        state, payload = message
        if state == "error":
            raise ParserExecutionError(payload)
        return payload
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        parent_connection.close()


def _parser_worker(parser_func, connection):
    try:
        connection.send(("ok", parser_func()))
    except BaseException as error:
        connection.send(
            (
                "error",
                f"{type(error).__name__}: {str(error)[:500]}",
            )
        )
    finally:
        connection.close()
