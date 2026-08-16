"""Запускает основной парсер и записывает ночную телеметрию ресурсов."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

try:
    import psutil
except ImportError as error:  # pragma: no cover - понятная ошибка для пользователя
    raise SystemExit(
        "Не установлен psutil. Выполните: "
        "python -m pip install -r requirements.txt"
    ) from error


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "night_runs"
CSV_FIELDS = (
    "timestamp",
    "elapsed_seconds",
    "parser_alive",
    "parser_exit_code",
    "tree_processes",
    "python_processes",
    "browser_processes",
    "tree_rss_mb",
    "python_rss_mb",
    "browser_rss_mb",
    "tree_cpu_percent",
    "system_memory_percent",
    "system_available_mb",
    "database_mb",
    "news_count",
    "found_count",
)


def _arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Ночной запуск парсера с мониторингом RAM и CPU",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10,
        help="интервал замеров в секундах (по умолчанию: 10)",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=0,
        help="остановить через N часов; 0 — работать до Ctrl+C",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="каталог для результатов",
    )
    return parser.parse_args(argv)


def _database_path():
    configured = os.environ.get("NEWS_DATABASE_PATH")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_DIR / path
    return PROJECT_DIR / "news.db"


def _database_stats(path):
    stats = {
        "database_mb": round(path.stat().st_size / 1024 / 1024, 3)
        if path.exists()
        else 0,
        "news_count": "",
        "found_count": "",
    }
    if not path.exists():
        return stats
    connection = None
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=1)
        stats["news_count"] = int(
            connection.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
        )
        stats["found_count"] = int(
            connection.execute("SELECT COUNT(*) FROM found_items").fetchone()[0]
        )
    except (OSError, sqlite3.Error):
        # Замер ресурсов не должен мешать работающему парсеру из-за блокировки БД.
        pass
    finally:
        if connection is not None:
            connection.close()
    return stats


def _kind(name):
    lowered = name.lower()
    if "python" in lowered:
        return "python"
    if any(word in lowered for word in ("chromium", "chrome", "msedge", "firefox")):
        return "browser"
    return "other"


def _process_sample(root):
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    seen = set()
    rss = {"python": 0, "browser": 0, "other": 0}
    counts = {"python": 0, "browser": 0, "other": 0}
    cpu_percent = 0.0
    for process in processes:
        if process.pid in seen:
            continue
        seen.add(process.pid)
        try:
            kind = _kind(process.name())
            rss[kind] += process.memory_info().rss
            counts[kind] += 1
            cpu_percent += process.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    total_rss = sum(rss.values())
    return {
        "tree_processes": sum(counts.values()),
        "python_processes": counts["python"],
        "browser_processes": counts["browser"],
        "tree_rss_mb": round(total_rss / 1024 / 1024, 3),
        "python_rss_mb": round(rss["python"] / 1024 / 1024, 3),
        "browser_rss_mb": round(rss["browser"] / 1024 / 1024, 3),
        "tree_cpu_percent": round(cpu_percent, 2),
    }


def _write_summary(path, rows, started_at, exit_code, reason):
    memory = [float(row["tree_rss_mb"]) for row in rows]
    browser = [float(row["browser_rss_mb"]) for row in rows]
    summary = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "stop_reason": reason,
        "parser_exit_code": exit_code,
        "samples": len(rows),
        "duration_hours": round(
            (float(rows[-1]["elapsed_seconds"]) if rows else 0) / 3600,
            3,
        ),
        "tree_rss_start_mb": memory[0] if memory else 0,
        "tree_rss_end_mb": memory[-1] if memory else 0,
        "tree_rss_growth_mb": round(memory[-1] - memory[0], 3) if memory else 0,
        "tree_rss_min_mb": min(memory, default=0),
        "tree_rss_max_mb": max(memory, default=0),
        "browser_rss_max_mb": max(browser, default=0),
        "system_memory_max_percent": max(
            (float(row["system_memory_percent"]) for row in rows),
            default=0,
        ),
    }
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _stop_process(process):
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def run(interval=10, hours=0, output_dir=DEFAULT_OUTPUT_DIR):
    if interval <= 0:
        raise ValueError("Интервал должен быть больше нуля")
    if hours < 0:
        raise ValueError("Количество часов не может быть отрицательным")

    started_at = datetime.now()
    run_dir = Path(output_dir) / started_at.strftime("%Y-%m-%d_%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    csv_path = run_dir / "memory.csv"
    log_path = run_dir / "parser.log"
    summary_path = run_dir / "summary.json"
    database_path = _database_path()
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

    print(f"📁 Результаты ночного запуска: {run_dir}")
    print(f"📏 Замер каждые {interval:g} сек.; остановка — Ctrl+C")
    with log_path.open("w", encoding="utf-8", buffering=1) as parser_log:
        process = subprocess.Popen(
            [sys.executable, "-u", "main.py"],
            cwd=PROJECT_DIR,
            stdout=parser_log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        root = psutil.Process(process.pid)
        # Первый вызов инициализирует счётчики CPU psutil.
        root.cpu_percent(None)
        rows = []
        stop_reason = "parser_exited"
        deadline = time.monotonic() + hours * 3600 if hours else None
        started_monotonic = time.monotonic()

        try:
            with csv_path.open("w", newline="", encoding="utf-8-sig") as output:
                writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
                writer.writeheader()
                while True:
                    alive = process.poll() is None
                    try:
                        process_stats = _process_sample(root)
                    except psutil.NoSuchProcess:
                        process_stats = {
                            "tree_processes": 0,
                            "python_processes": 0,
                            "browser_processes": 0,
                            "tree_rss_mb": 0,
                            "python_rss_mb": 0,
                            "browser_rss_mb": 0,
                            "tree_cpu_percent": 0,
                        }
                    memory = psutil.virtual_memory()
                    row = {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "elapsed_seconds": round(time.monotonic() - started_monotonic, 1),
                        "parser_alive": int(alive),
                        "parser_exit_code": "" if alive else process.returncode,
                        **process_stats,
                        "system_memory_percent": memory.percent,
                        "system_available_mb": round(memory.available / 1024 / 1024, 1),
                        **_database_stats(database_path),
                    }
                    writer.writerow(row)
                    output.flush()
                    rows.append(row)
                    print(
                        f"\rRAM дерева: {row['tree_rss_mb']:>8.1f} МБ | "
                        f"браузеры: {row['browser_rss_mb']:>7.1f} МБ | "
                        f"процессов: {row['tree_processes']:>2} | "
                        f"система: {row['system_memory_percent']:>4.1f}%",
                        end="",
                        flush=True,
                    )
                    if not alive:
                        break
                    if deadline is not None and time.monotonic() >= deadline:
                        stop_reason = "time_limit"
                        break
                    time.sleep(interval)
        except KeyboardInterrupt:
            stop_reason = "keyboard_interrupt"
            print("\n🛑 Останавливаю парсер и сохраняю итог…")
        finally:
            _stop_process(process)
            exit_code = process.poll()
            summary = _write_summary(
                summary_path,
                rows,
                started_at,
                exit_code,
                stop_reason,
            )

    print("\n✅ Ночной замер сохранён")
    print(f"   Пик RAM: {summary['tree_rss_max_mb']:.1f} МБ")
    print(f"   Изменение RAM: {summary['tree_rss_growth_mb']:+.1f} МБ")
    print(f"   Папка: {run_dir}")
    return run_dir


def main(argv=None):
    arguments = _arguments(argv)
    run(arguments.interval, arguments.hours, arguments.output_dir)


if __name__ == "__main__":
    multiprocessing_support = getattr(__import__("multiprocessing"), "freeze_support")
    multiprocessing_support()
    main()
