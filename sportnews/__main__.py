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
"""
import argparse
import json
import sys

from .common import load_config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sportnews", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily"); d.add_argument("--publish", action="store_true", help="publish immediately")
    sub.add_parser("collect")
    sub.add_parser("inbox")
    sub.add_parser("build-style")
    p = sub.add_parser("publish"); p.add_argument("ids", nargs="+"); p.add_argument("--force", action="store_true", help="publish even with BLOCK problems")
    sub.add_parser("publish-anyway").add_argument("ids", nargs="+")
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
        run_daily(publish_now=True if a.publish else None)
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
        handle_commands()                    # your Telegram replies first: they refer to the list sent BEFORE this scan
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
    elif a.cmd == "site":
        from .common import load_articles, log_to_file, save_articles
        log_to_file("last_rebuild.log")
        from .site import build_site
        from .images import apply_overrides, backfill, load_overrides
        arts = load_articles()
        changed = backfill(arts) if cfg["publish"].get("photos", True) else 0
        changed += apply_overrides(arts, load_overrides())
        if changed:
            save_articles(arts)
        build_site(cfg)


if __name__ == "__main__":
    sys.exit(main())
