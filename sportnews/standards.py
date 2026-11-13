"""Editorial standards check: ethics, professionalism and up-to-date sources.

Every story is checked automatically
  * when it is written or imported (problems are listed in the draft you review on Telegram/email),
  * again before it is published (stories with a BLOCK problem are not published unless you choose
    "publish-anyway" in the Publish workflow),
  * every week for all published stories, including whether every source link still opens
    (report: data/audit.md, workflow "Weekly standards audit").

Levels:  BLOCK = must be fixed before publishing · WARN = check by hand · INFO = note only.
The rules live in config.yaml under `standards:` so you can change them without touching code.
"""
from __future__ import annotations

import re
import urllib.request
from datetime import date as Date

from .common import log

# ------------------------------------------------------------------ word lists (English master text)
BETTING = re.compile(r"\b(betting tips?|odds (?:of|at) \d|bookmakers?|accumulator|place (?:a|your) bets?|"
                     r"sure bet|tipster|parlay|bet365|1xbet|stake (?:on|your))\b", re.I)
PRIVATE = re.compile(r"\b(divorce|girlfriend|boyfriend|affair|pregnan\w*|rehab|depression|diagnos\w+|"
                     r"rumou?red (?:to be )?dating|sexual\w*|arrest\w*|police)\b", re.I)
OPINION = [  # phrases that turn news into a personal column or a sermon
    r"\bwatching from\b", r"\bhere in (?:cambodia|phnom penh)\b", r"\bfrom phnom penh\b",
    r"\brest in peace\b", r"\bRIP\b", r"\bsoul of the game\b", r"\bcorporate machine\b",
    r"\bthere is a lesson\b", r"\bthe lesson (?:here|for)\b", r"\bwe (?:all )?should\b",
    r"\bbelongs to the people\b", r"\bthe beauty of this game\b", r"\bmy view\b", r"\bwhy (?:this|it) matters to me\b",
]
CLICKBAIT = re.compile(r"(you won'?t believe|shocking|jaw[- ]dropping|insane|mind[- ]blowing|what happened next|"
                       r"!!|\?\!|\bOMG\b)", re.I)
CLICHES = [r"end of an era", r"rewrote the (?:record|history) books?", r"proved the doubters wrong",
           r"took the world by storm", r"needs no introduction"]
FILLER = [r"high-stakes (?:encounter|clash|affair)", r"tactical discipline", r"vital stepping stone",
          r"(?:observers|fans|coaches)(?: and \w+)? will be watching closely", r"dictate the trajectory",
          r"underscores? the importance", r"serves? as (?:a|an) (?:essential|vital|crucial) (?:platform|stepping stone)",
          r"remains to be seen", r"only time will tell", r"in the fray"]
VAGUE_TIME = re.compile(r"(?:^|[.!?]\s+)(Today|Yesterday|Tonight|This morning)\b,?", re.M)
DEATH_DATE = re.compile(r"\b(?:on|On) (?:\d{1,2} \w+|\w+ \d{1,2}),? \d{4}[^.]{0,80}\b(died|passed away|death)\b"
                        r"|\b(died|passed away)\b[^.]{0,40}\bon (?:\d{1,2} \w+|\w+ \d{1,2}),? \d{4}", re.I)
CLAIMS = re.compile(r"\b(debut|first[- ]ever|for the first time|first (?:man|woman|player|team|boxer|athlete) to|"
                    r"world record|all-time record|unbeaten|undefeated|oldest|youngest)\b", re.I)
URL_DATE = re.compile(r"/(20\d\d)[/-](\d{1,2})[/-](\d{1,2})(?:/|-|$)|/(20\d\d)/([a-z]{3})/(\d{1,2})/"
                      r"|/(20\d\d)(\d\d)(\d\d)/", re.I)      # last form: ria.ru/20261111/...
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
WEAK_SOURCES = ("blogspot.", "wordpress.com", "medium.com", "nigfooty.", "reddit.com", "facebook.com",
                "x.com/", "twitter.com", "tiktok.com", "youtube.com")
STRONG_SOURCES = ("bbc.", "reuters.", "apnews.", "theguardian.", "skysports.", "espn.", "aljazeera.", "fifa.com",
                  "uefa.com", "olympics.com", "afc.com", "the-afc.com", "nba.com", "formula1.com", "nytimes.",
                  "xinhuanet.", "sina.", "sport-express.", "championat.", "tass.", "kyodonews.", "nikkansports.",
                  "sponichi.", "atptour.", "britannica.com", "history.com", "boxrec.com", "olympedia.org", "thestar.com.my", "straitstimes.", "bangkokpost.", "khmertimeskh.", "phnompenhpost.", "vnexpress.", "insideworldfootball.", "the-afc.com", "aseanfootball.", "wtatennis.", "icc-cricket.", "worldathletics.", "fiba.basketball")

DEFAULTS = {
    "enabled": True,
    "block_on_publish": True,       # BLOCK problems stop the Publish workflow (use "publish-anyway" to override)
    "min_pictures": 2,              # each story needs at least this many relevant pictures (free licence or own work)
    "min_pictures_from": "2026-11-14",  # stories from this date with fewer pictures cannot be published (BLOCK)
    "max_cover_photo_age_years": 3, # news cover photo older than this -> warning: use the latest free photo
    "min_sources_news": 2,          # news needs at least this many sources (one must be a major outlet)
    "max_source_age_days_news": 3,  # a news story's sources should be this fresh (judged from dates in links)
    "max_story_age_days_news": 4,   # news drafts older than this should be updated or rejected before publishing
    "min_words": {"news": 250, "history": 400, "athlete_story": 500},
    "max_headline_chars": 110,
    "check_links": True,            # weekly audit opens every source link
    "auto_reject": True,            # AI drafts with BLOCK problems, too few words or sources never reach review
}


def rules(cfg: dict) -> dict:
    r = dict(DEFAULTS)
    r.update((cfg or {}).get("standards") or {})
    return r


def _strip_quotes(text: str) -> str:
    return re.sub(r'"[^"\n]*"|“[^”]*”|«[^»]*»', "", text or "")


def _url_date(url: str) -> Date | None:
    m = URL_DATE.search(url or "")
    if not m:
        return None
    try:
        if m.group(1):
            return Date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m.group(7):
            return Date(int(m.group(7)), int(m.group(8)), int(m.group(9)))
        return Date(int(m.group(4)), MONTHS[m.group(5).lower()], int(m.group(6)))
    except (ValueError, KeyError):
        return None


def _d(s: str) -> Date | None:
    try:
        return Date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _issue(level: str, area: str, msg: str) -> dict:
    return {"level": level, "area": area, "msg": msg}


def check_article(cfg: dict, a: dict, today: str | None = None) -> list[dict]:
    """All standards problems found in one story (no network calls)."""
    r = rules(cfg)
    if not r.get("enabled", True):
        return []
    from .writer import first_person_count
    out: list[dict] = []
    en = a.get("en") or {}
    head, sub, body, social = (en.get(k, "") or "" for k in ("headline", "subheadline", "body_markdown", "social_post"))
    text = "\n".join([head, sub, body])
    plain = _strip_quotes(text)
    kind = a.get("type", "news")

    # ---------------- PHOTOS: at least 2 relevant pictures per story (editor's rule, 13 Nov 2026)
    n_img = len([i for i in a.get("images") or [] if i.get("url")])
    if "images" in a and n_img < r.get("min_pictures", 2):
        # A rule from 14 Nov 2026: new stories cannot be published with fewer pictures (older ones only get a warning).
        level = "BLOCK" if str(a.get("date", "")) >= r.get("min_pictures_from", "2026-11-14") else "WARN"
        out.append(_issue(level, "photos", f"Only {n_img} picture(s). Rule: at least {r.get('min_pictures', 2)} relevant "
                                           "pictures (people in the story, venue, match card). Add free photos in photos.yaml, "
                                           "or use publish-anyway if no free photo exists"))
    # ---------------- PHOTOS: use the most recent free photo available (editor's rule, 10 Nov 2026)
    cover = (a.get("images") or [{}])[0]
    yr, story_yr = cover.get("year"), int(str(a.get("date") or "0000")[:4] or 0)
    if kind == "news" and yr and story_yr and story_yr - yr > r.get("max_cover_photo_age_years", 3):
        out.append(_issue("WARN", "photos", f"Cover photo is from {yr}. Use the most recent free photo available "
                                            "(for example the latest title celebration), even if it is not from this event"))

    # ---------------- ETHICS
    if BETTING.search(text + " " + social):
        out.append(_issue("BLOCK", "ethics", "Betting / gambling content: '%s'" % BETTING.search(text + " " + social).group(0)))
    style = (cfg.get("writing") or {}).get("style", "journalist")
    fp = first_person_count(body) + first_person_count(re.sub(r"(?i)let'?s|tell us|let us know|join us|follow us", "", social))
    if style == "journalist" and fp >= 1 and "editor's note" not in body.lower():
        out.append(_issue("BLOCK" if fp >= 2 else "WARN", "ethics",
                          f"{fp} first-person word(s) (I/my/we/us) outside quotes. Journalism style is third person; "
                          "never publish personal lines you did not write yourself"))
    for pat in OPINION:
        m = re.search(pat, plain, re.I)
        if m:
            out.append(_issue("WARN", "ethics", f"Opinion / personal framing: '{m.group(0)}'. Report facts neutrally"))
    m = PRIVATE.search(plain)
    if m:
        out.append(_issue("WARN", "ethics", f"Private-life or legal topic ('{m.group(0)}'). Only include it if it is "
                                            "the news itself, confirmed by a major outlet, and stated neutrally"))
    m = DEATH_DATE.search(body)
    if m:
        out.append(_issue("WARN", "ethics", "Exact date of a death is stated. Make sure a source gives that exact date; "
                                            "otherwise write 'has died, it was announced on ...'"))

    m = CLAIMS.search(plain)
    if m:
        out.append(_issue("INFO", "facts", f"Strong claim '{m.group(0)}': confirm it in a source before publishing"))

    if a.get("grounded") is False and a.get("model") not in ("editor", "mock"):
        out.append(_issue("BLOCK", "facts", "Written from AI memory without web search or source text: facts "
                                            "(dates, places, scores) are not checked"))

    # ---------------- PROFESSIONALISM
    if not head:
        out.append(_issue("BLOCK", "professional", "Missing headline"))
    if len(head) > r["max_headline_chars"]:
        out.append(_issue("WARN", "professional", f"Headline is {len(head)} characters (max {r['max_headline_chars']})"))
    if head and (head.isupper() or CLICKBAIT.search(head)):
        out.append(_issue("BLOCK", "professional", "Clickbait or all-caps headline (Google and AdSense penalise this)"))
    if CLICKBAIT.search(body):
        out.append(_issue("WARN", "professional", f"Sensational wording in text: '{CLICKBAIT.search(body).group(0)}'"))
    if not sub:
        out.append(_issue("WARN", "professional", "Missing subheadline (summary line)"))
    words = len(re.findall(r"\w+", body))
    need = r["min_words"].get(kind, 250)
    if words < need:
        out.append(_issue("WARN", "professional", f"Only {words} words (minimum {need} for {kind}). Thin content hurts AdSense approval"))
    for c in CLICHES:
        if re.search(c, body, re.I):
            out.append(_issue("INFO", "professional", f"Cliché: '{c}'"))
    fill = [m.group(0) for f in FILLER for m in [re.search(f, body, re.I)] if m]
    if fill:
        out.append(_issue("WARN", "professional", "Filler without facts: '" + "', '".join(fill[:4])
                                                  + "'. Cut these lines or replace them with facts from the sources"))
    if kind == "news":
        m = VAGUE_TIME.search(body)
        if m:
            out.append(_issue("WARN", "professional", f"'{m.group(1)}' becomes wrong after publishing. Use the day or date"))
    orig = a.get("originality") or {}
    if orig.get("overlap", 0) > 0.15:
        out.append(_issue("BLOCK", "professional", f"{orig['overlap']:.0%} copied word-for-word from the source. Rewrite"))
    for f in a.get("facts_to_verify") or []:
        if str(f).upper().startswith(("ORIGINALITY", "STYLE")):
            continue
        out.append(_issue("INFO", "facts", f"Verify: {f}"))

    # ---------------- SOURCES (up to date and credible)
    srcs = [s for s in a.get("sources") or [] if isinstance(s, dict) and s.get("url")]
    urls = [s["url"].lower() for s in srcs]
    if not srcs:
        out.append(_issue("BLOCK", "sources", "No sources listed. Every story must link to where its facts come from"))
    else:
        strong = [u for u in urls if any(k in u for k in STRONG_SOURCES)]
        weak = [u for u in urls if any(k in u for k in WEAK_SOURCES)]
        if kind == "news" and len(srcs) < r["min_sources_news"]:
            out.append(_issue("WARN", "sources", f"Only {len(srcs)} source(s). News needs at least {r['min_sources_news']}"))
        if not strong and not (kind != "news" and len(srcs) >= 2):
            out.append(_issue("WARN", "sources", "No major or official outlet among the sources (e.g. BBC, Reuters, AP, "
                                                 "ESPN, the Guardian, FIFA/UEFA/AFC, the club or federation)"))
        import urllib.parse as _up
        home = [u for u in urls if _up.urlparse(u).path.strip("/") == ""]
        if home and len(home) == len(urls):
            out.append(_issue("BLOCK", "sources", "Sources are only website homepages, not articles. Link the exact "
                                                  "report or record page that proves the facts"))
        elif home:
            out.append(_issue("WARN", "sources", f"{len(home)} source(s) are homepages, not articles: " + ", ".join(home[:3])))
        if weak and len(weak) == len(urls):
            out.append(_issue("BLOCK", "sources", "All sources are blogs or social media. Add a major or official source"))
        elif weak:
            out.append(_issue("INFO", "sources", f"{len(weak)} weaker source(s) (blog/social). Do not rely on them alone"))
    story_day = _d(a.get("date", "")) or _d(today or "")
    now = _d(today or "") or Date.today()
    if kind == "news" and story_day:
        dated = [d for d in (_url_date(u) for u in urls) if d]
        if dated:
            newest = max(dated)
            lag = (story_day - newest).days
            if lag > r["max_source_age_days_news"]:
                out.append(_issue("WARN", "sources", f"Newest source is {lag} days older than the story ({newest}). "
                                                     "Check for later developments before publishing"))
        if a.get("status") == "draft" and (now - story_day).days > r["max_story_age_days_news"]:
            out.append(_issue("WARN", "sources", f"Draft is {(now - story_day).days} days old. Update the facts or reject it"))

    # ---------------- TRANSLATIONS kept in step with English
    if a.get("updated_at"):
        for lang in (cfg.get("languages") or {}).get("others", ["zh", "ru"]):
            ts = (a.get("lang_updated") or {}).get(lang) or a.get("translated_at") or ""
            if ts < a["updated_at"]:
                out.append(_issue("WARN", "translation", f"{lang.upper()} version is older than the English correction (hidden on site)"))
    for lang in (cfg.get("languages") or {}).get("others", ["zh", "ru"]):
        t = a.get(lang) or {}
        if t and re.search(r"\b(I|my|we)\b", t.get("body_markdown", "")):
            out.append(_issue("INFO", "translation", f"{lang.upper()} text contains English first-person words. Check it"))
    return out


def auto_reject_reasons(cfg: dict, a: dict) -> list[str]:
    """Why an AI draft should never reach the editor (empty list = keep it for review).
    Editor-written stories (inbox) are never auto-rejected."""
    r = rules(cfg)
    if not r.get("auto_reject", True) or a.get("model") in ("editor", "mock") or a.get("origin"):
        return []
    issues = a.get("standards") or check_article(cfg, a)
    reasons = [i["msg"] for i in issues if i["level"] == "BLOCK" and i["area"] != "photos"]   # photos can be added later
    words = len(re.findall(r"\w+", (a.get("en") or {}).get("body_markdown", "")))
    need = r["min_words"].get(a.get("type", "news"), 250)
    if words < need:
        reasons.append(f"too short ({words} words, minimum {need})")
    if a.get("type") == "news" and len([s for s in a.get("sources") or [] if s.get("url")]) < r["min_sources_news"]:
        reasons.append(f"fewer than {r['min_sources_news']} sources")
    return reasons


def blocking(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["level"] == "BLOCK"]


def summary_lines(issues: list[dict], limit: int = 12) -> list[str]:
    order = {"BLOCK": 0, "WARN": 1, "INFO": 2}
    icon = {"BLOCK": "⛔", "WARN": "⚠️", "INFO": "ℹ️"}
    return [f"{icon[i['level']]} {i['level']} [{i['area']}] {i['msg']}" for i in sorted(issues, key=lambda x: order[x["level"]])][:limit]


def stamp(cfg: dict, articles: list[dict], today: str | None = None) -> None:
    """Store the current check result on each story (shown in review messages and the audit)."""
    for a in articles:
        a["standards"] = check_article(cfg, a, today)


# ------------------------------------------------------------------ weekly audit
def check_link(url: str, timeout: int = 15) -> int | str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BangSportDaily link check)"},
                                 method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def audit(cfg: dict, articles: list[dict], today: str, links: bool | None = None) -> str:
    """Markdown report for every published story (plus drafts waiting). Returns the report text."""
    r = rules(cfg)
    links = r.get("check_links", True) if links is None else links
    pub = [a for a in articles if a.get("status") == "published"]
    drafts = [a for a in articles if a.get("status") == "draft"]
    lines = [f"# Standards audit — {today}", "",
             f"Published stories: {len(pub)} · Drafts waiting: {len(drafts)}", "",
             "Levels: ⛔ BLOCK = fix now · ⚠️ WARN = check by hand · ℹ️ INFO = note", ""]
    totals = {"BLOCK": 0, "WARN": 0, "INFO": 0}
    broken_total = 0
    for a in pub + drafts:
        issues = check_article(cfg, a, today)
        if links:
            for s in a.get("sources") or []:
                if not (isinstance(s, dict) and s.get("url")):
                    continue
                code = check_link(s["url"])
                if code in (404, 410) or isinstance(code, str):
                    issues.append(_issue("WARN", "sources", f"Source link does not open ({code}): {s['url']}"))
                    broken_total += 1
                elif code in (401, 403, 429):
                    issues.append(_issue("INFO", "sources", f"Source blocks automatic checks ({code}), open it by hand: {s['url']}"))
        a["standards"] = issues
        for i in issues:
            totals[i["level"]] += 1
        if not issues:
            continue
        lines += [f"## {a['en'].get('headline', a['id'])}", f"`{a['id']}` · {a.get('status')} · {a.get('date')}", ""]
        lines += [f"- {x}" for x in summary_lines(issues, 30)] + [""]
    from .regions import balance_line, counts
    lines.insert(4, "Regional balance (last 7 days): " + balance_line(cfg, counts(articles, today)))
    lines.insert(4, f"Totals: ⛔ {totals['BLOCK']} · ⚠️ {totals['WARN']} · ℹ️ {totals['INFO']} · broken links: {broken_total}")
    lines.insert(5, "")
    if totals["BLOCK"] == totals["WARN"] == 0:
        lines.append("All stories meet the standards. ✅")
    log.info("Standards audit: %s", totals)
    return "\n".join(lines) + "\n"
