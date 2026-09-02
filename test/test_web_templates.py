import unittest
from pathlib import Path

import web_app


class WebTemplateTests(unittest.TestCase):
    def test_all_page_templates_are_available(self):
        template_names = (
            "admin_incidents.html",
            "admin_reliability.html",
            "admin_sources.html",
            "admin_system.html",
            "article.html",
            "auth.html",
            "bookmarks.html",
            "news.html",
            "notes.html",
            "settings.html",
        )

        for template_name in template_names:
            with self.subTest(template=template_name):
                template = web_app.app.jinja_env.get_template(template_name)
                self.assertEqual(template.name, template_name)

    def test_news_template_keeps_editorial_desktop_layout(self):
        template_path = Path(web_app.app.template_folder) / "news.html"
        template = template_path.read_text(encoding="utf-8")

        for marker in (
            'class="app-layout"',
            'class="left-rail"',
            'class="content-grid"',
            'class="clock-date"',
            'class="source-mark"',
            'class="news-summary"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)


if __name__ == "__main__":
    unittest.main()
