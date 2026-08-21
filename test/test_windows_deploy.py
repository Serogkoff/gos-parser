import importlib.util
from pathlib import Path
import tempfile
import unittest


PROJECT_DIR = Path(__file__).resolve().parents[1]
WINDOWS_DEPLOY_DIR = PROJECT_DIR / "deploy" / "windows"


def _load_entrypoint():
    path = PROJECT_DIR / "scripts" / "windows_entrypoint.py"
    spec = importlib.util.spec_from_file_location("windows_entrypoint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windows_entrypoint = _load_entrypoint()


class WindowsEntrypointTests(unittest.TestCase):
    def test_roles_resolve_only_to_existing_project_entrypoints(self):
        self.assertEqual(
            windows_entrypoint._target_path("worker"),
            PROJECT_DIR / "main.py",
        )
        self.assertEqual(
            windows_entrypoint._target_path("web"),
            PROJECT_DIR / "web_app.py",
        )
        with self.assertRaises(ValueError):
            windows_entrypoint._target_path("unknown")

    def test_log_writer_rotates_and_keeps_requested_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.log"
            writer = windows_entrypoint.RotatingTextWriter(
                path,
                max_bytes=12,
                backups=2,
            )
            try:
                writer.write("первая\n")
                writer.write("вторая\n")
                writer.write("третья\n")
                writer.flush()
            finally:
                writer.close()

            self.assertTrue(path.exists())
            self.assertTrue(Path(f"{path}.1").exists())
            self.assertLessEqual(
                len(list(path.parent.glob("worker.log.*"))),
                2,
            )


class WindowsDeployScriptTests(unittest.TestCase):
    def test_installer_uses_logon_tasks_with_restart_and_no_secrets(self):
        installer = (WINDOWS_DEPLOY_DIR / "install.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('"GosParser-Worker"', installer)
        self.assertIn('"GosParser-Web"', installer)
        self.assertIn("New-ScheduledTaskTrigger -AtLogOn", installer)
        self.assertIn("-RestartInterval", installer)
        self.assertIn("-MultipleInstances IgnoreNew", installer)
        self.assertNotIn("MONITOR_SECRET", installer)
        self.assertNotIn("SOCKS", installer)

    def test_uninstaller_preserves_project_data(self):
        uninstaller = (WINDOWS_DEPLOY_DIR / "uninstall.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("Unregister-ScheduledTask", uninstaller)
        self.assertNotIn("Remove-Item", uninstaller)

    def test_updater_tests_remote_commit_before_stopping_tasks(self):
        updater = (WINDOWS_DEPLOY_DIR / "update.ps1").read_text(
            encoding="utf-8"
        )

        test_position = updater.index("-m unittest discover")
        stop_position = updater.index("Stop-ScheduledTask")
        self.assertLess(test_position, stop_position)
        self.assertIn("git merge --ff-only origin/main", updater)
        self.assertIn("create_manual_backup", updater)
        self.assertNotIn("git reset", updater)


if __name__ == "__main__":
    unittest.main()
