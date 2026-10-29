"""On-demand discovery and safe relay helpers for the TV page.

The worker never imports this module.  Network activity starts only after an
authorised user presses Play on the MID channel.  HLS bytes are relayed without
transcoding, so the server spends bandwidth but almost no CPU on playback.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from threading import Lock, local
from time import monotonic
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils.http_client import HEADERS
from utils.logger import get_logger


MID_VIDEO_PAGE_URL = "https://www.mid.ru/ru/press_service/video/"
MID_RUTUBE_CHANNEL_URL = "https://rutube.ru/channel/23489815/"
MID_RUTUBE_CHANNEL_API = (
    "https://rutube.ru/api/video/person/23489815/"
    "?page=1&format=json&origin__type=rtb,rst,ifrm,rspa"
)
RUTUBE_OPTIONS_URL = (
    "https://rutube.ru/api/play/options/{video_id}/"
    "?format=json&no_404=true&referer=https%253A%252F%252Frutube.ru&pver=v2"
)
RUTUBE_EMBED_URL = "https://rutube.ru/play/embed/{video_id}/?autoplay=true&q=720"
RUSSIA24_PAGE_URL = "https://smotrim.ru/live/21"
RUSSIA24_HLS_URL = "https://stream.smotrim.ru/hls2/russia_24/playlist_3.m3u8"
DISCOVERY_CACHE_SECONDS = 60
DISCOVERY_ERROR_CACHE_SECONDS = 15
MAX_DISCOVERY_DOCUMENT_BYTES = 2_000_000
MAX_MANIFEST_BYTES = 2_000_000
STREAM_CHUNK_BYTES = 128 * 1024
KNOWN_MEDIA_HOST_SUFFIXES = (
    "mid.ru",
    "rutube.ru",
    "rtbcdn.ru",
    "rutube.video",
    "smotrim.ru",
)

logger = get_logger("tv_stream")
_cache_lock = Lock()
_discovery_cache = {"expires": 0.0, "value": None}
_stream_state = local()

_HLS_URL_PATTERN = re.compile(
    r"(?P<url>(?:https?:)?//[^\s\"'<>\\]+?\.m3u8(?:\?[^\s\"'<>\\]*)?)",
    re.IGNORECASE,
)
_QUOTED_HLS_PATTERN = re.compile(
    r"[\"'](?P<url>[^\"']+?\.m3u8(?:\?[^\"']*)?)[\"']",
    re.IGNORECASE,
)
_RUTUBE_ID_PATTERN = re.compile(
    r"(?:rutube\.ru/(?:play/)?embed/|rutube\.ru/(?:live/)?video/"
    r"(?:private/)?)(?P<video_id>[0-9a-f]{32})",
    re.IGNORECASE,
)
_MANIFEST_URI_PATTERN = re.compile(r'URI="(?P<url>[^"]+)"', re.IGNORECASE)


class TvStreamUnavailable(RuntimeError):
    """Raised when the upstream live source cannot be checked or resolved."""


def _request_headers(*, json_response=False, referer=""):
    headers = dict(HEADERS)
    if json_response:
        headers["Accept"] = "application/json"
    if referer:
        headers["Referer"] = referer
    return headers


def _stream_client():
    """Keeps upstream TLS connections pooled per web thread."""
    session = getattr(_stream_state, "session", None)
    if session is not None:
        return session
    retry = Retry(
        total=2,
        connect=2,
        read=1,
        status=1,
        backoff_factor=0.2,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(("GET", "HEAD")),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=24)
    session = requests.Session()
    session.mount("https://", adapter)
    _stream_state.session = session
    return session


def _response_text(response):
    content = bytes(getattr(response, "content", b"") or b"")
    if len(content) > MAX_DISCOVERY_DOCUMENT_BYTES:
        raise TvStreamUnavailable("ответ источника слишком большой")
    if content:
        encoding = getattr(response, "encoding", None) or "utf-8"
        return content.decode(encoding, errors="replace")
    return str(getattr(response, "text", "") or "")


def _get(client, url, *, timeout=(5, 12), json_response=False, referer="", stream=False):
    response = client.get(
        url,
        headers=_request_headers(json_response=json_response, referer=referer),
        timeout=timeout,
        verify=True,
        allow_redirects=True,
        stream=stream,
    )
    response.raise_for_status()
    return response


def _normalise_embedded_text(value):
    text = html.unescape(str(value or ""))
    text = text.replace("\\/", "/")
    try:
        text = unquote(text)
    except (UnicodeDecodeError, ValueError):
        pass
    return text


def extract_hls_url(value, base_url=""):
    """Returns the first HLS URL found in HTML, JSON or JavaScript text."""
    text = _normalise_embedded_text(value)
    for pattern in (_HLS_URL_PATTERN, _QUOTED_HLS_PATTERN):
        match = pattern.search(text)
        if not match:
            continue
        candidate = match.group("url").strip()
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        return urljoin(base_url, candidate)
    return ""


def extract_rutube_video_id(value):
    match = _RUTUBE_ID_PATTERN.search(_normalise_embedded_text(value))
    return match.group("video_id").casefold() if match else ""


def rutube_embed_url(video_id):
    """Builds an official embed URL only for a validated RUTUBE video id."""
    normalised = str(video_id or "").strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{32}", normalised):
        return ""
    return RUTUBE_EMBED_URL.format(video_id=normalised)


def _hls_url_from_options(options):
    if not isinstance(options, dict):
        return ""

    video_balancer = options.get("video_balancer")
    if isinstance(video_balancer, dict):
        for key in ("m3u8", "hls", "default"):
            value = video_balancer.get(key)
            if isinstance(value, str) and ".m3u8" in value.casefold():
                return value

    live_streams = options.get("live_streams")
    if isinstance(live_streams, dict):
        candidates = live_streams.get("hls") or ()
        if isinstance(candidates, dict):
            candidates = (candidates,)
        if isinstance(candidates, (list, tuple)):
            for item in candidates:
                value = item.get("url") if isinstance(item, dict) else item
                if isinstance(value, str) and ".m3u8" in value.casefold():
                    return value

    for value in options.values():
        if isinstance(value, dict):
            nested = _hls_url_from_options(value)
            if nested:
                return nested
    return ""


def _rutube_stream(client, video_id):
    response = _get(
        client,
        RUTUBE_OPTIONS_URL.format(video_id=video_id),
        json_response=True,
        referer=f"https://rutube.ru/play/embed/{video_id}/",
    )
    try:
        options = response.json()
    except (TypeError, ValueError) as error:
        raise TvStreamUnavailable("RUTUBE вернул некорректный JSON") from error
    hls_url = _hls_url_from_options(options)
    if not hls_url:
        raise TvStreamUnavailable("RUTUBE не вернул HLS-поток")
    return hls_url


def _same_mid_host(url):
    hostname = (urlsplit(url).hostname or "").casefold().rstrip(".")
    return hostname == "mid.ru" or hostname.endswith(".mid.ru")


def _discover_from_mid_page(client):
    response = _get(client, MID_VIDEO_PAGE_URL)
    page_url = str(getattr(response, "url", MID_VIDEO_PAGE_URL) or MID_VIDEO_PAGE_URL)
    page_text = _response_text(response)
    documents = [(page_url, page_text)]
    soup = BeautifulSoup(page_text, "html.parser")

    # The official page currently places its live player in a small same-origin
    # iframe.  Follow only likely player frames and never crawl the video list.
    frame_urls = []
    for frame in soup.find_all("iframe", src=True):
        frame_url = urljoin(page_url, str(frame.get("src", "")).strip())
        lowered = frame_url.casefold()
        if _same_mid_host(frame_url) and any(
            marker in lowered for marker in ("player", "stream", "transl", "video")
        ):
            frame_urls.append(frame_url)
        elif "rutube.ru" in lowered:
            video_id = extract_rutube_video_id(frame_url)
            if video_id:
                return {
                    "available": True,
                    "title": "Прямая трансляция МИД России",
                    "hls_url": _rutube_stream(client, video_id),
                    "external_url": MID_VIDEO_PAGE_URL,
                    "video_id": video_id,
                    "embed_url": rutube_embed_url(video_id),
                    "source": "mid-page-rutube",
                }

    for frame_url in dict.fromkeys(frame_urls[:3]):
        try:
            frame_response = _get(client, frame_url, referer=page_url)
            documents.append((frame_url, _response_text(frame_response)))
        except (requests.RequestException, TvStreamUnavailable) as error:
            logger.info("[ТВ · МИД] Не удалось открыть плеер %s: %s", frame_url, error)

    for document_url, document_text in documents:
        hls_url = extract_hls_url(document_text, document_url)
        if hls_url:
            return {
                "available": True,
                "title": "Прямая трансляция МИД России",
                "hls_url": hls_url,
                "external_url": MID_VIDEO_PAGE_URL,
                "video_id": "",
                "source": "mid-page-hls",
            }
        video_id = extract_rutube_video_id(document_text)
        if video_id:
            return {
                "available": True,
                "title": "Прямая трансляция МИД России",
                "hls_url": _rutube_stream(client, video_id),
                "external_url": MID_VIDEO_PAGE_URL,
                "video_id": video_id,
                "embed_url": rutube_embed_url(video_id),
                "source": "mid-page-rutube",
            }
    return None


def _is_active_rutube_live(item):
    if not isinstance(item, dict):
        return False
    is_live_kind = bool(item.get("is_livestream")) or str(
        item.get("stream_type", "")
    ).casefold() in {"live", "livestream"}
    # Older API responses omit is_on_air for an active livestream.  A clear
    # false means scheduled/finished; absence is accepted when the live flag is
    # still true.
    return is_live_kind and item.get("is_on_air") is not False


def _discover_from_rutube_channel(client):
    response = _get(
        client,
        MID_RUTUBE_CHANNEL_API,
        json_response=True,
        referer=MID_RUTUBE_CHANNEL_URL,
    )
    try:
        payload = response.json()
    except (TypeError, ValueError) as error:
        raise TvStreamUnavailable("RUTUBE вернул некорректный список эфиров") from error

    results = payload.get("results", ()) if isinstance(payload, dict) else ()
    live_item = next((item for item in results if _is_active_rutube_live(item)), None)
    if live_item is None:
        return {
            "available": False,
            "reason": "offline",
            "title": "Сейчас прямой трансляции нет",
            "external_url": MID_VIDEO_PAGE_URL,
            "channel_url": MID_RUTUBE_CHANNEL_URL,
        }

    video_id = str(live_item.get("id", "")).strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{32}", video_id):
        raise TvStreamUnavailable("RUTUBE вернул некорректный ID эфира")
    return {
        "available": True,
        "title": str(live_item.get("title", "")).strip()
        or "Прямая трансляция МИД России",
        "hls_url": _rutube_stream(client, video_id),
        "external_url": str(live_item.get("video_url", "")).strip()
        or MID_RUTUBE_CHANNEL_URL,
        "channel_url": MID_RUTUBE_CHANNEL_URL,
        "poster_url": str(
            live_item.get("thumbnail_url") or live_item.get("picture_url") or ""
        ).strip(),
        "video_id": video_id,
        "embed_url": rutube_embed_url(video_id),
        "source": "rutube-channel",
    }


def discover_mid_stream(*, force=False, client=requests):
    """Finds the current MID stream; errors are isolated from the web app."""
    now = monotonic()
    with _cache_lock:
        if not force and _discovery_cache["value"] is not None:
            if float(_discovery_cache["expires"]) > now:
                return dict(_discovery_cache["value"])

    errors = []
    result = None
    try:
        result = _discover_from_mid_page(client)
    except (requests.RequestException, TvStreamUnavailable) as error:
        errors.append(f"сайт МИД: {error}")

    if result is None:
        try:
            result = _discover_from_rutube_channel(client)
        except (requests.RequestException, TvStreamUnavailable) as error:
            errors.append(f"RUTUBE: {error}")

    if result is None:
        detail = "; ".join(errors) or "источники не ответили"
        logger.warning("[ТВ · МИД] Не удалось определить эфир: %s", detail)
        result = {
            "available": False,
            "reason": "unavailable",
            "title": "Не удалось проверить трансляцию",
            "external_url": MID_VIDEO_PAGE_URL,
            "channel_url": MID_RUTUBE_CHANNEL_URL,
        }

    ttl = (
        DISCOVERY_ERROR_CACHE_SECONDS
        if result.get("reason") == "unavailable"
        else DISCOVERY_CACHE_SECONDS
    )
    with _cache_lock:
        _discovery_cache["value"] = dict(result)
        _discovery_cache["expires"] = monotonic() + ttl
    return dict(result)


def _known_media_host(hostname):
    hostname = str(hostname or "").casefold().rstrip(".")
    return any(
        hostname == suffix or hostname.endswith("." + suffix)
        for suffix in KNOWN_MEDIA_HOST_SUFFIXES
    )


def is_safe_stream_url(url, *, resolve_unknown=True):
    """Rejects non-HTTPS and local destinations before the relay connects."""
    try:
        parts = urlsplit(str(url or ""))
        hostname = (parts.hostname or "").casefold().rstrip(".")
        port = parts.port
    except ValueError:
        return False
    if (
        parts.scheme.casefold() != "https"
        or not hostname
        or parts.username
        or parts.password
        or port not in {None, 443}
    ):
        return False
    if hostname == "localhost" or hostname.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        pass
    if _known_media_host(hostname):
        return True
    if not resolve_unknown:
        return False
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except (OSError, socket.gaierror):
        return False
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(address).is_global for address in addresses)
    except ValueError:
        return False


def rewrite_hls_manifest(manifest, base_url, sign_url):
    """Rewrites all playlists, segments and encryption keys through our relay."""

    def relay(value):
        upstream_url = urljoin(base_url, html.unescape(value.strip()))
        if not is_safe_stream_url(upstream_url):
            raise TvStreamUnavailable("HLS-плейлист содержит небезопасный URL")
        return sign_url(upstream_url)

    rewritten = []
    for raw_line in str(manifest or "").splitlines():
        line = raw_line.strip()
        if not line:
            rewritten.append(raw_line)
            continue
        if line.startswith("#"):
            line = _MANIFEST_URI_PATTERN.sub(
                lambda match: f'URI="{relay(match.group("url"))}"',
                line,
            )
            rewritten.append(line)
            continue
        rewritten.append(relay(line))
    return "\n".join(rewritten) + "\n"


def fetch_stream_resource(url, *, range_header="", client=None):
    """Opens one validated HLS manifest or media segment for streaming."""
    if not is_safe_stream_url(url):
        raise TvStreamUnavailable("запрещённый адрес потока")
    client = client or _stream_client()
    referer = (
        RUSSIA24_PAGE_URL
        if "smotrim.ru" in urlsplit(url).netloc
        else MID_RUTUBE_CHANNEL_URL
    )
    headers = _request_headers(referer=referer)
    if range_header:
        headers["Range"] = range_header
    response = client.get(
        url,
        headers=headers,
        timeout=(6, 30),
        verify=True,
        allow_redirects=True,
        stream=True,
    )
    response.raise_for_status()
    final_url = str(getattr(response, "url", url) or url)
    if not is_safe_stream_url(final_url):
        response.close()
        raise TvStreamUnavailable("источник перенаправил поток на запрещённый адрес")
    return response


def is_hls_manifest(response, url):
    content_type = str(response.headers.get("Content-Type", "")).casefold()
    return (
        urlsplit(str(getattr(response, "url", url))).path.casefold().endswith(".m3u8")
        or "mpegurl" in content_type
        or "application/vnd.apple" in content_type
    )


def read_manifest(response):
    content = response.content
    if len(content) > MAX_MANIFEST_BYTES:
        raise TvStreamUnavailable("HLS-плейлист слишком большой")
    encoding = response.encoding or "utf-8"
    return content.decode(encoding, errors="replace")
