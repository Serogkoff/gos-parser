"""The Insider через официальный RSS и страницы статей."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source

SOURCE_NAME = "The Insider"
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://theins.ru/feed",
    domains=("theins.ru",),
    article_selectors=("article", "main"),
    rss_full_text_fallback=True,
)


def parse():
    return parse_source(CONFIG)
