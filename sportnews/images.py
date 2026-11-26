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

UA = "BangSportDaily/1.1 (https://bangsportdaily.com/; sports news site) urllib"
OK_LICENSE = re.compile(r"\b(CC0|CC|Creative Commons|Public domain|PD|GFDL|FAL|Free Art License|Attribution|No restrictions)\b", re.I)   # FAL = Free Art License (free, attribution + share-alike)   # CC0 = public-domain dedication
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


def commons_info(filename: str, width: int = 1200, min_width: int = 400, allow_logo: bool = False) -> dict | None:
    """Licence-checked info for a file. Non-free ('fair use') files are rejected.
    Old public-domain photos are sometimes kept on English Wikipedia instead of Commons: those are accepted
    too, but only with a public-domain licence (never fair use).
    allow_logo: the editor named this file in photos.yaml, so a logo or SVG is allowed, still licence-checked."""
    if BAD_NAME.search(filename) and not allow_logo:
        return None
    params = {"action": "query", "titles": "File:" + filename, "prop": "imageinfo",
              "iiprop": "url|extmetadata|size", "iiurlwidth": width}
    d = _get("https://commons.wikimedia.org/w/api.php", params)
    pages = d.get("query", {}).get("pages", [])
    local = False
    if not pages or pages[0].get("missing") or not pages[0].get("imageinfo"):
        d = _get("https://en.wikipedia.org/w/api.php", params)
        pages = d.get("query", {}).get("pages", [])
        local = True
    if not pages or not pages[0].get("imageinfo"):
        log.info("Photo check %s: file not found", filename)
        return None
    ii = pages[0]["imageinfo"][0]
    meta = ii.get("extmetadata", {})
    lic = _clean(meta.get("LicenseShortName", {}).get("value", ""), 60)
    where = "English Wikipedia only" if local else "Wikimedia Commons"
    size = f"{ii.get('width', 0)}x{ii.get('height', 0)}"
    if not lic or not OK_LICENSE.search(lic) or meta.get("NonFree", {}).get("value") in ("true", True):
        log.info("Photo check %s (%s, %s): REFUSED, licence %r is not a free licence", filename, where, size, lic or "none")
        return None
    if local and not re.search(r"public domain|\bPD\b", lic, re.I):
        log.info("Photo check %s (%s, %s): REFUSED, licence %r (a file kept only on Wikipedia must be public domain)",
                 filename, where, size, lic)
        return None
    if ii.get("width", 0) < min_width:
        log.info("Photo check %s (%s, %s): REFUSED, smaller than %d px wide (licence %r is fine)",
                 filename, where, size, min_width, lic)
        return None
    log.info("Photo check %s (%s, %s): OK, licence %r", filename, where, size, lic)
    return {
        "url": ii.get("thumburl") or ii.get("url"),
        "page": ii.get("descriptionurl", ""),
        "artist": _clean(meta.get("Artist", {}).get("value", "")) or "Unknown author",
        "license": lic,
        "license_url": meta.get("LicenseUrl", {}).get("value", ""),
        "description": _clean(meta.get("ImageDescription", {}).get("value", ""), 200),
        "width": ii.get("thumbwidth") or ii.get("width"),
        "height": ii.get("thumbheight") or ii.get("height"),
        "year": photo_year(meta),
    }


def article_photos(title: str, max_n: int = 4, min_width: int = 200) -> list[dict]:
    """Every free-licence photo used in a Wikipedia article (not only its lead photo), in page order.
    Each file's licence is checked and the result is written to the log, so a refusal can be explained."""
    api = "https://en.wikipedia.org/w/api.php"
    d = _get(api, {"action": "query", "prop": "images", "titles": title, "imlimit": 50, "redirects": 1})
    pages = d.get("query", {}).get("pages", [])
    names = [i.get("title", "").split(":", 1)[-1] for i in (pages[0].get("images") or [])] if pages else []
    out = []
    for name in names:
        if not re.search(r"\.(jpe?g|png|webp)$", name, re.I) or BAD_NAME.search(name):
            continue                                    # icons, flags, logos, svg drawings
        info = commons_info(name.replace(" ", "_"), min_width=min_width)
        if info:
            out.append(info)
        if len(out) >= max_n:
            break
    log.info("Wikipedia article %r: %d file(s) listed, %d free photo(s) usable", title, len(names), len(out))
    return out


def photo_year(meta: dict) -> int | None:
    """Year the photo was taken (or uploaded, if the date taken is missing). Used by the 'latest photo' rule."""
    for k in ("DateTimeOriginal", "DateTime"):
        m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", _clean((meta.get(k) or {}).get("value", ""), 200))
        if m:
            return int(m.group(1))
    return None


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
                info["asked"] = subj                 # what we searched for (the photo check compares the two)
                info["page_title"] = title or subj
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
    ensure_match_card(article)
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
    if e.get("combine"):
        return combine_entry(e)
    if e.get("commons"):
        name = e["commons"].split("File:")[-1].replace("_", " ").strip()
        name = urllib.parse.unquote(name.split("/")[-1]) if name.startswith("http") else name
        info = commons_info(name.replace(" ", "_"), min_width=200, allow_logo=True)
        if not info:
            log.warning("Commons file %r not usable (missing or not a free licence)", e["commons"])
            return None
        info["subject"] = e.get("caption") or info.get("description") or name
        return info
    if e.get("wikipedia"):
        # lead photo of a Wikipedia article (e.g. a player or a stadium), licence checked like any Commons file
        name, title = page_image_name(e["wikipedia"])
        info = commons_info(name, min_width=200) if name else None
        if not info:
            log.warning("No free-licence lead photo for Wikipedia article %r", e["wikipedia"])
            return None
        info["subject"] = e.get("caption") or title or e["wikipedia"]
        info["asked"], info["page_title"] = e["wikipedia"], title or e["wikipedia"]
        return info
    if e.get("file"):
        if not (e.get("credit") and e.get("license")):
            log.warning("Photo %s skipped: 'credit' and 'license' are required for your own photos", e["file"])
            return None
        return {"url": f"../photos/{e['file']}", "page": e.get("source", ""), "artist": e["credit"],
                "license": e["license"], "license_url": e.get("license_url", ""), "subject": e.get("caption", ""),
                "via": e.get("via", "")}
    return None


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _ua()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _crop_to(img, ratio: float):
    """Centre-crop to width/height = ratio (a little higher than centre when cutting height: faces are near the top)."""
    w, h = img.size
    if w / h > ratio:
        nw = max(1, round(h * ratio))
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = max(1, round(w / ratio))
    y = int((h - nh) * 0.25)
    return img.crop((0, y, w, y + nh))


def combine_entry(e: dict) -> dict | None:
    """Two or more licence-checked photos side by side as ONE image (e.g. a cover showing two champions).
    Each part keeps its own author and licence in the credit line. If any part is not free-licensed,
    nothing is combined. The file is saved in docs/photos/ so it is published with the site."""
    import io
    from PIL import Image
    from .common import ROOT, short_hash
    subs = [x for x in e.get("combine") or [] if isinstance(x, dict)]
    parts = [resolve_entry(x) for x in subs]
    if len(parts) < 2 or not all(parts):
        log.warning("Combined photo skipped: every part must be a free-licence photo (%s)", e.get("caption", ""))
        return None
    name = e.get("name") or f"combined-{short_hash(json.dumps(subs, sort_keys=True))}.jpg"
    out = ROOT / "docs" / "photos" / name
    if not out.exists():
        imgs = [Image.open(io.BytesIO(_download(p["url"]))).convert("RGB") for p in parts]
        h = min(800, min(i.height for i in imgs))
        imgs = [i.resize((max(1, round(i.width * h / i.height)), h), Image.LANCZOS) for i in imgs]
        gap = 8
        aspect = e.get("aspect", 2.0)      # whole picture width:height. 2.0 keeps both halves visible on the
        if aspect:                         # 16:9 / 4:3 story cards; use "aspect: 0" to keep the photos uncropped
            part_r = (float(aspect) * h - gap * (len(imgs) - 1)) / len(imgs) / h
            imgs = [_crop_to(i, part_r) for i in imgs]
        canvas = Image.new("RGB", (sum(i.width for i in imgs) + gap * (len(imgs) - 1), h), "white")
        x = 0
        for i in imgs:
            canvas.paste(i, (x, 0))
            x += i.width + gap
        out.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out, "JPEG", quality=86, optimize=True)
        log.info("Combined photo saved: %s (%dx%d)", name, canvas.width, h)
    default = ["left", "right"] if len(parts) == 2 else [f"photo {n + 1}" for n in range(len(parts))]
    credits = [{"label": x.get("label") or default[n], "artist": p["artist"], "page": p.get("page", ""),
                "license": p["license"], "license_url": p.get("license_url", "")} for n, (x, p) in enumerate(zip(subs, parts))]
    years = [p.get("year") for p in parts if p.get("year")]
    return {"url": f"../photos/{name}", "page": parts[0].get("page", ""), "subject": e.get("caption", ""),
            "artist": "; ".join(f"{c['label']}: {c['artist']}" for c in credits),
            "license": " / ".join(dict.fromkeys(c["license"] for c in credits)), "license_url": "",
            "parts": credits, "via": "", "year": min(years) if years else None}


def apply_overrides(articles: list[dict], overrides: dict) -> int:
    """Apply photos.yaml choices. Each article is re-resolved only when its entry changes."""
    n = 0
    for a in articles:
        spec = overrides.get(a["id"])
        if spec is None:
            continue
        if isinstance(spec, dict) and "embeds" in spec:       # official Instagram/Facebook posts (click-to-load)
            a["embeds"] = [x for x in (parse_embed(e) for e in spec.get("embeds") or []) if x]
        if isinstance(spec, dict) and valid_fight(spec.get("fight")):   # fight result card set by the editor
            if a.get("fight") != spec["fight"]:
                a["fight"] = dict(spec["fight"])
                a["images"] = [i for i in (a.get("images") or []) if not i.get("card")]
                a.pop("photos_override", None)                  # redraw the card
        key_spec = {k: v for k, v in spec.items() if k != "photo_waiver"} if isinstance(spec, dict) else spec
        key = json.dumps(key_spec, sort_keys=True, ensure_ascii=False)   # a waiver note alone never re-fetches photos
        if a.get("photos_override") == key:
            continue
        if isinstance(spec, dict) and "photos" not in spec:   # only embeds: keep the photos as they are
            a["photos_override"] = key
            n += 1
            continue
        mode, entries = _override_entries(spec)
        chosen = []
        for e in entries:
            if isinstance(e, dict) and e.get("wikipedia_all"):   # all free photos of one Wikipedia article
                try:
                    for im in article_photos(e["wikipedia_all"], max_n=int(e.get("max", 4))):
                        im["subject"] = e.get("caption") or im.get("description") or e["wikipedia_all"]
                        chosen.append(im)
                except Exception as ex:  # noqa: BLE001
                    log.warning("Photos of article %r failed: %s", e["wikipedia_all"], str(ex)[:200])
                continue
            im = resolve_entry(e) if isinstance(e, dict) else None
            if im:
                im["editor"] = not e.get("wikipedia")   # a file the editor named is trusted; a Wikipedia lookup is checked
                if e.get("id"):
                    im["ref"] = str(e["id"])          # can be placed in the text with [[img:<id>]]
                chosen.append(im)
        refs = {c.get("ref") for c in chosen if c.get("ref")}
        base = [] if mode == "replace" else [i for i in (a.get("images") or [])
                                             if i.get("url") not in {c["url"] for c in chosen} and i.get("ref") not in refs]
        a["images"] = [i for i in (chosen + base) if not i.get("card")][:12]
        ensure_match_card(a)                          # an editor's photo choice never drops the match card
        a["photos_override"] = key
        n += 1
        log.info("Photos for %s set from photos.yaml (%d photo(s))", a["id"], len(a["images"]))
    return n


EMBED_IG = re.compile(r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(p|reel|tv)/([\w-]+)", re.I)
EMBED_FB = re.compile(r"https?://(?:www\.|m\.|web\.)?facebook\.com/\S+", re.I)
EMBED_X = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status(?:es)?/(\d+)", re.I)


def _cap(c):
    """A caption is one text, or one per language: {en: ..., zh: ..., ru: ...}."""
    return {str(k): str(v) for k, v in c.items()} if isinstance(c, dict) else str(c or "")


GETTY_ITEM = re.compile(r"items\s*:\s*['\"]([\w,]+)['\"]|gettyimages\.[a-z.]+/(?:detail|embed)/(?:[\w-]+/)*?(\d{6,})", re.I)


def _getty(raw: str, e: dict) -> dict | None:
    """Getty Images "Embed" code (the </> button on a Getty photo). Free for editorial use on news sites, inside
    Getty's own viewer only; Getty may show ads in it and track viewers, so it is click-to-load and never the cover.
    The code must be pasted whole: the iframe needs Getty's signature (sig) and embed token (id/et)."""
    m_item = GETTY_ITEM.search(raw)
    sig = re.search(r"sig\s*[:=]\s*['\"]?([\w\-=%]+)", raw)
    tok = re.search(r"\bid\s*:\s*['\"]([\w\-]+)['\"]|[?&]et=([\w\-]+)", raw)
    if not (m_item and sig and tok):
        log.warning("Getty embed skipped: paste the whole Embed code from the photo's </> button (link alone is not enough)")
        return None
    item = (m_item.group(1) or m_item.group(2)).split(",")[0]
    token = tok.group(1) or tok.group(2)
    w = re.search(r"\bw\s*:\s*['\"](\d+)", raw) or re.search(r'width="(\d+)"', raw)
    h = re.search(r"\bh\s*:\s*['\"](\d+)", raw) or re.search(r'height="(\d+)"', raw)
    w, h = (int(w.group(1)) if w else 594), (int(h.group(1)) if h else 396)
    src = (f"https://embed.gettyimages.com/embed/{item}?et={token}&tld=com&sig={sig.group(1)}"
           f"&caption=true&ver=1")
    return {"platform": "Getty Images", "url": f"https://www.gettyimages.com/detail/{item}", "src": src,
            "caption": _cap(e.get("caption")), "account": str(e.get("account", "") or e.get("credit", "")),
            "height": int(e.get("height", round(540 * h / max(w, 1)) + 90))}


def parse_embed(e) -> dict | None:
    """photos.yaml 'embeds:' entry -> {platform, url, src, caption, account}.
    The post stays on Instagram/Facebook (we never copy the picture). On the site it loads only when the reader
    clicks it, so no Meta cookies are set for readers who do not (see the privacy policy)."""
    if isinstance(e, str):
        e = {"url": e}
    if not isinstance(e, dict) or not (e.get("url") or e.get("code")):
        return None
    url = str(e.get("code") or e.get("url")).strip()
    if "gettyimages" in url.lower():
        return _getty(url, e)
    m = EMBED_IG.search(url)                      # a "Copy link" address, or the whole "Embed" code pasted in
    if m:
        kind, code = m.group(1).lower(), m.group(2)
        clean = f"https://www.instagram.com/{kind}/{code}/"
        return {"platform": "Instagram", "url": clean, "src": clean + "embed/captioned/",
                "caption": _cap(e.get("caption")), "account": str(e.get("account", "")), "height": int(e.get("height", 720))}
    m = EMBED_FB.search(url)
    if m:
        url = m.group(0).rstrip('"\'>')
        clean = url.split("?")[0] if "/posts/" in url or "/videos/" in url else url
        kind = "video" if re.search(r"/videos?/|/reel/|/watch", url) else "post"
        src = (f"https://www.facebook.com/plugins/{kind}.php?href={urllib.parse.quote(clean, safe='')}"
               f"&show_text=true&width=500")
        return {"platform": "Facebook", "url": clean, "src": src,
                "caption": _cap(e.get("caption")), "account": str(e.get("account", "")), "height": int(e.get("height", 640))}
    m = EMBED_X.search(url)                       # an X (Twitter) post link, or the whole "Embed post" code
    if m:
        user, sid = m.group(1), m.group(2)
        clean = f"https://x.com/{user}/status/{sid}"
        src = f"https://platform.twitter.com/embed/Tweet.html?id={sid}&dnt=true&theme=light"
        return {"platform": "X", "url": clean, "src": src, "caption": _cap(e.get("caption")),
                "account": str(e.get("account", "") or "@" + user), "height": int(e.get("height", 720))}
    log.warning("Embed %r skipped: only Instagram, Facebook, X and Getty Images are supported", url[:120])
    return None


def load_overrides() -> dict:
    import yaml
    from .common import ROOT
    p = ROOT / "photos.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def photo_waiver(article_id: str, overrides: dict | None = None) -> str:
    """The editor's note in photos.yaml that a story may have fewer than 2 pictures (e.g. "accepted: no free photo",
    "no picture by editor's choice"). Empty string = no waiver. Editor's rule, 26 Nov 2026."""
    spec = (load_overrides() if overrides is None else overrides).get(article_id)
    note = spec.get("photo_waiver") if isinstance(spec, dict) else None
    return str(note).strip() if note else ""


# ---------------------------------------------------------------- our own match card (always legal, always current)
def _font(size: int, bold: bool = True):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def valid_match(m) -> bool:
    try:
        return bool(m and m.get("home") and m.get("away") and str(m.get("home_score", "")).strip() != ""
                    and str(m.get("away_score", "")).strip() != "")
    except AttributeError:
        return False


def match_card(a: dict) -> dict | None:
    """A 1200x675 result graphic (competition, date, score, scorers) made from the story's own facts.
    It is our own work, so it is always free to use and always about this exact match."""
    m = a.get("match")
    if not valid_match(m):
        return None
    from PIL import Image, ImageDraw
    from .common import ROOT
    W, H = 1200, 675
    img = Image.new("RGB", (W, H), (17, 20, 26))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 12], fill=(220, 30, 40))
    def center(text, y, font, fill=(255, 255, 255), x0=0, x1=W):
        w = d.textlength(text, font=font)
        d.text((x0 + (x1 - x0 - w) / 2, y), text, font=font, fill=fill)
    def fit(text, size, maxw):
        f = _font(size)
        while d.textlength(text, font=f) > maxw and size > 20:
            size -= 2
            f = _font(size)
        return f
    comp = str(m.get("competition") or "").upper()
    center(comp, 50, fit(comp, 34, 1100), (200, 200, 205))
    if m.get("date"):
        center(str(m["date"]), 98, _font(26, False), (150, 150, 160))
    home, away = str(m["home"]), str(m["away"])
    center(home, 220, fit(home, 48, 400), x0=0, x1=440)
    center(away, 220, fit(away, 48, 400), x0=760, x1=W)
    score = f'{m["home_score"]} - {m["away_score"]}'
    center(score, 180, _font(120), (255, 255, 255), 440, 760)
    sf = _font(24, False)
    for side, x0, x1 in (("home_scorers", 0, 440), ("away_scorers", 760, W)):
        y = 300
        for s in (m.get(side) or [])[:6]:
            center(str(s), y, fit(str(s), 24, 400) if d.textlength(str(s), font=sf) > 400 else sf, (190, 190, 200), x0, x1)
            y += 36
    if m.get("note"):
        center(str(m["note"]), 560, fit(str(m["note"]), 26, 1100), (230, 230, 235))
    d.text((40, H - 50), "BANG SPORT DAILY", font=_font(22), fill=(220, 30, 40))
    name = f"card-{a['id']}.png"
    out = ROOT / "docs" / "photos" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    from datetime import date as _D
    return {"url": f"../photos/{name}", "page": "", "artist": "Bang Sport Daily (graphic)", "license": "Own work",
            "license_url": "", "subject": f"{home} {score} {away}" + (f" · {m.get('competition')}" if m.get("competition") else ""),
            "via": "", "card": True, "year": _D.today().year, "width": W, "height": H}


def valid_fight(f) -> bool:
    return bool(isinstance(f, dict) and f.get("winner") and f.get("loser"))


def fight_card(a: dict) -> dict | None:
    """Combat sports result graphic: "Winner def. Loser · KO · Round 2 · 4:58" (22 Nov 2026: no free photo of
    Navajo Stirling existed, so the cover of his knockout story is this card). Our own work, always free to use."""
    f = a.get("fight")
    if not valid_fight(f):
        return None
    from PIL import Image, ImageDraw
    from .common import ROOT
    W, H = 1200, 675
    img = Image.new("RGB", (W, H), (17, 20, 26))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 12], fill=(220, 30, 40))
    def center(text, y, font, fill=(255, 255, 255), x0=0, x1=W):
        w = d.textlength(text, font=font)
        d.text((x0 + (x1 - x0 - w) / 2, y), text, font=font, fill=fill)
    def fit(text, size, maxw):
        fnt = _font(size)
        while d.textlength(text, font=fnt) > maxw and size > 20:
            size -= 2
            fnt = _font(size)
        return fnt
    ev = str(f.get("event") or "").upper()
    center(ev, 50, fit(ev, 34, 1100), (200, 200, 205))
    if f.get("date"):
        center(str(f["date"]), 98, _font(26, False), (150, 150, 160))
    win, lose = str(f["winner"]), str(f["loser"])
    center("WIN", 190, _font(28), (60, 200, 110), 40, 470)
    center(win, 240, fit(win, 56, 400), x0=40, x1=470)
    center("def.", 236, _font(44, False), (170, 170, 180), 470, 730)
    center(lose, 240, fit(lose, 56, 400), (190, 190, 200), 730, W - 40)
    bits = [str(x) for x in (f.get("method"), f.get("round") and f"Round {f['round']}", f.get("time")) if x]
    if bits:
        line = " · ".join(bits)
        center(line, 380, fit(line, 52, 1100), (255, 255, 255))
    if f.get("note"):
        center(str(f["note"]), 560, fit(str(f["note"]), 26, 1100), (230, 230, 235))
    d.text((40, H - 50), "BANG SPORT DAILY", font=_font(22), fill=(220, 30, 40))
    name = f"card-{a['id']}.png"
    out = ROOT / "docs" / "photos" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    from datetime import date as _D
    subj = f"{win} def. {lose}" + (f" · {' · '.join(bits)}" if bits else "") + (f" · {f.get('event')}" if f.get("event") else "")
    return {"url": f"../photos/{name}", "page": "", "artist": "Bang Sport Daily (graphic)", "license": "Own work",
            "license_url": "", "subject": subj, "via": "", "card": True, "year": _D.today().year, "width": W, "height": H}


def ensure_match_card(a: dict) -> bool:
    """Add the match card after the photos (a photo stays the cover) if the story is about one finished match,
    or the fight card if it is about one finished fight (editor: the card leads when there is no photo of the winner)."""
    imgs = a.get("images") or []
    if any(i.get("card") for i in imgs):
        return False
    if valid_fight(a.get("fight")) and not valid_match(a.get("match")):
        try:
            card = fight_card(a)
        except Exception as e:  # noqa: BLE001
            log.warning("Fight card failed for %s: %s", a.get("id"), e)
            return False
        if card:
            a["images"] = ([card] + imgs) if a.get("fight", {}).get("card_first") else (imgs + [card])
            log.info("Fight card added to %s", a.get("id"))
            return True
        return False
    if not valid_match(a.get("match")):
        return False
    try:
        card = match_card(a)
    except Exception as e:  # noqa: BLE001
        log.warning("Match card failed for %s: %s", a.get("id"), e)
        return False
    if card:
        a["images"] = imgs + [card]
        log.info("Match card added to %s", a.get("id"))
        return True
    return False


# ---------------------------------------------------------------- one cover photo per story (editor's rule, 14 Nov 2026)
def photo_key(im: dict) -> str:
    """Identity of a picture: its Commons page, or its address for our own files."""
    url = im.get("url") or ""
    if url.startswith("../photos/"):                 # our own files (combined covers, charts, match cards)
        return url.lower()
    return (im.get("page") or url).split("?")[0].strip().lower()


def _story_time(a: dict) -> tuple:
    return (str(a.get("date", "")), str(a.get("published_at") or a.get("created") or ""))


def covers_in_use(articles: list[dict], a: dict, days: int = 60) -> set[str]:
    """Cover photos of the OTHER stories from the `days` before this story (rejected stories do not count)."""
    from datetime import date as Date, timedelta
    try:
        start = (Date.fromisoformat(str(a.get("date", ""))[:10]) - timedelta(days=days)).isoformat()
    except ValueError:
        start = ""
    me = _story_time(a)
    return {photo_key(o["images"][0]) for o in articles
            if o is not a and o.get("id") != a.get("id") and o.get("status") != "rejected" and o.get("images")
            and start <= str(o.get("date", "")) and _story_time(o) < me}


def unique_covers(articles: list[dict], only: list[dict] | None = None, days: int = 60) -> int:
    """No two stories may show the same cover photo. For each story (oldest first, so the earlier story keeps
    its cover): drop a picture that appears twice inside the story, and if the cover is already another recent
    story's cover, move the story's next unused picture (a person, a venue or the match card) to the front.
    Returns how many stories changed. `only` limits the changes to those stories."""
    changed = 0
    todo = sorted([a for a in (only if only is not None else articles) if a.get("images") and a.get("status") != "rejected"],
                  key=_story_time)
    for a in todo:
        before = [photo_key(i) for i in a["images"]]
        seen, imgs = set(), []
        for im in a["images"]:
            k = photo_key(im)
            if k and k in seen:
                continue
            seen.add(k)
            imgs.append(im)
        used = covers_in_use(articles, a, days)
        if imgs and photo_key(imgs[0]) in used:
            story_year = int(str(a.get("date") or "0")[:4] or 0)
            free = [i for i in imgs[1:] if photo_key(i) not in used]
            real = [i for i in free if not i.get("card")]           # a real photo (player, team, coach, venue) first;
            recent = [i for i in real if not i.get("year") or story_year - i["year"] <= 3]
            pick = (recent or real or free or [None])[0]            # the match card only when nothing else is left
            if pick is not None:
                imgs.remove(pick)
                imgs.insert(0, pick)
        a["images"] = imgs
        if [photo_key(i) for i in imgs] != before:
            changed += 1
            log.info("Cover photo of %s changed: another story already uses that picture", a.get("id"))
    return changed


# ---------------------------------------------------------------- our own copy of each photo (16 Nov 2026)
def local_copies(articles: list[dict], max_new: int = 250) -> int:
    """Keep a copy of every free-licence photo on our own site (docs/photos/c/), so pages load where Wikimedia
    is blocked (mainland China) and faster everywhere. The licence allows copies as long as the credit stays,
    and the credit line is unchanged. Each image gets 'local' = its address on our site; the original stays
    in 'url'. Returns how many new copies were made. A failed download simply keeps the Wikimedia address."""
    import hashlib
    import io
    import os
    from PIL import Image
    from .common import ROOT
    folder = ROOT / "docs" / "photos" / "c"
    offline = os.environ.get("SPORTNEWS_MOCK") == "1"
    made = 0
    for a in articles:
        for im in a.get("images") or []:
            url = im.get("url") or ""
            if not url.startswith("http"):
                continue
            name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
            out = folder / name
            if not out.exists():
                if offline or made >= max_new:
                    continue
                try:
                    img = Image.open(io.BytesIO(_download(url)))
                    if img.mode not in ("RGB", "L"):
                        bg = Image.new("RGB", img.size, "white")
                        bg.paste(img, mask=img.convert("RGBA").split()[3])
                        img = bg
                    img = img.convert("RGB")
                    img.thumbnail((1200, 1200), Image.LANCZOS)
                    folder.mkdir(parents=True, exist_ok=True)
                    img.save(out, "JPEG", quality=82, optimize=True, progressive=True)
                    made += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("Photo copy failed (Wikimedia address kept): %s: %s", url[:90], str(e)[:120])
                    continue
            im["local"] = f"../photos/c/{name}"
            small = folder / name.replace(".jpg", "-640.jpg")      # phone-size copy (about a third of the bytes)
            if not small.exists():
                try:
                    sm = Image.open(out)
                    if sm.width > 640:
                        sm = sm.convert("RGB")
                        sm.thumbnail((640, 640 * sm.height // sm.width + 1), Image.LANCZOS)
                        sm.save(small, "JPEG", quality=78, optimize=True, progressive=True)
                except Exception as e:  # noqa: BLE001
                    log.warning("Small photo copy failed: %s: %s", name, str(e)[:120])
            if small.exists():
                im["local_sm"] = f"../photos/c/{small.name}"
                im["local_w"] = 1200
    if made:
        log.info("Photo copies: %d new photo(s) saved on our own site", made)
    return made
