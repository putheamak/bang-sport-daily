"""CLI.

  python -m sportnews daily                 # full daily run (collect, write, export, notify, dashboard)
  python -m sportnews collect               # only show today's relevant news items (no AI cost)
  python -m sportnews build-style           # learn your voice from voice/samples/
  python -m sportnews publish ID [ID ...]   # publish to Telegram/Facebook (or 'today' / 'all-drafts')
  python -m sportnews reject ID [ID ...]    # mark drafts as rejected
  python -m sportnews book 2026-11 [--lang zh]  # compile a month into an ebook-style .docx
  python -m sportnews site                  # rebuild the website only
  python -m sportnews headlines             # refresh the "Around the world" box (RSS only, no AI) + rebuild
  python -m sportnews trending              # talking points: scan feeds, send top 5 to Telegram (no AI)
  python -m sportnews replies               # act on your Telegram replies (write / publish / reject), hourly
  python -m sportnews write-trending 1 3    # write talking points 1 and 3 as short explainers (drafts)
  python -m sportnews audit [--no-links]    # standards audit of all stories -> data/audit.md
  python -m sportnews check ID              # standards check of one story
python -m sportnews voiceover <id>[,<id>] [--voices Charon,Kore]   # presenter voice-over MP3 -> output/voice/
python -m sportnews photocheck [recent]   # right person/place in each photo -> data/photo-review.md
"""
import argparse
import json
import sys

from .common import load_config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sportnews", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily"); d.add_argument("--publish", action="store_true", help="publish immediately")
    d.add_argument("--once", action="store_true", help="skip if today's stories are already written (scheduled runs)")
    sub.add_parser("collect")
    sub.add_parser("inbox")
    bs = sub.add_parser("bluesky", help="label the Bluesky account as automated (--setup) or post published stories")
    bs.add_argument("ids", nargs="*"); bs.add_argument("--setup", action="store_true")
    rp = sub.add_parser("reelphotos", help="save free photos from Wikipedia articles to choose Reel pictures")
    rp.add_argument("id"); rp.add_argument("titles", help="Wikipedia article titles, separated by |")
    vo = sub.add_parser("voiceover", help="AI presenter voice-over for a story (script in voiceover/<id>.en.txt)")
    vo.add_argument("ids"); vo.add_argument("--voices", default="Charon,Kore")
    sub.add_parser("build-style")
    p = sub.add_parser("publish"); p.add_argument("ids", nargs="+"); p.add_argument("--force", action="store_true", help="publish even with BLOCK problems")
    sub.add_parser("publish-anyway").add_argument("ids", nargs="+")
    fb = sub.add_parser("facebook", help="check the Facebook Page token; optionally post published stories")
    fb.add_argument("ids", nargs="*", help="published story IDs to post to the Facebook Page")
    fb.add_argument("--mode", choices=["post+reel", "post", "reel", "redo-reel", "rescrape", "redo-post", "cancel", "requeue"], default="post+reel",
                    help="what to post for those stories (reel = only the Reel, e.g. when the post was made by hand)")
    pc = sub.add_parser("photocheck", help="check photos (right person/place) and write data/photo-review.md")
    pc.add_argument("ids", nargs="*", help="story IDs, or 'recent' (default: drafts + last 3 days) or 'drafts'")
    pc.add_argument("--again", action="store_true", help="check again even if already checked")
    au = sub.add_parser("audit"); au.add_argument("--no-links", action="store_true")
    sub.add_parser("check").add_argument("ids", nargs="+")
    r = sub.add_parser("reject"); r.add_argument("ids", nargs="+")
    b = sub.add_parser("book"); b.add_argument("month"); b.add_argument("--published-only", action="store_true"); b.add_argument("--lang", choices=["en", "zh", "ru"])
    sub.add_parser("site")
    sub.add_parser("headlines")
    sub.add_parser("trending")
    sub.add_parser("replies")
    sub.add_parser("write-trending").add_argument("numbers", nargs="*")
    a = ap.parse_args(argv)
    cfg = load_config()

    if a.cmd == "daily":
        from .pipeline import run_daily
        run_daily(publish_now=True if a.publish else None, once=a.once)
    elif a.cmd == "bluesky":
        from . import bluesky
        from .common import load_articles, now_iso, save_articles
        if not bluesky.ready():
            print("Bluesky secrets missing (BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)")
        elif a.setup:
            print(bluesky.setup_profile())
        else:
            arts = load_articles()
            for x in arts:
                if x["id"] in a.ids and x.get("status") == "published" and \
                        "bluesky" not in {p.get("channel") for p in x.get("published_to") or []}:
                    x.setdefault("published_to", []).append({"channel": "bluesky", "id": bluesky.post(cfg, x), "at": now_iso(cfg)})
                    print("Bluesky:", x["id"])
            save_articles(arts)
    elif a.cmd == "reelphotos":
        from .voicereel import fetch_photos
        print(fetch_photos(a.id, [t.strip() for t in a.titles.split("|") if t.strip()]))
    elif a.cmd == "voiceover":
        from .voiceover import run as voiceover
        for x in voiceover([i.strip() for i in a.ids.split(",") if i.strip()], [v.strip() for v in a.voices.split(",") if v.strip()]):
            print(x)
    elif a.cmd == "inbox":
        from .pipeline import run_inbox
        for x in run_inbox():
            print(x["id"], "|", x["en"]["headline"])
    elif a.cmd == "collect":
        from .collect import collect
        for it in collect(cfg):
            print(json.dumps({k: it.get(k) for k in ("score", "sport", "source", "title", "link")}, ensure_ascii=False))
    elif a.cmd == "build-style":
        from .style import build_style
        print(build_style())
    elif a.cmd in ("audit", "check"):
        from .common import DATA, load_articles, save_articles, today
        from .standards import audit, check_article, summary_lines
        arts = load_articles()
        if a.cmd == "check":
            from .publishers import _match
            for x in _match(arts, [i for v in a.ids for i in v.replace(",", " ").split()]):
                print(x["id"], "|", x["en"]["headline"])
                print("\n".join(summary_lines(check_article(cfg, x, today(cfg)), 50)) or "  no problems")
        else:
            report = audit(cfg, arts, today(cfg), links=not a.no_links)
            (DATA / "audit.md").write_text(report, encoding="utf-8")
            save_articles(arts)
            print(report)
    elif a.cmd in ("publish", "reject", "publish-anyway"):
        from .publishers import publish_articles, set_status
        from .site import build_site
        ids = [i for x in a.ids for i in x.replace(",", " ").split()]
        if a.cmd in ("publish", "publish-anyway"):
            publish_articles(cfg, ids, force=a.cmd == "publish-anyway" or getattr(a, "force", False))
        else:
            set_status(ids, "rejected")
        build_site(cfg)
    elif a.cmd == "book":
        from .exporters import compile_book
        print(compile_book(cfg, a.month, "published" if a.published_only else None, a.lang))
    elif a.cmd == "headlines":
        from .common import log_to_file
        log_to_file("last_headlines.log")
        from .collect import collect, save_wire
        from .site import build_site
        collect(cfg)
        save_wire(cfg)
        build_site(cfg)
    elif a.cmd == "trending":
        from .common import log_to_file
        log_to_file("last_trending.log")
        from .trending import handle_commands, scan
        if (cfg.get("trending") or {}).get("read_replies", False):
            handle_commands()                # your Telegram replies first: they refer to the list sent BEFORE this scan
        scan(cfg)
    elif a.cmd == "replies":
        from .common import log_to_file
        log_to_file("last_replies.log")
        from .trending import handle_commands
        handle_commands()
    elif a.cmd == "write-trending":
        from .common import log_to_file
        log_to_file("last_trending_write.log")
        from .trending import parse_choice, write_selected
        write_selected(cfg, parse_choice(" ".join(a.numbers)))
    elif a.cmd == "photocheck":
        from .common import load_articles, log_to_file, save_articles, today
        log_to_file("last_photocheck.log")
        from .images import apply_overrides, load_overrides
        from .photocheck import check_many
        from datetime import date as _D, timedelta as _TD
        arts = load_articles()
        apply_overrides(arts, load_overrides())
        want = [x.strip() for x in " ".join(a.ids).replace(",", " ").split() if x.strip()] or ["recent"]
        since = (_D.fromisoformat(today(cfg)) - _TD(days=3)).isoformat()
        pick = [x for x in arts if x["id"] in want
                or ("drafts" in want and x.get("status") == "draft")
                or ("recent" in want and (x.get("status") == "draft"
                                          or (x.get("status") == "published" and str(x.get("date", "")) >= since)))]
        if a.again:
            for x in pick:
                for im in x.get("images") or []:
                    im.pop("check", None)
        n = check_many(cfg, pick)
        from .standards import check_article
        for x in pick:
            x["standards"] = check_article(cfg, x, today(cfg))
        save_articles(arts)
        from .site import build_site
        build_site(cfg)
        bad = [(x["id"], k) for x in pick for k, im in enumerate(x.get("images") or [], 1)
               if (im.get("check") or {}).get("verdict") == "wrong"]
        print(f"Checked {n} photo(s) in {len(pick)} stories. Wrong: " + (", ".join(f"{i} photo {k}" for i, k in bad) or "none"))
    elif a.cmd == "facebook":
        from .common import load_articles, save_articles
        from .publishers import facebook_check, facebook_publish
        print("Facebook Page OK: " + facebook_check())
        ids = [x.strip() for x in " ".join(a.ids).replace(",", " ").split() if x.strip()]
        if ids:
            arts = load_articles()
            if a.mode == "redo-post":
                from .publishers import facebook_redo_post
                for x in arts:
                    if x["id"] in ids:
                        print(x["id"] + ": " + facebook_redo_post(cfg, x))
                save_articles(arts)
                return
            if a.mode == "requeue":
                from .publishers import facebook_requeue
                try:
                    for line in facebook_requeue(cfg, arts, ids):
                        print(line)
                finally:
                    save_articles(arts)
                return
            if a.mode == "cancel":
                from .publishers import facebook_cancel
                for x in arts:
                    if x["id"] in ids:
                        print(x["id"] + ": " + facebook_cancel(cfg, x))
                save_articles(arts)
                return
            if a.mode == "rescrape":
                from .publishers import facebook_rescrape
                for x in arts:
                    if x["id"] in ids:
                        print(x["id"] + ": " + facebook_rescrape(cfg, x))
                return
            if a.mode == "redo-reel":
                from .publishers import facebook_redo_reel
                for x in arts:
                    if x["id"] in ids:
                        print(x["id"] + ": " + facebook_redo_reel(cfg, x, arts))
                save_articles(arts)
                return
            done = facebook_publish(cfg, [x for x in arts if x["id"] in ids],
                                    post=a.mode != "reel", reel=a.mode != "post", everything=arts)
            save_articles(arts)
            print("Posted to Facebook: " + (", ".join(done) or "nothing (already posted or not published)"))
    elif a.cmd == "site":
        from .common import load_articles, log_to_file, save_articles
        log_to_file("last_rebuild.log")
        from .site import build_site
        from .images import apply_overrides, backfill, load_overrides
        arts = load_articles()
        from .gnlinks import fix_sources
        if fix_sources(arts):
            save_articles(arts)
        changed = backfill(arts) if cfg["publish"].get("photos", True) else 0
        changed += apply_overrides(arts, load_overrides())
        from .images import unique_covers
        changed += unique_covers(arts)               # every story has its own cover photo
        if changed:
            save_articles(arts)
        build_site(cfg)


if __name__ == "__main__":
    sys.exit(main())
