"""BBC Russian: официальный RSS и полный текст через общий VPN."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source

SOURCE_NAME = "BBC Russian"
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://feeds.bbci.co.uk/russian/rss.xml",
    domains=("bbc.com", "bbc.co.uk"),
    article_selectors=("main p", "main"),
    default_section="Русская служба",
)


def parse():
    return parse_source(CONFIG)
