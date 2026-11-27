"""Voice-over for a story (editor's request, 27 Nov 2026): a short news-presenter read of a story, for Reels.

The editor (or Claude) writes the script in voiceover/<story id>.en.txt (facts only from the published story;
lines starting with # are notes and are not read). Gemini's text-to-speech reads it in a presenter style, and the
voice is mixed over Bang Sport Daily's own sound (sound.py: logo, quiet bed that ducks under the voice, closing
sting) and levelled to -16 LUFS. Output: output/voice/<id>-<voice>.mp3 (+ a voice-only file without music).

Nothing is posted anywhere: the files are for the editor to check and use by hand. Say in the caption that the
voice is AI-generated (and use Meta's "AI info" label) when posting.

Run:  python -m sportnews voiceover <id>[,<id>...] [--voices Charon,Kore]
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

from .common import ROOT, load_articles

log = logging.getLogger("sportnews")

SCRIPTS = ROOT / "voiceover"
OUT = ROOT / "output" / "voice"
LEAD_IN = 1.3          # seconds of the "Bang" logo before the voice starts
TAIL = 2.2             # seconds after the voice (closing sting + fade)
STYLE = ("Read this as a professional sports news presenter on international TV: clear, warm and confident, "
         "steady pace, natural pauses between sentences, neutral accent, never shouting or over-dramatic. "
         "Read every name carefully. Text to read:\n\n")
FALLBACK_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]


def script_for(story_id: str) -> str:
    p = SCRIPTS / f"{story_id}.en.txt"
    if not p.exists():
        raise FileNotFoundError(f"No script: write {p.relative_to(ROOT)} first")
    lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("#"))


def _tts_models(client) -> list[str]:
    try:
        names = [m.name.split("/")[-1] for m in client.models.list()]
    except Exception as e:  # noqa: BLE001
        log.warning("Could not list Gemini models: %s", str(e)[:150])
        names = []
    tts = [n for n in names if "tts" in n]

    def rank(n: str) -> tuple:
        v = re.search(r"(\d+(?:\.\d+)?)", n)
        return ("flash" in n, float(v.group(1)) if v else 0.0, "preview" not in n)
    return sorted(tts, key=rank, reverse=True) + [m for m in FALLBACK_MODELS if m not in tts]


def speak(text: str, voice: str) -> tuple[bytes, int, str]:
    """Gemini text-to-speech. Returns (16-bit mono PCM, sample rate, model)."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    errors = []
    for model in _tts_models(client):
        try:
            resp = client.models.generate_content(
                model=model, contents=STYLE + text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
            part = resp.candidates[0].content.parts[0].inline_data
            rate = int((re.search(r"rate=(\d+)", part.mime_type or "") or [0, 24000])[1])
            if part.data:
                return part.data, rate, model
            errors.append(f"{model}: empty audio")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{model}: {str(e)[:160]}")
    raise RuntimeError("Text-to-speech failed: " + " | ".join(errors))


def _write_wav(path: Path, pcm: bytes, rate: int) -> float:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return len(pcm) / 2 / rate


def mix(voice_wav: Path, seconds: float, mood: str, out_mp3: Path, dry_mp3: Path) -> None:
    """Voice over our own bed (ducked under the voice), levelled for social video (-16 LUFS, -1.5 dBTP)."""
    from .sound import make
    total = LEAD_IN + seconds + TAIL
    with tempfile.TemporaryDirectory() as tmp:
        bed = make(Path(tmp) / "bed.wav", mood=mood, total=total, cta_at=LEAD_IN + seconds + 0.1)
        ms = int(LEAD_IN * 1000)
        voice_chain = ("aresample=44100,highpass=f=70,"
                       "acompressor=threshold=-20dB:ratio=3:attack=5:release=80:makeup=2,"
                       "aformat=channel_layouts=stereo")
        fc = (f"[1:a]{voice_chain},adelay={ms}|{ms},apad,asplit=2[v][key];"
              "[0:a]volume=0.22[bed];"
              "[bed][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];"
              "[duck][v]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bed), "-i", str(voice_wav),
                        "-filter_complex", fc, "-map", "[out]", "-ar", "44100", "-b:a", "192k", str(out_mp3)],
                       check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice_wav), "-af",
                        "aresample=44100,highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11", "-b:a", "192k",
                        str(dry_mp3)], check=True)


def run(ids: list[str], voices: list[str]) -> list[Path]:
    from .sound import mood_for
    arts = {a["id"]: a for a in load_articles()}
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for sid in ids:
        a = arts.get(sid)
        if not a:
            log.warning("Voice-over skipped: story %s not found", sid)
            continue
        text = script_for(sid)
        for voice in voices:
            pcm, rate, model = speak(text, voice)
            with tempfile.TemporaryDirectory() as tmp:
                wav = Path(tmp) / "voice.wav"
                secs = _write_wav(wav, pcm, rate)
                out = OUT / f"{sid}-{voice.lower()}.mp3"
                mix(wav, secs, mood_for(a), out, OUT / f"{sid}-{voice.lower()}-voice-only.mp3")
            log.info("Voice-over %s (%s, %s): %.1f s -> %s", sid, voice, model, secs, out.relative_to(ROOT))
            made.append(out)
    return made
