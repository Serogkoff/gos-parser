import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEPLOY_DIR = PROJECT_DIR / "deploy"


class ServerDeployTests(unittest.TestCase):
    def test_services_are_independent_and_restart_automatically(self):
        worker = (DEPLOY_DIR / "gos-parser-worker.service").read_text(
            encoding="utf-8"
        )
        web = (DEPLOY_DIR / "gos-parser-web.service").read_text(encoding="utf-8")

        self.assertIn("main.py", worker)
        self.assertIn("Restart=always", worker)
        self.assertIn("gunicorn", web)
        self.assertIn("wsgi:application", web)
        self.assertIn("Restart=always", web)
        self.assertIn("unix:/run/gos-parser/web.sock", web)

    def test_nginx_uses_unix_socket_and_never_exposes_flask_port(self):
        nginx = (DEPLOY_DIR / "nginx-gos-parser.conf").read_text(encoding="utf-8")

        self.assertIn("unix:/run/gos-parser/web.sock", nginx)
        self.assertIn("location = /healthz", nginx)
        self.assertNotIn("127.0.0.1:5000", nginx)

    def test_environment_example_contains_only_placeholders(self):
        environment = (DEPLOY_DIR / "gos-parser.env.example").read_text(
            encoding="utf-8"
        )

        self.assertIn("replace-with-a-long-random-value", environment)
        self.assertIn("proxy.example", environment)
        self.assertNotIn("serogkoff", environment.casefold())

    def test_installer_does_not_start_before_proxy_review(self):
        installer = (DEPLOY_DIR / "install_ubuntu.sh").read_text(encoding="utf-8")

        self.assertIn("systemctl enable", installer)
        self.assertNotIn("systemctl enable --now", installer)
        self.assertIn("службы пока не запущены", installer)


if __name__ == "__main__":
    unittest.main()
