"""«Вёрстка»: только оригинальный verstka.media через VPN."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source

SOURCE_NAME = "Вёрстка"
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://verstka.media/feed/",
    domains=("verstka.media",),
    article_selectors=(".vm-single-post-content", "article", "main"),
    rss_full_text_fallback=True,
    prefer_rss_full_text=True,
    # Оригинальный домен остаётся главным и запрашивается через VPN. Сейчас
    # Cloudflare отвечает этому VPN кодом 403, а прямое соединение из РФ
    # обрывается на TLS. Зеркало используется только для обнаружения новых
    # публикаций; все ссылки сразу возвращаются на канонический домен.
    feed_fallback_urls=("https://verstka-media.nproxy.org/feed/",),
    feed_url_rewrites=(("verstka-media.nproxy.org", "verstka.media"),),
)


def parse():
    return parse_source(CONFIG)
