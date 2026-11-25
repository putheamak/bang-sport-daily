"""Telegram (one channel per language + a private review chat), Facebook (optional) and the email digest."""
from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .common import load_articles, log, now_iso, save_articles, today

LANGS = ("en", "zh", "ru")
READ_MORE = {"en": "Read more", "zh": "阅读全文", "ru": "Читать полностью"}


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as r:
        return json.loads(r.read().decode())


def article_url(cfg: dict, a: dict, lang: str) -> str | None:
    from .common import site_url
    base = site_url(cfg)
    if not base:
        return None
    return f"{base}/{lang}/{a['slug']}"


def social_text(cfg: dict, a: dict, lang: str) -> str:
    L = a.get(lang) or {}
    from .site import byline_name
    text = f"{L.get('headline', '')}\n\n{L.get('social_post', '')}\n\n✍️ {byline_name(cfg, a, lang)}".strip()
    url = article_url(cfg, a, lang)
    return text + (f"\n\n👉 {READ_MORE[lang]}: {url}" if url else "")


def telegram_send(chat: str, text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not (token and chat):
        raise RuntimeError("TELEGRAM_BOT_TOKEN or chat id not set")
    for i in range(0, len(text), 4000):  # Telegram limit 4096
        _post(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat, "text": text[i:i + 4000]})


FB_API = os.environ.get("FB_API_VERSION", "v24.0")


_PAGE_TOKEN: dict = {}


def fb_page_token() -> tuple[str, str]:
    """(page id, Page access token). If the saved secret is the editor's long-lived USER token, ask Facebook for
    the Page's own token with it (a Page token made from a long-lived user token does not expire)."""
    page, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not (page and token):
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_TOKEN are not set in GitHub › Settings › Secrets › Actions")
    if token in _PAGE_TOKEN:
        return page, _PAGE_TOKEN[token]
    page_tok = token
    try:
        q = urllib.parse.urlencode({"fields": "access_token", "access_token": token})
        with urllib.request.urlopen(f"https://graph.facebook.com/{FB_API}/{page}?{q}", timeout=30) as r:
            page_tok = json.loads(r.read().decode()).get("access_token") or token
    except Exception:  # noqa: BLE001
        pass                                                 # already a Page token (or no right to ask): use as is
    _PAGE_TOKEN[token] = page_tok
    return page, page_tok


def facebook_ready() -> bool:
    return bool(os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_TOKEN"))


def facebook_text(cfg: dict, a: dict) -> str:
    """Facebook shows the link as a preview card (cover photo + headline), so the post text is just the social
    post: no headline repeat, no link in the text."""
    L = a.get("en") or {}
    return (L.get("social_post") or L.get("subheadline") or L.get("headline") or "").strip()


def facebook_post(text: str, link: str | None, when: int | None = None) -> str:
    """Post now, or schedule it on the Page (when = unix time, at least 10 minutes ahead; Facebook publishes it)."""
    page, token = fb_page_token()
    data = {"message": text, "access_token": token}
    if link:
        data["link"] = link
    if when:
        data.update(published="false", scheduled_publish_time=str(when))
    try:
        return _post(f"https://graph.facebook.com/{FB_API}/{page}/feed", data).get("id", "")
    except urllib.error.HTTPError as e:
        raise RuntimeError("Facebook says: " + e.read().decode()[:400]) from e


def facebook_slot(cfg: dict, articles: list[dict]) -> int | None:
    """Spacing on the Page: every Facebook item (post or Reel) at least `facebook_gap_minutes` after the last one,
    so a batch of stories is spread out instead of landing at once (bursts look like spam and get less reach).
    Returns None = post now, or a unix time to schedule it."""
    import time
    from datetime import datetime
    gap = int(cfg["publish"].get("facebook_gap_minutes", 90)) * 60
    last = 0.0
    for a in articles:
        for p in a.get("published_to") or []:
            if p.get("channel") in ("facebook", "facebook-reel"):
                ts = p.get("scheduled_for") or p.get("at")
                try:
                    last = max(last, datetime.fromisoformat(ts).timestamp())
                except Exception:  # noqa: BLE001
                    pass
    now = time.time()
    slot = max(now, last + gap)
    quiet = cfg["publish"].get("facebook_quiet_hours") or [0, 6]   # no posts while the Page's readers sleep
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(cfg.get("timezone") or "Asia/Phnom_Penh")
        loc = datetime.fromtimestamp(slot, tz)
        if quiet[0] <= loc.hour < quiet[1]:
            slot = loc.replace(hour=quiet[1], minute=30, second=0, microsecond=0).timestamp()
    except Exception:  # noqa: BLE001
        pass
    if slot - now < 60:
        return None
    return int(max(slot, now + 11 * 60))                     # Facebook needs at least 10 minutes' notice


def facebook_send(cfg: dict, articles: list[dict], a: dict, post: bool = True, reel: bool = True) -> list[str]:
    """Normal Page post and/or Reel for one story, each in its own time slot. Records what was sent or scheduled."""
    from datetime import datetime
    out = []
    a.setdefault("published_to", [])
    done = {p.get("channel") for p in a["published_to"]}

    def record(channel, item_id, when):
        rec = {"channel": channel, "id": item_id, "at": now_iso(cfg)}
        if when:
            rec["scheduled_for"] = datetime.fromtimestamp(when).astimezone().isoformat(timespec="seconds")
        a["published_to"].append(rec)
        out.append(channel + (f" (scheduled {rec['scheduled_for'][:16]})" if when else ""))

    if post and "facebook" not in done:
        log.info("Facebook link check for %s: %s", a["id"], facebook_rescrape(cfg, a))   # page must be live first:
        when = facebook_slot(cfg, articles)                  # Facebook freezes the link preview when the post is made
        record("facebook", facebook_post(facebook_text(cfg, a), article_url(cfg, a, "en"), when), when)
    if reel and "facebook-reel" not in done:
        from .reels import make_reel, upload_reel
        for lang in ("zh", "ru"):                            # kept as files for Weibo / VK / Telegram by hand
            make_reel(cfg, a, lang)
        clip = make_reel(cfg, a, "en")
        if clip:
            when = facebook_slot(cfg, articles)
            vid = upload_reel(clip, f'{facebook_text(cfg, a)}\n\nFull story: {article_url(cfg, a, "en")}', when)
            record("facebook-reel", vid, when)
    return out


def facebook_check() -> str:
    """Is the Page token valid and allowed to post? Returns the Page's name (raises with Facebook's message if not)."""
    page, token = fb_page_token()
    url = f"https://graph.facebook.com/{FB_API}/{page}?fields=name,link&access_token={urllib.parse.quote(token)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Facebook says: " + e.read().decode()[:400]) from e
    info = ""
    try:                                                     # what the token may do (no secret is printed)
        q = urllib.parse.urlencode({"input_token": token, "access_token": token})
        with urllib.request.urlopen(f"https://graph.facebook.com/{FB_API}/debug_token?{q}", timeout=30) as r:
            dt = json.loads(r.read().decode()).get("data", {})
        exp = dt.get("expires_at")
        info = (f" · token type {dt.get('type')}, expires {'never' if not exp else exp}, "
                f"permissions: {', '.join(dt.get('scopes') or [])}")
    except Exception as e:  # noqa: BLE001
        info = f" · (token details unavailable: {str(e)[:80]})"
    return f"{d.get('name')} ({d.get('link', '')}){info}"


def facebook_rescrape(cfg: dict, a: dict) -> str:
    """Ask Facebook to read the story page again, so its link preview shows the story, not "Page not found".
    Needed because the publish run sends the post before the new page is live on the site."""
    import time
    url = article_url(cfg, a, "en")
    if os.environ.get("SPORTNEWS_MOCK") == "1" or not facebook_ready() or not url:
        return "skipped (tests / no Facebook token)"
    for _ in range(40):                                     # wait (up to ~10 min) until the page is live
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                        timeout=20) as r:
                if r.status == 200 and b"Page not found" not in r.read(4000):
                    break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(15)
    page, token = fb_page_token()
    try:
        d = _post(f"https://graph.facebook.com/{FB_API}/", {"id": url, "scrape": "true", "access_token": token})
    except urllib.error.HTTPError as e:
        return "Facebook says: " + e.read().decode()[:300]
    return f"preview now: {d.get('title', '?')}"


def facebook_redo_post(cfg: dict, a: dict) -> str:
    """Replace a Page post whose link preview is wrong: delete it on Facebook and post it again, in the same
    scheduled slot if that is still ahead, otherwise now. Only for posts this system made (recorded ids)."""
    from datetime import datetime, timedelta, timezone
    recs = [p for p in a.get("published_to") or [] if p.get("channel") == "facebook"]
    if not recs:
        return "no Facebook post recorded"
    rec = recs[-1]
    page, token = fb_page_token()
    req = urllib.request.Request(f"https://graph.facebook.com/{FB_API}/{rec['id']}?access_token={urllib.parse.quote(token)}",
                                 method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        return "not deleted, Facebook says: " + e.read().decode()[:300]
    a["published_to"].remove(rec)
    log.info("Facebook link check for %s: %s", a["id"], facebook_rescrape(cfg, a))
    when = None
    if rec.get("scheduled_for"):
        ts = datetime.fromisoformat(rec["scheduled_for"])
        if ts > datetime.now(timezone.utc) + timedelta(minutes=12):
            when = int(ts.timestamp())
    new = facebook_post(facebook_text(cfg, a), article_url(cfg, a, "en"), when)
    a["published_to"].append({**rec, "id": new, "at": now_iso(cfg), "replaced": rec["id"]})
    return f"post replaced ({'scheduled ' + rec['scheduled_for'][:16] if when else 'posted now'})"


def facebook_redo_reel(cfg: dict, a: dict, everything: list[dict]) -> str:
    """Replace a Reel that is still waiting (scheduled) on the Page: delete it there, then send the new clip in the
    same time slot. A Reel that is already public is left alone."""
    from datetime import datetime, timezone
    recs = [p for p in a.get("published_to") or [] if p.get("channel") == "facebook-reel"]
    if not recs:
        return "no Reel recorded"
    rec = recs[-1]
    when = rec.get("scheduled_for")
    if not when or datetime.fromisoformat(when) <= datetime.now(timezone.utc) + __import__("datetime").timedelta(minutes=12):
        return "Reel is already public (or about to be): not replaced"
    page, token = fb_page_token()
    req = urllib.request.Request(f"https://graph.facebook.com/{FB_API}/{rec['id']}?access_token={urllib.parse.quote(token)}",
                                 method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise RuntimeError("Facebook says: " + e.read().decode()[:400]) from e
    a["published_to"].remove(rec)
    from .reels import make_reel, upload_reel
    clip = make_reel(cfg, a, "en")
    ts = int(datetime.fromisoformat(when).timestamp())
    vid = upload_reel(clip, f'{facebook_text(cfg, a)}\n\nFull story: {article_url(cfg, a, "en")}', ts)
    a["published_to"].append({**rec, "id": vid, "at": now_iso(cfg), "replaced": rec["id"]})
    return f"Reel replaced, still scheduled for {when[:16]}"


def facebook_publish(cfg: dict, articles: list[dict], post: bool = True, reel: bool = True,
                     everything: list[dict] | None = None) -> list[str]:
    """Post already-published stories to the Facebook Page (post and/or Reel; never twice; spaced out)."""
    out = []
    for a in articles:
        if a.get("status") == "published":
            out += [f"{a['id']}: {x}" for x in facebook_send(cfg, everything or articles, a, post, reel)]
    return out


def send_for_review(cfg: dict, items: list[dict]) -> None:
    """Send full drafts to your PRIVATE Telegram chat so you can read them on your phone."""
    chat = os.environ.get("TELEGRAM_REVIEW_CHAT")
    if not (chat and os.environ.get("TELEGRAM_BOT_TOKEN")):
        log.info("Telegram review skipped (TELEGRAM_REVIEW_CHAT not set)")
        return
    for a in items:
        en = a.get("en", {})
        from .standards import summary_lines
        verify = "\n".join(summary_lines(a.get("standards") or [], 15)) or "\n".join(f"• {f}" for f in a.get("facts_to_verify", [])) or "✅ No problems found"
        langs = "/".join(l.upper() for l in LANGS if a.get(l))
        msg = (f"📝 DRAFT {a['type'].upper()} · {a.get('sport', '')} · {langs}\nID: {a['id']}\n\n"
               f"{en.get('headline', '')}\n\n{en.get('body_markdown', '')}\n\n⚠️ Check:\n{verify}\n\n"
               f"Sources: {len(a.get('sources', []))} · Originality: "
               f"{(1 - (a.get('originality') or {}).get('overlap', 0)):.0%} own words\n\n"
               "Before approving (Google requires human fact-checking of AI text):\n"
               "☐ Names, dates, scores and quotes match the sources\n☐ Source links open and say what the story says\n"
               "☐ Headline is accurate, not clickbait\n☐ Nothing about private life, health, betting\n\n"
               f"Reply here:  publish {a['id']}   or   reject {a['id']}")
        try:
            telegram_send(chat, msg)
        except Exception as e:  # noqa: BLE001
            log.error("Review message failed: %s", e)


def _match(articles: list[dict], ids: list[str]) -> list[dict]:
    """Exact id match, or a prefix that matches exactly one article (safe for short typed IDs)."""
    out = []
    for i in ids:
        exact = [a for a in articles if a["id"] == i]
        pref = [a for a in articles if a["id"].startswith(i)]
        hit = exact or (pref if len(pref) == 1 else [])
        if not hit:
            log.warning("ID %r matched %d articles — skipped (use the full ID)", i, len(pref))
        out += [a for a in hit if a not in out]
    return out


def publish_articles(cfg: dict, ids: list[str], force: bool = False) -> list[str]:
    """Publish by id (prefix ok) or 'today' / 'all-drafts'. Marks status=published so the website shows it.
    Stories with a BLOCK standards problem are held back unless force=True ("publish-anyway")."""
    articles = load_articles()
    if ids in (["today"], ["all-drafts"]):
        d = today(cfg)
        targets = [a for a in articles if a["status"] == "draft" and (ids == ["all-drafts"] or a["date"] == d)]
    else:
        targets = _match(articles, ids)
    from .standards import blocking, check_article, rules, summary_lines
    held = []
    for a in targets:
        a["standards"] = check_article(cfg, a, today(cfg))
        if blocking(a["standards"]) and rules(cfg).get("block_on_publish", True) and not force:
            held.append(a)
            log.error("NOT published %s: standards problems must be fixed first:\n  %s", a["id"],
                      "\n  ".join(summary_lines(blocking(a["standards"]))))
    targets = [a for a in targets if a not in held]
    if held:
        save_articles(articles)
    done = []
    if cfg["publish"].get("photos", True):
        from .images import attach_images
        for a in targets:
            if "images" not in a:
                try:
                    attach_images(a)
                except Exception as e:  # noqa: BLE001
                    log.warning("Photos failed for %s: %s", a["id"], e)
    from .images import apply_overrides, load_overrides
    apply_overrides(articles, load_overrides())
    from .images import ensure_match_card
    for a in targets:
        ensure_match_card(a)
    from .images import unique_covers
    unique_covers(articles, only=targets)          # every story has its own cover photo
    for a in targets:
        posted = {p.get("channel") for p in a.get("published_to") or []}   # re-publishing a correction never posts twice
        if cfg["publish"].get("telegram"):
            for lang in LANGS:
                chat = os.environ.get(f"TELEGRAM_CHANNEL_{lang.upper()}")
                if not (chat and a.get(lang)) or f"telegram-{lang}" in posted:
                    continue
                try:
                    telegram_send(chat, social_text(cfg, a, lang))
                    a["published_to"].append({"channel": f"telegram-{lang}", "at": now_iso(cfg)})
                except Exception as e:  # noqa: BLE001
                    log.error("Telegram %s failed for %s: %s", lang, a["id"], e)
        if os.environ.get("DEFER_FACEBOOK") == "1":
            pass                                             # posted by the workflow's next step, once the page is live
        elif cfg["publish"].get("facebook") and facebook_ready():
            try:
                for x in facebook_send(cfg, articles, a, post=True, reel=bool(cfg["publish"].get("facebook_reels"))):
                    log.info("Facebook %s: %s", a["id"], x)
            except Exception as e:  # noqa: BLE001
                log.error("Facebook failed for %s: %s", a["id"], e)
        elif cfg["publish"].get("facebook_reels"):
            try:
                from .reels import make_reel
                for lang in ("en", "zh", "ru"):                # files only, for posting by hand
                    make_reel(cfg, a, lang)
            except Exception as e:  # noqa: BLE001
                log.error("Reel failed for %s: %s", a["id"], e)
        if a.get("status") == "published" and a.get("published_at"):
            a["republished_at"] = now_iso(cfg)      # a correction keeps its original publication time
        else:
            a["published_at"] = now_iso(cfg)
        a["status"] = "published"
        done.append(a["id"])
    save_articles(articles)
    try:
        from .reels import prune
        prune()
    except Exception:  # noqa: BLE001
        pass
    log.info("Published %d article(s)", len(done))
    return done


def set_status(ids: list[str], status: str) -> int:
    articles = load_articles()
    n = 0
    for a in _match(articles, ids):
        a["status"] = status
        n += 1
    save_articles(articles)
    return n


def send_digest(cfg: dict, date: str, items: list[dict], published: bool = False) -> None:
    user, pwd, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), os.environ.get("EMAIL_TO")
    if not (user and pwd and to):
        log.info("Email digest skipped (SMTP_USER / SMTP_PASS / EMAIL_TO not set)")
        return
    rows = []
    for a in items:
        en = a.get("en", {})
        from .standards import summary_lines
        verify = "".join(f"<li>{f}</li>" for f in (summary_lines(a.get("standards") or [], 15) or a.get("facts_to_verify", [])))
        heads = "".join(f"<div style='color:#555'>{l.upper()}: {a[l]['headline']}</div>" for l in ("zh", "ru") if a.get(l))
        body = en.get("body_markdown", "").replace("\n\n", "</p><p>")
        rows.append(
            f"<div style='border:1px solid #ddd;border-radius:8px;padding:14px;margin:14px 0'>"
            f"<div style='font-size:12px;color:#666'>{a['type'].upper()} · {a.get('sport', '')} · ID <code>{a['id']}</code></div>"
            f"<h2 style='margin:6px 0'>{en.get('headline', '')}</h2>{heads}<p>{body}</p>"
            + (f"<p><b>Check before publishing:</b></p><ul>{verify}</ul>" if verify else "")
            + "</div>")
    state = "published" if published else "drafts waiting for your approval"
    html = (f"<div style='font-family:sans-serif;max-width:680px'><h1>{cfg['site']['name']} — {date}</h1>"
            f"<p>{len(items)} {state}. To publish: GitHub › Actions › <b>Publish</b> › Run workflow › paste ID "
            f"(or <code>today</code>).</p>" + "".join(rows) + "</div>")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{cfg['site']['name']} — {date}: {len(items)} {'published' if published else 'drafts'}"
    msg["From"], msg["To"] = user, to
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "465")), timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
    log.info("Email digest sent to %s", to)
