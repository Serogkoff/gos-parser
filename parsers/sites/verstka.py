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
    feed_fallback_urls=("https://verstka.media/?feed=rss2",),
    browser_fallback=True,
    browser_warmup_url="https://verstka.media/",
)


def parse():
    return parse_source(CONFIG)
