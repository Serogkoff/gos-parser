"""Русская и английская версии The Moscow Times в одном источнике."""

from parsers.sites.vpn_rss import VpnRssSource, parse_source
from utils.news import deduplicate_news

SOURCE_NAME = "The Moscow Times"
CONFIG_RU = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://ru.themoscowtimes.com/rss/news",
    domains=("ru.themoscowtimes.com", "www.themoscowtimes.com"),
    article_selectors=(".article__content", "article"),
)
CONFIG_EN = VpnRssSource(
    name=SOURCE_NAME,
    feed_url="https://www.themoscowtimes.com/rss/news",
    domains=("www.themoscowtimes.com", "themoscowtimes.com"),
    article_selectors=(".article__content", "article"),
)
# Backward-compatible name used by source registry/tests.
CONFIG = CONFIG_RU


def parse():
    return deduplicate_news([
        *parse_source(CONFIG_RU),
        *parse_source(CONFIG_EN),
    ])
