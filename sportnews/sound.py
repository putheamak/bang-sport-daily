"""Bang Sport Daily's own sound for Reels, made in code: nothing licensed, nothing anyone can claim.

One audio logo (the "Bang": punchy hit + rising sting) on the headline card, a quiet bed in one of three moods,
and a closing sting on the "Full story" card. Mood by story: news (upbeat), combat (heavy drums), story (warm).
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
RNG = np.random.default_rng(7)            # fixed seed: the same sound every time = a recognisable signature


def _t(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def _env(n: int, a: float = 0.005, d: float = 0.3) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / d)


def _note(f: float, sec: float, d: float = 0.4, harm=(1, .5, .25), a: float = .005) -> np.ndarray:
    t = _t(sec)
    w = sum(h * np.sin(2 * np.pi * f * (i + 1) * t) for i, h in enumerate(harm))
    return w * _env(len(t), a, d)


def _kick(sec: float = .45, top: float = 140, low: float = 42) -> np.ndarray:
    t = _t(sec)
    f = low + (top - low) * np.exp(-t / .04)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(len(t), .001, .16)


def _noise(sec: float, d: float, hp: bool = True) -> np.ndarray:
    n = RNG.standard_normal(int(sec * SR))
    if hp:
        n = np.diff(n, prepend=0)                        # crude high-pass: hats, snares
    return n * _env(len(n), .001, d)


def _tom(f: float, sec: float = .5) -> np.ndarray:
    t = _t(sec)
    fr = f * (1 + .6 * np.exp(-t / .03))
    return np.sin(2 * np.pi * np.cumsum(fr) / SR) * _env(len(t), .001, .22)


def _pad(freqs, sec: float, a: float = .6) -> np.ndarray:
    t = _t(sec)
    w = sum(np.sin(2 * np.pi * f * t + i) + .3 * np.sin(2 * np.pi * f * 2.003 * t) for i, f in enumerate(freqs))
    env = np.minimum(1, t / a) * np.minimum(1, (sec - t) / .5)
    return w * env / len(freqs)


def _add(buf: np.ndarray, x: np.ndarray, at: float, g: float = 1.0) -> None:
    i = int(at * SR)
    j = min(len(buf), i + len(x))
    if i < len(buf):
        buf[i:j] += g * x[: j - i]


def _logo(buf, at: float = 0.0, big: bool = True) -> None:
    """The "Bang": kick + snare crack, then a rising two-note sting and a bright bell (E5 -> B5)."""
    _add(buf, _kick(.6, 160, 40), at, 1.0 if big else .7)
    _add(buf, _noise(.18, .04), at, .2)
    t = _t(.55)
    glide = 330 * 2 ** (t / .55 * 7 / 12)                 # E4 rising a fifth
    sting = np.sign(np.sin(2 * np.pi * np.cumsum(glide) / SR)) * .25 + np.sin(2 * np.pi * np.cumsum(glide) / SR)
    _add(buf, sting * np.minimum(1, t / .3) * np.exp(-np.maximum(0, t - .4) / .1), at + .12, .18)
    _add(buf, _note(659.3, 1.2, .5, (1, .4, .2, .1)), at + .62, .30)
    _add(buf, _note(987.8, 1.4, .6, (1, .3, .1)), at + .70, .26)


def _bed_news(buf, start: float, end: float) -> None:
    beat = 60 / 120
    prog = [(110, (220, 277.2, 329.6)), (98, (196, 246.9, 293.7)), (130.8, (261.6, 329.6, 392)),
            (123.5, (246.9, 311.1, 370))]                 # A - G - C - B: bright, moving
    k, t = 0, start
    while t < end:
        bar = int((t - start) / (4 * beat)) % len(prog)
        root, chord = prog[bar]
        if k % 2 == 0:
            _add(buf, _kick(.4), t, .55)
        if k % 4 == 2:
            _add(buf, _noise(.15, .05), t, .13)
        _add(buf, _noise(.05, .015), t + beat / 2, .06)
        _add(buf, _noise(.05, .015), t, .04)
        _add(buf, _note(root, beat * .9, .18, (1, .6, .3)), t, .20)
        if k % 4 in (1, 3):
            for f in chord:
                _add(buf, _note(f, .25, .08, (1, .5, .3, .2)), t + beat / 2, .06)
        k += 1
        t += beat


def _bed_combat(buf, start: float, end: float) -> None:
    beat = 60 / 92
    pattern = [(0, 70, .7), (.75, 95, .4), (1.5, 70, .55), (2, 120, .45), (2.5, 95, .35), (3, 70, .7),
               (3.5, 140, .3), (3.75, 120, .3)]          # drum-circle feel, low and driving
    t = start
    while t < end:
        for off, f, g in pattern:
            if t + off * beat < end:
                _add(buf, _tom(f), t + off * beat, g * .6)
        _add(buf, _noise(.2, .06), t + 2 * beat, .1)
        t += 4 * beat
    n = int((end - start) * SR)
    tt = np.arange(n) / SR
    drone = (np.sin(2 * np.pi * 55 * tt) + .4 * np.sin(2 * np.pi * 58.27 * tt)) * (.5 + .5 * np.sin(2 * np.pi * tt / (2 * beat)))
    _add(buf, drone * np.minimum(1, tt / 1.0) * np.minimum(1, (tt[-1] - tt) / .8), start, .10)


def _bed_story(buf, start: float, end: float) -> None:
    chords = [(261.6, 329.6, 392.0), (220.0, 261.6, 329.6), (174.6, 220.0, 261.6), (196.0, 246.9, 293.7)]
    step = (end - start) / len(chords)                   # C - Am - F - G: warm, hopeful
    melody = [523.3, 659.3, 587.3, 523.3, 440.0, 523.3, 587.3, 659.3, 698.5, 659.3, 587.3, 523.3, 493.9, 587.3]
    for i, ch in enumerate(chords):
        _add(buf, _pad(ch, step + .6, .8), start + i * step, .16)
        _add(buf, _note(ch[0] / 2, step, 1.2, (1, .3)), start + i * step, .14)
    gap = (end - start) / len(melody)
    for i, f in enumerate(melody):
        _add(buf, _note(f, 1.4, .6, (1, .45, .15, .08), .003), start + i * gap, .10)
    for i in range(int((end - start) / .95)):
        _add(buf, _kick(.35, 90, 45), start + i * .95, .18)


def mood_for(a: dict) -> str:
    kind = (a.get("type") or a.get("kind") or "").lower()
    sport = (a.get("sport") or "").lower()
    if kind in ("athlete_story", "history") or "history" in kind:
        return "story"
    if sport in ("combat", "boxing", "mma", "kun khmer", "muay thai", "kickboxing"):
        return "combat"
    return "news"


def make(path: Path, mood: str = "news", total: float = 12.5, cta_at: float = 8.0) -> Path:
    """Write a stereo WAV: logo at 0 s, mood bed until the end card, closing sting at cta_at."""
    buf = np.zeros(int(total * SR))
    _logo(buf, 0.0)
    {"news": _bed_news, "combat": _bed_combat, "story": _bed_story}.get(mood, _bed_news)(buf, 1.4, total - .6)
    _logo(buf, cta_at + .2, big=False)
    fade = int(.8 * SR)
    buf[-fade:] *= np.linspace(1, 0, fade)
    buf = np.tanh(buf * 1.4) / np.tanh(1.4)               # gentle limiter
    d = int(.011 * SR)                                    # a little stereo width
    left, right = buf, np.concatenate([np.zeros(d), buf[:-d]]) * .9 + buf * .1
    st = np.stack([left, right], 1)
    st = (st / max(1e-9, np.abs(st).max()) * .89 * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(st.tobytes())
    return path
