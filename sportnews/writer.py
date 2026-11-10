"""Writer: English story in the author's voice (with web research), then native adaptation to Chinese and Russian."""
from __future__ import annotations

import json
import re

from . import llm
from .common import MEMOS, VOICE, log, now_iso, read_text, short_hash, slugify

LANG_NAMES = {"en": "English", "zh": "Chinese", "ru": "Russian"}

WRITE_SYSTEM = """You are a professional sports journalist writing for "{site}", a world-sport news site edited by {author}.
{voice_rules}

ACCURACY RULES (most important):
- Use only facts from the SOURCE MATERIAL or your web search results. Never invent quotes, scores, dates,
  transfer fees, ages or statistics. Do not copy sentences from sources: write original prose.
- Add real value the sources don't have: context, history, comparison, what it means for fans — not a rewording.
- Direct quotes from people must be short, exact and attributed (e.g. "…," he told BBC Sport).
- If something is unclear or sources disagree, say so or leave it out, and list it in "facts_to_verify".
- No betting advice, no gossip about private life, health or relationships.

SOURCE RULES:
- News must rest on at least two sources, one of them a major or official outlet (BBC, Reuters, AP, ESPN,
  the Guardian, FIFA/UEFA/AFC, the club, league or federation). Never rely only on blogs or social media.
- Use the most recent reports. Search for later developments before writing; if the story has moved on
  (new score, new statement, correction), report the latest position and say when it changed.
- Write exact dates only when a source gives them. Avoid "today"/"yesterday": use the weekday or the date.
- For deaths, injuries or legal matters, report only what is officially confirmed, neutrally, without tributes
  or moral lessons ("Rest in peace", "there is a lesson for young athletes").
- No clickbait or sensational words in headlines; the headline must match what the story proves.

<style_profile>
{style}
</style_profile>

<editor_background>
{memo}
</editor_background>
(Background on the editor's interests. Use it only to choose angles. Never quote it as personal experience
unless the TASK explicitly includes an editor's memo for this story.)

OUTPUT: one JSON object inside <article_json> ... </article_json> tags, nothing after it:
{{"headline": str, "subheadline": str, "body_markdown": str, "social_post": str, "sport": str,
  "tags": [str], "athletes": [str], "image_subjects": [str], "facts_to_verify": [str],
  "sources_used": [{{"title": str, "url": str}}]}}
- image_subjects: 2-4 exact English Wikipedia article titles for photos — the main people first, then teams,
  venues or events (e.g. "Yao Ming", "Houston Rockets", "Toyota Center").
- body_markdown: {words} words, short paragraphs, up to 3 "##" subheadings written for THIS story
  (never generic headings like "My view", "Why this matters to me", "A view from ...").
- social_post: 50-100 words for Telegram/Facebook, 2-4 hashtags, ends inviting readers to comment.
"""

VOICE_RULES = {
    "journalist": """STYLE: sports journalism, third person.
- Lead with the news: who, what, when, where, the result. Then context, key numbers, history and what comes next.
- Analysis is welcome but must rest on facts and be phrased neutrally ("The result leaves...", "It was the first time...").
- Do NOT write in the first person (no "I", "my", "we", "us") and do NOT mention where the writer lives or watches.
- Never invent personal experiences, feelings, memories or anecdotes for anyone.
- Exception: if the TASK contains an editor's memo with a real personal experience for this story, you may add ONE
  short final paragraph headed "## Editor's note" that uses only what the memo says.
- Vary openings and structure from story to story; avoid clichés ("end of an era", "rewrote the record books",
  "proved the doubters wrong") unless genuinely apt.
The STYLE PROFILE below guides rhythm and tone only (clear, warm, human) — not first-person voice.""",
    "personal": """STYLE: personal column in the editor's own voice, as described in the STYLE PROFILE.
Use first person only for experiences and opinions the editor actually stated in the memos. Never invent
personal experiences, locations or anecdotes. Vary openings; do not repeat the same personal framing every day.""",
}

TASKS = {
    "news": """TASK: Write today's NEWS story ({date}). Report what happened accurately (who, what, when, where,
result), then explain why it matters with context and analysis. Use web search to confirm the latest
details and find context. Prefer official and major outlets.""",
    "explainer": """TASK: Write a short EXPLAINER ({date}) about a sport story that many outlets are covering right
now: "{title}". Readers have seen the headline; tell them WHY it matters. Use exactly these ## headings:
## What happened
## Why it is being talked about
## Key facts and numbers
## What happens next
Report only what the SOURCE MATERIAL (and web search, if available) confirms. Check the date of every fact: never
mix last year's list, season or result with this year's. If outlets disagree, say so plainly or leave the point out.
Neutral and factual: no opinion, no speculation presented as fact, no politics.""",
    "history": """TASK: Write today's "ON THIS DAY IN SPORT" story ({date}). Search for a famous, well-documented
world sport moment that happened on this calendar date ({month_day}) in an earlier year — prefer moments that
Chinese and Russian readers also care about. Tell it as a story: the era, the people, the drama, its legacy today.""",
    "history_event": """TASK: Write today's "ON THIS DAY IN SPORT" story ({date}) about this event, which happened
on this calendar date ({month_day}) in {event_year}: "{event_text}".
The date and the event are FIXED by the source (Wikipedia's dated 'On this day' list): do not move it to another
date, place or year, and do not switch to a different event. Use the SOURCE MATERIAL as your fact base and web
search (if available) only to confirm details. If a detail is not in the sources, leave it out.
Tell it as a story: the era, the people, the drama, its legacy today. Report tragedies or controversies, if any,
factually and respectfully.""",
    "athlete_story": """TASK: Write the LIFE STORY of {athlete} ({sport}). Research childhood and background, how
they started, key turning points, struggles, greatest achievements and life today. Write it as a human story,
not a list of results. Notes (verify, do not copy blindly): {notes}
Use the SOURCE MATERIAL (the athlete's Wikipedia article) as your fact base. Only include facts you find there or
in web search results. Never invent childhood scenes, family details, quotes or feelings.""",
}
WORDS = {"explainer": "300-450", "news": "350-550", "history": "550-850", "history_event": "550-850", "athlete_story": "700-1000"}

LOCALIZE_SYSTEM = """You are a team of senior sport editors who are native speakers of {targets}.
Adapt the English article into each language so it reads as if originally written by a native sport columnist —
natural idioms and rhythm, not word-for-word translation — while keeping the author's first-person voice.

Rules:
- Keep every fact, number, date and quote meaning exactly the same. Add nothing, remove nothing factual.
- Use the standard names readers know: e.g. Chinese 梅西 / 姚明 / 曼联, Russian Месси / Яо Мин / «Манчестер Юнайтед».
  For less-known names, transliterate in the standard way and add the Latin spelling in brackets on first mention.
- Chinese: {script} Chinese characters, Chinese punctuation (，。！？「」or“”).
- Russian: proper typography (« », —), sports terminology used by Russian sports media.
- Adapt hashtags to each language.

OUTPUT: one JSON object inside <article_json> ... </article_json>:
{{{schema}}}
where each value is {{"headline": str, "subheadline": str, "body_markdown": str, "social_post": str}}.
"""


def extract_json(text: str) -> dict:
    m = re.search(r"<article_json>\s*(\{.*\})\s*</article_json>", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip())
    return json.loads(raw)


def _ask_json(cfg, system, prompt, search):
    text, sources, model = llm.generate(cfg, system, prompt, search)
    try:
        return extract_json(text), sources, model
    except (json.JSONDecodeError, ValueError):
        log.warning("Model returned invalid JSON; asking again without search")
        text, s2, model = llm.generate(cfg, system, prompt + "\n\nReturn ONLY the valid JSON in the tags.", False)
        return extract_json(text), sources + s2, model


def split_memo(memo: str) -> tuple[str, str]:
    """(general part, assignment part). Everything from the first 'Must cover:' line on belongs to assignments."""
    lines = (memo or "").splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("must cover:"):
            return "\n".join(lines[:i]).strip(), "\n".join(lines[i:]).strip()
    return (memo or "").strip(), ""


def _write_prompt(kind: str, ctx: dict, date: str) -> str:
    task = "history_event" if kind == "history" and ctx.get("event_text") else ctx.get("task") or kind
    fmt = dict(ctx.get("fmt", {}))
    if task == "explainer":
        fmt.setdefault("title", ctx.get("title", ""))
    if task == "history_event":
        fmt.update(event_year=ctx["event_year"], event_text=ctx["event_text"])
    parts = [TASKS[task].format(date=date, month_day=date[5:], **fmt)]
    daily = split_memo(read_text(MEMOS / f"{date}.md"))
    memo_part = ctx.get("assignment_memo") if ctx.get("assignment_memo") else daily[0]
    if memo_part:
        parts.append(f"<todays_memo_from_author>\n{memo_part}\n</todays_memo_from_author>\n"
                     "The memo is background on the author's mood and views today. Stay strictly on the TASK topic "
                     "above; never switch the story to a different subject mentioned in the memo.")
    if ctx.get("region_focus") and ctx["region_focus"] != "global":
        from .regions import LABEL
        parts.append(f"REGIONAL FOCUS: this site balances coverage across regions and is short of stories from "
                     f"{LABEL[ctx['region_focus']]}. Choose a well-documented moment from {LABEL[ctx['region_focus']]} "
                     "sport (its athletes, teams or events) if one fits this calendar date; otherwise any famous moment.")
    if ctx.get("athlete_memo"):
        parts.append(f"<author_memo_about_this_athlete>\n{ctx['athlete_memo']}\n</author_memo_about_this_athlete>")
    if ctx.get("sources"):
        parts.append("<source_material>\n" + ctx["sources"] + "\n</source_material>")
    return "\n\n".join(parts)


def _mock(kind, ctx, date, langs):
    title = ctx.get("title") or ctx.get("fmt", {}).get("athlete") or "On this day"
    body = (f"*MOCK DRAFT — no AI key set.*\n\nThis is where the {kind.replace('_', ' ')} story about "
            f"**{title}** will be written in your voice.\n\n## Why it matters\n\nSource material: "
            f"{len(ctx.get('sources', ''))} characters.")
    en = {"headline": f"[Mock] {title}", "subheadline": "Sample draft", "body_markdown": body,
          "social_post": f"{title} #sport", "sport": ctx.get("sport") or "", "tags": [kind], "athletes": [],
          "facts_to_verify": ["Mock article — not real"], "sources_used": ctx.get("source_links", [])}
    loc = {"zh": {"headline": f"[示例] {title}", "subheadline": "示例稿件", "body_markdown": "*示例稿件。*\n\n" + body,
                  "social_post": f"{title} #体育"},
           "ru": {"headline": f"[Пример] {title}", "subheadline": "Черновик", "body_markdown": "*Черновик.*\n\n" + body,
                  "social_post": f"{title} #спорт"}}
    return en, [], {k: v for k, v in loc.items() if k in langs}, "mock"


def first_person_count(text: str) -> int:
    body = re.sub(r'"[^"]*"|“[^”]*”', "", text or "")          # ignore quotes from other people
    # case-aware: "I" but not "i"; "us"/"Us" but not "US" (United States)
    return len(re.findall(r"\bI\b|\b(?:[Mm]y|[Mm]e|[Ww]e|[Oo]ur)\b|\b(?:us|Us)\b", body))


def localize(cfg: dict, en: dict) -> dict:
    """Adapt an English article into the other languages. Returns {lang: {...}} (empty on failure/mock)."""
    langs = cfg["languages"].get("others", ["zh", "ru"])
    if not langs or llm.provider(cfg) == "mock":
        return {}
    script = "Simplified" if cfg["languages"].get("chinese_script", "simplified") == "simplified" else "Traditional"
    schema = ", ".join(f'"{l}": {{...}}' for l in langs)
    lsys = LOCALIZE_SYSTEM.format(targets=" and ".join(LANG_NAMES[l] for l in langs), script=script, schema=schema)
    src = json.dumps({k: en.get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")}, ensure_ascii=False)
    log.info("Adapting to %s ...", ", ".join(langs))
    try:
        loc, _, _ = _ask_json(cfg, lsys, f"<english_article>\n{src}\n</english_article>", search=False)
        return loc
    except Exception as e:  # noqa: BLE001
        log.error("Localization failed (%s) — article kept in English only", e)
        return {}


def write_article(cfg: dict, kind: str, ctx: dict, date: str) -> dict:
    site = cfg["site"]
    langs = cfg["languages"].get("others", ["zh", "ru"])
    if llm.provider(cfg) == "mock":
        log.warning("No AI key (or SPORTNEWS_MOCK=1): writing mock %s article", kind)
        en, cites, loc, model = _mock(kind, ctx, date, langs)
    else:
        system = WRITE_SYSTEM.format(author=site["author"], site=site["name"], words=WORDS[ctx.get("task") or kind],
                                     voice_rules=VOICE_RULES.get(cfg.get("writing", {}).get("style", "journalist"), VOICE_RULES["journalist"]),
                                     style=read_text(VOICE / "style_profile.md"), memo=read_text(MEMOS / "general.md"))
        log.info("Writing %s (EN) ...", kind)
        en, cites, model = _ask_json(cfg, system, _write_prompt(kind, ctx, date), search=True)
        # Originality: rewrite once if the story repeats the source text too closely
        from .originality import check, too_close
        orig = check(en.get("body_markdown", ""), ctx.get("sources", ""))
        if too_close(orig):
            log.warning("Story too close to its source (%.0f%% overlap, %d-word run) — rewriting", orig["overlap"] * 100, orig["longest"])
            fix = (_write_prompt(kind, ctx, date) + "\n\nIMPORTANT: your previous draft copied these phrases from the source. "
                   "Rewrite the whole story in completely your own words, keeping the facts:\n- " + "\n- ".join(orig["phrases"]))
            try:
                en2, cites2, model = _ask_json(cfg, system, fix, search=False)
                orig2 = check(en2.get("body_markdown", ""), ctx.get("sources", ""))
                if orig2["overlap"] <= orig["overlap"]:
                    en, orig = en2, orig2
                    cites = cites + cites2
            except Exception as e:  # noqa: BLE001
                log.warning("Rewrite failed: %s", e)
        # Length: free models often stop short. Ask once to expand from the SAME sources (no new facts).
        need = {"news": 300, "history": 450, "athlete_story": 550}.get(kind, 300)
        words = len(re.findall(r"\w+", en.get("body_markdown", "")))
        if words < need:
            log.warning("Draft is only %d words (want %d+) — asking once to expand from the sources", words, need)
            grow = (_write_prompt(kind, ctx, date) + f"\n\nYour previous draft was only {words} words:\n<draft>\n"
                    + en.get("body_markdown", "") + f"\n</draft>\nRewrite it to {WORDS.get(kind, '400-600')} words. "
                    "Add depth ONLY from the SOURCE MATERIAL and verified context: background, key numbers, earlier "
                    "meetings or records, what happens next. Never pad with opinion, clichés or invented details. "
                    "If the sources truly hold too little, keep it short; it will then be dropped.")
            try:
                en2, cites2, model = _ask_json(cfg, system, grow, search=False)
                w2 = len(re.findall(r"\w+", en2.get("body_markdown", "")))
                if w2 > words and en2.get("headline"):
                    log.info("Expanded draft: %d -> %d words", words, w2)
                    en, cites = en2, cites + cites2
                    orig = check(en.get("body_markdown", ""), ctx.get("sources", ""))
            except Exception as e:  # noqa: BLE001
                log.warning("Expansion failed: %s", e)
        if too_close(orig):
            en.setdefault("facts_to_verify", []).insert(
                0, f"ORIGINALITY: {orig['overlap']:.0%} of the text repeats the source word-for-word — rewrite before publishing")
        if cfg.get("writing", {}).get("style", "journalist") == "journalist":
            fp = first_person_count(en.get("body_markdown", ""))
            if fp >= 2 and "editor's note" not in en.get("body_markdown", "").lower():
                en.setdefault("facts_to_verify", []).insert(
                    0, f"STYLE: {fp} first-person words found ('I', 'my', 'we'). Remove personal lines you did not write yourself")
        loc = localize(cfg, en)
        if not cites and not ctx.get("source_links"):
            en.setdefault("facts_to_verify", []).insert(
                0, "NO SOURCES: written from AI memory without web search or source text. Do not publish unverified")

    sources, seen = [], set()
    for s in en.get("sources_used", []) + cites + ctx.get("source_links", []):
        if s.get("url") and s["url"] not in seen:
            seen.add(s["url"])
            sources.append({"title": s.get("title") or s["url"], "url": s["url"]})
    article = {
        "id": f"{date}-{kind[:4]}-{short_hash(en.get('headline', '') + now_iso())[:6]}",
        "slug": slugify(en.get("headline") or ctx.get("title", kind)),
        "date": date, "created": now_iso(cfg), "type": kind, "status": "draft", "model": model,
        "sport": en.get("sport") or ctx.get("sport") or "",
        "tags": en.get("tags", []), "athletes": en.get("athletes", []),
        "image_subjects": en.get("image_subjects", []),
        "facts_to_verify": en.get("facts_to_verify", []), "sources": sources, "published_to": [],
        "originality": locals().get("orig"),
        "grounded": bool(locals().get("cites")) or bool(ctx.get("source_links")),
        "en": {k: en.get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")},
    }
    for l in langs:
        if isinstance(loc.get(l), dict) and loc[l].get("headline"):
            article[l] = {k: loc[l].get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")}
    return article


REVISE_SYSTEM = """You are the senior sport editor of {site}. Revise the draft below using the EDITOR'S NOTES and any
attached screenshots (they show facts from a source the editor checked).
Rules:
- Add or correct exactly the facts the editor gives (dates, places, teams, numbers). Put them where they belong.
- If a note contradicts the draft, the editor's note wins; remove the wrong statement.
- Keep everything else: structure, ## headings, neutral third-person style, length within about 20%.
- Never invent facts that are neither in the draft, the notes nor the screenshots.
OUTPUT: one JSON object inside <article_json> ... </article_json> with keys
"headline", "subheadline", "body_markdown", "social_post", "facts_added" (list of short strings: what you changed)."""


def revise_article(cfg: dict, a: dict, notes: str, images=None) -> dict:
    """Return a revised copy of story `a` following the editor's notes (+ screenshots). Translations are redone."""
    en = a.get("en") or {}
    if llm.provider(cfg) == "mock":
        new_en = dict(en, body_markdown=en.get("body_markdown", "") + "\n\n" + notes)
        changes = [notes]
    else:
        prompt = ("<draft>\n" + json.dumps({k: en.get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")},
                                           ensure_ascii=False) + "\n</draft>\n\n<editors_notes>\n" + (notes or "(see screenshots)")
                  + "\n</editors_notes>")
        text, _src, _m = llm.generate(cfg, REVISE_SYSTEM.format(site=cfg["site"]["name"]), prompt, False, images)
        out = extract_json(text)
        new_en = {k: out.get(k) or en.get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")}
        changes = [str(x) for x in out.get("facts_added") or []]
    b = dict(a)
    b["en"] = new_en
    loc = localize(cfg, new_en)
    others = cfg["languages"].get("others", ["zh", "ru"])
    for l in others:
        if isinstance(loc.get(l), dict) and loc[l].get("headline"):
            b[l] = {k: loc[l].get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")}
    b["revisions"] = (a.get("revisions") or []) + [{"at": now_iso(cfg), "notes": notes[:1000], "changes": changes[:10],
                                                   "screenshots": len(images or [])}]
    b["updated_at"] = now_iso(cfg)
    if llm.provider(cfg) == "mock" or all(isinstance(loc.get(l), dict) and loc[l].get("headline") for l in others):
        b["translated_at"] = b["updated_at"]      # otherwise the old ZH/RU text stays hidden until re-translated
    return b
