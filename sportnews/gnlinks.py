"""Replace Google News redirect links (news.google.com/rss/articles/...) with the original article's address.

Why: Google News RSS feeds are offered for "personal, non-commercial use within a feed reader". Our published
stories must therefore never show Google News links in their source lists: readers get the outlet's own URL.
Resolved links are cached in data/gn_links.json so each one is looked up once.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .common import DATA, read_json, write_json

log = logging.getLogger("sportnews")
CACHE = DATA / "gn_links.json"


def is_gn(url: str) -> bool:
    return "news.google.com/" in (url or "")


def resolve(url: str, cache: dict | None = None) -> str | None:
    """The original article URL, or None if it cannot be resolved. A failed link is retried after 7 days."""
    if not is_gn(url):
        return url
    cache = cache if cache is not None else read_json(CACHE, {})
    hit = cache.get(url)
    if isinstance(hit, str) and hit:
        return hit
    if isinstance(hit, dict) and hit.get("failed", "") > (datetime.now(timezone.utc) - timedelta(days=7)).isoformat():
        return None
    try:
        from googlenewsdecoder import gnewsdecoder
        r = gnewsdecoder(url, interval=1)
        out = r.get("decoded_url") if r.get("status") else None
    except Exception as e:  # noqa: BLE001
        log.warning("Google News link not resolved: %s", e)
        return None                       # not cached: try again next time
    cache[url] = out if out else {"failed": datetime.now(timezone.utc).isoformat()}
    return out


def fix_sources(articles: list[dict], max_new: int = 10) -> int:
    """Resolve Google News links in every story's sources (and in-text references). Returns links fixed."""
    cache = read_json(CACHE, {})
    fixed, tries = 0, 0
    for a in articles:
        for s in a.get("sources") or []:
            u = s.get("url") or s.get("link") or ""
            if is_gn(u):
                if u not in cache:
                    tries += 1
                    if tries > max_new:        # never slow a build down: at most a few new lookups per run
                        continue
                real = resolve(u, cache)
                if real:
                    s["url" if "url" in s else "link"] = real
                    fixed += 1
    write_json(CACHE, cache)
    if fixed:
        log.info("Replaced %d Google News links with the outlets' own links", fixed)
    return fixed
