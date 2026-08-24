"""Небольшие защитные примитивы для публичного веб-интерфейса."""

from collections import defaultdict, deque
from threading import RLock
from time import monotonic


class AttemptLimiter:
    """Ограничивает серию неудачных попыток без хранения паролей."""

    def __init__(self, maximum, window_seconds, lock_seconds):
        self.maximum = max(1, int(maximum))
        self.window_seconds = max(1, int(window_seconds))
        self.lock_seconds = max(1, int(lock_seconds))
        self._attempts = defaultdict(deque)
        self._locked_until = {}
        self._lock = RLock()

    def _prune(self, key, now):
        attempts = self._attempts[key]
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        return attempts

    def retry_after(self, key):
        """Возвращает оставшееся время блокировки в секундах."""
        key = str(key or "")
        now = monotonic()
        with self._lock:
            locked_until = self._locked_until.get(key, 0)
            if locked_until <= now:
                self._locked_until.pop(key, None)
                return 0
            return max(1, int(locked_until - now + 0.999))

    def register_failure(self, key):
        """Записывает отказ и при необходимости включает блокировку."""
        key = str(key or "")
        now = monotonic()
        with self._lock:
            attempts = self._prune(key, now)
            attempts.append(now)
            if len(attempts) < self.maximum:
                return 0
            locked_until = now + self.lock_seconds
            self._locked_until[key] = locked_until
            attempts.clear()
            return self.lock_seconds

    def clear(self, key):
        """Снимает накопленные отказы после успешной аутентификации."""
        key = str(key or "")
        with self._lock:
            self._attempts.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self):
        """Очищает состояние; используется изолированными тестами."""
        with self._lock:
            self._attempts.clear()
            self._locked_until.clear()
