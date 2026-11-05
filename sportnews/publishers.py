"""Telegram (one channel per language + a private review chat), Facebook (optional) and the email digest."""
from __future__ import annotations

import json
import os
import smtplib
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
    base = (os.environ.get("SITE_URL") or cfg["site"].get("url", "")).rstrip("/")
    if not base or "YOUR-GITHUB-USERNAME" in base:
        return None
    return f"{base}/{lang}/{a['slug']}.html"


def social_text(cfg: dict, a: dict, lang: str) -> str:
    L = a.get(lang) or {}
    text = f"{L.get('headline', '')}\n\n{L.get('social_post', '')}".strip()
    url = article_url(cfg, a, lang)
    return text + (f"\n\n👉 {READ_MORE[lang]}: {url}" if url else "")


def telegram_send(chat: str, text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not (token and chat):
        raise RuntimeError("TELEGRAM_BOT_TOKEN or chat id not set")
    for i in range(0, len(text), 4000):  # Telegram limit 4096
        _post(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat, "text": text[i:i + 4000]})


def facebook_post(text: str, link: str | None) -> str:
    page, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not (page and token):
        raise RuntimeError("FB_PAGE_ID / FB_PAGE_TOKEN not set")
    data = {"message": text, "access_token": token}
    if link:
        data["link"] = link
    return _post(f"https://graph.facebook.com/v21.0/{page}/feed", data).get("id", "")


def send_for_review(cfg: dict, items: list[dict]) -> None:
    """Send full drafts to your PRIVATE Telegram chat so you can read them on your phone."""
    chat = os.environ.get("TELEGRAM_REVIEW_CHAT")
    if not (chat and os.environ.get("TELEGRAM_BOT_TOKEN")):
        log.info("Telegram review skipped (TELEGRAM_REVIEW_CHAT not set)")
        return
    for a in items:
        en = a.get("en", {})
        verify = "\n".join(f"• {f}" for f in a.get("facts_to_verify", [])) or "—"
        langs = "/".join(l.upper() for l in LANGS if a.get(l))
        msg = (f"📝 DRAFT {a['type'].upper()} · {a.get('sport', '')} · {langs}\nID: {a['id']}\n\n"
               f"{en.get('headline', '')}\n\n{en.get('body_markdown', '')}\n\n⚠️ Check:\n{verify}\n\n"
               f"Sources: {len(a.get('sources', []))}\nApprove → GitHub › Actions › Publish › Run workflow › ID")
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


def publish_articles(cfg: dict, ids: list[str]) -> list[str]:
    """Publish by id (prefix ok) or 'today' / 'all-drafts'. Marks status=published so the website shows it."""
    articles = load_articles()
    if ids in (["today"], ["all-drafts"]):
        d = today(cfg)
        targets = [a for a in articles if a["status"] == "draft" and (ids == ["all-drafts"] or a["date"] == d)]
    else:
        targets = _match(articles, ids)
    done = []
    for a in targets:
        if cfg["publish"].get("telegram"):
            for lang in LANGS:
                chat = os.environ.get(f"TELEGRAM_CHANNEL_{lang.upper()}")
                if not (chat and a.get(lang)):
                    continue
                try:
                    telegram_send(chat, social_text(cfg, a, lang))
                    a["published_to"].append({"channel": f"telegram-{lang}", "at": now_iso(cfg)})
                except Exception as e:  # noqa: BLE001
                    log.error("Telegram %s failed for %s: %s", lang, a["id"], e)
        if cfg["publish"].get("facebook"):
            try:
                fid = facebook_post(social_text(cfg, a, "en"), article_url(cfg, a, "en"))
                a["published_to"].append({"channel": "facebook", "id": fid, "at": now_iso(cfg)})
            except Exception as e:  # noqa: BLE001
                log.error("Facebook failed for %s: %s", a["id"], e)
        a["status"] = "published"
        a["published_at"] = now_iso(cfg)
        done.append(a["id"])
    save_articles(articles)
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
        verify = "".join(f"<li>{f}</li>" for f in a.get("facts_to_verify", []))
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
