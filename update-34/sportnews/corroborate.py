"""Check that a news story is reported by at least two independent outlets BEFORE spending AI on it.

Why: a story seen in one feed only (often a quote-led Russian headline) used to be written, then auto-rejected
for "fewer than 2 sources", wasting a daily slot. Now each candidate must be confirmed first:
  1. by another outlet already in today's feeds (same names in the headline/summary), or
  2. by a free Google News search for the story's names (no AI, no key).
Stories that touch politics are skipped (editorial rule: no politics).
"""
from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from .common import log

POLITICS = re.compile(
    r"(politic|sanction|kremlin|putin|trump|parliament|\bminister|government|election|senator|"
    r"полит|санкци|кремл|путин|трамп|госдум|депутат|министр|правительств|выборы|выборах|"
    r"政治|外交部|制裁|普京|特朗普|议员)", re.I)

# Capitalised words that start sentences or are too generic to identify a story.
STOP = {
    "after", "with", "how", "what", "why", "when", "this", "that", "from", "will", "could", "would", "should", "their",
    "there", "here", "first", "last", "watch", "live", "report", "news", "sport", "sports", "today", "says", "said",
    "league", "world", "team", "club", "final", "match", "game", "season", "coach", "player", "players", "fans",
    "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "после", "когда", "почему", "это", "этот", "будет", "может", "стал", "стало", "стали", "заявил", "сказал",
    "россия", "россии", "матч", "лига", "клуб", "сборная", "сборной", "тренер", "игрок", "чемпионат", "золото",
    "победа", "сезон", "финал", "новости", "спорт", "сегодня",
}
GN_LANG = {"en": "hl=en-US&gl=US&ceid=US:en", "ru": "hl=ru&gl=RU&ceid=RU:ru", "zh": "hl=zh-CN&gl=CN&ceid=CN:zh-Hans"}
CAP = re.compile(r"[A-ZА-ЯЁ][\w'’-]{3,}")
CJK = re.compile(r"[一-鿿]")


GENERIC_FIRST = re.compile(r"(ого|ему|ый|ий|ая|ое|ые|ских|ский|ская|ю|ли|ла|ло)$", re.I)   # Двукратного, Думаю


def _words(text: str) -> list[str]:
    """Capitalised words that may be names. A Russian sentence-opening adjective or verb is not a name."""
    out = []
    for n, m in enumerate(CAP.finditer(text or "")):
        w = re.sub(r"['’]s$", "", m.group(0))
        if w.lower() in STOP or len(w) < 4:
            continue
        if m.start() == 0 and re.match(r"[А-ЯЁ]", w) and GENERIC_FIRST.search(w):
            continue
        out.append(w)
    return out


def _stems(text: str) -> set[str]:
    """Name stems: first 5 letters, so Russian case endings still match (Мишиной / Мишина, Галлямова / Галлямов)."""
    return {w.lower()[:5] for w in _words(text)}


def _bigrams(text: str) -> set[str]:
    chars = "".join(CJK.findall(text or ""))
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def same_story(a: dict, b: dict, title_only: bool = False) -> bool:
    """True when two items are very probably about the same event."""
    if a.get("sport") and b.get("sport") and a["sport"] != b["sport"]:
        return False
    ta = a["title"] if title_only else f"{a['title']} {a.get('summary', '')}"
    tb = b["title"] if title_only else f"{b['title']} {b.get('summary', '')}"
    if a.get("lang") == "zh" or CJK.search(a["title"]):
        return len(_bigrams(a["title"]) & _bigrams(b["title"])) >= 4
    return len(_stems(ta) & _stems(tb)) >= 2


def outlets(item: dict) -> set[str]:
    from .collect import _src_key
    return {_src_key(item.get("source", ""))} | {_src_key(o.get("source", "")) for o in item.get("also_reported_by", [])}


def _add(item: dict, other: dict) -> None:
    item.setdefault("also_reported_by", []).append(
        {"source": other.get("source", ""), "link": other.get("link", ""), "title": other.get("title", "")})


def search_google_news(item: dict, cfg: dict) -> list[dict]:
    """Free Google News search for the story's names (last 3 days, same language)."""
    from .collect import parse_feed
    lang = item.get("lang", "en")
    if lang == "zh" or CJK.search(item["title"]):
        q = re.sub(r"[^\w一-鿿]+", " ", item["title"])[:30]
    else:
        seen, names = set(), []
        for w in _words(item["title"]) + _words(item.get("summary", "")):
            if w.lower()[:5] not in seen:
                seen.add(w.lower()[:5]); names.append(w)
        if len(names) < 2:
            return []
        q = " ".join(names[:3])
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q + ' when:3d')}&{GN_LANG.get(lang, GN_LANG['en'])}"
    return parse_feed({"name": "Google News search", "url": url, "lang": lang}, cfg, max_age_hours=72)


def _recent(a: dict, b: dict, hours: int = 72) -> bool:
    try:
        return abs(datetime.fromisoformat(a["published"]) - datetime.fromisoformat(b["published"])) <= timedelta(hours=hours)
    except (TypeError, ValueError, KeyError):
        return True


def confirm(items: list[dict], cfg: dict, top: int = 25, max_searches: int = 12, need: int = 2) -> list[dict]:
    """Return the candidates (best first) that at least `need` independent outlets report, politics removed.
    Items merged into another story are dropped so the same event is never written twice."""
    search = os.environ.get("SPORTNEWS_MOCK") != "1" and (cfg.get("corroborate") or {}).get("search", True)
    pool = sorted(items, key=lambda x: -x.get("score", 0))
    merged, out, searches = set(), [], 0
    for it in pool[:top]:
        if id(it) in merged:
            continue
        if POLITICS.search(f"{it['title']} {it.get('summary', '')}"):
            log.info("Skipped (politics): %s", it["title"][:100])
            continue
        if any(it.get("lang") == o.get("lang") and same_story(it, o) for o in out):
            log.info("Skipped (same event as a stronger story): %s", it["title"][:100])
            merged.add(id(it))
            continue
        if len(outlets(it)) < need:
            for other in pool:
                if other in out:
                    continue
                if other is it or id(other) in merged or other.get("lang") != it.get("lang") or not _recent(it, other):
                    continue
                if not (outlets(other) - outlets(it)) or not same_story(it, other):
                    continue
                _add(it, other)
                for o in other.get("also_reported_by", []):
                    _add(it, o)
                merged.add(id(other))
                if len(outlets(it)) >= need:
                    break
        if len(outlets(it)) < need and search and searches < max_searches:
            searches += 1
            try:
                found = search_google_news(it, cfg)
            except Exception as e:  # noqa: BLE001
                log.info("Google News search failed for %r: %s", it["title"][:60], e)
                found = []
            for f in found:
                if (outlets(f) - outlets(it)) and same_story(it, f, title_only=True):
                    _add(it, f)
                    if len(outlets(it)) >= need:
                        break
        n = len(outlets(it))
        if n >= need:
            out.append(it)
        else:
            log.info("Skipped (only %d outlet): %s", n, it["title"][:100])
    out = [i for i in out if id(i) not in merged]
    log.info("Confirmed by %d+ outlets: %d of %d candidates (%d searches)", need, len(out), min(top, len(pool)), searches)
    return out
