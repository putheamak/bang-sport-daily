"""Reel with the AI presenter's voice (editor's request, 27 Nov 2026): one caption card per paragraph of the
voice-over script, cut to the moment the presenter starts that paragraph, over the voice-over mix from voiceover.py.

Cards: 1) the opening line, big; 2) "This is Bang Sport Daily" = brand card; then one caption card per paragraph;
last paragraph = the "Full story" card, held to the end of the sound. Captions come from voiceover/<id>.en.captions.txt
(same paragraphs as the script, but with digits: "47 trophies"); without that file the spoken text is shown.
Every card carries a small "AI voice" label (honest with viewers; Meta asks for AI audio to be labelled).

Photos: only video-safe licences (reels.video_safe: no share-alike), else colour cards — same rule as the 12 s Reels.
Timing: pauses in the voice-only track (ffmpeg silencedetect) are matched to the paragraph breaks.
"""
from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from .common import ROOT

log = logging.getLogger("sportnews")

SCRIPTS = ROOT / "voiceover"
OUT = ROOT / "output" / "voice"


def paragraphs(path: Path) -> list[str]:
    text = "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("#"))
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def pauses(path: Path, noise: str = "-35dB", min_len: float = 0.3) -> list[float]:
    """Middle of each pause in the voice-only track (seconds)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise={noise}:d={min_len}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return [(s + e) / 2 for s, e in zip(starts, ends)]


def boundaries(paras: list[str], total: float, gaps: list[float], window: float = 3.0) -> list[float]:
    """Start time of each paragraph (first = 0). Each break is the pause nearest to where the text length says it
    should be; if no pause is near, the estimate is used."""
    w = [len(p) + 12 for p in paras]                       # +12: the pause after every paragraph
    cum, starts, used = 0, [0.0], set()
    for i in range(len(paras) - 1):
        cum += w[i]
        est = total * cum / sum(w)
        cands = [g for g in gaps if g > starts[-1] + 0.8 and g not in used and abs(g - est) <= window]
        t = min(cands, key=lambda g: abs(g - est)) if cands else max(est, starts[-1] + 0.8)
        used.add(t)
        starts.append(t)
    return starts


def _photo_block(im, d, photo: dict, height: int = 1240) -> None:
    """Photo across the top of the card (cropped around its focus point), fading into the dark background,
    with the photographer's credit (required by every free licence)."""
    from PIL import Image, ImageOps
    from .reels import BG, W, _font
    p = Image.open(photo["path"]).convert("RGB")
    fx, fy = (photo.get("focus") or [0.5, 0.35])[:2]
    p = ImageOps.fit(p, (W, height), method=Image.LANCZOS, centering=(fx, fy))
    im.paste(p, (0, 0))
    shade = Image.new("RGB", (W, height), BG)
    top = Image.linear_gradient("L").resize((W, 260)).transpose(Image.FLIP_TOP_BOTTOM).point(lambda v: int(v * .75))
    bottom = Image.linear_gradient("L").resize((W, 380))
    mask = Image.new("L", (W, height), 0)
    mask.paste(top, (0, 0))
    mask.paste(bottom, (0, height - 380))
    im.paste(Image.composite(shade, im.crop((0, 0, W, height)), mask), (0, 0))
    if photo.get("credit"):
        d.text((70, height - 70), photo["credit"][:80], font=_font(28, False), fill=(205, 210, 218))


def _card(cfg, a: dict, text: str, kind: str, n: int, lead_hint: str = "", photo: dict | None = None):
    from PIL import Image, ImageDraw
    from .reels import BG, H, RED, W, _brand, _font, _len, _sport, _text, _wrap, frames
    if kind == "cta":
        im = frames(cfg, a, "en")[2]
        d = ImageDraw.Draw(im)
    else:
        bg = RED if kind == "brand" else (BG if (n % 2 or photo) else (24, 30, 40))
        im = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(im)
        if photo and kind != "brand":                # photo = moving background, text = still layer on top
            _photo_block(im, d, {**photo, "credit": ""})
            bg_im, im = im, Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            if photo.get("credit"):
                d.text((70, 1240 - 70), photo["credit"][:80], font=_font(28, False), fill=(205, 210, 218))
        _brand(d, on_red=(bg == RED))
        if kind == "brand":
            _text(d, (70, 760), "THIS IS", 96, True, "white")
            _text(d, (70, 880), "BANG SPORT DAILY", 120, True, "white")
            _text(d, (70, 1060), lead_hint, 52, False, (255, 225, 222))
        else:
            head = kind == "hook"
            if photo:                                # caption under the photo, like TV subtitles
                size = 92 if head else (64 if len(text) < 130 else 56)
                top_y, bottom_y = 1290, H - 170
            else:
                size = 104 if head else (84 if len(text) < 120 else 72)
                top_y, bottom_y = 560, H - 170
                _text(d, (70, 470), _sport(cfg, a, "en"), 46, True, RED)
            lead = int(size * (1.2 if head else 1.3))
            lines = _wrap(d, text, size, head, W - 140)
            while photo and top_y + len(lines) * lead > bottom_y and size > 44:
                size -= 4
                lead = int(size * (1.2 if head else 1.3))
                lines = _wrap(d, text, size, head, W - 140)
            y = top_y if photo else max(top_y, (H - len(lines) * lead) // 2 - 60)
            for line in lines[:12]:
                x = 70
                for k, word in enumerate(line.split(" ")):       # numbers in red: the facts stand out
                    piece = word + (" " if k < len(line.split(" ")) - 1 else "")
                    _text(d, (x, y), piece, size, head, RED if re.search(r"\d", word) else "white")
                    x += _len(d, piece, size, head)
                y += lead
            if not photo:
                d.rectangle([70, y + 30, 270, y + 42], fill=RED)
    d.text((70, H - 130), "AI voice · facts from our reviewed story", font=_font(34, False), fill=(170, 176, 186))
    if im.mode == "RGBA":
        return bg_im, im
    return im


COURT = (28, 62, 104)


def graphic(g: dict, w: int = 1080, h: int = 1240):
    """Our own broadcast-style graphic on a drawn tennis court (used where no video-safe photo exists).
    g = {kind: score, title, rows: [[name, s1, s2, ...], ...], winner: 0}
      | {kind: tie, left, right, score, note}  | {kind: big, top, main, bottom}"""
    from PIL import Image, ImageDraw
    from .reels import RED, _font, _len, _text
    im = Image.new("RGB", (w, h), COURT)
    d = ImageDraw.Draw(im)
    line = (92, 128, 170)                                  # court lines, faint
    x0, x1, y0, y1 = 140, w - 140, 120, h - 120
    d.rectangle([x0, y0, x1, y1], outline=line, width=8)
    d.line([x0 + 120, y0, x0 + 120, y1], fill=line, width=6)
    d.line([x1 - 120, y0, x1 - 120, y1], fill=line, width=6)
    d.line([x0 + 120, h // 2 - 260, x1 - 120, h // 2 - 260], fill=line, width=6)
    d.line([x0 + 120, h // 2 + 260, x1 - 120, h // 2 + 260], fill=line, width=6)
    d.line([w // 2, h // 2 - 260, w // 2, h // 2 + 260], fill=line, width=6)
    d.rectangle([x0 - 40, h // 2 - 6, x1 + 40, h // 2 + 6], fill=(230, 232, 236))      # the net
    kind = g.get("kind", "big")
    panel = (13, 17, 23)
    if kind == "score":
        rows = g["rows"]
        top = 330
        d.rectangle([60, top - 110, w - 60, top + 150 * len(rows) + 30], fill=panel)
        _text(d, (100, top - 90), g.get("title", "").upper(), 44, True, RED)
        for r, row in enumerate(rows):
            y = top + r * 150
            win = r == g.get("winner", 0)
            _text(d, (100, y + 20), row[0], 60 if len(row[0]) < 18 else 46, True, "white" if win else (170, 176, 186))
            sets = [str(x) for x in row[1:]]
            for k, sc in enumerate(reversed(sets)):
                main, _, tb = sc.partition("(")
                x = w - 140 - k * 120
                _text(d, (x - _len(d, main, 84, True) // 2, y + 6), main, 84, True, "white" if win else (170, 176, 186))
                if tb:
                    _text(d, (x + 30, y + 8), tb.rstrip(")"), 34, True, RED)
            if r < len(rows) - 1:
                d.line([100, y + 140, w - 100, y + 140], fill=(50, 58, 70), width=3)
    elif kind == "tie":
        d.rectangle([60, 300, w - 60, 900], fill=panel)
        _text(d, (100, 330), g.get("title", "").upper(), 44, True, RED)
        for k, side in enumerate((g["left"], g["right"])):
            _text(d, (100, 430 + k * 200), side, 80, True, "white")
        sc = str(g["score"]).split("-")
        for k, v in enumerate(sc[:2]):
            _text(d, (w - 200, 400 + k * 200), v, 130, True, RED if k == 0 else "white")
        if g.get("note"):
            _text(d, (100, 820), g["note"], 44, False, (205, 210, 218))
    else:
        d.rectangle([60, 360, w - 60, 880], fill=panel)
        _text(d, (100, 400), g.get("top", "").upper(), 48, True, RED)
        size = 170 if _len(d, g.get("main", ""), 170, True) < w - 200 else 120
        _text(d, (100, 490), g.get("main", ""), size, True, "white")
        _text(d, (100, 760), g.get("bottom", ""), 48, False, (205, 210, 218))
    return im


def load_photos(sid: str) -> dict[int, dict]:
    """voiceover/<id>.photos.yaml: {paragraph number (1 = first): {commons: "File name.jpg", focus: [x, y]}}.
    The file is taken from output/voice/photos/<id>/ (saved by reelphotos) or fetched from Commons, where the
    licence is checked again (images.commons_info); only video-safe licences are used (no share-alike)."""
    import json
    import yaml
    from .reels import video_safe
    f = SCRIPTS / f"{sid}.photos.yaml"
    if not f.exists():
        return {}
    spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    cache = OUT / "photos" / sid
    index = {}
    if (cache / "index.json").exists():
        for e in json.loads((cache / "index.json").read_text(encoding="utf-8")):
            index[urllib.parse.unquote(e["page"].split("File:")[-1])] = e
    out = {}
    for para, e in spec.items():
        if e.get("graphic"):                         # our own scoreboard graphic: no licence question
            cache.mkdir(parents=True, exist_ok=True)
            path = cache / f"graphic-{para}.png"
            graphic(e["graphic"]).save(path)
            out[int(para)] = {"path": path, "focus": [0.5, 0.5], "credit": "Graphic: Bang Sport Daily"}
            continue
        name = str(e["commons"]).replace(" ", "_")
        info = index.get(name)
        path = cache / f"{info['n']:02d}.jpg" if info else None
        if not (path and path.exists()):
            from .images import _download, commons_info
            info = commons_info(name, width=1280, min_width=600)
            if not info:
                log.warning("Reel photo %s: not found or not free", name)
                continue
            cache.mkdir(parents=True, exist_ok=True)
            path = cache / ("x-" + re.sub(r"[^\w.-]", "_", name)[:80])
            path.write_bytes(_download(info["url"]))
        if not video_safe(info):
            log.warning("Reel photo %s: licence %s is share-alike, not used in videos", name, info.get("license"))
            continue
        out[int(para)] = {"path": path, "focus": e.get("focus"),
                          "credit": f"Photo: {info.get('artist', '')} · {info.get('license', '')} · Wikimedia Commons"}
    return out


def make(cfg, a: dict, voice: str, lead_in: float = 1.3) -> Path | None:
    """output/voice/<id>-<voice>.mp4 from the voice-over mix and its voice-only track (made by voiceover.py)."""
    sid, v = a["id"], voice.lower()
    mix_mp3, dry_mp3 = OUT / f"{sid}-{v}.mp3", OUT / f"{sid}-{v}-voice-only.mp3"
    if not (mix_mp3.exists() and dry_mp3.exists()):
        log.warning("Voice reel %s: run the voice-over first (%s missing)", sid, mix_mp3.name)
        return None
    spoken = paragraphs(SCRIPTS / f"{sid}.en.txt")
    cap_file = SCRIPTS / f"{sid}.en.captions.txt"
    caps = paragraphs(cap_file) if cap_file.exists() else spoken
    if len(caps) != len(spoken):
        raise ValueError(f"{cap_file.name}: {len(caps)} paragraphs, script has {len(spoken)}")
    starts = boundaries(spoken, duration(dry_mp3), pauses(dry_mp3))
    total = duration(mix_mp3)
    times = [0.0] + [lead_in + s for s in starts[1:]] + [total]      # card 1 also covers the "Bang" logo
    dest = OUT / f"{sid}-{v}.mp4"
    photos = load_photos(sid)
    with tempfile.TemporaryDirectory() as tmp:
        clips = []
        for i, cap in enumerate(caps):
            low = spoken[i].lower()
            kind = "hook" if i == 0 else "brand" if "this is bang sport daily" in low else \
                "cta" if i == len(caps) - 1 and "bangsportdaily" in low else "text"
            p, fg = Path(tmp) / f"c{i}.png", Path(tmp) / f"c{i}-text.png"
            card = _card(cfg, a, cap, kind, i, "World sport, told with sources", photos.get(i + 1))
            dur = times[i + 1] - times[i]
            frames_n = max(1, round(dur * 30))
            c = Path(tmp) / f"c{i}.mp4"
            enc = ["-frames:v", str(frames_n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
                   "-pix_fmt", "yuv420p", str(c)]
            if isinstance(card, tuple):              # slow zoom on the photo only; captions stay still
                card[0].save(p)
                card[1].save(fg)
                fc = (f"[0:v]scale=2160:-1,zoompan=z='min(zoom+0.0005,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":d={frames_n + 2}:s=1080x1920:fps=30[bg];[bg][1:v]overlay=0:0")
                cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(p),
                       "-loop", "1", "-framerate", "30", "-i", str(fg), "-filter_complex", fc, *enc]
            else:
                card.save(p)
                cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(p), *enc]
            subprocess.run(cmd, check=True, timeout=300)
            clips.append(c)
        (Path(tmp) / "list.txt").write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(Path(tmp) / "list.txt"),
                        "-i", str(mix_mp3), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dest)],
                       check=True, timeout=600)
    log.info("Voice reel %s: %d cards, %.1f s -> %s", sid, len(caps), total, dest.relative_to(ROOT))
    return dest


def fetch_photos(sid: str, titles: list[str], max_n: int = 40, width: int = 1280) -> int:
    """Every free-licence photo in the given Wikipedia articles (licence read from Commons by images.commons_info),
    saved for choosing Reel pictures: output/voice/photos/<id>/NN.jpg + index.json (file, licence, author, year,
    description, video_safe). Runs on GitHub Actions (Wikimedia is not reachable from every machine)."""
    import json
    from .images import _download, article_photos
    from .reels import video_safe
    dest = OUT / "photos" / sid
    dest.mkdir(parents=True, exist_ok=True)
    index, seen = [], set()
    from .images import _get, commons_info

    def category(cat: str):                           # "Category:..." = files in a Commons category (video-safe only)
        try:
            d = _get("https://commons.wikimedia.org/w/api.php", {"action": "query", "list": "categorymembers",
                     "cmtitle": cat, "cmtype": "file", "cmlimit": 60})
        except Exception as e:  # noqa: BLE001
            log.warning("Category %s: %s", cat, e)
            return
        found = 0
        for m in d.get("query", {}).get("categorymembers", []):
            name = m.get("title", "").split(":", 1)[-1]
            if not re.search(r"\.(jpe?g|png|webp)$", name, re.I):
                continue
            time.sleep(1.5)                           # Wikimedia asks bots to go slowly (429 otherwise)
            try:
                info = commons_info(name.replace(" ", "_"), width=1280, min_width=600)
            except Exception as e:  # noqa: BLE001
                log.warning("Commons %s: %s (waiting 60 s)", name[:60], str(e)[:80])
                time.sleep(60)
                continue
            if info and video_safe(info):
                found += 1
                yield info
            if found >= max_n // 4:
                return

    for title in titles:
        source = category(title) if title.startswith("Category:") else article_photos(title, max_n=max_n, min_width=600)
        for info in source:
            if info["page"] in seen:
                continue
            seen.add(info["page"])
            url = re.sub(r"/\d+px-", f"/{width}px-", info["url"])
            time.sleep(1.5)
            try:
                data = _download(url)
            except Exception as e:  # noqa: BLE001
                log.warning("Photo download failed %s: %s", url[:100], e)
                continue
            n = len(index) + 1
            (dest / f"{n:02d}.jpg").write_bytes(data)
            index.append({"n": n, **{k: info.get(k) for k in ("page", "artist", "license", "license_url", "description",
                                                              "year", "url")}, "video_safe": video_safe(info)})
    (dest / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Reel photos for %s: %d saved (%d video-safe)", sid, len(index), sum(i["video_safe"] for i in index))
    return len(index)
