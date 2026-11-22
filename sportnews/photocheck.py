"""Photo check before publishing (editor's request, 21 Nov 2026, after a 19th-century portrait of a Brazilian
doctor appeared as "Martins Júnior" of Svay Rieng, and a photo of Aljamain Sterling appeared as Navajo Stirling).

Two layers, both run automatically on every new draft:
  1. Rules (free): the Wikipedia page the photo came from must match the name we asked for; drawings, engravings,
     very old photos of active athletes and non-sport scenes are flagged.
  2. AI look (Gemini, about US$0.0003 a photo): the model is shown the picture and asked whether it plausibly shows
     the person/place the caption claims, in the right sport and era.

Result per photo: im["check"] = {"verdict": ok | unsure | wrong, "shows": ..., "reason": ..., "flags": [...]}
  wrong  -> BLOCK in the standards check (the story cannot be published until the photo is replaced)
  unsure -> WARN (look at it in data/photo-review.md)
The review page data/photo-review.md shows every photo of every draft (and stories published in the last 3 days)
with its verdict, so the editor can approve all photos in about a minute.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.request

log = logging.getLogger("sportnews")

CHECK_VERSION = 2   # 2: today's date in the prompt (v1 called real 2026 photos 'AI-generated')
OLD_STYLE = re.compile(r"\b(engraving|lithograph|etching|drawing|sketch|painting|illustration|caricature|portrait of dr\.?|"
                       r"\bdr\.\s|daguerreotype|19th[- ]century|18\d\d)\b", re.I)
NON_SPORT = re.compile(r"\b(motorcycle stunt|fireworks?|white house|parliament|ministry|received|meeting with|"
                       r"press conference of the president|wedding|funeral|protest|rally)\b", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def name_mismatch(asked: str, got: str) -> bool:
    """True when the Wikipedia page we got is clearly not the subject we asked for (e.g. asked 'Navajo Stirling',
    got 'Aljamain Sterling'; asked 'Carlos Ulberg', got a page about motorcycle stunts). Accents, brackets and
    word order are ignored; every word of the shorter name must appear in the longer one."""
    a, g = set(_norm(asked).split()), set(_norm(got).split())
    if not a or not g:
        return False
    small, big = (a, g) if len(a) <= len(g) else (g, a)
    from rapidfuzz import fuzz                     # transliteration: Sadulaev / Sadulayev, Nurmagomedov / Nurmagomedow
    return not all(w in big or any(fuzz.ratio(w, x) >= 85 for x in big) for w in small)


def rule_flags(a: dict, im: dict) -> list[str]:
    """Free checks that need no AI. Each flag is a short sentence for the editor."""
    out = []
    asked, got = im.get("asked") or "", im.get("page_title") or im.get("subject") or ""
    if asked and got and name_mismatch(asked, got):
        out.append(f"asked for '{asked}' but the photo comes from the page '{got}'")
    text = " ".join(str(im.get(k) or "") for k in ("description", "page", "subject"))
    text = urllib.request.unquote(text).replace("_", " ")
    if a.get("type") != "history" and OLD_STYLE.search(text):
        out.append("looks like a drawing / old portrait (" + OLD_STYLE.search(text).group(0).strip() + ")")
    if NON_SPORT.search(text):
        out.append("file looks like a non-sport scene (" + NON_SPORT.search(text).group(0) + ")")
    yr, story = im.get("year"), int(str(a.get("date") or "0")[:4] or 0)
    if yr and story and a.get("type") != "history" and yr < 2000:
        out.append(f"photo is from {yr}: too old for a story about current athletes")
    return out


PROMPT = """You check photos for a sports news website before publication. Be strict: a wrong photo of a person is a
serious error, an old but correct photo is acceptable.
Today's date is {today}. Events and photos up to today are real, even if they are later than what you know: never
call a photo fake, AI-generated or "future" because of its date, kit or event. Judge only what you can see.

Story headline: {headline}
Sport / people in the story: {sport}; {people}
The photo is captioned as: "{subject}"
The file's own description: "{description}"
Year of the photo (if known): {year}

Look at the image and answer with JSON only, no other text:
{{"verdict": "ok" | "unsure" | "wrong", "shows": "<what the photo actually shows, max 15 words>", "reason": "<max 25 words>"}}

- "wrong": the image clearly cannot be the captioned subject: a drawing or 19th-century portrait for a modern athlete,
  a non-sport scene (politics, stunts, fireworks) when a person or venue is captioned, a different sport, a different
  kind of place, or a visible name/number that contradicts the caption.
- "unsure": it is a plausible sports photo, but you cannot tell whether it is this specific person or place.
- "ok": it plausibly shows the captioned subject (right sport, era, setting; famous people you recognise; the venue).
Do not guess identities from faces of non-famous people; judge plausibility from sport, kit, era and setting."""


def _image_bytes(im: dict) -> tuple[bytes, str] | None:
    from .common import ROOT
    url = im.get("local_sm") or im.get("local") or im.get("url") or ""
    try:
        if url.startswith("../"):
            p = ROOT / "docs" / url[3:]
            data = p.read_bytes()
        else:
            from .images import _download
            data = _download(url)
    except Exception as e:  # noqa: BLE001
        log.warning("Photo check: could not load %s: %s", url[:100], str(e)[:150])
        return None
    mime = "image/png" if data[:8].startswith(b"\x89PNG") else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg"
    if len(data) > 6_000_000:
        return None
    return data, mime


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    v = str(d.get("verdict", "")).lower().strip()
    if v not in ("ok", "unsure", "wrong"):
        return None
    return {"verdict": v, "shows": str(d.get("shows", ""))[:160], "reason": str(d.get("reason", ""))[:220]}


def ai_look(cfg: dict, a: dict, im: dict) -> dict | None:
    from .llm import generate, provider
    if provider(cfg) != "gemini":
        return None
    img = _image_bytes(im)
    if not img:
        return None
    en = a.get("en") or {}
    from .common import today
    prompt = PROMPT.format(today=today(cfg), headline=en.get("headline", ""), sport=a.get("sport", "") or ", ".join(a.get("tags", [])[:3]),
                           people=", ".join((a.get("athletes") or [])[:6]) or "-", subject=im.get("subject", ""),
                           description=(im.get("description") or "")[:200], year=im.get("year") or "unknown")
    text, _, model = generate(cfg, "Answer with one JSON object only.", prompt, search=False, images=[img])
    out = _parse(text)
    if out:
        out["model"] = model
    return out


def needs_check(im: dict) -> bool:
    if not im.get("url") or im.get("card"):
        return False                                  # our own score card: always correct
    c = im.get("check") or {}
    return c.get("v") != CHECK_VERSION or c.get("key") != _key(im)


def _key(im: dict) -> str:
    from .images import photo_key
    return photo_key(im) + "|" + (im.get("subject") or "")


def check_article(cfg: dict, a: dict, use_ai: bool = True) -> int:
    """Check every photo of one story that was not checked yet. Returns how many photos were checked."""
    n = 0
    for i, im in enumerate(a.get("images") or []):
        if not needs_check(im):
            continue
        flags = rule_flags(a, im)
        res = None
        if im.get("editor"):                          # chosen by the editor in photos.yaml: rules only
            use = False
        else:
            use = use_ai and (cfg.get("photo_check") or {}).get("ai", True)
        if use:
            try:
                res = ai_look(cfg, a, im)
            except Exception as e:  # noqa: BLE001
                log.warning("AI photo check failed for %s photo %d: %s", a.get("id"), i + 1, str(e)[:200])
        verdict = (res or {}).get("verdict") or ("unsure" if flags else "unchecked")
        hard = [f for f in flags if not f.startswith("file looks like a non-sport")]
        if hard and verdict == "ok":
            verdict = "unsure"                        # a wrong name / drawing / very old photo is never waved through
        if any(f.startswith("asked for") for f in flags) and verdict == "unsure" and res:
            verdict = "wrong"                         # wrong page AND the AI cannot confirm it: treat as wrong
        if im.get("editor") and verdict == "unchecked":
            verdict = "ok"
        im["check"] = {"v": CHECK_VERSION, "key": _key(im), "verdict": verdict, "flags": flags,
                       "shows": (res or {}).get("shows", ""), "reason": (res or {}).get("reason", ""),
                       "by": "editor" if im.get("editor") else ("ai" if res else "rules")}
        log.info("Photo check %s #%d %r: %s%s", a.get("id"), i + 1, (im.get("subject") or "")[:40], verdict.upper(),
                 (" — " + "; ".join(flags)) if flags else "")
        n += 1
    return n


def check_many(cfg: dict, articles: list[dict], use_ai: bool = True) -> int:
    n = 0
    for a in articles:
        n += check_article(cfg, a, use_ai)
    return n


# ------------------------------------------------------------------ the one-minute review page
BADGE = {"ok": "🟢 OK", "unsure": "🟠 CHECK", "wrong": "🔴 WRONG", "unchecked": "⚪ not checked"}


def _thumb(im: dict) -> str:
    url = im.get("local_sm") or im.get("local") or im.get("url") or ""
    if url.startswith("../"):
        url = "../docs/" + url[3:]                    # this page lives in data/, the site files in docs/
    return url


def review_markdown(articles: list[dict], today: str, days: int = 3) -> str:
    from datetime import date as D, timedelta
    since = (D.fromisoformat(today) - timedelta(days=days)).isoformat()
    show = [a for a in articles if a.get("status") == "draft"
            or (a.get("status") == "published" and str(a.get("date", "")) >= since)]
    show.sort(key=lambda a: (str(a.get("date", "")), a.get("id", "")), reverse=True)      # newest first
    show.sort(key=lambda a: a.get("status") != "draft")                                      # drafts on top
    bad = sum(1 for a in show for im in a.get("images") or [] if (im.get("check") or {}).get("verdict") == "wrong")
    unsure = sum(1 for a in show for im in a.get("images") or [] if (im.get("check") or {}).get("verdict") in ("unsure", "unchecked")
                 and not im.get("card"))
    L = [f"# Photo review — {today}", "",
         f"Drafts and stories published in the last {days} days. **🔴 wrong: {bad} · 🟠 to look at: {unsure}**", "",
         "How to use (about a minute): look at each picture next to its caption. 🔴 photos block publishing. "
         "To remove or replace a photo, add the story ID to `photos.yaml` (examples at the top of that file), "
         "or tell Claude the story ID and which photo is wrong. Official Instagram/Facebook posts can be added "
         "with `embed:` lines in `photos.yaml`.", ""]
    for a in show:
        en = a.get("en") or {}
        L += [f"## {'📝 DRAFT' if a.get('status') == 'draft' else '✅ live'} · {en.get('headline', a['id'])}",
              f"`{a['id']}` · {a.get('date')}", ""]
        imgs = a.get("images") or []
        if not imgs and not a.get("embeds"):
            L += ["_No photos._", ""]
        for n, im in enumerate(imgs, 1):
            c = im.get("check") or {}
            badge = "🟢 our score card" if im.get("card") else BADGE.get(c.get("verdict", "unchecked"), "⚪")
            bits = [f"**{n}. {badge}**{' · cover' if n == 1 else ''}",
                    f"Caption: **{im.get('subject', '')}**"]
            if im.get("asked") and _norm(im["asked"]) != _norm(im.get("page_title") or im.get("subject") or ""):
                bits.append(f"Asked for: {im['asked']} → got page: {im.get('page_title') or im.get('subject')}")
            meta = " · ".join(x for x in [str(im.get("year") or ""), im.get("license", ""),
                                         f"[source]({im['page']})" if im.get("page") else ""] if x)
            if meta:
                bits.append(meta)
            if c.get("shows"):
                bits.append(f"AI sees: _{c['shows']}_")
            if c.get("reason") and c.get("verdict") != "ok":
                bits.append(f"Why: {c['reason']}")
            for f in c.get("flags") or []:
                bits.append(f"⚑ {f}")
            L += [f'<img src="{_thumb(im)}" width="240" align="left" hspace="10">', "", "<br>".join(bits),
                  '<br clear="left">', ""]
        for e in a.get("embeds") or []:
            L += [f"🔗 Embedded post: [{e.get('account') or e.get('platform')}]({e['url']}) — {e.get('caption', '')}", ""]
        L += ["---", ""]
    if not show:
        L.append("Nothing to review.")
    return "\n".join(L) + "\n"


def write_review(cfg: dict, articles: list[dict]) -> None:
    from .common import DATA, today
    try:
        (DATA / "photo-review.md").write_text(review_markdown(articles, today(cfg)), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("Photo review page not written: %s", str(e)[:200])
