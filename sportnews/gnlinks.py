"""Replace Google News redirect links (news.google.com/rss/articles/...) with the original article's address.

Why: Google News RSS feeds are offered for "personal, non-commercial use within a feed reader". Our published
stories must therefore never show Google News links in their source lists: readers get the outlet's own URL.
Resolved links are cached in data/gn_links.json so each one is looked up once.
"""
from __future__ import annotations

import logging

from .common import DATA, read_json, write_json

log = logging.getLogger("sportnews")
CACHE = DATA / "gn_links.json"


def is_gn(url: str) -> bool:
    return "news.google.com/" in (url or "")


def resolve(url: str, cache: dict | None = None) -> str | None:
    """The original article URL, or None if it cannot be resolved."""
    if not is_gn(url):
        return url
    cache = cache if cache is not None else read_json(CACHE, {})
    if url in cache:
        return cache[url] or None
    try:
        from googlenewsdecoder import gnewsdecoder
        r = gnewsdecoder(url, interval=1)
        out = r.get("decoded_url") if r.get("status") else None
    except Exception as e:  # noqa: BLE001
        log.warning("Google News link not resolved: %s", e)
        return None                       # not cached: try again next time
    cache[url] = out or ""
    return out


def fix_sources(articles: list[dict]) -> int:
    """Resolve Google News links in every story's sources (and in-text references). Returns links fixed."""
    cache = read_json(CACHE, {})
    fixed = 0
    for a in articles:
        for s in a.get("sources") or []:
            u = s.get("url") or s.get("link") or ""
            if is_gn(u):
                real = resolve(u, cache)
                if real:
                    s["url" if "url" in s else "link"] = real
                    fixed += 1
    write_json(CACHE, cache)
    if fixed:
        log.info("Replaced %d Google News links with the outlets' own links", fixed)
    return fixed
