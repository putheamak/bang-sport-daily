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


T = {
    "en": {"full": "FULL STORY", "tag": "Sport news with sources · English · 中文 · Русский. Follow us for more.",
           "photo": "Photo"},
    "zh": {"full": "阅读全文", "tag": "有来源的体育新闻 · English · 中文 · Русский。关注我们，获取更多。", "photo": "图片"},
    "ru": {"full": "ЧИТАТЬ ПОЛНОСТЬЮ", "tag": "Спортивные новости с источниками · English · 中文 · Русский. "
           "Подписывайтесь!", "photo": "Фото"},
}
SPORT = {"shooting": ("Shooting", "射击", "Стрельба"), "biathlon": ("Biathlon", "冬季两项", "Биатлон"),
         "tennis": ("Tennis", "网球", "Теннис"), "athletics": ("Athletics", "田径", "Лёгкая атлетика"),
         "swimming": ("Swimming", "游泳", "Плавание"), "hockey": ("Hockey", "冰球", "Хоккей"),
         "basketball": ("Basketball", "篮球", "Баскетбол"), "boxing": ("Boxing", "拳击", "Бокс"),
         "f1": ("Formula 1", "F1赛车", "Формула-1"), "cricket": ("Cricket", "板球", "Крикет")}
_CACHE: dict = {}


def _cjk_file(bold: bool) -> tuple[str, int] | None:
    """Noto Sans CJK SC from the system (GitHub runner: apt fonts-noto-cjk)."""
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}:%{index}", "Noto Sans CJK SC" + (":bold" if bold else "")],
                             capture_output=True, text=True, timeout=10).stdout
        f, i = out.rsplit(":", 1)
        if "CJK" in f:
            return f, int(i)
    except Exception:  # noqa: BLE001
        pass
    return None


def _font(size: int, head: bool = True, script: str = "latin"):
    """Oswald (headings) / Inter (text) for Latin and Cyrillic; Noto Sans CJK for Chinese."""
    from PIL import ImageFont
    key = (size, head, script)
    if key in _CACHE:
        return _CACHE[key]
    f = None
    if script == "cjk":
        c = _cjk_file(bold=head)
        if c:
            f = ImageFont.truetype(c[0], size, index=c[1])
    else:
        name = f'{"oswald" if head else "inter"}-{script}-wght-normal.woff2'
        try:
            f = ImageFont.truetype(str(FONTS / name), size)
            try:
                f.set_variation_by_axes([700 if head else 400])
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            f = None
    if f is None:
        try:
            f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        except Exception:  # noqa: BLE001
            f = ImageFont.load_default()
    _CACHE[key] = f
    return f


def _script(ch: str) -> str:
    o = ord(ch)
    if 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF or 0x3000 <= o <= 0x303F:
        return "cjk"
    if 0x0400 <= o <= 0x052F:
        return "cyrillic"
    return "latin"


def _runs(text: str) -> list[tuple[str, str]]:
    """Split text into (script, piece) runs; spaces and punctuation stay with the run they are in."""
    out: list[list] = []
    for ch in text:
        s = _script(ch)
        if s == "latin" and not ch.isalnum() and out and out[-1][0] == "cjk":
            s = "cjk"                                            # ASCII marks inside Chinese: CJK font has them
        if out and s == out[-1][0]:
            out[-1][1] += ch
        else:
            out.append([s, ch])
    return [(s, p) for s, p in out]


def _len(draw, text: str, size: int, head: bool) -> float:
    return sum(draw.textlength(p, font=_font(size, head, s)) for s, p in _runs(text))


def _text(draw, xy, text: str, size: int, head: bool, fill) -> None:
    x, y = xy
    for s, p in _runs(text):
        f = _font(size, head, s)
        dy = int(size * 0.08) if s == "cjk" and head else 0      # Oswald sits low; line the CJK glyphs up
        draw.text((x, y + dy), p, font=f, fill=fill)
        x += draw.textlength(p, font=f)


def _tokens(text: str) -> list[str]:
    """Words for Latin/Cyrillic, single characters for Chinese (no spaces there). Punctuation sticks to the left."""
    toks: list[str] = []
    for word in text.split(" "):
        buf = ""
        for ch in word:
            if _script(ch) == "cjk" and not ("\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef"):
                if buf:
                    toks.append(buf)
                buf = ch
                toks.append(buf)
                buf = ""
            elif toks and not buf and not ch.isalnum() and _script(ch) == "cjk":
                toks[-1] += ch                                   # 。，！ never start a line
            else:
                buf += ch
        if buf:
            toks.append(buf)
        toks.append(" ")
    return toks[:-1]


def _wrap(draw, text: str, size: int, head: bool, width: int) -> list[str]:
    lines, cur = [], ""
    for tok in _tokens(text):
        t = cur + tok
        if _len(draw, t.strip(), size, head) <= width or not cur.strip():
            cur = t
        else:
            lines.append(cur.strip())
            cur = "" if tok == " " else tok
    return [ln for ln in lines + [cur.strip()] if ln]


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


def _brand(draw, on_red: bool = False):
    f = _font(54)
    draw.rectangle([70, 90, 70 + draw.textlength("BANG", font=f) + 30, 170], fill=BG if on_red else RED)
    draw.text((85, 95), "BANG", font=f, fill="white")
    draw.text((85 + draw.textlength("BANG", font=f) + 40, 95), "SPORT DAILY", font=f, fill="white")


def _sport(cfg, a: dict, lang: str) -> str:
    k = (a.get("sport") or "sport").strip().lower()
    i = ("en", "zh", "ru").index(lang) if lang in ("en", "zh", "ru") else 0
    if k in SPORT:
        name = SPORT[k][i]
    else:
        from .site import section_name
        name = section_name(cfg, k, lang)
    return name.upper() if lang != "zh" else name


def frames(cfg, a: dict, lang: str = "en") -> list:
    """Three 1080x1920 PIL images: headline, picture + summary, call to action."""
    from PIL import Image, ImageDraw, ImageOps
    L = a.get(lang) or a.get("en") or {}
    tx = T.get(lang, T["en"])
    zh = lang == "zh"
    out = []
    # 1 · headline
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    _brand(d)
    hs = 92 if zh else 104
    lead = int(hs * (1.32 if zh else 1.2))
    _text(d, (70, 560), _sport(cfg, a, lang), 46, True, RED)
    y = 650
    for line in _wrap(d, L.get("headline", ""), hs, True, W - 140)[:8]:
        _text(d, (70, y), line, hs, True, "white")
        y += lead
    d.rectangle([70, y + 30, 270, y + 42], fill=RED)
    out.append(im)
    # 2 · picture + summary
    pic, credit = _picture(a)
    if pic:
        im = Image.new("RGB", (W, H), (244, 245, 247))
        d = ImageDraw.Draw(im)
        p = Image.open(pic).convert("RGB")
        p = ImageOps.fit(p, (W, 1000), method=Image.LANCZOS, centering=(0.5, 0.3))
        im.paste(p, (0, 0))
        top, color = 1000, INK
        if credit:
            d.rectangle([0, 1000 - 48, W, 1000], fill=(0, 0, 0))
            _text(d, (24, 1000 - 42), (tx["photo"] + credit[5:])[:90], 26, False, (220, 220, 220))
    else:
        im = Image.new("RGB", (W, H), RED)
        d = ImageDraw.Draw(im)
        _brand(d, on_red=True)
        top, color = 560, (255, 255, 255)
    ss = 56 if zh else 60
    y = top + 70
    for line in _wrap(d, L.get("subheadline") or (L.get("social_post") or "")[:220], ss, False, W - 140)[:10]:
        _text(d, (70, y), line, ss, False, color)
        y += int(ss * (1.45 if zh else 1.33))
    out.append(im)
    # 3 · call to action
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    _brand(d)
    fs = 120 if _len(d, tx["full"], 120, True) <= W - 140 else 96
    _text(d, (70, 760), tx["full"], fs, True, "white")
    d.text((70, 900), "bangsportdaily.com", font=_font(84), fill=RED)
    y = 1060
    for line in _wrap(d, tx["tag"], 44, False, W - 140):
        _text(d, (70, y), line, 44, False, (200, 205, 212))
        y += 64
    out.append(im)
    return out


def make_reel(cfg, a: dict, lang: str = "en", mood: str | None = None, suffix: str = "") -> Path | None:
    """Render the MP4 (H.264, silent AAC track) into output/reels/<id>.mp4. Returns the path, or None."""
    if os.environ.get("SPORTNEWS_MOCK") == "1":                  # tests: no video rendering
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{a['id']}-{lang}{suffix}.mp4"
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
        audio = ["-f", "lavfi", "-t", str(total), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        afilter = []
        if (cfg.get("publish") or {}).get("reel_sound", True):
            try:
                from .sound import make as make_sound, mood_for
                wav = make_sound(Path(tmp) / "sound.wav", mood or mood_for(a), total, 2 * dur - 2 * fade)
                audio = ["-i", str(wav)]
                afilter = ["-af", "loudnorm=I=-16:TP=-2:LRA=11,alimiter=limit=0.8:level=false"]   # the usual loudness for social video
            except Exception as e:  # noqa: BLE001
                log.warning("Reel sound failed, silent clip instead: %s", e)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, *audio, "-filter_complex", fc, "-map", "[v]", "-map", "3:a",
               *afilter,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-shortest",
               "-movflags", "+faststart", str(dest)]
        try:
            subprocess.run(cmd, check=True, timeout=240)
        except Exception as e:  # noqa: BLE001
            log.error("Reel not made for %s: %s", a["id"], e)
            return None
    log.info("Reel made: %s", dest.relative_to(ROOT))
    return dest


def upload_reel(path: Path, description: str, when: int | None = None) -> str:
    """Publish a Reel on the Facebook Page (Graph API video_reels: start -> upload -> finish). Returns the video id."""
    import json
    import urllib.parse
    import urllib.request
    from .publishers import FB_API, fb_page_token
    page, token = fb_page_token()
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
    fin = {"upload_phase": "finish", "video_id": vid, "video_state": "SCHEDULED" if when else "PUBLISHED",
           "description": description}
    if when:
        fin["scheduled_publish_time"] = str(when)
    post(base, {**fin,
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
