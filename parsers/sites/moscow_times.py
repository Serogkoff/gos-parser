"""Русская версия The Moscow Times через общий RSS/VPN-конвейер."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source

SOURCE_NAME = "The Moscow Times"
CONFIG = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://ru.themoscowtimes.com/rss/news",
    domains=("ru.themoscowtimes.com",),
    article_selectors=(".article__content", "article"),
)


def parse():
    return parse_source(CONFIG)
