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
    """A Google link that stands in for the real article: Google News, or Gemini's search-grounding redirect."""
    return "news.google.com/" in (url or "") or "vertexaisearch.cloud.google.com/" in (url or "")


def _follow(url: str) -> str | None:
    """Grounding redirects answer with a 302 to the real page: read the Location header, don't load the page."""
    import urllib.error
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, method="GET"), timeout=15)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        if e.code in (301, 302, 303, 307, 308) and loc and "google.com" not in loc:
            return loc
    except Exception:  # noqa: BLE001
        return None
    return None


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
        if "vertexaisearch" in url:
            out = _follow(url)
        else:
            from googlenewsdecoder import gnewsdecoder
            r = gnewsdecoder(url, interval=1)
            out = r.get("decoded_url") if r.get("status") else None
    except Exception as e:  # noqa: BLE001
        log.warning("Google News link not resolved: %s", e)
        return None                       # not cached: try again next time
    cache[url] = out if out else {"failed": datetime.now(timezone.utc).isoformat()}
    return out


def fix_sources(articles: list[dict], max_new: int = 40) -> int:
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
