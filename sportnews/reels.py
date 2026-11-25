"""Short vertical videos (Facebook Reels, TikTok, Instagram, YouTube Shorts) made from our OWN material.

Each published story can get a 12-second 1080x1920 clip: headline card -> picture + summary -> "full story" card.
No music, no match footage, no TV images. Pictures are used only when the licence clearly allows video use:
our own score/fight cards, public domain/CC0, or CC BY (credit shown on screen). CC BY-SA photos are NOT used
(a cropped, animated photo in a video may count as an adaptation that would have to carry the same licence),
so those stories get a text-only middle card instead. Rules: AGENTS.md section 4.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

from .common import ROOT

log = logging.getLogger("sportnews")
W, H = 1080, 1920
OUT = ROOT / "output" / "reels"
DOCS = ROOT / "docs"
FONTS = Path(__file__).parent / "fonts"
RED, INK, BG = (225, 6, 0), (18, 20, 23), (13, 17, 23)
VIDEO_OK = re.compile(r"^(cc0|public domain|pd\b|no restrictions|cc by \d|cc-by-\d|attribution \d|cc by$)", re.I)


def _font(size: int, head: bool = True):
    from PIL import ImageFont
    name = "oswald-latin-wght-normal.woff2" if head else "inter-latin-wght-normal.woff2"
    for p in (FONTS / name, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            f = ImageFont.truetype(str(p), size)
            if head:
                try:
                    f.set_variation_by_axes([700])
                except Exception:  # noqa: BLE001
                    pass
            return f
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def video_safe(im: dict) -> bool:
    """Our own card, or a licence that allows use in a video without share-alike."""
    lic = (im.get("license") or "").strip()
    if im.get("own") or "card-" in (im.get("url") or "") or lic.lower().startswith("own work"):
        return True
    return bool(VIDEO_OK.search(lic)) and "sa" not in lic.lower().replace("usa", "")


def _local_file(im: dict) -> Path | None:
    """Our copy of the picture: docs/photos/c/<sha1>.jpg for Wikimedia photos, docs/photos/... for our cards."""
    import hashlib
    url = im.get("url") or ""
    if url.startswith("http"):
        return DOCS / "photos" / "c" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
    if url:
        return DOCS / url.replace("../", "").lstrip("/")
    return None


def _picture(a: dict) -> tuple[Path | None, str]:
    for im in a.get("images") or []:
        if not video_safe(im):
            continue
        p = _local_file(im)
        if p and p.is_file():
            credit = "" if p.name.startswith("card-") else \
                f'Photo: {im.get("artist", "")} · {im.get("license", "")}'.strip(" ·")
            return p, credit
    return None, ""


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def _brand(draw, on_red: bool = False):
    f = _font(54)
    draw.rectangle([70, 90, 70 + draw.textlength("BANG", font=f) + 30, 170], fill=BG if on_red else RED)
    draw.text((85, 95), "BANG", font=f, fill="white")
    draw.text((85 + draw.textlength("BANG", font=f) + 40, 95), "SPORT DAILY", font=f, fill="white")


def frames(cfg, a: dict, lang: str = "en") -> list:
    """Three 1080x1920 PIL images: headline, picture + summary, call to action."""
    from PIL import Image, ImageDraw, ImageOps
    L = a.get(lang) or a.get("en") or {}
    sport = (a.get("sport") or "sport").upper()
    out = []
    # 1 · headline
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    _brand(d)
    fk, fh = _font(46), _font(104)
    d.text((70, 560), sport, font=fk, fill=RED)
    y = 640
    for line in _wrap(d, L.get("headline", ""), fh, W - 140)[:7]:
        d.text((70, y), line, font=fh, fill="white")
        y += 124
    d.rectangle([70, y + 30, 270, y + 42], fill=RED)
    out.append(im)
    # 2 · picture + summary
    im = Image.new("RGB", (W, H), (244, 245, 247))
    d = ImageDraw.Draw(im)
    pic, credit = _picture(a)
    top = 0
    if pic:
        p = Image.open(pic).convert("RGB")
        p = ImageOps.fit(p, (W, 1000), method=Image.LANCZOS, centering=(0.5, 0.3))
        im.paste(p, (0, 0))
        top = 1000
        if credit:
            fc = _font(26, head=False)
            d.rectangle([0, 1000 - 48, W, 1000], fill=(0, 0, 0))
            d.text((24, 1000 - 42), credit[:90], font=fc, fill=(220, 220, 220))
    else:
        im = Image.new("RGB", (W, H), RED)
        d = ImageDraw.Draw(im)
        _brand(d, on_red=True)
        top = 560
    fs = _font(60, head=False)
    y = top + 70
    color = INK if pic else (255, 255, 255)
    for line in _wrap(d, L.get("subheadline") or L.get("social_post", "")[:220], fs, W - 140)[:10]:
        d.text((70, y), line, font=fs, fill=color)
        y += 80
    out.append(im)
    # 3 · call to action
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    _brand(d)
    d.text((70, 760), "FULL STORY", font=_font(120), fill="white")
    d.text((70, 900), "bangsportdaily.com", font=_font(84), fill=RED)
    fo = _font(44, head=False)
    for i, line in enumerate(textwrap.wrap("Sport news with sources, in English, Chinese and Russian. Follow us for more.", 34)):
        d.text((70, 1060 + i * 62), line, font=fo, fill=(200, 205, 212))
    out.append(im)
    return out


def make_reel(cfg, a: dict, lang: str = "en") -> Path | None:
    """Render the MP4 (H.264, silent AAC track) into output/reels/<id>.mp4. Returns the path, or None."""
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{a['id']}-{lang}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for i, fr in enumerate(frames(cfg, a, lang)):
            p = Path(tmp) / f"f{i}.png"
            fr.save(p)
            paths.append(p)
        dur, fade = 4.5, 0.5
        inputs = []
        for p in paths:
            inputs += ["-loop", "1", "-t", str(dur), "-i", str(p)]
            fc = (f"[0:v]scale={W}:{H},zoompan=z='min(zoom+0.0006,1.06)':d={int(dur*30)}:s={W}x{H}:fps=30[v0];"
              f"[1:v]scale={W}:{H},zoompan=z='min(zoom+0.0006,1.06)':d={int(dur*30)}:s={W}x{H}:fps=30[v1];"
              f"[2:v]scale={W}:{H},fps=30[v2];"
              f"[v0][v1]xfade=transition=fade:duration={fade}:offset={dur-fade}[x1];"
              f"[x1][v2]xfade=transition=fade:duration={fade}:offset={2*dur-2*fade},format=yuv420p[v]")
        total = 3 * dur - 2 * fade
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-f", "lavfi", "-t", str(total), "-i",
               "anullsrc=channel_layout=stereo:sample_rate=44100", "-filter_complex", fc, "-map", "[v]", "-map", "3:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-shortest",
               "-movflags", "+faststart", str(dest)]
        try:
            subprocess.run(cmd, check=True, timeout=240)
        except Exception as e:  # noqa: BLE001
            log.error("Reel not made for %s: %s", a["id"], e)
            return None
    log.info("Reel made: %s", dest.relative_to(ROOT))
    return dest


def upload_reel(path: Path, description: str) -> str:
    """Publish a Reel on the Facebook Page (Graph API video_reels: start -> upload -> finish). Returns the video id."""
    import json
    import urllib.parse
    import urllib.request
    from .publishers import FB_API
    page, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not (page and token):
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_TOKEN not set")
    base = f"https://graph.facebook.com/{FB_API}/{page}/video_reels"

    def post(url, data=None, headers=None, body=None):
        req = urllib.request.Request(url, data=body if body is not None else urllib.parse.urlencode(data or {}).encode(),
                                     headers=headers or {}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError("Facebook says: " + e.read().decode()[:400]) from e

    start = post(base, {"upload_phase": "start", "access_token": token})
    vid = start["video_id"]
    blob = path.read_bytes()
    post(start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{FB_API}/{vid}", body=blob,
         headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(blob))})
    post(base, {"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": description,
                "access_token": token})
    return vid


def prune(keep_days: int = 14) -> None:
    """Keep the reels folder small: delete clips older than two weeks."""
    import time
    if not OUT.exists():
        return
    cut = time.time() - keep_days * 86400
    for p in OUT.glob("*.mp4"):
        if p.stat().st_mtime < cut:
            p.unlink()
