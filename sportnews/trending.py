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


def _rare(items: list[dict]):
    """Name stems that identify a story. Words in many headlines ('Football', 'Team', 'NFL', 'Cup') do not:
    English headlines are written in Title Case, so capital letters alone cannot tell names from ordinary words."""
    from collections import Counter
    from .corroborate import _stems
    df = Counter(st for it in items for st in _stems(it["title"]))
    limit = max(4, int(len(items) * 0.03))
    return lambda title: {st for st in _stems(title) if df[st] <= limit}


def _same(a: dict, b: dict, rare) -> bool:
    """Same story? Headlines only: Google News summaries bundle other outlets' headlines, which made unrelated
    stories look alike (10 Nov 2026: Pochettino grouped with NFL and college football)."""
    from .corroborate import CJK, cjk_same
    if a.get("lang") != b.get("lang"):
        return False
    if a.get("sport") and b.get("sport") and a["sport"] != b["sport"]:
        return False
    if a.get("lang") == "zh" or CJK.search(a["title"]):
        return cjk_same(a["title"], b["title"])
    return len(rare(a["title"]) & rare(b["title"])) >= 2


BET_SOURCE = re.compile(r"(stavk|prognoz|ставк|прогноз|букмек|betting|sportsbook|odds)", re.I)
COMBAT_PREVIEW = (r"(face-?off|weigh-?in|press conference|presser|warning|predict|preview|odds|what time|how to watch|"
                  r"live fight coverage|live coverage|live updates|live blog|live results|^live\b|midnight mania|"
                  r"онлайн|прямая трансляция|"
                  r"битв\w* взглядов|взвешивани|пресс-конференц|прогноз|перед боем|перед турниром|"
                  r"称重|对视|发布会|前瞻)")


def _group(items: list[dict]) -> list[dict]:
    """Group the same story from different outlets (same language), counting independent outlets."""
    from .collect import _src_key
    rare = _rare(items)
    groups: list[dict] = []
    for it in sorted(items, key=lambda x: -x.get("score", 0)):
        g = next((g for g in groups if _same(g["lead"], it, rare)), None)
        refs = [{"source": it["source"], "link": it["link"], "title": it["title"]}] + list(it.get("also_reported_by", []))
        if g is None:
            g = {"lead": it, "lang": it["lang"], "refs": [], "outlets": set()}
            groups.append(g)
        g["kun"] = g.get("kun") or bool(it.get("kun"))
        for r in refs:
            if BET_SOURCE.search(r.get("source", "")):        # betting sites are never a source
                continue
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
        why_blocked = _blocked(it["title"].replace("!", "").replace("！", "")) or (
            "not our audience" if re.search(tcfg.get("skip", SKIP), it["title"], re.I) else None)
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
        if per_lang.get(s["lang"], 0) >= tcfg.get("max_per_language", 3) or (s["sport"] and per_sport.get(sp, 0) >= 2):
            continue
        picked.append(s)
        per_lang[s["lang"]] = per_lang.get(s["lang"], 0) + 1
        per_sport[sp] = per_sport.get(sp, 0) + 1
        if len(picked) >= top:
            break
    return picked



def rank_combat(cfg: dict, items: list[dict], prev: dict | None = None) -> list[dict]:
    """Combat watch: the top combat-sport stories (MMA, kickboxing, Muay Thai, Kun Khmer, boxing, bare-knuckle).
    Kun Khmer stories are always listed, even with one outlet (marked: needs a 2nd source before writing)."""
    from .collect import COMBAT_RX
    cw = cfg.get("combat_watch") or {}
    if not cw.get("enabled", True):
        return []
    always = [a.lower() for a in cw.get("always_include", ["kun khmer"])]
    need = cw.get("min_outlets", 2)
    skip = re.compile(cw.get("skip", COMBAT_PREVIEW), re.I)
    pool = [it for it in items if (it.get("sport") == "combat" or COMBAT_RX.search(it.get("title", "")))
            and not skip.search(it.get("title", ""))]       # previews out BEFORE grouping, so a result is not
                                                            # swallowed by a preview of the same fight
    prev_n = {s["key"]: s["outlets"] for s in (prev or {}).get("combat", [])}
    now = datetime.now(timezone.utc)
    out = []
    for g in _group(pool):
        it = g["lead"]
        n = len(g["outlets"])
        text = f"{it['title']} {it.get('summary', '')}".lower()
        kun = g.get("kun") or any(a in text for a in always)
        if n < need and not kun:
            continue
        if any(_blocked(r.get("title", "").replace("!", "").replace("！", "")) for r in [it] + g["refs"]):
            continue                                    # one outlet calling it politics is enough to skip
        key = _key(it)
        growth = n - prev_n.get(key, n)
        age_h = 24.0
        if it.get("published"):
            try:
                age_h = (now - datetime.fromisoformat(it["published"])).total_seconds() / 3600
            except ValueError:
                pass
        heat = round(n * 2 + max(growth, 0) * 1.5 + max(0.0, 2 - age_h / 12) + it.get("score", 0) * 0.3
                     + (6 if kun else 0), 2)
        out.append({"key": key, "title": it["title"], "summary": (it.get("summary") or "")[:400], "lang": it["lang"],
                    "sport": "combat", "outlets": n, "growth": growth, "heat": heat, "kun_khmer": kun,
                    "needs_source": n < need, "published": it.get("published"), "refs": g["refs"][:8]})
    out.sort(key=lambda s: -s["heat"])
    return out[:cw.get("top", 5)]

SKIP = (r"\b(NFL|NCAA|college football|fantasy|Super Bowl|quarterback|touchdown|MLB|NHL trade|waiver wire|"
        r"school|schools|schoolboys|grassroots|amateur|8U|U8|U10|U12|7s|"
        r"Jaguars|Vikings|Bills|49ers|Raiders|Cardinals|Hokies)\b")

FLAG = {"en": "🇬🇧", "zh": "🇨🇳", "ru": "🇷🇺", "km": "🇰🇭"}


def message(stories: list[dict], combat: list[dict] | None = None) -> str:
    lines = ["🔥 TALKING POINTS (stories many outlets are covering now)", ""]
    for i, s in enumerate(stories, 1):
        rise = f", +{s['growth']} since last scan" if s.get("growth", 0) > 0 else ""
        names = ", ".join(r["source"] for r in s["refs"][:4])
        lines += [f"{i}. {FLAG.get(s['lang'], '')} {s['title']}",
                  f"   {s['outlets']} outlets{rise} · {s.get('sport') or 'sport'} · {names}", ""]
    if combat:
        lines += ["🥊 COMBAT WATCH (MMA, kickboxing, Muay Thai, Kun Khmer, boxing, bare-knuckle)", ""]
        for i, s in enumerate(combat, 1):
            names = ", ".join(r["source"] for r in s["refs"][:4])
            tag = " 🇰🇭" if s.get("kun_khmer") else ""
            need = " · needs a 2nd source" if s.get("needs_source") else ""
            lines += [f"C{i}. {FLAG.get(s['lang'], '')}{tag} {s['title']}", f"   {s['outlets']} outlet(s){need} · {names}", ""]
    lines += ["To write short explainers, reply for example:", "write 1 3" + (" C1" if combat else ""),
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
    combat = data.get("combat_sent") or data.get("combat") or []
    if combat:
        rows += ["", "## Combat watch", "",
                 "MMA, kickboxing, Muay Thai, Kun Khmer, boxing, bare-knuckle. Write with C-numbers, e.g. `C1 C3`.", ""]
        for i, s in enumerate(combat, 1):
            need = ", needs a 2nd source" if s.get("needs_source") else ""
            rows.append(f"C{i}. **{s['title']}** ({s['lang']}, {s['outlets']} outlet(s){need})")
            rows += [f"   - [{r['source']}]({r['link']})" for r in s["refs"][:5]]
    (DATA / "trending.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def scan(cfg: dict, items: list[dict] | None = None, notify: bool = True) -> dict:
    from .collect import collect
    from .publishers import telegram_send
    tcfg = cfg.get("trending") or {}
    data = read_json(TRENDING, {})
    items = collect(cfg) if items is None else items
    stories = rank(cfg, items, data, tcfg.get("top", 5))
    combat = rank_combat(cfg, items, data)
    now = datetime.now(timezone.utc)
    data.update(updated=now.isoformat(timespec="seconds"), stories=stories, combat=combat)
    known = data.setdefault("known", {})
    for st in stories + combat:
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
            telegram_send(chat, message(stories, combat))
            data.update(sent=stories, combat_sent=combat, sent_at=now.isoformat(timespec="seconds"))
            log.info("Talking points sent to Telegram (%d stories)", len(stories))
        except Exception as e:  # noqa: BLE001
            log.error("Talking points message failed: %s", e)
    else:
        log.info("Talking points: %d stories (not sent now: due=%s quiet=%s)", len(stories), due, quiet)
    for i, s in enumerate(stories, 1):
        log.info("  %d. [%s %d outlets, heat %.1f] %s", i, s["lang"], s["outlets"], s["heat"], s["title"][:100])
    for i, s in enumerate(combat, 1):
        log.info("  C%d. [%s %d outlets, heat %.1f] %s", i, s["lang"], s["outlets"], s["heat"], s["title"][:100])
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
    """'1 3' -> [1, 3] (numbers of the last list sent); 'k:abc k:def' -> story keys (from a Telegram reply);
    'rev:<data>' -> a revision request {id, notes, photos}."""
    if (text or "").strip().startswith("rev:"):
        import base64
        return [json.loads(base64.urlsafe_b64decode(text.strip()[4:].encode()).decode())]
    keys = re.findall(r"k:([0-9a-f]{6,})", text or "")
    if keys:
        return keys
    out: list = []
    combat = None
    for tok in re.findall(r"[cC]\s?\d+|\d+", text or ""):
        if tok[0] in "cC":
            if combat is None:
                d = read_json(TRENDING, {})
                combat = d.get("combat_sent") or d.get("combat") or []
            i = int(tok[1:].strip())
            if 1 <= i <= len(combat):
                out.append(combat[i - 1]["key"])
            else:
                log.warning("Combat story C%d does not exist (list has %d)", i, len(combat))
        else:
            out.append(int(tok))
    return out


PUB_CMD = re.compile(r"^\s*/?(publish-anyway|publish|reject)\s+(.+)$", re.I)
HELP = ("Commands (reply here):\n"
        "• write 1 3 — write talking points 1 and 3 as explainers\n"
        "• publish <ID> — publish a draft (several IDs: separate with spaces)\n"
        "• reject <ID> — reject a draft\n"
        "• publish-anyway <ID> — publish despite a standards warning (use with care)\n"
        "• Reply to a draft message with: publish / reject — or with notes and/or a screenshot to have it revised\n"
        "  (or: fix <ID> your notes)\n"
        "Replies are read every hour, so allow up to an hour (sometimes more) before the work starts.")


FIX_CMD = re.compile(r"^\s*/?(?:fix|revise|edit)\s+([0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z]{4}-[0-9a-f]{6})\s*[:\-]?\s*(.*)$",
                     re.I | re.S)
ID_RE = re.compile(r"\bID:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z]{4}-[0-9a-f]{6})")


def _draft_id(text: str | None) -> str | None:
    """The story ID inside one of the bot's draft messages ('ID: 2026-11-10-news-abc123')."""
    m = ID_RE.search(text or "")
    return m.group(1) if m else None


def usable_refs(s: dict) -> list[dict]:
    """Outlets whose own headline is about this exact story (one per outlet)."""
    from .collect import _src_key
    from .corroborate import same_story
    lead = {"title": s["title"], "lang": s.get("lang"), "sport": s.get("sport")}
    refs, seen = [], set()
    for r in s.get("refs", []):
        o = _src_key(r.get("source", ""))
        if o in seen:
            continue
        if refs and not same_story(lead, {"title": r.get("title", ""), "lang": s.get("lang")}, title_only=True):
            continue
        refs.append(r)
        seen.add(o)
    return refs


def read_commands() -> dict:
    """Commands from the editor's private chat since the last check (nobody else is obeyed):
    'write 1 3', 'publish <ID>', 'reject <ID>', 'publish-anyway <ID>', 'help'.
    Talking-point numbers become story keys of the list the editor SAW, so a newer list never changes the choice."""
    out = {"write": [], "publish": [], "reject": [], "publish-anyway": [], "revise": []}
    chat = str(os.environ.get("TELEGRAM_REVIEW_CHAT", ""))
    if not (chat and os.environ.get("TELEGRAM_BOT_TOKEN")):
        return out
    data = read_json(TRENDING, {})
    try:
        res = _tg("getUpdates", {"offset": data.get("tg_offset", 0), "timeout": 0, "allowed_updates": ["message"]})
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read Telegram replies: %s", e)
        return out
    nums: list[int] = []
    ids: dict[str, list[str]] = {"publish": [], "reject": [], "publish-anyway": []}
    revs: dict[str, dict] = {}
    want_help = False
    for u in res.get("result", []):
        data["tg_offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) != chat:
            continue
        text = (m.get("text") or m.get("caption") or "").strip()
        photo = (m.get("photo") or [{}])[-1].get("file_id")               # largest size of a screenshot
        target = _draft_id((m.get("reply_to_message") or {}).get("text") or (m.get("reply_to_message") or {}).get("caption"))
        short = text.lower().strip(" .!/")
        if target and short in ("publish", "reject", "publish-anyway", "approve", "ok"):
            ids["reject" if short == "reject" else "publish-anyway" if short == "publish-anyway" else "publish"].append(target)
            continue
        fix = FIX_CMD.match(text)
        if fix or (target and not (WRITE_CMD.match(text) or PUB_CMD.match(text)) and (text or photo)):
            rid = fix.group(1) if fix else target
            notes = fix.group(2) if fix else text
            r = revs.setdefault(rid, {"id": rid, "notes": [], "photos": []})
            if notes.strip():
                r["notes"].append(notes.strip())
            if photo:
                r["photos"].append(photo)
            continue
        for line in text.splitlines():
            w, p = WRITE_CMD.match(line), PUB_CMD.match(line)
            if w:
                nums += parse_numbers(w.group(1))
            elif p:
                ids[p.group(1).lower()] += re.findall(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z]{4}-[0-9a-f]{6}|[\w-]{6,}", p.group(2))
            elif line.lower().lstrip("/") in ("help", "start", "?"):
                want_help = True
    write_json(TRENDING, data)
    replies = []
    for action in ("publish", "publish-anyway"):          # never publish a draft that is being revised right now
        held = [i for i in ids[action] if i in revs]
        if held:
            ids[action] = [i for i in ids[action] if i not in revs]
            replies.append("⏸ Not published yet: " + ", ".join(held) + " is being revised. Reply publish to the "
                           "revised draft when it arrives.")
    if want_help:
        replies.append(HELP)
    if nums:
        sent = data.get("sent") or []
        ok, skipped = [], []
        for n in sorted(set(nums)):
            if not 1 <= n <= len(sent):
                skipped.append(f"• {n}: no such number in the last list")
            elif len(usable_refs(sent[n - 1])) < 2:
                skipped.append(f"• {sent[n - 1]['title']} (only 1 outlet reports this exact story)")
            else:
                ok.append(sent[n - 1])
        out["write"] = [s["key"] for s in ok]
        if ok:
            replies.append("✍️ Writing explainers (drafts in about 10–30 minutes):\n" + "\n".join(f"• {s['title']}" for s in ok))
        if skipped:
            replies.append("⚠️ Not written:\n" + "\n".join(skipped))
    if any(ids.values()):
        from .common import load_articles
        from .publishers import _match
        arts = load_articles()
        for action, wanted in ids.items():
            if not wanted:
                continue
            found = _match(arts, wanted)
            missing = [w for w in wanted if not _match(arts, [w])]
            out[action] = [a["id"] for a in found]
            if found:
                verb = {"publish": "📢 Publishing", "reject": "🗑 Rejecting", "publish-anyway": "📢 Publishing (anyway)"}[action]
                replies.append(f"{verb} (in a few minutes):\n" + "\n".join(f"• {a['id']}: {a['en'].get('headline', '')[:90]}"
                                                                         for a in found))
            if missing:
                replies.append("❓ Not found (check the ID): " + ", ".join(missing))
    if revs:
        from .common import load_articles
        arts = {a["id"]: a for a in load_articles()}
        for rid, r in revs.items():
            a = arts.get(rid)
            if not a:
                replies.append(f"❓ Draft {rid} not found")
            elif a.get("status") == "published":
                replies.append(f"ℹ️ {rid} is already published. Send corrections for published stories through the inbox "
                               "(or ask Claude); only drafts are revised from Telegram.")
            else:
                out["revise"].append({"id": rid, "notes": "\n".join(r["notes"]), "photos": r["photos"][:3]})
                what = (f"{len(r['notes'])} note(s)" if r["notes"] else "") + (
                    f"{' + ' if r['notes'] else ''}{len(r['photos'])} screenshot(s)" if r["photos"] else "")
                replies.append(f"✏️ Revising {rid} with your {what}. The revised draft comes back here in about 10–30 minutes.")
    for r in replies:
        try:
            _tg("sendMessage", {"chat_id": chat, "text": r})
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram reply failed: %s", e)
    return out


def read_replies() -> list[str]:
    """Kept for older callers: only the 'write' part."""
    return read_commands()["write"]


def dispatch(workflow: str, inputs: dict) -> bool:
    """Start a workflow (GitHub allows this from a workflow that has 'actions: write')."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        log.error("GITHUB_TOKEN missing: cannot start %s", workflow)
        return False
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches",
        data=json.dumps({"ref": "main", "inputs": inputs}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
        log.info("Started %s with %s", workflow, inputs)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("Could not start %s: %s", workflow, e)
        return False


def handle_commands() -> dict:
    cmds = read_commands()
    if cmds["write"]:
        dispatch_write(cmds["write"])
    for r in cmds["revise"]:
        import base64
        dispatch(WRITE_WORKFLOW, {"numbers": "rev:" + base64.urlsafe_b64encode(json.dumps(r).encode()).decode()})
    for action in ("publish", "reject", "publish-anyway"):
        if cmds[action]:
            dispatch("publish.yml", {"ids": ",".join(cmds[action]), "action": action})
    return cmds


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


def _notify(text: str) -> None:
    chat = os.environ.get("TELEGRAM_REVIEW_CHAT")
    if chat and os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            _tg("sendMessage", {"chat_id": chat, "text": text})
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram message failed: %s", e)


def _photo_bytes(file_id: str):
    f = _tg("getFile", {"file_id": file_id})["result"]["file_path"]
    req = urllib.request.Request(f"https://api.telegram.org/file/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{f}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(), "image/png" if f.lower().endswith(".png") else "image/jpeg"


def revise_draft(cfg: dict, req: dict) -> dict | None:
    """Revise a draft with the editor's Telegram notes/screenshots and send it back for review."""
    from .common import load_articles, save_articles, today
    from .publishers import send_for_review
    from .site import build_site
    from .standards import stamp
    from .writer import revise_article
    arts = load_articles()
    a = next((x for x in arts if x["id"] == req["id"]), None)
    if not a or a.get("status") == "published":
        log.warning("Revision skipped: %s not found or already published", req["id"])
        return None
    images = []
    for fid in req.get("photos") or []:
        try:
            images.append(_photo_bytes(fid))
        except Exception as e:  # noqa: BLE001
            log.warning("Screenshot download failed: %s", e)
    try:
        b = revise_article(cfg, a, req.get("notes", ""), images)
    except Exception as e:  # noqa: BLE001
        log.error("Revision of %s failed: %s", a["id"], e)
        _notify(f"⚠️ Revision of {a['id']} failed (AI busy?). Send your note again later. ({str(e)[:120]})")
        return None
    b["status"] = "draft"
    b.pop("auto_rejected", None)
    stamp(cfg, [b], today(cfg))
    save_articles([b if x["id"] == b["id"] else x for x in arts])
    ch = (b.get("revisions") or [{}])[-1].get("changes") or []
    if ch:
        _notify("✏️ Revised. Changes:\n" + "\n".join(f"• {c}" for c in ch[:8]))
    send_for_review(cfg, [b])
    build_site(cfg)
    log.info("Revised %s: %s", b["id"], ch)
    return b


def _more_refs(cfg: dict, s: dict, refs: list[dict]) -> list[dict]:
    """One outlet only (often Kun Khmer): search Google News once for another outlet with the same story."""
    from .collect import _src_key
    from .corroborate import same_story, search_google_news
    try:
        found = search_google_news({"title": s["title"], "summary": s.get("summary", ""), "lang": s.get("lang", "en")}, cfg)
    except Exception as e:  # noqa: BLE001
        log.info("Second-source search failed: %s", e)
        return refs
    have = {_src_key(r.get("source", "")) for r in refs}
    lead = {"title": s["title"], "lang": s.get("lang"), "sport": s.get("sport")}
    for f in found:
        k = _src_key(f.get("source", ""))
        if k not in have and same_story(lead, {"title": f["title"], "lang": s.get("lang")}, title_only=True):
            refs = refs + [{"source": f["source"], "link": f["link"], "title": f["title"]}]
            have.add(k)
    return refs


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
    revs = [n for n in numbers if isinstance(n, dict)]
    numbers = [n for n in numbers if not isinstance(n, dict)]
    revised = [b for b in (revise_draft(cfg, r) for r in revs) if b]
    if revs and not numbers:
        return revised
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
        refs = usable_refs(s)
        if len(refs) < 2:
            refs = _more_refs(cfg, s, refs)
        if len(refs) < 2:
            log.warning("Talking point %s skipped: fewer than 2 outlets report this exact story: %s", n, s["title"][:80])
            _notify(f"⚠️ Not written (only 1 outlet reports this exact story): {s['title']}")
            continue
        s = dict(s, refs=refs, outlets=len(refs))
        if s["key"] in set(data.get("written", [])) or any(a.get("trending_key") == s["key"] for a in load_articles()):
            log.info("Talking point %s already written: %s", n, s["title"][:80])
            continue
        log.info("Writing explainer %s: %s", n, s["title"])
        try:
            art = write_article(cfg, "news", _context(s), date)
        except Exception as e:  # noqa: BLE001
            log.error("Explainer %s failed: %s", n, e)
            continue
        art["format"] = "explainer"
        art["region"] = "cambodia" if s.get("kun_khmer") else classify(f"{s['title']} {s.get('summary', '')}", s.get("lang", "en"))
        new.append(art)
        art["trending_key"] = s["key"]          # remembered in the story itself, not in trending.json
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
    # The radar job also saves data/trending.json; writing it here too made the two jobs' saves clash on
    # 10 Nov 2026 (the first explainer reached Telegram but was never saved). This job only saves stories.
    save_articles(merge_articles(new, load_articles()))
    kept = [a for a in new if a["status"] != "rejected"]
    if kept:
        send_for_review(cfg, kept)
    build_site(cfg)
    log.info("Explainers written: %d (%d kept for review)", len(new), len(kept))
    return new
