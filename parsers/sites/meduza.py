"""Meduza через официальный RSS и обычные страницы материалов."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source

SOURCE_NAME = "Meduza"
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://meduza.io/rss2/all",
    domains=("meduza.io",),
    article_selectors=("[class*='GeneralMaterial-module-article']", "main"),
    rss_full_text_fallback=True,
)


def parse():
    return parse_source(CONFIG)
