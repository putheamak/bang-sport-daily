"""Daily run: collect -> rank -> write (EN) -> adapt (ZH/RU) -> save -> export -> review/publish -> website."""
from __future__ import annotations

import re

from . import collect as C
from .common import (MEMOS, STATE, log_to_file, load_articles, load_athletes, load_config, log, read_json, read_text,
                     save_articles, slugify, today, write_json)
from .writer import write_article


def _news_context(item: dict) -> dict:
    body = C.fetch_full_text(item["link"])
    links = [{"title": f"{item['source']}: {item['title']}", "url": item["link"]}]
    links += [{"title": f"{o['source']}: {o.get('title', '')}", "url": o["link"]} for o in item.get("also_reported_by", [])]
    src = (f"HEADLINE: {item['title']}\nPUBLISHER: {item['source']}\nPUBLISHED: {item['published']}\n"
           f"SPORT: {item.get('sport') or 'unknown'}\nLINK: {item['link']}\nSUMMARY: {item['summary']}\n")
    for o in item.get("also_reported_by", []):
        src += f"ALSO REPORTED BY {o['source']}: {o.get('title', '')}\n"
    if body:
        src += f"\nARTICLE TEXT (for facts only, do not copy):\n{body}\n"
    return {"title": item["title"], "sport": item.get("sport"), "sources": src, "source_links": links}


def must_cover(memo: str) -> list[tuple[str, list[str]]]:
    """Memo lines 'Must cover: <topic>' followed by optional 'Source: <url>' lines."""
    out: list[tuple[str, list[str]]] = []
    for line in memo.splitlines():
        low = line.strip().lower()
        if low.startswith("must cover:"):
            out.append((line.split(":", 1)[1].strip(), []))
        elif low.startswith("source:") and out:
            url = line.split(":", 1)[1].strip()
            if url.startswith("http"):
                out[-1][1].append(url)
    return [(t, u) for t, u in out if t]


def _must_context(topic: str, urls: list[str], items: list[dict]) -> dict | None:
    from rapidfuzz import fuzz
    words = [w for w in re.findall(r"\w+", topic.lower()) if len(w) > 3]
    matched = [i for i in items if fuzz.token_set_ratio(topic.lower(), i["title"].lower()) >= 60
               or (words and sum(w in i["title"].lower() for w in words) >= max(2, len(words) // 2))][:4]
    src, links = f"EDITOR'S ASSIGNMENT: {topic}\n", []
    for i in matched:
        src += f"\nHEADLINE: {i['title']}\nPUBLISHER: {i['source']}\nPUBLISHED: {i['published']}\nSUMMARY: {i['summary']}\n"
        links.append({"title": f"{i['source']}: {i['title']}", "url": i["link"]})
    got_text = False
    for u in urls:
        body = C.fetch_full_text(u)
        if body:
            got_text = True
            src += f"\nARTICLE TEXT from {u} (for facts only, do not copy):\n{body}\n"
        links.append({"title": u.split("/")[2], "url": u})
    if not matched and not got_text:
        return None
    return {"title": topic, "sources": src, "source_links": links, "_matched": matched}


def merge_articles(new: list[dict], existing: list[dict]) -> list[dict]:
    """New stories first; an update replaces the story with the same ID in place."""
    upd = {a["id"]: a for a in new if a.pop("_update", False)}
    fresh = [a for a in new if a["id"] not in upd]
    return fresh + [upd.get(a["id"], a) for a in existing]


def retry_translations(cfg: dict, articles: list[dict], limit: int = 5) -> int:
    """Stories saved in English only (AI was overloaded) get their Chinese/Russian versions on a later run."""
    from .writer import localize
    langs = cfg["languages"].get("others", ["zh", "ru"])
    n = 0
    for a in articles:
        from .site import stale
        if n >= limit or a.get("status") == "rejected" or all(a.get(l) and not stale(a, l) for l in langs):
            continue
        loc = localize(cfg, a["en"])
        ok = 0
        for l in langs:
            if isinstance(loc.get(l), dict) and loc[l].get("headline"):
                a[l] = {k: loc[l].get(k, "") for k in ("headline", "subheadline", "body_markdown", "social_post")}
                ok += 1
        if ok == len(langs):
            from .common import now_iso
            a["translated_at"] = now_iso(cfg)
            a["lang_updated"] = {l: a["translated_at"] for l in langs}
        log.info("Translation retry for %s: %s", a["id"], [l for l in langs if a.get(l)])
        n += 1
    return n


def run_inbox() -> list[dict]:
    """Only import editor's articles from inbox/ (no AI news writing)."""
    log_to_file("last_inbox.log")
    cfg = load_config()
    date = today(cfg)
    state = read_json(STATE, {})
    from .inbox import import_inbox
    new = import_inbox(cfg, date, state)
    if cfg["publish"].get("photos", True):
        from .images import attach_images
        for a in new:
            if "images" in a:            # updates keep their photos
                continue
            try:
                attach_images(a)
            except Exception as e:  # noqa: BLE001
                log.warning("Photos failed for %s: %s", a["id"], e)
    write_json(STATE, state)
    from .standards import stamp
    stamp(cfg, new, date)              # ethics / professionalism / sources check, shown in the review message
    articles = merge_articles(new, load_articles())
    retry_translations(cfg, [a for a in articles if a not in new])
    save_articles(articles)
    from .exporters import export_day
    export_day(cfg, date, [a for a in articles if a["date"] == date])
    from .publishers import send_digest, send_for_review
    if new:
        send_for_review(cfg, new)
        if cfg["publish"].get("email_digest"):
            send_digest(cfg, date, new)
    from .site import build_site
    build_site(cfg)
    log.info("Imported %d editor's article(s): %s", len(new), ", ".join(a["id"] for a in new))
    return new


def run_daily(publish_now: bool | None = None) -> list[dict]:
    log_to_file()
    cfg = load_config()
    date = today(cfg)
    plan = cfg.get("daily_plan", {})
    state = read_json(STATE, {})
    memo = read_text(MEMOS / f"{date}.md").lower()
    new: list[dict] = []

    from .inbox import import_inbox
    new += import_inbox(cfg, date, state)        # your own articles from inbox/

    raw_memo = read_text(MEMOS / f"{date}.md")
    musts = must_cover(raw_memo)
    items = C.collect(cfg) if (plan.get("news", 0) or musts) else []
    done_titles = []
    from .writer import split_memo
    assignment_memo = split_memo(raw_memo)[1]
    covered = state.setdefault("must_covered", [])
    for topic, urls in musts:
        if topic.lower() in covered:
            log.info("Must cover %r: already written earlier — skipped", topic)
            continue
        ctx = _must_context(topic, urls, items)
        if not ctx:
            log.error("Must cover %r: no source text found — add a 'Source: <link>' line to the memo", topic)
            continue
        log.info("Must cover: %s (%d source(s))", topic, len(ctx["source_links"]))
        try:
            ctx["assignment_memo"] = assignment_memo
            new.append(write_article(cfg, "news", ctx, date))
            done_titles += [x["title"] for x in ctx.pop("_matched", [])]
            covered.append(topic.lower())
        except Exception as e:  # noqa: BLE001
            log.error("Must-cover story failed (%s): %s", topic, e)

    if plan.get("news", 0) and "skip: news" not in memo:
        n_left = max(0, plan["news"] - len(new))
        items = [i for i in items if i["title"] not in done_titles]
        from .regions import counts, pick_balanced
        bal = counts(load_articles() + new, date, (cfg.get("regions") or {}).get("window_days", 7))
        if n_left:
            from .corroborate import confirm
            items = confirm(items, cfg)            # 2+ independent outlets, no politics: before any AI is spent
        spare = (cfg.get("corroborate") or {}).get("spare_attempts", 2)
        picked = pick_balanced(cfg, items, n_left + spare, bal, plan.get("max_per_sport", 1)) if n_left else []
        from .standards import auto_reject_reasons
        good = 0
        for it in picked:
            if good >= n_left:
                break
            log.info("Picked [%s %s %.1f · %d outlets] %s", it.get("region"), it.get("sport"), it["score"],
                     1 + len(it.get("also_reported_by", [])), it["title"])
            try:
                ctx = _news_context(it)
                art = write_article(cfg, "news", ctx, date)
                art["region"] = it.get("region") or art.get("region")
                new.append(art)
                done_titles.append(it["title"])
                why = auto_reject_reasons(cfg, art)
                if why:
                    log.warning("Draft will be auto-rejected (%s); trying the next story", "; ".join(why))
                else:
                    good += 1
            except Exception as e:  # noqa: BLE001
                log.error("News article failed (%s): %s", it["title"], e)

    C.mark_seen(done_titles)   # failed stories stay available for the next run

    from .regions import LABEL, article_region, counts, next_region
    win = (cfg.get("regions") or {}).get("window_days", 7)
    do_history, do_athlete = plan.get("history", 0), plan.get("athlete_story", 0)
    if plan.get("alternate_features"):       # one feature a day: history on even days, life story on odd days
        from datetime import date as _D
        even = _D.fromisoformat(date).toordinal() % 2 == 0
        do_history, do_athlete = (do_history and even), (do_athlete and not even)
    if do_history and "skip: history" not in memo:
        try:
            focus = next_region(cfg, counts(load_articles() + new, date, win))
            from .factsource import history_context
            hctx = history_context(date[5:], focus)
            if not hctx:
                log.warning("No dated sport event found for %s: no history story today (never written from memory)", date[5:])
            else:
                art = write_article(cfg, "history", hctx, date)
                art["region"] = article_region(art) if article_region(art) != "global" else hctx.get("region_hint", "global")
                new.append(art)
        except Exception as e:  # noqa: BLE001
            log.error("History article failed: %s", e)

    athletes = load_athletes()
    if do_athlete and athletes and "skip: athlete" not in memo:
        idx = state.get("athlete_idx", 0) % len(athletes)
        focus = next_region(cfg, counts(load_articles() + new, date, win))
        order = [(idx + k) % len(athletes) for k in range(len(athletes))]
        idx = next((i for i in order if athletes[i].get("region", "global") == focus), idx)   # region behind target
        a = athletes[idx]
        ctx = {"fmt": {"athlete": a["name"], "sport": a.get("sport", ""), "notes": a.get("notes", "")},
               "title": a["name"], "sport": a.get("sport", ""),
               "athlete_memo": read_text(MEMOS / "athletes" / f"{slugify(a['name'])}.md")}
        from .factsource import athlete_context
        ctx["sources"], ctx["source_links"] = athlete_context(a.get("wikipedia") or a["name"])
        try:
            art = write_article(cfg, "athlete_story", ctx, date)
            art["region"] = a.get("region") or article_region(art)
            new.append(art)
            state["athlete_idx"] = idx + 1          # only move on when the story was written
        except Exception as e:  # noqa: BLE001
            log.error("Athlete story failed (%s): %s", a["name"], e)

    write_json(STATE, state)
    if cfg["publish"].get("photos", True):
        from .images import attach_images
        for a in new:
            if "images" in a:
                continue
            try:
                attach_images(a)
            except Exception as e:  # noqa: BLE001
                log.warning("Photos failed for %s: %s", a["id"], e)
    from .collect import save_wire
    save_wire(cfg)
    from .standards import auto_reject_reasons, stamp
    stamp(cfg, new, date)              # ethics / professionalism / sources check, shown in the review message
    for a in new:
        why = auto_reject_reasons(cfg, a)
        if why:                        # never reaches the editor: fails the site's standards
            a["status"], a["auto_rejected"] = "rejected", why
            log.warning("Auto-rejected %s (%s): %s", a["id"], a["en"].get("headline", "")[:60], "; ".join(why)[:300])
    kept = [a for a in new if a["status"] != "rejected"]
    log.info("Drafts for review: %d of %d (others auto-rejected by the standards check)", len(kept), len(new))
    articles = merge_articles(new, load_articles())
    if cfg["publish"].get("photos", True):
        from .images import backfill
        try:
            backfill(articles)           # older published stories that never had a photo lookup
        except Exception as e:  # noqa: BLE001
            log.warning("Photo backfill failed: %s", e)
    from .images import apply_overrides, load_overrides
    apply_overrides(articles, load_overrides())
    retry_translations(cfg, articles)
    save_articles(articles)
    log.info("Wrote %d new articles for %s", len(new), date)
    if not new:
        log.error("No articles were written today — see the warnings above (data/last_run.log)")

    from .exporters import export_day
    export_day(cfg, date, [a for a in articles if a["date"] == date])

    from .publishers import publish_articles, send_digest, send_for_review
    auto = cfg["publish"].get("auto_publish", False) if publish_now is None else publish_now
    if kept:
        if auto:
            publish_articles(cfg, [a["id"] for a in kept])
        else:
            send_for_review(cfg, kept)
        if cfg["publish"].get("email_digest"):
            send_digest(cfg, date, kept, published=auto)

    from .site import build_site
    build_site(cfg)
    return new
