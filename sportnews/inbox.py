"""Editor's own articles: drop a Markdown file in inbox/ and the system turns it into a draft —
adapted into Chinese and Russian, with free photos — ready for your approval like any other story.

File format (inbox/any-name.md):

---
headline: "Your headline"
subheadline: "One-line summary"
type: news            # news | history | athlete_story
sport: football
image_subjects: ["Morodok Techo National Stadium"]
sources:
  - {title: "AFC report", url: "https://..."}
social_post: "Optional short text for Telegram/Facebook"
---
Article body in Markdown (## for subheadings)...
"""
from __future__ import annotations

import re

import yaml

from .common import ROOT, log, now_iso, read_text, short_hash, slugify
from .writer import localize

INBOX = ROOT / "inbox"


def parse(text: str) -> tuple[dict, str]:
    m = re.match(r"^﻿?---\s*\n(.*?)\n---[ \t]*(?:\n(.*))?$", text.rstrip() + "\n", re.S)
    if not m:
        return {}, text.strip()
    return yaml.safe_load(m.group(1)) or {}, (m.group(2) or "").strip()


def import_inbox(cfg: dict, date: str, state: dict) -> list[dict]:
    done = state.setdefault("inbox_done", [])
    out = []
    for f in sorted(INBOX.glob("*.md")) if INBOX.exists() else []:
        if f.name.lower() == "readme.md" or f.name in done:
            continue
        meta, body = parse(read_text(f))
        if meta.get("update") and not body and (meta.get("sources") or meta.get("facts_to_verify") is not None):
            upd = _fix_details(meta)                 # sources / facts list only: no text change, no AI
            if upd:
                out.append(upd)
                done.append(f.name)
            continue
        if (not meta.get("headline") and not meta.get("update")) or not body:
            log.warning("Inbox %s skipped: needs a 'headline' and a body", f.name)
            continue
        social = meta.get("social_post") or (meta.get("subheadline") or "")
        if meta.get("update") and meta.get("translations"):
            upd = _add_translations(cfg, meta, body)
            if upd:
                out.append(upd)
                done.append(f.name)
            continue
        if meta.get("update"):
            upd = _update_existing(cfg, meta, body, social)
            if upd:
                out.append(upd)
                done.append(f.name)
            continue
        tr = meta.get("translations") or {}
        parts = _split_langs(body) if tr else {}
        en = {"headline": meta["headline"], "subheadline": meta.get("subheadline", ""),
              "body_markdown": parts.get("en", body), "social_post": social}
        log.info("Importing editor's article: %s", f.name)
        if tr and parts:                       # ready-made translations: no AI needed
            loc = {l: {"headline": h.get("headline", ""), "subheadline": h.get("subheadline", ""),
                       "body_markdown": parts.get(l, ""), "social_post": h.get("social_post", "")}
                   for l, h in tr.items() if isinstance(h, dict) and parts.get(l)}
        else:
            loc = localize(cfg, en)
        kind = meta.get("type", "news")
        a = {
            "id": f"{date}-{kind[:4]}-{short_hash(en['headline'] + now_iso())[:6]}",
            "slug": slugify(en["headline"]), "date": date, "created": now_iso(cfg), "type": kind,
            "status": "draft", "model": "editor", "sport": meta.get("sport", ""),
            "tags": meta.get("tags", []), "athletes": meta.get("athletes", []),
            "image_subjects": meta.get("image_subjects", []),
            "facts_to_verify": meta.get("facts_to_verify", []),
            "sources": [s for s in meta.get("sources", []) if isinstance(s, dict) and s.get("url")],
            "published_to": [], "en": en, "origin": f"inbox/{f.name}",
        }
        if meta.get("region"):
            a["region"] = meta["region"]
        if meta.get("photos"):               # your own charts/photos (photos/ folder) or Commons files
            from .images import resolve_entry
            imgs = []
            for e in meta["photos"]:
                try:
                    im = resolve_entry(e) if isinstance(e, dict) else None
                except Exception as ex:  # noqa: BLE001  (a photo lookup must never stop the import)
                    log.warning("Photo %s skipped: %s", e.get("id") or e, str(ex)[:200])
                    im = None
                if im:
                    if e.get("id"):
                        im["ref"] = str(e["id"])      # lets the text place it with [[img:<id>]]
                    imgs.append(im)
            a["images"] = imgs[:10]
        for lang in cfg["languages"].get("others", ["zh", "ru"]):
            if isinstance(loc.get(lang), dict) and loc[lang].get("headline"):
                a[lang] = {k: loc[lang].get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")}
        out.append(a)
        done.append(f.name)
    return out


def _update_existing(cfg: dict, meta: dict, body: str, social: str) -> dict | None:
    """'update: <story id>' in the header rewrites an existing story (keeps its ID, link, status and photos)."""
    from .common import load_articles
    old = next((a for a in load_articles() if a["id"] == str(meta["update"]).strip()), None)
    if not old:
        log.warning("Update skipped: story %s not found", meta["update"])
        return None
    a = dict(old)
    a["en"] = {"headline": meta.get("headline") or old["en"].get("headline", ""),
               "subheadline": meta.get("subheadline", old["en"].get("subheadline", "")),
               "body_markdown": body, "social_post": social or old["en"].get("social_post", "")}
    for k in ("facts_to_verify", "tags", "image_subjects"):
        if k in meta:
            a[k] = meta[k]
    if meta.get("sources"):
        a["sources"] = [x for x in meta["sources"] if isinstance(x, dict) and x.get("url")]
    log.info("Updating story %s from inbox", a["id"])
    loc = localize(cfg, a["en"])
    for lang in cfg["languages"].get("others", ["zh", "ru"]):
        if isinstance(loc.get(lang), dict) and loc[lang].get("headline"):
            a[lang] = {k: loc[lang].get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")}
        else:
            log.warning("Translation to %s failed — the %s page is hidden until a later run re-translates it", lang, lang)
    a["updated_at"] = now_iso(cfg)
    if all(isinstance(loc.get(l), dict) and loc[l].get("headline") for l in cfg["languages"].get("others", ["zh", "ru"])):
        a["translated_at"] = a["updated_at"]
    a["_update"] = True
    return a


def _split_langs(body: str) -> dict:
    return dict((m.group(1), m.group(2).strip()) for m in
                re.finditer(r"^===\s*([a-z]{2})\s*===\s*\n(.*?)(?=^===\s*[a-z]{2}\s*===|\Z)", body, re.S | re.M))


def _add_translations(cfg: dict, meta: dict, body: str) -> dict | None:
    """Ready-made translations for an existing story (no AI needed).
    Header:  update: <id>   translations: {zh: {headline, subheadline, social_post}, ru: {...}}
    Body:    === zh ===  <Chinese markdown>   === ru ===  <Russian markdown>"""
    from .common import load_articles
    old = next((a for a in load_articles() if a["id"] == str(meta["update"]).strip()), None)
    if not old:
        log.warning("Translations skipped: story %s not found", meta["update"])
        return None
    parts = dict((m.group(1), m.group(2).strip()) for m in
                 re.finditer(r"^===\s*([a-z]{2})\s*===\s*\n(.*?)(?=^===\s*[a-z]{2}\s*===|\Z)", body, re.S | re.M))
    a = dict(old)
    stamps = dict(a.get("lang_updated") or {})
    stamp = now_iso(cfg)
    tr = meta.get("translations") or {}
    if "en" in tr and parts.get("en") and tr["en"].get("headline"):
        # corrected English supplied together with its translations: all versions share one timestamp
        a["en"] = {"headline": tr["en"]["headline"], "subheadline": tr["en"].get("subheadline", ""),
                   "body_markdown": parts["en"], "social_post": tr["en"].get("social_post", "")}
        a["updated_at"] = stamp
        log.info("Corrected English for %s", a["id"])
    for lang, head in tr.items():
        if lang not in cfg["languages"].get("others", ["zh", "ru"]) or not parts.get(lang) or not head.get("headline"):
            continue
        a[lang] = {"headline": head["headline"], "subheadline": head.get("subheadline", ""),
                   "body_markdown": parts[lang], "social_post": head.get("social_post", "")}
        stamps[lang] = stamp
        log.info("Added %s translation for %s", lang, a["id"])
    a["lang_updated"] = stamps
    _apply_details(a, meta)
    a["_update"] = True
    return a


def _apply_details(a: dict, meta: dict) -> None:
    if meta.get("sources"):
        a["sources"] = [x for x in meta["sources"] if isinstance(x, dict) and x.get("url")]
    if meta.get("facts_to_verify") is not None:
        a["facts_to_verify"] = list(meta.get("facts_to_verify") or [])


def _fix_details(meta: dict) -> dict | None:
    """'update: <id>' with only 'sources:' and/or 'facts_to_verify:' (empty body): fixes source links
    without touching the text, so no translation is needed and no page is hidden."""
    from .common import load_articles
    old = next((a for a in load_articles() if a["id"] == str(meta["update"]).strip()), None)
    if not old:
        log.warning("Source fix skipped: story %s not found", meta["update"])
        return None
    a = dict(old)
    _apply_details(a, meta)
    a["_update"] = True
    log.info("Updated sources/notes for %s", a["id"])
    return a
