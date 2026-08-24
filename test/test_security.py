import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import auth
from utils.security import AttemptLimiter


class RuntimeSecurityTests(unittest.TestCase):
    def test_environment_value_reads_last_private_file_value(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "MONITOR_HTTPS=0\n"
                "# MONITOR_HTTPS=ignored\n"
                "MONITOR_HTTPS='1'\n",
                encoding="utf-8",
            )
            with (
                patch.object(auth, "ENV_FILE", env_file),
                patch.dict("os.environ", {}, clear=True),
            ):
                self.assertEqual(auth.environment_value("MONITOR_HTTPS"), "1")
                self.assertEqual(auth.environment_value("MISSING", "fallback"), "fallback")

    def test_environment_takes_precedence_over_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("MONITOR_HTTPS=0\n", encoding="utf-8")
            with (
                patch.object(auth, "ENV_FILE", env_file),
                patch.dict("os.environ", {"MONITOR_HTTPS": "1"}, clear=True),
            ):
                self.assertEqual(auth.environment_value("MONITOR_HTTPS"), "1")

    def test_attempt_limiter_locks_and_can_be_reset(self):
        limiter = AttemptLimiter(2, 60, 120)

        self.assertEqual(limiter.register_failure("client"), 0)
        self.assertEqual(limiter.register_failure("client"), 120)
        self.assertGreater(limiter.retry_after("client"), 0)
        limiter.clear("client")
        self.assertEqual(limiter.retry_after("client"), 0)


if __name__ == "__main__":
    unittest.main()
