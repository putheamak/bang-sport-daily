"""Originality check: how much of a story repeats the source text word-for-word.

Google treats "scraping or automated rewording of other content" as scaled content abuse, and AdSense
rejects copied content. We measure shared 8-word sequences between our English story and the source text.
"""
from __future__ import annotations

import re

WORD = re.compile(r"[\w'’]+", re.U)


def _words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text or "")]


def check(story: str, source: str, n: int = 8) -> dict:
    """Return {'overlap': share of the story's 8-word sequences found in the source (0-1),
               'longest': longest copied run in words, 'phrases': up to 5 copied phrases}."""
    sw, src = _words(story), _words(source)
    if len(sw) < n or len(src) < n:
        return {"overlap": 0.0, "longest": 0, "phrases": []}
    src_grams = {tuple(src[i:i + n]) for i in range(len(src) - n + 1)}
    hits = [i for i in range(len(sw) - n + 1) if tuple(sw[i:i + n]) in src_grams]
    overlap = len(hits) / max(1, len(sw) - n + 1)
    # merge consecutive hits into runs
    runs, start, prev = [], None, None
    for i in hits:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            runs.append((start, prev))
            start = prev = i
    if start is not None:
        runs.append((start, prev))
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    phrases = [" ".join(sw[a:b + n]) for a, b in runs[:5]]
    longest = (runs[0][1] - runs[0][0] + n) if runs else 0
    return {"overlap": round(overlap, 3), "longest": longest, "phrases": phrases}


def too_close(result: dict, max_overlap: float = 0.10, max_run: int = 20) -> bool:
    return result["overlap"] > max_overlap or result["longest"] > max_run
