"""Free, legal photos from Wikimedia Commons (via Wikipedia), with credit and licence.

We never copy photos from news sites (they are copyrighted, usually by Getty/Reuters/AP).
Wikimedia Commons hosts millions of freely licensed photos of athletes, teams, venues and events.
Each image keeps its author + licence so the site can show the required credit.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from .common import log

UA = "BangSportDaily/1.1 (https://putheamak.github.io/bang-sport-daily/; sports news site) urllib"
OK_LICENSE = re.compile(r"\b(CC|Creative Commons|Public domain|PD|GFDL|Attribution|No restrictions)\b", re.I)
BAD_NAME = re.compile(r"(logo|flag|map|icon|crest|emblem|signature|badge|coat[_ ]of[_ ]arms|kit|diagram|\.svg$)", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _ua() -> str:
    """Wikimedia requires a descriptive User-Agent with a contact URL (generic library agents get blocked)."""
    import os
    site = os.environ.get("SITE_URL") or ""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not site and repo:
        owner, name = repo.split("/", 1)
        site = f"https://{owner.lower()}.github.io/{name}/"
    return f"BangSportDaily/1.1 (+{site or 'https://github.com'}; sports news site) urllib/3"


def _get(api: str, params: dict) -> dict:
    url = api + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": _ua(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _clean(v: str, n: int = 120) -> str:
    t = re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", v or ""))).strip()
    return t[:n]


def page_image_name(title: str, wiki: str = "en") -> tuple[str | None, str | None]:
    """Return (lead image filename, resolved page title) of a Wikipedia article, searching if needed."""
    api = f"https://{wiki}.wikipedia.org/w/api.php"
    d = _get(api, {"action": "query", "prop": "pageimages", "piprop": "name", "titles": title, "redirects": 1})
    pages = d.get("query", {}).get("pages", [])
    if pages and not pages[0].get("missing") and pages[0].get("pageimage"):
        return pages[0]["pageimage"], pages[0].get("title", title)
    s = _get(api, {"action": "query", "list": "search", "srsearch": title, "srlimit": 1})
    hits = s.get("query", {}).get("search", [])
    if not hits:
        return None, None
    t = hits[0]["title"]
    d = _get(api, {"action": "query", "prop": "pageimages", "piprop": "name", "titles": t, "redirects": 1})
    pages = d.get("query", {}).get("pages", [])
    return (pages[0].get("pageimage"), t) if pages and not pages[0].get("missing") else (None, None)


def commons_info(filename: str, width: int = 1200) -> dict | None:
    """Licence-checked info for a file. Files that are not on Commons (non-free 'fair use') are rejected."""
    if BAD_NAME.search(filename):
        return None
    d = _get("https://commons.wikimedia.org/w/api.php",
             {"action": "query", "titles": "File:" + filename, "prop": "imageinfo",
              "iiprop": "url|extmetadata|size", "iiurlwidth": width})
    pages = d.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or not pages[0].get("imageinfo"):
        return None
    ii = pages[0]["imageinfo"][0]
    meta = ii.get("extmetadata", {})
    lic = _clean(meta.get("LicenseShortName", {}).get("value", ""), 60)
    if not lic or not OK_LICENSE.search(lic) or meta.get("NonFree", {}).get("value") in ("true", True):
        return None
    if ii.get("width", 0) < 400:
        return None
    return {
        "url": ii.get("thumburl") or ii.get("url"),
        "page": ii.get("descriptionurl", ""),
        "artist": _clean(meta.get("Artist", {}).get("value", "")) or "Unknown author",
        "license": lic,
        "license_url": meta.get("LicenseUrl", {}).get("value", ""),
        "description": _clean(meta.get("ImageDescription", {}).get("value", ""), 200),
        "width": ii.get("thumbwidth") or ii.get("width"),
        "height": ii.get("thumbheight") or ii.get("height"),
    }


def find_images(subjects: list[str], max_n: int = 3) -> list[dict]:
    """Up to max_n free photos for the given subjects (people, teams, venues, events), most important first."""
    out, seen = [], set()
    for subj in [s for s in subjects if s and isinstance(s, str)][:6]:
        if len(out) >= max_n:
            break
        try:
            name, title = page_image_name(subj)
            if not name or name in seen:
                continue
            seen.add(name)
            info = commons_info(name)
            if info:
                info["subject"] = title or subj
                out.append(info)
                log.info("Photo for %r: %s (%s, %s)", subj, name, info["artist"][:40], info["license"])
            else:
                log.warning("No free-licence photo for %r (%s)", subj, name)
        except Exception as e:  # noqa: BLE001
            log.warning("Photo lookup failed for %r: %s", subj, str(e)[:300])
    return out


def subjects_for(article: dict) -> list[str]:
    subs = list(article.get("image_subjects") or []) + list(article.get("athletes") or [])
    if not subs:
        subs = [t for t in article.get("tags", []) if t and t[0].isupper()]
    seen, out = set(), []
    for s in subs:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def attach_images(article: dict, max_n: int = 3) -> dict:
    subs = subjects_for(article)
    log.info("Looking up photos for %s: %s", article.get("id"), subs[:6])
    article["images"] = find_images(subs, max_n)
    return article


def backfill(articles: list[dict], only_published: bool = True) -> int:
    """Add photos to stories that never had a lookup (older stories)."""
    n = 0
    for a in articles:
        if "images" in a or (only_published and a.get("status") != "published"):
            continue
        attach_images(a)
        n += 1
    return n


# ---------------------------------------------------------------- editor's photo choices (photos.yaml)
def _override_entries(spec) -> tuple[str, list]:
    if isinstance(spec, list):
        return "replace", spec
    return (spec or {}).get("mode", "replace"), (spec or {}).get("photos", [])


def resolve_entry(e: dict) -> dict | None:
    """One photos.yaml entry -> image dict. Either a Wikimedia Commons file (licence read automatically)
    or your own uploaded file in photos/ with credit + licence written by you."""
    if e.get("commons"):
        name = e["commons"].split("File:")[-1].replace("_", " ").strip()
        name = urllib.parse.unquote(name.split("/")[-1]) if name.startswith("http") else name
        info = commons_info(name.replace(" ", "_"))
        if not info:
            log.warning("Commons file %r not usable (missing or not a free licence)", e["commons"])
            return None
        info["subject"] = e.get("caption") or info.get("description") or name
        return info
    if e.get("wikipedia"):
        # lead photo of a Wikipedia article (e.g. a player or a stadium), licence checked like any Commons file
        name, title = page_image_name(e["wikipedia"])
        info = commons_info(name) if name else None
        if not info:
            log.warning("No free-licence lead photo for Wikipedia article %r", e["wikipedia"])
            return None
        info["subject"] = e.get("caption") or title or e["wikipedia"]
        return info
    if e.get("file"):
        if not (e.get("credit") and e.get("license")):
            log.warning("Photo %s skipped: 'credit' and 'license' are required for your own photos", e["file"])
            return None
        return {"url": f"../photos/{e['file']}", "page": e.get("source", ""), "artist": e["credit"],
                "license": e["license"], "license_url": e.get("license_url", ""), "subject": e.get("caption", ""),
                "via": e.get("via", "")}
    return None


def apply_overrides(articles: list[dict], overrides: dict) -> int:
    """Apply photos.yaml choices. Each article is re-resolved only when its entry changes."""
    n = 0
    for a in articles:
        spec = overrides.get(a["id"])
        if spec is None:
            continue
        key = json.dumps(spec, sort_keys=True, ensure_ascii=False)
        if a.get("photos_override") == key:
            continue
        mode, entries = _override_entries(spec)
        chosen = [x for x in (resolve_entry(e) for e in entries if isinstance(e, dict)) if x]
        base = [] if mode == "replace" else [i for i in (a.get("images") or []) if i.get("url") not in {c["url"] for c in chosen}]
        a["images"] = (chosen + base)[:4]
        a["photos_override"] = key
        n += 1
        log.info("Photos for %s set from photos.yaml (%d photo(s))", a["id"], len(a["images"]))
    return n


def load_overrides() -> dict:
    import yaml
    from .common import ROOT
    p = ROOT / "photos.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
