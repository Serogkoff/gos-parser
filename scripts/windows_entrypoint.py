"""Фоновый запуск worker/web с UTF-8 и ограниченными по размеру логами."""

import argparse
import os
import runpy
import sys
from datetime import datetime
from pathlib import Path
from threading import RLock


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_DIR / "runtime_logs"
DEFAULT_MAX_LOG_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_BACKUPS = 7
TARGETS = {
    "worker": PROJECT_DIR / "main.py",
    "web": PROJECT_DIR / "web_app.py",
}


def _positive_integer(value, default):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _log_settings():
    directory = Path(os.environ.get("GOS_PARSER_LOG_DIR", DEFAULT_LOG_DIR))
    max_bytes = _positive_integer(
        os.environ.get("GOS_PARSER_LOG_MAX_BYTES"),
        DEFAULT_MAX_LOG_BYTES,
    )
    backups = _positive_integer(
        os.environ.get("GOS_PARSER_LOG_BACKUPS"),
        DEFAULT_LOG_BACKUPS,
    )
    return directory, max_bytes, backups


class RotatingTextWriter:
    """Простой UTF-8 writer для stdout/stderr без внешних зависимостей."""

    encoding = "utf-8"

    def __init__(self, path, max_bytes, backups):
        self.path = Path(path)
        self.max_bytes = _positive_integer(max_bytes, DEFAULT_MAX_LOG_BYTES)
        self.backups = _positive_integer(backups, DEFAULT_LOG_BACKUPS)
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8", buffering=1)

    def _rotate_if_needed(self, text):
        try:
            current_size = self.path.stat().st_size
        except OSError:
            current_size = 0
        # Одна очень длинная строка может быть больше лимита. Пустой файл
        # бессмысленно переносить в историю перед первой записью.
        if current_size == 0:
            return
        if current_size + len(text.encode("utf-8")) <= self.max_bytes:
            return

        self._file.close()
        oldest = self.path.with_name(f"{self.path.name}.{self.backups}")
        if oldest.exists():
            oldest.unlink()
        for number in range(self.backups - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{number}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{number + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))
        self._file = self.path.open("a", encoding="utf-8", buffering=1)

    def write(self, value):
        text = str(value)
        if not text:
            return 0
        with self._lock:
            self._rotate_if_needed(text)
            return self._file.write(text)

    def flush(self):
        with self._lock:
            self._file.flush()

    def close(self):
        with self._lock:
            if not self._file.closed:
                self._file.close()

    @property
    def closed(self):
        return self._file.closed

    def isatty(self):
        return False


def _target_path(role):
    try:
        return TARGETS[role]
    except KeyError as error:
        raise ValueError(f"Неизвестная роль: {role}") from error


def run(role):
    target = _target_path(role)
    log_dir, max_bytes, backups = _log_settings()
    writer = RotatingTextWriter(log_dir / f"{role}.log", max_bytes, backups)
    previous_stdout, previous_stderr = sys.stdout, sys.stderr
    previous_argv = sys.argv[:]
    previous_sys_path = sys.path[:]
    previous_cwd = Path.cwd()
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"
    try:
        sys.stdout = writer
        sys.stderr = writer
        sys.argv = [str(target)]
        os.chdir(PROJECT_DIR)
        project_path = str(PROJECT_DIR)
        if project_path not in sys.path:
            sys.path.insert(0, project_path)
        print("\n" + "=" * 70)
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} | запуск Windows-задачи: {role}")
        print(f"Python: {sys.executable}")
        print(f"Проект: {PROJECT_DIR}")
        print("=" * 70, flush=True)
        runpy.run_path(str(target), run_name="__main__")
    finally:
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr
        sys.argv = previous_argv
        sys.path[:] = previous_sys_path
        os.chdir(previous_cwd)
        writer.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Фоновый запуск gos-parser на Windows")
    parser.add_argument("role", choices=sorted(TARGETS))
    arguments = parser.parse_args(argv)
    run(arguments.role)


if __name__ == "__main__":
    main()
