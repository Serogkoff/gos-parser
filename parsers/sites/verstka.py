"""«Вёрстка»: только оригинальный verstka.media через VPN."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source

SOURCE_NAME = "Вёрстка"
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://verstka.media/feed/",
    domains=("verstka.media",),
    article_selectors=(".vm-single-post-content", "article", "main"),
    rss_full_text_fallback=True,
)


def parse():
    return parse_source(CONFIG)
