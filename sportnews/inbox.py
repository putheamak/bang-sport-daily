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
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        return {}, text.strip()
    return yaml.safe_load(m.group(1)) or {}, m.group(2).strip()


def import_inbox(cfg: dict, date: str, state: dict) -> list[dict]:
    done = state.setdefault("inbox_done", [])
    out = []
    for f in sorted(INBOX.glob("*.md")) if INBOX.exists() else []:
        if f.name.lower() == "readme.md" or f.name in done:
            continue
        meta, body = parse(read_text(f))
        if not meta.get("headline") or not body:
            log.warning("Inbox %s skipped: needs a 'headline' and a body", f.name)
            continue
        social = meta.get("social_post") or (meta.get("subheadline") or "")
        if meta.get("update"):
            upd = _update_existing(cfg, meta, body, social)
            if upd:
                out.append(upd)
                done.append(f.name)
            continue
        en = {"headline": meta["headline"], "subheadline": meta.get("subheadline", ""),
              "body_markdown": body, "social_post": social}
        log.info("Importing editor's article: %s", f.name)
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
