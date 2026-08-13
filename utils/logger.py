import logging
import sys
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
ERROR_LOG_FILE = PROJECT_DIR / "parser_errors.log"


def get_logger(name):
    """
    Создаёт логгер, который:
    - печатает INFO и выше в консоль (как обычный print, но с меткой времени)
    - пишет WARNING и выше в файл parser_errors.log

    Использование:
        from utils.logger import get_logger
        logger = get_logger("government")
        logger.warning("Сайт не ответил")
    """
    logger = logging.getLogger(name)

    # Если у логгера уже есть обработчики - значит, get_logger для этого
    # имени уже вызывался раньше. Не добавляем обработчики повторно,
    # иначе одно и то же сообщение будет печататься несколько раз.
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler(ERROR_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.WARNING)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def read_recent_errors(limit=100, max_bytes=256_000):
    """Читает только хвост журнала, не загружая большой файл целиком."""
    try:
        limit = min(500, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = 100
    try:
        max_bytes = min(2_000_000, max(4096, int(max_bytes)))
    except (TypeError, ValueError):
        max_bytes = 256_000
    if not ERROR_LOG_FILE.exists():
        return []
    try:
        with ERROR_LOG_FILE.open("rb") as file:
            file.seek(0, 2)
            size = file.tell()
            file.seek(max(0, size - max_bytes))
            data = file.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # При чтении с середины файла первый фрагмент может быть неполной строкой.
    if size > max_bytes and lines:
        lines = lines[1:]
    return lines[-limit:]


def error_log_stats():
    """Возвращает размер и время изменения журнала ошибок."""
    if not ERROR_LOG_FILE.exists():
        return {"path": str(ERROR_LOG_FILE), "size_bytes": 0, "modified_at": ""}
    try:
        stat = ERROR_LOG_FILE.stat()
    except OSError:
        return {"path": str(ERROR_LOG_FILE), "size_bytes": 0, "modified_at": ""}
    return {
        "path": str(ERROR_LOG_FILE),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
            timespec="seconds"
        ),
    }
