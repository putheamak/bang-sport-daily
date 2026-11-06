"""Daily run: collect -> rank -> write (EN) -> adapt (ZH/RU) -> save -> export -> review/publish -> website."""
from __future__ import annotations

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


def run_daily(publish_now: bool | None = None) -> list[dict]:
    log_to_file()
    cfg = load_config()
    date = today(cfg)
    plan = cfg.get("daily_plan", {})
    state = read_json(STATE, {})
    memo = read_text(MEMOS / f"{date}.md").lower()
    new: list[dict] = []

    if plan.get("news", 0) and "skip: news" not in memo:
        picked = C.select(C.collect(cfg), plan["news"], plan.get("max_per_sport", 1))
        done_titles = []
        for it in picked:
            log.info("Picked [%s %.1f] %s", it.get("sport"), it["score"], it["title"])
            try:
                new.append(write_article(cfg, "news", _news_context(it), date))
                done_titles.append(it["title"])
            except Exception as e:  # noqa: BLE001
                log.error("News article failed (%s): %s", it["title"], e)
        C.mark_seen(done_titles)   # failed stories stay available for the next run

    if plan.get("history", 0) and "skip: history" not in memo:
        try:
            new.append(write_article(cfg, "history", {"title": f"On this day: {date[5:]}"}, date))
        except Exception as e:  # noqa: BLE001
            log.error("History article failed: %s", e)

    athletes = load_athletes()
    if plan.get("athlete_story", 0) and athletes and "skip: athlete" not in memo:
        idx = state.get("athlete_idx", 0) % len(athletes)
        a = athletes[idx]
        ctx = {"fmt": {"athlete": a["name"], "sport": a.get("sport", ""), "notes": a.get("notes", "")},
               "title": a["name"], "sport": a.get("sport", ""),
               "athlete_memo": read_text(MEMOS / "athletes" / f"{slugify(a['name'])}.md")}
        try:
            new.append(write_article(cfg, "athlete_story", ctx, date))
            state["athlete_idx"] = idx + 1          # only move on when the story was written
        except Exception as e:  # noqa: BLE001
            log.error("Athlete story failed (%s): %s", a["name"], e)

    write_json(STATE, state)
    if cfg["publish"].get("photos", True):
        from .images import attach_images
        for a in new:
            try:
                attach_images(a)
            except Exception as e:  # noqa: BLE001
                log.warning("Photos failed for %s: %s", a["id"], e)
    from .collect import save_wire
    save_wire(cfg)
    articles = new + load_articles()
    if cfg["publish"].get("photos", True):
        from .images import backfill
        try:
            backfill(articles)           # older published stories that never had a photo lookup
        except Exception as e:  # noqa: BLE001
            log.warning("Photo backfill failed: %s", e)
    save_articles(articles)
    log.info("Wrote %d new articles for %s", len(new), date)
    if not new:
        log.error("No articles were written today — see the warnings above (data/last_run.log)")

    from .exporters import export_day
    export_day(cfg, date, [a for a in articles if a["date"] == date])

    from .publishers import publish_articles, send_digest, send_for_review
    auto = cfg["publish"].get("auto_publish", False) if publish_now is None else publish_now
    if new:
        if auto:
            publish_articles(cfg, [a["id"] for a in new])
        else:
            send_for_review(cfg, new)
        if cfg["publish"].get("email_digest"):
            send_digest(cfg, date, new, published=auto)

    from .site import build_site
    build_site(cfg)
    return new
