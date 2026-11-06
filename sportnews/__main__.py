"""CLI.

  python -m sportnews daily                 # full daily run (collect, write, export, notify, dashboard)
  python -m sportnews collect               # only show today's relevant news items (no AI cost)
  python -m sportnews build-style           # learn your voice from voice/samples/
  python -m sportnews publish ID [ID ...]   # publish to Telegram/Facebook (or 'today' / 'all-drafts')
  python -m sportnews reject ID [ID ...]    # mark drafts as rejected
  python -m sportnews book 2026-11 [--lang zh]  # compile a month into an ebook-style .docx
  python -m sportnews site                  # rebuild the website only
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
    p = sub.add_parser("publish"); p.add_argument("ids", nargs="+")
    r = sub.add_parser("reject"); r.add_argument("ids", nargs="+")
    b = sub.add_parser("book"); b.add_argument("month"); b.add_argument("--published-only", action="store_true"); b.add_argument("--lang", choices=["en", "zh", "ru"])
    sub.add_parser("site")
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
    elif a.cmd in ("publish", "reject"):
        from .publishers import publish_articles, set_status
        from .site import build_site
        ids = [i for x in a.ids for i in x.replace(",", " ").split()]
        if a.cmd == "publish":
            publish_articles(cfg, ids)
        else:
            set_status(ids, "rejected")
        build_site(cfg)
    elif a.cmd == "book":
        from .exporters import compile_book
        print(compile_book(cfg, a.month, "published" if a.published_only else None, a.lang))
    elif a.cmd == "site":
        from .common import load_articles, log_to_file, save_articles
        log_to_file("last_rebuild.log")
        from .site import build_site
        if cfg["publish"].get("photos", True):
            from .images import backfill
            arts = load_articles()
            if backfill(arts):
                save_articles(arts)
        build_site(cfg)


if __name__ == "__main__":
    sys.exit(main())
