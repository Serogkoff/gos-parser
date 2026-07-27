import logging
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


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

    file_handler = logging.FileHandler(PROJECT_DIR / "parser_errors.log", encoding="utf-8")
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
