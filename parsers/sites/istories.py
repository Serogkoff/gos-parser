"""«Важные истории» через официальный RSS и общий VPN."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source

SOURCE_NAME = "Важные истории"
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://istories.media/rss/all.xml",
    domains=("istories.media",),
    article_selectors=("[class*='BlocksContainer']", "article"),
    default_section="Материалы",
    rss_full_text_fallback=True,
)


def parse():
    return parse_source(CONFIG)
