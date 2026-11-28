"""Bluesky: one post per published story (editor, 28 Nov 2026), in English, with a link card.

Official AT Protocol API with an app password (secrets BLUESKY_HANDLE and BLUESKY_APP_PASSWORD; never committed).
Bluesky welcomes automated accounts that post regularly if they label themselves: `python -m sportnews bluesky
--setup` adds the "bot" self-label to the profile once. The account only posts; it never likes, follows or replies.
Without the secrets nothing happens.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("sportnews")
PDS = "https://bsky.social/xrpc/"
MAX_CHARS = 300                       # Bluesky's limit (graphemes); we count characters, which is stricter


def ready() -> bool:
    return bool(os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD"))


def _call(method: str, body=None, token: str = "", raw: bytes | None = None, ctype: str = "application/json",
          query: str = "") -> dict:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(PDS + method + (f"?{query}" if query else ""), data=data,
                                 method="POST" if data is not None else "GET")
    if data is not None:
        req.add_header("Content-Type", ctype)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        out = r.read()
    return json.loads(out) if out else {}


def session() -> dict:
    return _call("com.atproto.server.createSession", {"identifier": os.environ["BLUESKY_HANDLE"],
                                                     "password": os.environ["BLUESKY_APP_PASSWORD"]})


def text_for(a: dict, url: str) -> str:
    """Our own social text (facts from the story), shortened to fit; the link goes in the card, not the text."""
    L = a.get("en") or {}
    t = " ".join((L.get("social_post") or L.get("subheadline") or L.get("headline") or "").split())
    t = re.sub(r"\s*(share your thoughts|tell us|let us know)[^.!?]*[.!?]", "", t, flags=re.I).strip()
    if len(t) <= MAX_CHARS:
        return t
    tags = " ".join(re.findall(r"#\w+", t)[:3])
    body = re.sub(r"\s*#\w+", "", t).strip()
    room = MAX_CHARS - len(tags) - 2
    cut = body[:room].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return (cut + " " + tags).strip()


def hashtag_facets(text: str) -> list[dict]:
    """Clickable hashtags: Bluesky needs their byte positions."""
    out = []
    for m in re.finditer(r"(?<!\w)#(\w+)", text):
        start = len(text[:m.start()].encode())
        out.append({"index": {"byteStart": start, "byteEnd": start + len(m.group(0).encode())},
                    "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1)}]})
    return out


def _thumb(a: dict, token: str) -> dict | None:
    from .reels import _local_file
    for im in a.get("images") or []:
        p = _local_file(im)
        og = p.with_name(p.stem + "-og.jpg") if p else None      # 1200x630 card crop made by the site build
        sm = p.with_name(p.stem + "-640" + p.suffix) if p else None
        for f in (og, sm, p):
            if f and Path(f).is_file() and Path(f).stat().st_size < 950_000:
                try:
                    return _call("com.atproto.repo.uploadBlob", raw=Path(f).read_bytes(), token=token,
                                 ctype="image/jpeg").get("blob")
                except Exception as e:  # noqa: BLE001
                    log.warning("Bluesky thumbnail upload failed: %s", str(e)[:150])
                    return None
    return None


def post(cfg: dict, a: dict) -> str:
    """Post the story; returns the post's at:// URI."""
    from .site import _base
    L = a.get("en") or {}
    url = f"{_base(cfg) or cfg['site']['url']}/en/{a['slug']}"
    s = session()
    text = text_for(a, url)
    card = {"uri": url, "title": L.get("headline", "")[:300], "description": (L.get("subheadline") or "")[:300]}
    thumb = _thumb(a, s["accessJwt"])
    if thumb:
        card["thumb"] = thumb
    record = {"$type": "app.bsky.feed.post", "text": text, "langs": ["en"],
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "embed": {"$type": "app.bsky.embed.external", "external": card}}
    facets = hashtag_facets(text)
    if facets:
        record["facets"] = facets
    r = _call("com.atproto.repo.createRecord", {"repo": s["did"], "collection": "app.bsky.feed.post",
                                                "record": record}, token=s["accessJwt"])
    return r.get("uri", "")


def setup_profile() -> str:
    """Label the account as automated ("bot" self-label), keeping its name, bio and pictures."""
    s = session()
    try:
        cur = _call("com.atproto.repo.getRecord", token=s["accessJwt"],
                    query=f"repo={s['did']}&collection=app.bsky.actor.profile&rkey=self").get("value", {})
    except Exception:  # noqa: BLE001  (no profile record yet)
        cur = {}
    cur = dict(cur or {}, **{"$type": "app.bsky.actor.profile"})
    vals = [v for v in ((cur.get("labels") or {}).get("values") or []) if v.get("val") != "bot"] + [{"val": "bot"}]
    cur["labels"] = {"$type": "com.atproto.label.defs#selfLabels", "values": vals}
    _call("com.atproto.repo.putRecord", {"repo": s["did"], "collection": "app.bsky.actor.profile", "rkey": "self",
                                         "record": cur}, token=s["accessJwt"])
    return f"{os.environ['BLUESKY_HANDLE']}: profile labelled as automated (bot)"
