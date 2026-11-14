"""IndexNow: tell Bing (and Yandex, Seznam, Naver) about new or corrected stories, so they are crawled quickly.

Free, no account. The key in config.yaml (site.indexnow_key) is public by design: it is also written to
docs/<key>.txt, which proves the site owns it.

A page must be LIVE before a search engine is told about it, and the site only goes live a minute after a
workflow has saved its results. So a story published in one run is put on a waiting list (data/indexnow.json)
and submitted by the NEXT run that builds the site (the headlines refresh runs every 4 hours, so the wait is
4 hours at most, usually less).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

from . import common
from .common import log, read_json, site_url, write_json

ENDPOINT = "https://api.indexnow.org/indexnow"
LANGS = ("en", "zh", "ru")
WAIT = timedelta(minutes=10)


def _post(payload: dict) -> int:
    req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def run(cfg: dict, articles: list[dict], now: datetime | None = None, post=_post) -> list[str]:
    """Called on every site build. Returns the URLs submitted in this run."""
    key = (cfg["site"].get("indexnow_key") or "").strip()
    base = site_url(cfg)
    if not key or not base or not cfg["site"].get("custom_domain"):
        return []
    common.DOCS.mkdir(parents=True, exist_ok=True)
    (common.DOCS / f"{key}.txt").write_text(key)
    state_file = common.DATA / "indexnow.json"
    now = now or datetime.now(timezone.utc)
    st = read_json(state_file, {"sent": {}, "pending": {}})
    sent, pending = st.setdefault("sent", {}), st.setdefault("pending", {})
    for a in articles:
        if a.get("status") != "published":
            continue
        stamp = a.get("republished_at") or a.get("published_at") or ""
        for lang in LANGS:
            if not a.get(lang):
                continue
            url = f"{base}/{lang}/{a['slug']}.html"
            if sent.get(url) != stamp and url not in pending:
                pending[url] = {"stamp": stamp, "seen": now.isoformat(timespec="seconds")}
    ready = [u for u, p in pending.items() if now - datetime.fromisoformat(p["seen"]) >= WAIT]
    done: list[str] = []
    live = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("SPORTNEWS_MOCK") != "1"
    if ready and (live or post is not _post):
        urls = ready + [f"{base}/{lang}/index.html" for lang in LANGS]      # home pages changed too
        host = base.split("://", 1)[-1].strip("/")
        try:
            code = post({"host": host, "key": key, "keyLocation": f"{base}/{key}.txt", "urlList": urls[:10000]})
            if code in (200, 202):
                for u in ready:
                    sent[u] = pending.pop(u)["stamp"]
                done = ready
                log.info("IndexNow: %d page(s) submitted (HTTP %s)", len(ready), code)
            else:
                log.warning("IndexNow answered HTTP %s; will retry on the next run", code)
        except Exception as e:  # noqa: BLE001
            log.warning("IndexNow failed (will retry on the next run): %s", str(e)[:200])
    elif pending:
        log.info("IndexNow: %d page(s) waiting for the next run", len(pending))
    write_json(state_file, st)
    return done
