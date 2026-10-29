import unittest
from unittest.mock import patch

import web_app
from utils import tv_stream


class FakeResponse:
    def __init__(self, *, url, content=b"", payload=None, headers=None, status=200):
        self.url = url
        self.content = content
        self._payload = payload
        self.headers = headers or {}
        self.status_code = status
        self.encoding = "utf-8"

    @property
    def text(self):
        return self.content.decode(self.encoding)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        return None

    def iter_content(self, chunk_size=1):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError(f"unexpected request: {url}")
        return self.responses.pop(0)


class TvStreamTests(unittest.TestCase):
    def test_extracts_escaped_hls_and_rutube_ids(self):
        self.assertEqual(
            tv_stream.extract_hls_url(
                r'window.source="https:\/\/video-storage.rutube.ru\/hls\/live\/master.m3u8?x=1"'
            ),
            "https://video-storage.rutube.ru/hls/live/master.m3u8?x=1",
        )
        self.assertEqual(
            tv_stream.extract_rutube_video_id(
                "https://rutube.ru/play/embed/33e5364433359c6be79b89a00034e8a5/"
            ),
            "33e5364433359c6be79b89a00034e8a5",
        )
        self.assertEqual(
            tv_stream.rutube_embed_url("33e5364433359c6be79b89a00034e8a5"),
            "https://rutube.ru/play/embed/33e5364433359c6be79b89a00034e8a5/"
            "?autoplay=true&q=720",
        )
        self.assertEqual(tv_stream.rutube_embed_url("bad"), "")

    def test_discovers_hls_in_official_mid_player_iframe(self):
        page = b'<iframe src="/assets/mid_player_live.html?v=2"></iframe>'
        player = (
            b'<script>const source="https://video-storage.rutube.ru/'
            b'hls/mid/master.m3u8?token=ok";</script>'
        )
        client = FakeClient(
            [
                FakeResponse(url=tv_stream.MID_VIDEO_PAGE_URL, content=page),
                FakeResponse(
                    url="https://www.mid.ru/assets/mid_player_live.html?v=2",
                    content=player,
                ),
            ]
        )

        result = tv_stream._discover_from_mid_page(client)

        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "mid-page-hls")
        self.assertEqual(
            result["hls_url"],
            "https://video-storage.rutube.ru/hls/mid/master.m3u8?token=ok",
        )
        self.assertEqual(len(client.urls), 2)

    def test_discovers_only_active_rutube_live(self):
        video_id = "1" * 32
        client = FakeClient(
            [
                FakeResponse(
                    url=tv_stream.MID_RUTUBE_CHANNEL_API,
                    payload={
                        "results": [
                            {"id": "2" * 32, "is_livestream": True, "is_on_air": False},
                            {
                                "id": video_id,
                                "title": "Брифинг",
                                "is_livestream": True,
                                "is_on_air": True,
                                "video_url": f"https://rutube.ru/video/{video_id}/",
                            },
                        ]
                    },
                ),
                FakeResponse(
                    url=tv_stream.RUTUBE_OPTIONS_URL.format(video_id=video_id),
                    payload={
                        "video_balancer": {
                            "m3u8": "https://bl.rutube.ru/route/live.m3u8?token=ok"
                        }
                    },
                ),
            ]
        )

        result = tv_stream._discover_from_rutube_channel(client)

        self.assertTrue(result["available"])
        self.assertEqual(result["title"], "Брифинг")
        self.assertEqual(result["video_id"], video_id)
        self.assertIn(video_id, result["embed_url"])

    def test_reports_offline_without_requesting_play_options(self):
        client = FakeClient(
            [
                FakeResponse(
                    url=tv_stream.MID_RUTUBE_CHANNEL_API,
                    payload={"results": [{"is_livestream": False}]},
                )
            ]
        )

        result = tv_stream._discover_from_rutube_channel(client)

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "offline")
        self.assertEqual(len(client.urls), 1)

    def test_accepts_live_item_when_legacy_api_omits_on_air_flag(self):
        self.assertTrue(
            tv_stream._is_active_rutube_live(
                {"is_livestream": True, "id": "a" * 32}
            )
        )

    def test_rewrites_every_hls_resource_through_signed_relay(self):
        manifest = "\n".join(
            (
                "#EXTM3U",
                '#EXT-X-KEY:METHOD=AES-128,URI="keys/live.key"',
                "#EXTINF:4.0,",
                "segments/one.ts",
                "https://bl.rutube.ru/segments/two.ts?x=1",
            )
        )

        result = tv_stream.rewrite_hls_manifest(
            manifest,
            "https://video-storage.rutube.ru/hls/live/index.m3u8",
            lambda url: "/relay/" + url,
        )

        self.assertIn(
            'URI="/relay/https://video-storage.rutube.ru/hls/live/keys/live.key"',
            result,
        )
        self.assertIn(
            "/relay/https://video-storage.rutube.ru/hls/live/segments/one.ts",
            result,
        )
        self.assertIn(
            "/relay/https://bl.rutube.ru/segments/two.ts?x=1",
            result,
        )

    def test_relay_rejects_local_or_unsigned_style_destinations(self):
        self.assertTrue(
            tv_stream.is_safe_stream_url(
                "https://video-storage.rutube.ru/hls/live/master.m3u8",
                resolve_unknown=False,
            )
        )
        for url in (
            "http://bl.rutube.ru/live.m3u8",
            "https://localhost/live.m3u8",
            "https://127.0.0.1/live.m3u8",
            "https://user:pass@bl.rutube.ru/live.m3u8",
            "https://example.com/live.m3u8",
        ):
            with self.subTest(url=url):
                self.assertFalse(
                    tv_stream.is_safe_stream_url(url, resolve_unknown=False)
                )


class TvStreamWebTests(unittest.TestCase):
    def setUp(self):
        self.previous_auth_disabled = web_app.app.config["AUTH_DISABLED"]
        web_app.app.config["AUTH_DISABLED"] = True
        self.client = web_app.app.test_client()

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled

    def test_mid_discovery_returns_only_signed_local_relay_url(self):
        discovered = {
            "available": True,
            "title": "Прямой эфир",
            "hls_url": "https://bl.rutube.ru/route/live.m3u8?token=secret",
            "external_url": tv_stream.MID_VIDEO_PAGE_URL,
            "embed_url": "https://rutube.ru/play/embed/" + "1" * 32 + "/",
            "source": "rutube-channel",
        }
        with patch("web_app.discover_mid_stream", return_value=discovered):
            response = self.client.get("/api/tv/mid-stream")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["transport"], "ria")
        self.assertTrue(payload["stream_url"].startswith("/api/tv/hls/"))
        self.assertTrue(payload["embed_url"].startswith("https://rutube.ru/play/embed/"))
        self.assertNotIn("hls_url", payload)
        self.assertNotIn("token=secret", response.get_data(as_text=True))

    def test_russia24_returns_official_stream_and_signed_fallback(self):
        response = self.client.get("/api/tv/russia24-stream")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["direct_stream_url"], tv_stream.RUSSIA24_HLS_URL)
        self.assertTrue(payload["stream_url"].startswith("/api/tv/hls/"))
        self.assertEqual(payload["transport"], "auto")

    def test_mid_offline_is_normal_response(self):
        discovered = {
            "available": False,
            "reason": "offline",
            "title": "Сейчас прямой трансляции нет",
            "external_url": tv_stream.MID_VIDEO_PAGE_URL,
        }
        with patch("web_app.discover_mid_stream", return_value=discovered):
            response = self.client.get("/api/tv/mid-stream")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["available"])

    def test_hls_manifest_is_rewritten_to_signed_local_urls(self):
        upstream_url = "https://video-storage.rutube.ru/live/master.m3u8"
        manifest = b"#EXTM3U\n#EXTINF:4,\nsegment-1.ts\n"
        upstream = FakeResponse(
            url=upstream_url,
            content=manifest,
            headers={"Content-Type": "application/vnd.apple.mpegurl"},
        )
        with web_app.app.test_request_context():
            token = web_app._tv_stream_serializer().dumps({"url": upstream_url})

        with patch("web_app.fetch_stream_resource", return_value=upstream):
            response = self.client.get(f"/api/tv/hls/{token}")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("#EXTM3U", body)
        self.assertIn("/api/tv/hls/", body)
        self.assertNotIn("segment-1.ts\n", body.replace("/api/tv/hls/", ""))
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_hls_relay_rejects_invalid_signature(self):
        response = self.client.get("/api/tv/hls/not-a-signed-token")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
