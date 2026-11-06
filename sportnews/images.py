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

UA = "BangSportDaily/1.0 (static sports site; https://github.com) python-urllib"
OK_LICENSE = re.compile(r"\b(CC|Creative Commons|Public domain|PD|GFDL|Attribution|No restrictions)\b", re.I)
BAD_NAME = re.compile(r"(logo|flag|map|icon|crest|emblem|signature|badge|coat[_ ]of[_ ]arms|kit|diagram|\.svg$)", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _get(api: str, params: dict) -> dict:
    url = api + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
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
                log.info("No free-licence photo for %r (%s)", subj, name)
        except Exception as e:  # noqa: BLE001
            log.info("Photo lookup failed for %r: %s", subj, str(e)[:160])
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
    article["images"] = find_images(subjects_for(article), max_n)
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
