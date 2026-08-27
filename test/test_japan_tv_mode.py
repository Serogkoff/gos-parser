from pathlib import Path
import unittest

import web_app


ROOT = Path(__file__).resolve().parents[1]


class JapanTvModeTests(unittest.TestCase):
    def setUp(self):
        self.previous_auth_disabled = web_app.app.config["AUTH_DISABLED"]
        web_app.app.config["AUTH_DISABLED"] = True
        web_app.app.config["TESTING"] = True

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled
        web_app.app.config["TESTING"] = False

    def test_every_html_page_receives_theme_assets(self):
        response = web_app.app.test_client().get("/login")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/japan-tv.css', page)
        self.assertIn('/static/japan-tv.js', page)
        self.assertEqual(page.count('japan-tv.css'), 1)
        self.assertEqual(page.count('japan-tv.js'), 1)

    def test_four_brand_clicks_toggle_hidden_mode(self):
        self.assertIn("if(brandClicks >= 4)", web_app.HTML)
        self.assertIn("window.toggleJapanTVMode()", web_app.HTML)

        script = (ROOT / "static" / "japan-tv.js").read_text(encoding="utf-8")
        self.assertIn("monitor-japan-tv", script)
        self.assertIn("速報モニター", script)
        self.assertIn("window.toggleJapanTVMode", script)

    def test_news_titles_and_article_body_are_not_translated(self):
        script = (ROOT / "static" / "japan-tv.js").read_text(encoding="utf-8")

        self.assertIn(".news-card h3", script)
        self.assertIn("article h1", script)
        self.assertIn(".body", script)


if __name__ == "__main__":
    unittest.main()
