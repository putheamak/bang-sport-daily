"""Trending radar: which sport stories are many outlets talking about right now?

No AI is used. Every few hours the feeds are scanned (English, Chinese, Russian), the same story from different
outlets is grouped, and stories are ranked by how many independent outlets cover them and how fast that number
is growing. The top 5 are sent to the editor's private Telegram chat as a numbered list.

The editor replies "write 1 3" in Telegram (or runs the "Write trending stories" workflow with "1 3"), and the
chosen stories are written as short EXPLAINERS: what happened, why it is being talked about, key facts, what next.
They arrive as drafts for review, like every other story.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

from .common import DATA, log, read_json, short_hash, write_json

TRENDING = DATA / "trending.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "putheamak/bang-sport-daily")
WRITE_WORKFLOW = "write-trending.yml"
WRITE_CMD = re.compile(r"^\s*/?(?:write|w)\s+([\d ,]+)\s*$", re.I)


def _key(it: dict) -> str:
    """Stable id of a story across scans (its main names), so growth can be measured."""
    from .corroborate import CJK, _bigrams, _stems
    if it.get("lang") == "zh" or CJK.search(it["title"]):
        base = "".join(sorted(_bigrams(it["title"]))[:6])
    else:
        base = " ".join(sorted(_stems(it["title"] + " " + it.get("summary", "")))[:4])
    return short_hash(it.get("lang", "") + "|" + (base or it["title"].lower()))[:10]


def _group(items: list[dict]) -> list[dict]:
    """Group the same story from different outlets (same language), counting independent outlets."""
    from .collect import _src_key
    from .corroborate import same_story
    groups: list[dict] = []
    for it in sorted(items, key=lambda x: -x.get("score", 0)):
        g = next((g for g in groups if g["lang"] == it["lang"] and same_story(g["lead"], it)), None)
        refs = [{"source": it["source"], "link": it["link"], "title": it["title"]}] + list(it.get("also_reported_by", []))
        if g is None:
            g = {"lead": it, "lang": it["lang"], "refs": [], "outlets": set()}
            groups.append(g)
        for r in refs:
            k = _src_key(r.get("source", ""))
            if k not in g["outlets"]:
                g["outlets"].add(k)
                g["refs"].append(r)
    return groups


def _blocked(text: str) -> str | None:
    from .collect import WIRE_CLICKBAIT
    from .corroborate import POLITICS
    from .standards import BETTING
    for name, rx in (("politics", POLITICS), ("betting", BETTING), ("clickbait", WIRE_CLICKBAIT)):
        if rx.search(text):
            return name
    return None


def rank(cfg: dict, items: list[dict], prev: dict | None = None, top: int = 5) -> list[dict]:
    """Top stories by outlet count + growth since the last scan + freshness. At least 2 outlets each."""
    tcfg = cfg.get("trending") or {}
    prev_n = {s["key"]: s["outlets"] for s in (prev or {}).get("stories", [])}
    now = datetime.now(timezone.utc)
    out = []
    for g in _group(items):
        it = g["lead"]
        n = len(g["outlets"])
        if n < tcfg.get("min_outlets", 2):
            continue
        why_blocked = _blocked(f"{it['title']} {it.get('summary', '')}")
        if why_blocked:
            log.info("Trending skipped (%s): %s", why_blocked, it["title"][:90])
            continue
        key = _key(it)
        growth = n - prev_n.get(key, n)
        age_h = 24.0
        if it.get("published"):
            try:
                age_h = (now - datetime.fromisoformat(it["published"])).total_seconds() / 3600
            except ValueError:
                pass
        heat = round(n * 2 + max(growth, 0) * 1.5 + max(0.0, 2 - age_h / 12) + (it.get("score", 0) * 0.3), 2)
        out.append({"key": key, "title": it["title"], "summary": (it.get("summary") or "")[:400], "lang": it["lang"],
                    "sport": it.get("sport"), "outlets": n, "growth": growth, "heat": heat,
                    "published": it.get("published"), "refs": g["refs"][:8]})
    out.sort(key=lambda s: -s["heat"])
    # variety: at most 3 stories from one language and 2 from one sport, so ZH and RU stories get a place
    picked, per_lang, per_sport = [], {}, {}
    for s in out:
        sp = s["sport"] or "other"
        if per_lang.get(s["lang"], 0) >= tcfg.get("max_per_language", 3) or per_sport.get(sp, 0) >= 2:
            continue
        picked.append(s)
        per_lang[s["lang"]] = per_lang.get(s["lang"], 0) + 1
        per_sport[sp] = per_sport.get(sp, 0) + 1
        if len(picked) >= top:
            break
    return picked


FLAG = {"en": "🇬🇧", "zh": "🇨🇳", "ru": "🇷🇺"}


def message(stories: list[dict]) -> str:
    lines = ["🔥 TALKING POINTS (stories many outlets are covering now)", ""]
    for i, s in enumerate(stories, 1):
        rise = f", +{s['growth']} since last scan" if s.get("growth", 0) > 0 else ""
        names = ", ".join(r["source"] for r in s["refs"][:4])
        lines += [f"{i}. {FLAG.get(s['lang'], '')} {s['title']}",
                  f"   {s['outlets']} outlets{rise} · {s.get('sport') or 'sport'} · {names}", ""]
    lines += ["To write short explainers, reply for example:", "write 1 3",
              f"(or GitHub › Actions › Write trending stories: https://github.com/{REPO}/actions/workflows/{WRITE_WORKFLOW})",
              "They arrive as drafts for your review."]
    return "\n".join(lines)


def save_md(data: dict) -> None:
    rows = [f"# Talking points ({data.get('updated', '')} UTC)", "",
            "Stories many outlets are covering right now. Write any of them with the "
            "**Write trending stories** workflow (numbers refer to the list last sent to Telegram).", ""]
    for i, s in enumerate(data.get("sent") or data.get("stories") or [], 1):
        rows.append(f"{i}. **{s['title']}** ({s['lang']}, {s['outlets']} outlets)")
        rows += [f"   - [{r['source']}]({r['link']})" for r in s["refs"][:5]]
    (DATA / "trending.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def scan(cfg: dict, items: list[dict] | None = None, notify: bool = True) -> dict:
    from .collect import collect
    from .publishers import telegram_send
    tcfg = cfg.get("trending") or {}
    data = read_json(TRENDING, {})
    items = collect(cfg) if items is None else items
    stories = rank(cfg, items, data, tcfg.get("top", 5))
    now = datetime.now(timezone.utc)
    data.update(updated=now.isoformat(timespec="seconds"), stories=stories)
    known = data.setdefault("known", {})
    for st in stories:
        known[st["key"]] = st
    for k in list(known)[:-80]:                          # keep the newest 80
        known.pop(k, None)
    chat = os.environ.get("TELEGRAM_REVIEW_CHAT")
    every = timedelta(hours=tcfg.get("notify_every_hours", 8))
    last = data.get("sent_at")
    due = not last or now - datetime.fromisoformat(last) >= every
    local_h = (now + timedelta(hours=7)).hour            # Cambodia time: no messages at night
    quiet = not (tcfg.get("quiet_from", 23) > local_h >= tcfg.get("quiet_until", 7))
    new_top = bool(stories) and stories[0]["key"] not in {s["key"] for s in data.get("sent") or []}
    if notify and stories and chat and os.environ.get("TELEGRAM_BOT_TOKEN") and not quiet and (due or new_top and
                                                                                              stories[0]["outlets"] >= 5):
        try:
            telegram_send(chat, message(stories))
            data.update(sent=stories, sent_at=now.isoformat(timespec="seconds"))
            log.info("Talking points sent to Telegram (%d stories)", len(stories))
        except Exception as e:  # noqa: BLE001
            log.error("Talking points message failed: %s", e)
    else:
        log.info("Talking points: %d stories (not sent now: due=%s quiet=%s)", len(stories), due, quiet)
    for i, s in enumerate(stories, 1):
        log.info("  %d. [%s %d outlets, heat %.1f] %s", i, s["lang"], s["outlets"], s["heat"], s["title"][:100])
    write_json(TRENDING, data)
    save_md(data)
    return data


# ------------------------------------------------------------------ editor's reply in Telegram: "write 1 3"
def _tg(method: str, params: dict) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}",
                                 data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def parse_numbers(text: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", text or "")]


def parse_choice(text: str) -> list:
    """'1 3' -> [1, 3] (numbers of the last list sent); 'k:abc k:def' -> story keys (from a Telegram reply)."""
    keys = re.findall(r"k:([0-9a-f]{6,})", text or "")
    return keys if keys else parse_numbers(text)


def read_replies() -> list[str]:
    """Stories the editor asked for since the last check ('write 1 3' in the private chat; nobody else counts).
    Numbers are turned into story keys of the list the editor SAW, so a newer list can never change the choice."""
    chat = str(os.environ.get("TELEGRAM_REVIEW_CHAT", ""))
    if not (chat and os.environ.get("TELEGRAM_BOT_TOKEN")):
        return []
    data = read_json(TRENDING, {})
    try:
        res = _tg("getUpdates", {"offset": data.get("tg_offset", 0), "timeout": 0, "allowed_updates": ["message"]})
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read Telegram replies: %s", e)
        return []
    nums: list[int] = []
    for u in res.get("result", []):
        data["tg_offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) != chat:
            continue
        hit = WRITE_CMD.match(m.get("text") or "")
        if hit:
            nums += parse_numbers(hit.group(1))
    sent = data.get("sent") or []
    keys = [sent[n - 1]["key"] for n in sorted(set(nums)) if 1 <= n <= len(sent)]
    write_json(TRENDING, data)
    if nums:
        names = "\n".join(f"• {sent[n - 1]['title']}" for n in sorted(set(nums)) if 1 <= n <= len(sent))
        try:
            _tg("sendMessage", {"chat_id": chat, "text": ("✍️ Writing explainers (drafts in about 10–30 minutes):\n" + names)
                                if keys else "No such numbers in the last list. Reply like: write 1 3"})
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram acknowledgement failed: %s", e)
    return keys


def dispatch_write(numbers: list) -> bool:
    """Start the 'Write trending stories' workflow (GitHub allows this from a workflow with actions: write)."""
    token = os.environ.get("GITHUB_TOKEN")
    if not (token and numbers):
        return False
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WRITE_WORKFLOW}/dispatches",
        data=json.dumps({"ref": "main", "inputs": {"numbers": " ".join(
            (f"k:{x}" if isinstance(x, str) else str(x)) for x in numbers)}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
        log.info("Started 'Write trending stories' for %s", numbers)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("Could not start the write workflow: %s", e)
        return False


# ------------------------------------------------------------------ write the chosen stories as explainers
def _context(s: dict) -> dict:
    from .collect import fetch_full_text
    src = (f"STORY MANY OUTLETS ARE COVERING ({s['outlets']} independent outlets, first seen {s.get('published')}):\n"
           f"{s['title']}\nSUMMARY: {s.get('summary', '')}\n")
    texts = 0
    for r in s["refs"]:
        src += f"\nOUTLET: {r['source']}\nHEADLINE: {r.get('title', '')}\nLINK: {r['link']}\n"
        if texts < 2:
            body = fetch_full_text(r["link"], 4000)
            if body:
                src += f"ARTICLE TEXT (facts only, do not copy):\n{body}\n"
                texts += 1
    links = [{"title": f"{r['source']}: {r.get('title', '')}", "url": r["link"]} for r in s["refs"] if r.get("link")]
    return {"title": s["title"], "sport": s.get("sport"), "sources": src, "source_links": links, "task": "explainer"}


def write_selected(cfg: dict, numbers: list) -> list[dict]:
    from .common import load_articles, save_articles, today
    from .pipeline import merge_articles
    from .publishers import send_for_review
    from .regions import classify
    from .site import build_site
    from .standards import auto_reject_reasons, stamp
    from .writer import write_article
    data = read_json(TRENDING, {})
    pool = data.get("sent") or data.get("stories") or []
    date = today(cfg)
    new = []
    known = data.get("known") or {}
    for n in numbers:
        if isinstance(n, str):
            s = known.get(n)
            if not s:
                log.warning("Talking point %s not found", n)
                continue
        elif 1 <= n <= len(pool):
            s = pool[n - 1]
        else:
            log.warning("Talking point %s does not exist (list has %d)", n, len(pool))
            continue
        if s["key"] in set(data.get("written", [])):
            log.info("Talking point %s already written: %s", n, s["title"][:80])
            continue
        log.info("Writing explainer %s: %s", n, s["title"])
        try:
            art = write_article(cfg, "news", _context(s), date)
        except Exception as e:  # noqa: BLE001
            log.error("Explainer %s failed: %s", n, e)
            continue
        art["format"] = "explainer"
        art["region"] = classify(f"{s['title']} {s.get('summary', '')}", s.get("lang", "en"))
        new.append(art)
        data.setdefault("written", []).append(s["key"])
    if cfg["publish"].get("photos", True):
        from .images import attach_images
        for a in new:
            try:
                attach_images(a)
            except Exception as e:  # noqa: BLE001
                log.warning("Photos failed for %s: %s", a["id"], e)
    stamp(cfg, new, date)
    for a in new:
        why = auto_reject_reasons(cfg, a)
        if why:
            a["status"], a["auto_rejected"] = "rejected", why
            log.warning("Auto-rejected %s: %s", a["id"], "; ".join(why))
    save_articles(merge_articles(new, load_articles()))
    write_json(TRENDING, data)
    kept = [a for a in new if a["status"] != "rejected"]
    if kept:
        send_for_review(cfg, kept)
    build_site(cfg)
    log.info("Explainers written: %d (%d kept for review)", len(new), len(kept))
    return new
