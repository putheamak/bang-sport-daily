"""Free, citable fact sources so the AI never writes history or life stories from memory alone.

* "On this day" events come from Wikipedia's dated feed (the date is fixed by the source, not guessed).
* Athlete life stories start from the athlete's Wikipedia article text.
Both are used as FACTS ONLY: the story is written in original words and links to the source pages.
"""
from __future__ import annotations

import re
import urllib.parse

from .common import log

SPORT = re.compile(
    r"\b(football|soccer|world cup|olympic|olympics|paralympic|boxing|boxer|heavyweight|tennis|wimbledon|grand slam|"
    r"cricket|rugby|basketball|nba|baseball|ice hockey|nhl|stanley cup|formula one|grand prix|motor racing|cycling|"
    r"tour de france|marathon|athletics|sprinter|swimmer|swimming|gymnast|figure skat|skier|skiing|badminton|"
    r"table tennis|golf|golfer|chess|wrestl|judo|taekwondo|martial art|fifa|uefa|champions league|asian games|"
    r"sea games|commonwealth games|world record|race|tournament|championship|cup final|grandmaster|jockey|derby)\b", re.I)
TRAGEDY = re.compile(r"\b(killed|kills|dies|died|death|disaster|crash|crushed|massacre|terror|bomb|riot|stampede|"
                     r"murder|shot dead|assassinat)\w*", re.I)


def _json(url: str) -> dict:
    import json
    import urllib.request
    from .images import _ua
    req = urllib.request.Request(url, headers={"User-Agent": _ua(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def wiki_extract(title: str, chars: int = 7000) -> tuple[str, str]:
    """(plain text, page URL) of an English Wikipedia article ('' if not found)."""
    try:
        from .images import _get as wiki_get
        d = wiki_get("https://en.wikipedia.org/w/api.php",
                     {"action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "redirects": 1})
        pages = d.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return "", ""
        p = pages[0]
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p["title"].replace(" ", "_"))
        return (p.get("extract") or "")[:chars], url
    except Exception as e:  # noqa: BLE001
        log.warning("Wikipedia text for %r failed: %s", title, e)
        return "", ""


def on_this_day(month_day: str, focus: str = "global") -> dict | None:
    """Best sport event for this calendar date from Wikipedia's 'On this day' feed.
    Prefers the region behind its target; skips tragedies (an 'on this day' feature should not turn
    deaths and disasters into entertainment)."""
    from .regions import classify
    mm, dd = month_day.split("-")
    try:
        d = _json(f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/all/{mm}/{dd}")
    except Exception as e:  # noqa: BLE001
        log.warning("Wikipedia 'On this day' failed: %s", e)
        return None
    cands = []
    for kind in ("selected", "events"):
        for ev in d.get(kind) or []:
            pages = ev.get("pages") or []
            blob = ev.get("text", "") + " " + " ".join((p.get("description") or "") + " " + (p.get("extract") or "")[:300]
                                                     for p in pages)
            if not SPORT.search(blob) or TRAGEDY.search(ev.get("text", "")):
                continue
            region = classify(blob)
            score = 2 if region == focus and focus != "global" else 0
            score += 1 if kind == "selected" else 0
            score += min(len(pages), 3) * 0.2
            cands.append((score, ev, region))
    if not cands:
        log.info("No sport event in Wikipedia's 'On this day' for %s", month_day)
        return None
    cands.sort(key=lambda x: -x[0])
    _, ev, region = cands[0]
    pages = [p for p in ev.get("pages") or [] if p.get("titles", {}).get("canonical")][:3]
    out = {"year": ev.get("year"), "text": ev.get("text", ""), "region": region, "pages": []}
    for p in pages[:2]:
        text, url = wiki_extract(p["titles"]["canonical"].replace("_", " "))
        if text:
            out["pages"].append({"title": p["titles"].get("normalized") or p["titles"]["canonical"], "url": url, "text": text})
    log.info("On this day %s: %s – %s (%s)", month_day, out["year"], out["text"][:90], region)
    return out if out["pages"] else None


def history_context(month_day: str, focus: str) -> dict | None:
    ev = on_this_day(month_day, focus)
    if not ev:
        return None
    src = f"EVENT (Wikipedia 'On this day', {month_day}): {ev['year']} – {ev['text']}\n"
    for p in ev["pages"]:
        src += f"\nWIKIPEDIA ARTICLE: {p['title']} ({p['url']})\n{p['text']}\n"
    return {"title": f"On this day: {ev['year']} – {ev['text'][:80]}", "event_year": ev["year"], "event_text": ev["text"],
            "sources": src, "source_links": [{"title": f"Wikipedia: {p['title']}", "url": p["url"]} for p in ev["pages"]],
            "region_hint": ev["region"]}


def athlete_context(name: str) -> tuple[str, list[dict]]:
    text, url = wiki_extract(name, 9000)
    if not text:
        return "", []
    return f"WIKIPEDIA ARTICLE: {name} ({url})\n{text}\n", [{"title": f"Wikipedia: {name}", "url": url}]
