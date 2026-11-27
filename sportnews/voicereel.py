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


def _card(cfg, a: dict, text: str, kind: str, n: int, lead_hint: str = ""):
    from PIL import Image, ImageDraw
    from .reels import BG, H, RED, W, _brand, _font, _len, _sport, _text, _wrap, frames
    if kind == "cta":
        im = frames(cfg, a, "en")[2]
        d = ImageDraw.Draw(im)
    else:
        bg = RED if kind == "brand" else (BG if n % 2 else (24, 30, 40))
        im = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(im)
        _brand(d, on_red=(bg == RED))
        if kind == "brand":
            _text(d, (70, 760), "THIS IS", 96, True, "white")
            _text(d, (70, 880), "BANG SPORT DAILY", 120, True, "white")
            _text(d, (70, 1060), lead_hint, 52, False, (255, 225, 222))
        else:
            _text(d, (70, 470), _sport(cfg, a, "en"), 46, True, RED if bg != RED else "white")
            size = 104 if kind == "hook" else (84 if len(text) < 120 else 72)
            lead = int(size * (1.2 if kind == "hook" else 1.3))
            lines = _wrap(d, text, size, kind == "hook", W - 140)
            y = max(560, (H - len(lines) * lead) // 2 - 60)
            for line in lines[:12]:
                x = 70
                for k, word in enumerate(line.split(" ")):       # numbers in red: the facts stand out
                    piece = word + (" " if k < len(line.split(" ")) - 1 else "")
                    _text(d, (x, y), piece, size, kind == "hook", RED if re.search(r"\d", word) else "white")
                    x += _len(d, piece, size, kind == "hook")
                y += lead
            d.rectangle([70, y + 30, 270, y + 42], fill=RED if bg != RED else "white")
    d.text((70, H - 130), "AI voice · facts from our reviewed story", font=_font(34, False), fill=(170, 176, 186))
    return im


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
    with tempfile.TemporaryDirectory() as tmp:
        lst = []
        for i, cap in enumerate(caps):
            low = spoken[i].lower()
            kind = "hook" if i == 0 else "brand" if "this is bang sport daily" in low else \
                "cta" if i == len(caps) - 1 and "bangsportdaily" in low else "text"
            p = Path(tmp) / f"c{i}.png"
            _card(cfg, a, cap, kind, i, "World sport, told with sources").save(p)
            lst += [f"file '{p}'", f"duration {times[i + 1] - times[i]:.3f}"]
        lst.append(f"file '{p}'")                                    # concat needs the last file twice
        (Path(tmp) / "list.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(Path(tmp) / "list.txt"),
                        "-i", str(mix_mp3), "-map", "0:v", "-map", "1:a", "-vf", "fps=30,format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart", str(dest)], check=True, timeout=600)
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
    for title in titles:
        for info in article_photos(title, max_n=max_n, min_width=600):
            if info["page"] in seen:
                continue
            seen.add(info["page"])
            url = re.sub(r"/\d+px-", f"/{width}px-", info["url"])
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
