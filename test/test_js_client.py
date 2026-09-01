import unittest
from unittest import mock

from utils import js_client


class JsClientTests(unittest.TestCase):
    def _browser(self, document_body, page_html):
        playwright_manager = mock.MagicMock()
        playwright = playwright_manager.__enter__.return_value
        browser = playwright.chromium.launch.return_value
        browser.version = "151.0.7922.34"
        context = browser.new_context.return_value
        page = context.new_page.return_value
        page.main_frame = object()
        page.content.return_value = page_html

        response = mock.MagicMock()
        response.request.resource_type = "document"
        response.frame = page.main_frame
        response.body.return_value = document_body

        handlers = {}
        page.on.side_effect = lambda event, handler: handlers.__setitem__(
            event,
            handler,
        )

        def goto(*args, **kwargs):
            handlers["response"](response)
            return response

        page.goto.side_effect = goto
        return playwright_manager, browser, page

    def test_can_parse_original_xml_response_instead_of_browser_view(self):
        raw_feed = b"""
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry><title>News from raw response</title></entry>
            </feed>
        """
        manager, browser, page = self._browser(
            raw_feed,
            "<html><body>XML browser viewer</body></html>",
        )

        with mock.patch.object(js_client, "sync_playwright", return_value=manager):
            soup = js_client.fetch_soup_js(
                "https://example.test/feed.xml",
                "Test feed",
                parser="xml",
                response_body=True,
                desktop_user_agent=True,
            )

        self.assertEqual(soup.find("entry").title.get_text(), "News from raw response")
        browser.new_context.assert_called_once_with(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.7922.34 Safari/537.36"
            ),
        )
        page.content.assert_not_called()

    def test_regular_pages_still_use_rendered_dom(self):
        manager, browser, page = self._browser(
            b"<html><body>Raw response</body></html>",
            "<html><body><article>Rendered page</article></body></html>",
        )

        with mock.patch.object(js_client, "sync_playwright", return_value=manager):
            soup = js_client.fetch_soup_js(
                "https://example.test/page",
                "Test page",
            )

        self.assertEqual(soup.article.get_text(), "Rendered page")
        browser.new_context.assert_called_once_with(ignore_https_errors=True)
        page.content.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
