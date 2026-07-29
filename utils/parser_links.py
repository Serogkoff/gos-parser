"""Поиск настоящей ссылки публикации внутри карточки новости."""

from urllib.parse import urljoin


def find_article_url(node, page_url, validator, max_parent_levels=5):
    """
    Ищет ссылку не только внутри заголовка, но и вокруг него.

    На сайтах ведомств заголовок часто является ``div`` или ``span``,
    а настоящий ``a[href]`` оборачивает всю карточку либо находится рядом.
    """
    _, article_url = find_article_link(
        node,
        page_url,
        validator,
        max_parent_levels=max_parent_levels,
    )
    return article_url


def find_article_link(node, page_url, validator, max_parent_levels=5):
    """Возвращает одновременно найденный тег ``a`` и абсолютный URL."""
    current = node

    for _ in range(max_parent_levels + 1):
        if current is None:
            break

        candidates = []
        if any(current.get(attribute) for attribute in ("href", "data-href", "data-url")):
            candidates.append(current)
        candidates.extend(
            current.select("a[href], [data-href], [data-url]")
        )

        seen = set()
        for link in candidates:
            href = str(
                link.get("href")
                or link.get("data-href")
                or link.get("data-url")
                or ""
            ).strip()
            if not href or href in seen:
                continue
            seen.add(href)

            absolute = urljoin(page_url, href)
            if validator(absolute):
                return link, absolute

        if getattr(current, "name", "") in {"main", "body", "html"}:
            break
        current = current.parent

    return None, ""
