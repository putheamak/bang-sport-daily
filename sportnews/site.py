"""Static public website (GitHub Pages): /en /zh /ru article pages, home pages, RSS, sitemap, optional review page.

Only PUBLISHED stories appear on the public site.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import urllib.parse
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

from .common import DOCS, load_articles, log, write_json
from .exporters import label

LANGS = ("en", "zh", "ru")
HTML_LANG = {"en": "en", "zh": "zh-Hans", "ru": "ru"}
LANG_LABEL = {"en": "English", "zh": "中文", "ru": "Русский"}
UI = {
    "en": {"latest": "Latest stories", "sources": "Sources", "more": "More stories", "home": "Home",
           "ai": "Written by {author} with AI assistance, from the sources listed below.", "empty": "The first stories are coming soon.",
           "all": "All", "rss": "RSS", "pen": "Pen name · AI-assisted · edited by {author}", "about": "About us"},
    "zh": {"latest": "最新文章", "sources": "资料来源", "more": "更多文章", "home": "首页",
           "ai": "本文由 {author} 在 AI 协助下根据下列来源撰写。", "empty": "首批文章即将发布。", "all": "全部", "rss": "RSS",
           "pen": "笔名 · AI 辅助写作 · 主编 {author}", "about": "关于我们"},
    "ru": {"latest": "Последние материалы", "sources": "Источники", "more": "Ещё материалы", "home": "Главная",
           "ai": "Текст подготовлен автором {author} с помощью ИИ на основе источников ниже.", "empty": "Первые материалы скоро появятся.",
           "all": "Все", "rss": "RSS", "pen": "Псевдоним · с помощью ИИ · редактор {author}", "about": "О проекте"},
}
TEMPLATE_DIR = Path(__file__).parent
E = html.escape


def md_to_html(md: str) -> str:
    out = []
    for block in re.split(r"\n\s*\n", (md or "").strip()):
        b = block.strip()
        if not b:
            continue
        if b.startswith("#"):
            first, _, rest = b.partition("\n")
            out.append(f"<h2>{_inline(first.lstrip('#').strip())}</h2>")
            if rest.strip():
                out.append("<p>" + _inline(rest.strip()).replace("\n", "<br>") + "</p>")
        elif re.match(r"^[-*] ", b):
            lis = [_inline(re.sub(r"^[-*]\s*", "", ln)) for ln in b.splitlines()]
            out.append("<ul>" + "".join("<li>" + x + "</li>" for x in lis) + "</ul>")
        elif b.startswith("|") and len(b.splitlines()) >= 2 and re.match(r"^\|?\s*:?-{3,}", b.splitlines()[1]):
            rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in b.splitlines() if ln.strip()]
            head, body = rows[0], rows[2:]
            out.append('<div class="tablewrap"><table><thead><tr>' + "".join(f"<th>{_inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                                                         for r in body) + "</tbody></table></div>")
        elif b.startswith(">"):
            quote = _inline(re.sub(r"^>\s?", "", b, flags=re.M))
            out.append("<blockquote>" + quote + "</blockquote>")
        else:
            out.append("<p>" + _inline(b).replace("\n", "<br>") + "</p>")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = E(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener nofollow" target="_blank">\1</a>', s)


def _plain(md: str, n: int = 160) -> str:
    t = re.sub(r"\[\[img:[\w-]+\]\]", "", md or "")
    t = re.sub(r"[#*>\[\]|]|\(https?://[^)]+\)|-{3,}", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n] + ("…" if len(t) > n else "")


def _base(cfg) -> str:
    from .common import site_url
    return site_url(cfg)


def _site_name(cfg, lang):
    s = cfg["site"]
    return {"en": s["name"], "zh": s.get("name_zh", s["name"]), "ru": s.get("name_ru", s["name"])}[lang]


def _tagline(cfg, lang):
    return cfg["site"].get(f"tagline_{lang}", "")


MONTHS = {"en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
          "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
                 "ноября", "декабря"]}
UI2 = {
    "en": {"top": "Top stories", "latest_lbl": "Latest", "world": "Around the world", "world_note": "Headlines from other outlets",
           "follow": "Follow us on Telegram", "follow_btn": "Join the channel", "cols": "Our columnists", "read": "min read",
           "more_in": "More", "share": "Share", "copy": "Copy link", "copied": "Copied", "photo": "Photo", "via": "via Wikimedia Commons",
           "features": "Features", "home": "Home", "sections": "Sections", "nostories": "No stories in this section yet.",
           "small": "Stories are written with AI assistance and edited by {author}. Columnists are pen names. Photos from Wikimedia Commons contributors under their licences.",
           "latest_side": "Latest"},
    "zh": {"top": "头条", "latest_lbl": "最新", "world": "全球速递", "world_note": "来自其他媒体的标题",
           "follow": "关注我们的 Telegram 频道", "follow_btn": "加入频道", "cols": "专栏作者", "read": "分钟阅读",
           "more_in": "更多", "share": "分享", "copy": "复制链接", "copied": "已复制", "photo": "图片", "via": "来自维基共享资源",
           "features": "专题", "home": "首页", "sections": "栏目", "nostories": "本栏目暂无文章。",
           "small": "本站文章在 AI 协助下撰写，并由 {author} 编辑。专栏作者均为笔名。图片来自维基共享资源贡献者，遵循其授权协议。",
           "latest_side": "最新"},
    "ru": {"top": "Главное", "latest_lbl": "Срочно", "world": "В мире", "world_note": "Заголовки других СМИ",
           "follow": "Подписывайтесь в Telegram", "follow_btn": "Открыть канал", "cols": "Наши колумнисты", "read": "мин чтения",
           "more_in": "Ещё", "share": "Поделиться", "copy": "Скопировать ссылку", "copied": "Скопировано", "photo": "Фото",
           "via": "Викисклад", "features": "Истории", "home": "Главная", "sections": "Разделы", "nostories": "В этом разделе пока нет материалов.",
           "small": "Материалы готовятся с помощью ИИ и редактируются автором {author}. Колумнисты — псевдонимы. Фото — авторы Викисклада, по их лицензиям.",
           "latest_side": "Последнее"},
}
NAV_ORDER = ["football", "basketball", "tennis", "combat", "motorsport", "olympic", "hockey", "cricket", "history", "athlete_story"]


def fmt_date(d: str, lang: str) -> str:
    try:
        y, m, dd = (int(x) for x in d[:10].split("-"))
    except ValueError:
        return d
    if lang == "zh":
        return f"{y}年{m}月{dd}日"
    if lang == "ru":
        return f"{dd} {MONTHS['ru'][m - 1]} {y}"
    return f"{dd} {MONTHS['en'][m - 1]} {y}"


def read_minutes(L: dict, lang: str) -> int:
    body = L.get("body_markdown", "")
    n = len(re.sub(r"\s", "", body)) / 400 if lang == "zh" else len(body.split()) / (180 if lang == "ru" else 230)
    return max(1, round(n))


def sport_key(cfg, a) -> str:
    """Section of a story: history / athlete_story by type, else the detected sport (or 'default')."""
    if a["type"] in ("history", "athlete_story"):
        return a["type"]
    cols = cfg.get("columnists") or {}
    from .collect import detect_sport
    sport = detect_sport(f"{a.get('sport', '')} {a.get('en', {}).get('headline', '')}", cfg.get("sports", {}))
    if not sport and a.get("sport"):
        low = a["sport"].lower()
        sport = next((k for k in cols if k in low or low in k), None)
        if not sport and any(w in low for w in ("box", "mma", "ufc", "wrest", "judo", "fight")):
            sport = "combat"
        if not sport and any(w in low for w in ("athlet", "swim", "skat", "gymn", "badminton", "table tennis", "volley")):
            sport = "olympic"
    return sport or "default"


def stale(a, lang) -> bool:
    """A translation older than the latest English correction is hidden until it is re-translated."""
    if lang == "en" or not a.get("updated_at"):
        return False
    ts = (a.get("lang_updated") or {}).get(lang) or a.get("translated_at") or ""
    return ts < a["updated_at"]


def columnist(cfg, a) -> dict:
    """The pen-name columnist for a story (by section)."""
    cols = cfg.get("columnists") or {}
    return cols.get(sport_key(cfg, a)) or cols.get("default") or {"en": cfg["site"]["author"]}


DESK = {"en": "{s} Desk", "zh": "{s}编辑组", "ru": "Отдел «{s}»"}
AUTH_NOTE = {
    "author": {"en": "AI-assisted · reviewed by the author", "zh": "AI 辅助写作 · 作者审核", "ru": "С помощью ИИ · проверено автором"},
    "desk": {"en": "AI-assisted · edited by {author}", "zh": "AI 辅助写作 · 主编 {author}", "ru": "С помощью ИИ · редактор {author}"},
}


def byline_mode(cfg) -> str:
    return cfg["site"].get("bylines", "author")


def byline_name(cfg, a, lang) -> str:
    mode = byline_mode(cfg)
    if mode == "pen_names":
        c = columnist(cfg, a)
        return c.get(lang) or c.get("en") or cfg["site"]["author"]
    if mode == "desk":
        return DESK[lang].format(s=section_name(cfg, sport_key(cfg, a), lang))
    return cfg["site"]["author"]


def byline_note(cfg, lang) -> str:
    mode = byline_mode(cfg)
    if mode == "pen_names":
        return UI[lang]["pen"].format(author=cfg["site"]["author"])
    return AUTH_NOTE[mode][lang].format(author=cfg["site"]["author"])


def note_link(cfg) -> str:
    return "about.html#columnists" if byline_mode(cfg) == "pen_names" else "editorial.html"


def section_name(cfg, key, lang) -> str:
    c = (cfg.get("columnists") or {}).get(key, {})
    if key == "athlete_story":
        return label("athlete_story", lang)
    if key == "history":
        return label("history", lang)
    return c.get(f"beat_{lang}") or key.title()


def section_file(key) -> str:
    return f"section-{key}.html"


def initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s·\-]+", name) if p]
    if not parts:
        return "B"
    if re.search(r"[一-鿿]", name):
        return name[0]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def _img(a, i=0, cls="ph", size="") -> str:
    imgs = a.get("images") or []
    if i < len(imgs):
        im = imgs[i]
        return (f'<img class="{cls}" src="{E(im["url"])}" alt="{E(im.get("subject", ""))}" loading="lazy" '
                f'decoding="async" referrerpolicy="no-referrer">')
    return ""


def _cover(cfg, a, lang, cls="ph") -> str:
    """Photo if we have one, otherwise a designed cover in the section colour."""
    im = _img(a, 0, cls)
    if im:
        return im
    key = sport_key(cfg, a)
    return f'<div class="{cls} cover k-{key}" aria-hidden="true"><span>{E(section_name(cfg, key, lang))}</span></div>'


def _credit(im, lang) -> str:
    if im.get("parts"):             # combined photo: each part keeps its own author and licence
        bits = []
        for c in im["parts"]:
            lic = (f'<a href="{E(c["license_url"])}" rel="noopener nofollow" target="_blank">{E(c["license"])}</a>'
                   if c.get("license_url") else E(c["license"]))
            who = (f'<a href="{E(c["page"])}" rel="noopener nofollow" target="_blank">{E(c["artist"])}</a>'
                   if c.get("page") else E(c["artist"]))
            bits.append(f'{E(c.get("label", ""))}: {who} / {lic}')
        subj = f'{E(im["subject"])} · ' if im.get("subject") else ""
        return f'{subj}{UI2[lang]["photo"]}: {"; ".join(bits)} {UI2[lang]["via"]}'.rstrip()
    lic = f'<a href="{E(im["license_url"])}" rel="noopener nofollow" target="_blank">{E(im["license"])}</a>' if im.get("license_url") else E(im["license"])
    who = (f'<a href="{E(im["page"])}" rel="noopener nofollow" target="_blank">{E(im["artist"])}</a>'
           if im.get("page") else E(im["artist"]))
    via = E(im["via"]) if im.get("via") else ("" if im.get("url", "").startswith("../photos/") else UI2[lang]["via"])
    subj = f'{E(im["subject"])} · ' if im.get("subject") else ""
    return f'{subj}{UI2[lang]["photo"]}: {who} / {lic} {via}'.rstrip()


def _kicker(cfg, a, lang) -> str:
    key = sport_key(cfg, a)
    return f'<span class="kick k-{key}">{E(section_name(cfg, key, lang))}</span>'


def _page(cfg, lang, title, desc, body, alternates: dict[str, str], canonical: str, extra_head: str = "",
          ticker: list | None = None, og_image: str = "", active: str = "", noindex: bool = False) -> str:
    base = _base(cfg)
    alt = "".join(f'<link rel="alternate" hreflang="{HTML_LANG[l]}" href="{base}/{p}">' for l, p in alternates.items()) if base else ""
    if base and "en" in alternates:
        alt += f'<link rel="alternate" hreflang="x-default" href="{base}/{alternates["en"]}">'
    robots = '\n<meta name="robots" content="noindex,follow">' if noindex else ""
    ads_id = cfg["site"].get("adsense_client") or ""
    adsense = (f'\n<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={E(ads_id)}" crossorigin="anonymous"></script>'
               if ads_id else "")
    switch = "".join(f'<a href="../{p}" class="{"on" if l == lang else ""}" hreflang="{HTML_LANG[l]}">{LANG_LABEL[l]}</a>'
                     for l, p in alternates.items())
    tg = cfg["site"].get(f"telegram_{lang}") or ""
    nav = f'<a href="index.html" class="{"on" if active == "home" else ""}">{UI2[lang]["home"]}</a>' + "".join(
        f'<a href="{section_file(k)}" class="k-{k} {"on" if active == k else ""}">{E(section_name(cfg, k, lang))}</a>'
        for k in NAV_ORDER if k in (cfg.get("columnists") or {}))
    tick = ""
    if ticker:
        items = "".join(f'<a href="{t["slug"]}.html">{E(t[lang]["headline"])}</a>' for t in ticker[:8])
        tick = (f'<div class="ticker"><div class="wrap"><span class="tlabel">{UI2[lang]["latest_lbl"]}</span>'
                f'<div class="tviewport"><div class="ttrack">{items}{items}</div></div></div></div>')
    cols = cfg.get("columnists") or {}
    foot_sections = "".join(f'<li><a href="{section_file(k)}">{E(section_name(cfg, k, lang))}</a></li>' for k in NAV_ORDER if k in cols)
    og = f'<meta property="og:image" content="{E(og_image)}">' if og_image else ""
    return f"""<!doctype html>
<html lang="{HTML_LANG[lang]}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
{f'<link rel="canonical" href="{base}/{canonical}">' if base else ''}{alt}
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:type" content="article">{og}
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" href="feed.xml" title="RSS">
<link rel="preload" href="../fonts/oswald-latin-wght-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="../style.css">{robots}{adsense}
{extra_head}
</head>
<body class="l-{lang}">
<a class="skip" href="#main">Skip to content</a>
<div class="topbar"><div class="wrap">
  <span class="today" data-lang="{lang}"></span>
  <nav class="langs" aria-label="Language">{switch}</nav>
  {f'<a class="tg" href="https://t.me/{E(tg)}" target="_blank" rel="noopener">Telegram</a>' if tg else ''}
</div></div>
<header class="masthead"><div class="wrap">
  <a class="brand" href="index.html"><b>BANG</b><span>SPORT</span><i>DAILY</i></a>
  <p class="tagline">{E(_tagline(cfg, lang))}</p>
</div></header>
<nav class="sportnav" aria-label="{UI2[lang]['sections']}"><div class="wrap">{nav}</div></nav>
{tick}
<main id="main">{body}</main>
<footer class="foot"><div class="wrap fgrid">
  <div><a class="brand light" href="index.html"><b>BANG</b><span>SPORT</span><i>DAILY</i></a>
       <p>{E(_tagline(cfg, lang))}</p></div>
  <div><h4>{UI2[lang]['sections']}</h4><ul>{foot_sections}</ul></div>
  <div><h4>{E(_site_name(cfg, lang))}</h4><ul><li><a href="about.html">{UI[lang]['about']}</a></li>
       <li><a href="editorial.html">{LEGAL_T["editorial"][lang]}</a></li><li><a href="contact.html">{LEGAL_T["contact"][lang]}</a></li>
       <li><a href="privacy.html">{LEGAL_T["privacy"][lang]}</a></li><li><a href="terms.html">{LEGAL_T["terms"][lang]}</a></li>
       <li><a href="feed.xml">RSS</a></li>
       {f'<li><a href="https://t.me/{E(tg)}" target="_blank" rel="noopener">Telegram</a></li>' if tg else ''}</ul></div>
  <div><h4>Language</h4><ul>{"".join(f'<li><a href="../{p}">{LANG_LABEL[l]}</a></li>' for l, p in alternates.items())}</ul></div>
</div><div class="wrap small">© {datetime.now().year} {E(_site_name(cfg, lang))} · {E(SMALL[byline_mode(cfg) == "pen_names"][lang].format(author=cfg['site']['author']))}</div></footer>
<script>
(function(){{var el=document.querySelector('.today');if(!el)return;var l=el.dataset.lang,loc={{en:'en-GB',zh:'zh-CN',ru:'ru-RU'}}[l];
try{{el.textContent=new Date().toLocaleDateString(loc,{{weekday:'long',year:'numeric',month:'long',day:'numeric'}})}}catch(e){{}}}})();
document.querySelectorAll('[data-copy]').forEach(function(b){{b.addEventListener('click',function(){{var u=location.href;
(navigator.clipboard?navigator.clipboard.writeText(u):Promise.reject()).then(function(){{b.textContent=b.dataset.done}}).catch(function(){{prompt('',u)}})}})}});
</script>
</body></html>"""


def _card(cfg, a, lang, size="std") -> str:
    L = a[lang]
    dek = L.get("subheadline") or _plain(L.get("body_markdown", ""), 140)
    return (f'<a class="card {size}" href="{a["slug"]}.html">'
            f'<div class="media">{_cover(cfg, a, lang)}</div>'
            f'<div class="txt">{_kicker(cfg, a, lang)}<h3>{E(L["headline"])}</h3>'
            + (f'<p>{E(dek)}</p>' if size != "mini" else "")
            + f'<span class="meta">{E(byline_name(cfg, a, lang))} · <time>{fmt_date(a["date"], lang)}</time></span></div></a>')


def _fresh_wire(items: list, max_hours: int = 48) -> list:
    """Only headlines from the last 2 days: an out-of-date box is hidden instead of shown."""
    from datetime import datetime, timedelta, timezone
    cut = datetime.now(timezone.utc) - timedelta(hours=max_hours)
    out = []
    for x in items:
        try:
            if datetime.fromisoformat(str(x.get("published"))) >= cut:
                out.append(x)
        except (TypeError, ValueError):
            continue
    return out


def _rail(cfg, lang, wire, latest=None) -> str:
    parts = []
    if latest:
        parts.append(f'<section class="box"><h4 class="boxh">{UI2[lang]["latest_side"]}</h4><ol class="latest">'
                     + "".join(f'<li><a href="{a["slug"]}.html">{_kicker(cfg, a, lang)}<span>{E(a[lang]["headline"])}</span></a></li>' for a in latest)
                     + "</ol></section>")
    w = _fresh_wire((wire or {}).get(lang) or []) if cfg["site"].get("wire_box", True) else []
    if w:
        parts.append(f'<section class="box"><h4 class="boxh">{UI2[lang]["world"]}</h4><p class="note">{UI2[lang]["world_note"]}</p><ol class="wire">'
                     + "".join(f'<li><a href="{E(x["link"])}" target="_blank" rel="noopener nofollow"><span>{E(x["title"])}</span>'
                               f'<em>{E(x["source"])} ↗</em></a></li>' for x in w[:10]) + "</ol></section>")
    tg = cfg["site"].get(f"telegram_{lang}")
    if tg:
        parts.append(f'<section class="box cta"><h4>{UI2[lang]["follow"]}</h4><a class="btn" href="https://t.me/{E(tg)}" target="_blank" rel="noopener">{UI2[lang]["follow_btn"]} →</a></section>')
    if byline_mode(cfg) != "pen_names":
        bio = cfg["site"].get(f"author_bio_{lang}") or cfg["site"].get("author_bio_en", "")
        parts.append(f'<section class="box"><h4 class="boxh">{AUTHOR_T[lang]}</h4><div class="authorbox">'
                     f'<span class="mono">{E(initials(cfg["site"]["author"]))}</span><div><b>{E(cfg["site"]["author"])}</b>'
                     f'<p>{E(bio)}</p><a class="pen" href="author.html">{MORE_AUTHOR[lang]}</a> · '
                     f'<a class="pen" href="editorial.html">{LEGAL_T["editorial"][lang]}</a></div></div></section>')
        return '<aside class="rail">' + "".join(parts) + "</aside>"
    cols = cfg.get("columnists") or {}
    parts.append(f'<section class="box"><h4 class="boxh">{UI2[lang]["cols"]}</h4><ul class="cols">'
                 + "".join(f'<li><span class="mono k-{k}">{E(initials(c.get(lang) or c.get("en", "")))}</span>'
                           f'<a href="{section_file(k)}"><b>{E(c.get(lang) or c.get("en", ""))}</b><small>{E(c.get("beat_" + lang, ""))}</small></a></li>'
                           for k, c in cols.items() if k != "default")
                 + f'</ul><a class="pen" href="about.html#columnists">{E(UI[lang]["pen"].format(author=cfg["site"]["author"]))}</a></section>')
    return '<aside class="rail">' + "".join(parts) + "</aside>"


def _share(cfg, a, lang) -> str:
    url = f"{_base(cfg)}/{lang}/{a['slug']}.html" if _base(cfg) else ""
    if not url:
        return ""
    u, t = urllib.parse.quote(url, safe=""), urllib.parse.quote(a[lang]["headline"], safe="")
    nets = [("Telegram", f"https://t.me/share/url?url={u}&text={t}"),
            ("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={u}"),
            ("X", f"https://twitter.com/intent/tweet?url={u}&text={t}"),
            ("WhatsApp", f"https://wa.me/?text={t}%20{u}")]
    if lang == "ru":
        nets.insert(1, ("VK", f"https://vk.com/share.php?url={u}"))
    if lang == "zh":
        nets.insert(1, ("Weibo", f"https://service.weibo.com/share/share.php?url={u}&title={t}"))
    links = "".join(f'<a href="{h}" target="_blank" rel="noopener">{n}</a>' for n, h in nets)
    return (f'<div class="share"><span>{UI2[lang]["share"]}</span>{links}'
            f'<button type="button" data-copy data-done="{UI2[lang]["copied"]}">{UI2[lang]["copy"]}</button></div>')


def _figure(im, lang) -> str:
    return (f'<figure class="inline"><img src="{E(im["url"])}" alt="{E(im.get("subject", ""))}" loading="lazy" '
            f'referrerpolicy="no-referrer"><figcaption>{_credit(im, lang)}</figcaption></figure>')


def _body_with_images(a, lang) -> str:
    html_body = md_to_html(a[lang].get("body_markdown", ""))
    all_imgs = a.get("images") or []
    if "[[img:" in html_body:          # editor placed photos/charts: [[img:2]] = the 2nd photo of the story
        def put(m):
            key = m.group(1)
            im = next((x for x in all_imgs if x.get("ref") == key), None)
            if im is None and key.isdigit() and 0 < int(key) <= len(all_imgs):
                im = all_imgs[int(key) - 1]
            if im is None or (all_imgs and im is all_imgs[0]):
                return ""                                # missing photo, or already shown as the top photo
            return _figure(im, lang)
        return re.sub(r"<p>\[\[img:([\w-]+)\]\]</p>", put, html_body)
    imgs = all_imgs[1:3]
    if not imgs:
        return html_body
    paras = html_body.split("\n")
    slots = [3, 7]
    for im, pos in reversed(list(zip(imgs, slots))):
        if pos < len(paras):
            fig = (f'<figure class="inline"><img src="{E(im["url"])}" alt="{E(im.get("subject", ""))}" loading="lazy" '
                   f'referrerpolicy="no-referrer"><figcaption>{_credit(im, lang)}</figcaption></figure>')
            paras.insert(pos, fig)
    return "\n".join(paras)


def _article_page(cfg, a, lang, related, latest, wire):
    L = a[lang]
    key = sport_key(cfg, a)
    alternates = {l: f"{l}/{a['slug']}.html" for l in LANGS if a.get(l) and not stale(a, l)}
    src = "".join(f'<li><a href="{E(s["url"])}" rel="noopener nofollow" target="_blank">{E(s["title"])}</a></li>' for s in a.get("sources", []))
    rel = "".join(_card(cfg, r, lang) for r in related)
    name = byline_name(cfg, a, lang)
    imgs = a.get("images") or []
    hero = (f'<figure class="hero-fig">{_img(a, 0, "heroimg")}<figcaption>{_credit(imgs[0], lang)}</figcaption></figure>'
            if imgs else f'<figure class="hero-fig">{_cover(cfg, a, lang, "heroimg")}</figure>')
    ld = json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "headline": L["headline"][:110],
                     "datePublished": a.get("published_at") or a["created"], "inLanguage": HTML_LANG[lang],
                     "image": [imgs[0]["url"]] if imgs else [],
                     "dateModified": a.get("updated_at") or a.get("published_at") or a["created"],
                     "author": ({"@type": "Person", "name": cfg["site"]["author"], "url": f"{_base(cfg)}/{lang}/author.html"}
                                if byline_mode(cfg) != "pen_names" else
                                {"@type": "Person", "name": name, "description": "Pen name, edited by " + cfg["site"]["author"]}),
                     "publisher": {"@type": "Organization", "name": cfg["site"]["name"], "url": _base(cfg) or None}},
                    ensure_ascii=False)
    body = f"""<div class="wrap crumbs"><a href="index.html">{UI2[lang]['home']}</a> › <a href="{section_file(key)}">{E(section_name(cfg, key, lang))}</a></div>
<div class="wrap artgrid">
<article class="story">
  {_kicker(cfg, a, lang)}
  <h1>{E(L['headline'])}</h1>
  {f'<p class="dek">{E(L["subheadline"])}</p>' if L.get('subheadline') else ''}
  <div class="byline">
    <span class="mono k-{key}">{E(initials(name))}</span>
    <div><b>{E(name)}</b> · {E(columnist(cfg, a).get('beat_' + lang, ''))}<br>
      <small><time>{fmt_date(a['date'], lang)}</time> · {read_minutes(L, lang)} {UI2[lang]['read']} ·
      <a href="{note_link(cfg)}">{E(byline_note(cfg, lang))}</a></small></div>
  </div>
  {_share(cfg, a, lang)}
  {hero}
  <div class="prose">{_body_with_images(a, lang)}</div>
  <aside class="sources"><h4>{UI[lang]['sources']}</h4><ul>{src}</ul>
  <p class="ai">{E(UI[lang]['ai'].format(author=name))}</p></aside>
  {_share(cfg, a, lang)}
</article>
{_rail(cfg, lang, wire, latest)}
</div>
{f'<section class="wrap more"><h2 class="sech"><span>{UI[lang]["more"]}</span></h2><div class="grid g3">{rel}</div></section>' if rel else ''}"""
    return _page(cfg, lang, f"{L['headline']} — {_site_name(cfg, lang)}", L.get("subheadline") or _plain(L.get("body_markdown", "")),
                 body, alternates, f"{lang}/{a['slug']}.html", f'<script type="application/ld+json">{ld}</script>',
                 og_image=imgs[0]["url"] if imgs else "", active=key)


def _home_page(cfg, lang, items, wire):
    alternates = {l: f"{l}/index.html" for l in LANGS}
    if not items:
        body = f'<div class="wrap"><p class="empty">{UI[lang]["empty"]}</p></div>'
        return _page(cfg, lang, _site_name(cfg, lang), _tagline(cfg, lang), body, alternates, f"{lang}/index.html", active="home")
    news = [a for a in items if a["type"] == "news"] or items
    lead = news[0]
    side = [a for a in items if a is not lead][:4]
    L = lead[lang]
    used = {id(lead)} | {id(a) for a in side}
    top = [a for a in items if id(a) not in used][:6]
    athlete = next((a for a in items if a["type"] == "athlete_story"), None)
    history = next((a for a in items if a["type"] == "history"), None)
    feat = ""
    if athlete or history:
        def fcard(a):
            return (f'<a class="fcard" href="{a["slug"]}.html"><div class="media">{_cover(cfg, a, lang)}</div>'
                    f'<div class="txt">{_kicker(cfg, a, lang)}<h3>{E(a[lang]["headline"])}</h3>'
                    f'<p>{E(a[lang].get("subheadline") or _plain(a[lang].get("body_markdown", ""), 160))}</p>'
                    f'<span class="meta">{E(byline_name(cfg, a, lang))}</span></div></a>')
        feat = (f'<section class="band"><div class="wrap"><h2 class="sech light"><span>{UI2[lang]["features"]}</span></h2>'
                f'<div class="fgrid2">{"".join(fcard(a) for a in (athlete, history) if a)}</div></div></section>')
    by_sec: dict[str, list] = {}
    for a in items:
        by_sec.setdefault(sport_key(cfg, a), []).append(a)
    secs = ""
    for k in NAV_ORDER:
        if k in ("history", "athlete_story") or not by_sec.get(k):
            continue
        secs += (f'<section class="sec"><h2 class="sech k-{k}"><span>{E(section_name(cfg, k, lang))}</span>'
                 f'<a href="{section_file(k)}">{UI2[lang]["more_in"]} →</a></h2>'
                 f'<div class="grid g3">{"".join(_card(cfg, a, lang, "mini") for a in by_sec[k][:3])}</div></section>')
    body = f"""<section class="wrap hero">
  <a class="lead" href="{lead['slug']}.html">
    <div class="media">{_cover(cfg, lead, lang, "ph")}</div>
    <div class="txt">{_kicker(cfg, lead, lang)}<h1>{E(L['headline'])}</h1>
      <p>{E(L.get('subheadline') or _plain(L.get('body_markdown', ''), 220))}</p>
      <span class="meta">{E(byline_name(cfg, lead, lang))} · <time>{fmt_date(lead['date'], lang)}</time> · {read_minutes(L, lang)} {UI2[lang]['read']}</span></div>
  </a>
  <div class="side">{"".join(_card(cfg, a, lang, "row") for a in side)}</div>
</section>
<div class="wrap homegrid">
  <div class="maincol">
    {f'<section class="sec first"><h2 class="sech"><span>{UI2[lang]["top"]}</span></h2><div class="grid g3">{"".join(_card(cfg, a, lang) for a in top)}</div></section>' if top else ''}
    {secs}
  </div>
  {_rail(cfg, lang, wire)}
</div>
{feat}"""
    return _page(cfg, lang, f"{_site_name(cfg, lang)} — {_tagline(cfg, lang)}", _tagline(cfg, lang), body, alternates,
                 f"{lang}/index.html", ticker=items, og_image=(lead.get("images") or [{}])[0].get("url", ""), active="home")


def _section_page(cfg, lang, key, items, wire):
    alternates = {l: f"{l}/{section_file(key)}" for l in LANGS}
    name = section_name(cfg, key, lang)
    c = (cfg.get("columnists") or {}).get(key, {})
    col = c.get(lang) or c.get("en") or ""
    grid = "".join(_card(cfg, a, lang) for a in items) or f'<p class="empty">{UI2[lang]["nostories"]}</p>'
    body = f"""<div class="wrap sechero k-{key}"><h1>{E(name)}</h1>
{f'<p><span class="mono k-{key}">{E(initials(col))}</span> {E(col)} · <a href="about.html#columnists">{E(byline_note(cfg, lang))}</a></p>' if col and byline_mode(cfg) == "pen_names" else ''}</div>
<div class="wrap homegrid"><div class="maincol"><div class="grid g3">{grid}</div></div>{_rail(cfg, lang, wire)}</div>"""
    return _page(cfg, lang, f"{name} — {_site_name(cfg, lang)}", name, body, alternates, f"{lang}/{section_file(key)}", active=key,
                 noindex=not items)


ABOUT = {
    "en": ("About Bang Sport Daily", """<p>Bang Sport Daily tells the stories of world sport — the news, the history and the people — in English, Chinese and Russian.</p>
<h2>How our stories are written</h2>
<p>Every story is drafted with the help of artificial intelligence, using reports from established news outlets as sources of facts. Each story lists its sources. Nothing is published until our editor, {author}, has reviewed and approved it.</p>
<h2 id="columnists">Our columnists are pen names</h2>
<p>Stories are signed with <strong>pen names</strong>, one for each sport. They are not real people: they are the voices of our AI-assisted writing, each focused on one beat, and all edited by {author}.</p>
<table>{rows}</table>
<h2>Photos</h2><p>Photos come from Wikimedia Commons and are used under their free licences; each photo shows its author and licence. When no free photo exists we use a designed section cover instead.</p>
<h2>Corrections</h2><p>If you find a mistake, please tell us and we will correct it.</p>"""),
    "zh": ("关于棒体育日报", """<p>棒体育日报用中文、英文和俄文讲述世界体育——新闻、历史与人物。</p>
<h2>我们的文章如何写成</h2>
<p>每篇文章都在人工智能协助下起草，事实来自权威新闻媒体，并在文末列出来源。所有文章均经主编 {author} 审核批准后才会发布。</p>
<h2 id="columnists">我们的专栏作者是笔名</h2>
<p>文章以<strong>笔名</strong>署名，每个运动项目一位。他们不是真实人物，而是我们 AI 辅助写作的不同声音，全部由 {author} 编辑。</p>
<table>{rows}</table>
<h2>图片</h2><p>图片来自维基共享资源，按其自由授权协议使用，每张图片均注明作者与授权。若无可用的自由图片，则使用栏目设计封面。</p>
<h2>更正</h2><p>如发现错误，请告诉我们，我们会及时更正。</p>"""),
    "ru": ("О проекте Bang Sport Daily", """<p>Bang Sport Daily рассказывает о мировом спорте — новости, история и люди — на русском, английском и китайском языках.</p>
<h2>Как пишутся наши материалы</h2>
<p>Каждый материал готовится с помощью искусственного интеллекта на основе сообщений авторитетных СМИ; источники указаны в конце. Ничего не публикуется без проверки и одобрения редактора — {author}.</p>
<h2 id="columnists">Наши колумнисты — псевдонимы</h2>
<p>Материалы подписаны <strong>псевдонимами</strong> — по одному на каждый вид спорта. Это не реальные люди, а голоса нашего текста, созданного с помощью ИИ; всё редактирует {author}.</p>
<table>{rows}</table>
<h2>Фотографии</h2><p>Фотографии взяты с Викисклада и используются по свободным лицензиям; у каждой указаны автор и лицензия. Если свободного фото нет, используется оформленная обложка раздела.</p>
<h2>Исправления</h2><p>Если вы нашли ошибку, сообщите нам — мы её исправим.</p>"""),
}


def _about_page(cfg, lang):
    title, body = ABOUT[lang]
    if byline_mode(cfg) != "pen_names":
        body = re.sub(r'<h2 id="columnists">.*?</table>\n', ABOUT_AUTHOR[lang], body, flags=re.S)
    cols = cfg.get("columnists") or {}
    rows = "".join(f"<tr><td><strong>{E(c.get(lang) or c.get('en', ''))}</strong></td><td>{E(c.get('beat_' + lang, ''))}</td></tr>"
                   for k, c in cols.items() if k != "default")
    html_body = (f'<div class="wrap"><article class="story narrow"><h1>{E(title)}</h1><div class="prose about">'
                 + body.format(author=E(cfg["site"]["author"]), rows=rows) + "</div></article></div>")
    return _page(cfg, lang, f"{title} — {_site_name(cfg, lang)}", title, html_body,
                 {l: f"{l}/about.html" for l in LANGS}, f"{lang}/about.html")


LEGAL_T = {"editorial": {"en": "Editorial policy", "zh": "编辑方针", "ru": "Редакционная политика"},
           "privacy": {"en": "Privacy policy", "zh": "隐私政策", "ru": "Конфиденциальность"},
           "terms": {"en": "Terms of use", "zh": "使用条款", "ru": "Условия использования"},
           "contact": {"en": "Contact", "zh": "联系我们", "ru": "Контакты"}}
AUTHOR_T = {"en": "About the author", "zh": "关于作者", "ru": "Об авторе"}
MORE_AUTHOR = {"en": "All stories", "zh": "全部文章", "ru": "Все материалы"}
SMALL = {
    False: {"en": "Stories are written with AI assistance and reviewed by {author} before publication. Photos: Wikimedia Commons contributors, under their licences.",
            "zh": "本站文章在 AI 协助下撰写，发布前由 {author} 审核。图片来自维基共享资源贡献者，遵循其授权协议。",
            "ru": "Материалы готовятся с помощью ИИ и проверяются автором {author} перед публикацией. Фото — авторы Викисклада, по их лицензиям."},
    True: {l: UI2[l]["small"] for l in ("en", "zh", "ru")},
}
ABOUT_AUTHOR = {
    "en": '<h2 id="author">Who writes Bang Sport Daily</h2>\n<p>Every story is published under the name of its editor, {author}, who reviews and approves it. Read more on the <a href="author.html">author page</a> and in our <a href="editorial.html">editorial policy</a>.</p>\n',
    "zh": '<h2 id="author">谁在写棒体育日报</h2>\n<p>每篇文章均以审核并批准它的主编 {author} 署名。详见<a href="author.html">作者页面</a>和<a href="editorial.html">编辑方针</a>。</p>\n',
    "ru": '<h2 id="author">Кто пишет Bang Sport Daily</h2>\n<p>Каждый материал публикуется под именем редактора — {author}, который его проверяет и одобряет. Подробнее на <a href="author.html">странице автора</a> и в <a href="editorial.html">редакционной политике</a>.</p>\n',
}


def _legal_page(cfg, lang, key, store, **extra):
    from . import legal
    title, body = store[lang]
    ai_name = "Google Gemini" if cfg["ai"].get("provider", "gemini") == "gemini" else "Anthropic Claude"
    host = "GitHub Pages (GitHub, Inc.)" if not cfg["site"].get("custom_domain") else "our hosting provider"
    text = body.format(author=E(cfg["site"]["author"]), updated=legal.UPDATED, year=datetime.now().year,
                       ai_name=ai_name, host=host, **extra)
    html_body = f'<div class="wrap"><article class="story narrow"><h1>{E(title)}</h1><div class="prose about">{text}</div></article></div>'
    return _page(cfg, lang, f"{title} — {_site_name(cfg, lang)}", title, html_body,
                 {l: f"{l}/{key}.html" for l in LANGS}, f"{lang}/{key}.html")


def _author_page(cfg, lang, items):
    name = cfg["site"]["author"]
    bio = cfg["site"].get(f"author_bio_{lang}") or cfg["site"].get("author_bio_en", "")
    grid = "".join(_card(cfg, a, lang) for a in items[:30])
    body = (f'<div class="wrap sechero"><h1>{E(name)}</h1><p><span class="mono">{E(initials(name))}</span>{E(bio)}</p>'
            f'<p><a class="pen" href="editorial.html">{LEGAL_T["editorial"][lang]}</a> · <a class="pen" href="contact.html">{LEGAL_T["contact"][lang]}</a></p></div>'
            f'<div class="wrap"><div class="grid g3">{grid}</div></div>')
    ld = json.dumps({"@context": "https://schema.org", "@type": "ProfilePage",
                     "mainEntity": {"@type": "Person", "name": name, "description": bio}}, ensure_ascii=False)
    return _page(cfg, lang, f"{name} — {_site_name(cfg, lang)}", bio, body, {l: f"{l}/author.html" for l in LANGS},
                 f"{lang}/author.html", f'<script type="application/ld+json">{ld}</script>')


def _rss(cfg, lang, items):
    base = _base(cfg) or "."
    entries = "".join(
        f"<item><title>{E(a[lang]['headline'])}</title><link>{base}/{lang}/{a['slug']}.html</link>"
        f"<guid>{base}/{lang}/{a['slug']}.html</guid><description>{E(_plain(a[lang].get('body_markdown', ''), 300))}</description>"
        f"<pubDate>{format_datetime(datetime.fromisoformat(a.get('published_at') or a['created']))}</pubDate></item>"
        for a in items[:30])
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{E(_site_name(cfg, lang))}</title>'
            f"<link>{base}/{lang}/</link><description>{E(_tagline(cfg, lang))}</description><language>{HTML_LANG[lang]}</language>{entries}</channel></rss>")


ROOT_INDEX = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title><link rel="stylesheet" href="style.css"></head><body class="pick">
<main class="wrap"><h1 class="brand big"><b>BANG</b><span>SPORT</span><i>DAILY</i></h1>
<div class="choose"><a href="en/index.html">English</a><a href="zh/index.html">中文</a><a href="ru/index.html">Русский</a></div></main>
<script>try{{var l=(navigator.language||'en').slice(0,2);var m={{zh:'zh',ru:'ru',uk:'ru',be:'ru',kk:'ru'}}[l]||'en';
if(!sessionStorage.getItem('picked')){{sessionStorage.setItem('picked','1');location.replace(m+'/index.html')}}}}catch(e){{}}</script></body></html>"""


def _redirect_page(slug: str) -> str:
    t = E(slug)
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>Moved</title>'
            f'<link rel="canonical" href="{t}.html"><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={t}.html"></head>'
            f'<body><p>This story has moved: <a href="{t}.html">continue reading</a>.</p></body></html>')


def build_site(cfg: dict) -> None:
    if not cfg["publish"].get("website", True):
        return
    for l in LANGS:
        shutil.rmtree(DOCS / l, ignore_errors=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE_DIR / "site.css", DOCS / "style.css")
    shutil.copytree(TEMPLATE_DIR / "fonts", DOCS / "fonts", dirs_exist_ok=True)
    from .common import ROOT
    if (ROOT / "photos").is_dir():          # your own photos (see photos.yaml)
        shutil.copytree(ROOT / "photos", DOCS / "photos", dirs_exist_ok=True)
    (DOCS / ".nojekyll").write_text("")
    dom = (cfg["site"].get("custom_domain") or "").strip()
    if dom:
        (DOCS / "CNAME").write_text(dom + "\n")
    else:
        (DOCS / "CNAME").unlink(missing_ok=True)
    ads = (cfg["site"].get("adsense_client") or "").strip()
    if ads:
        (DOCS / "ads.txt").write_text(f"google.com, {ads.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
    else:
        (DOCS / "ads.txt").unlink(missing_ok=True)
    all_articles = load_articles()
    from .common import DATA, read_json
    wire = read_json(DATA / "wire.json", {})
    pub = [a for a in all_articles if a["status"] == "published"]
    pub.sort(key=lambda a: a.get("published_at") or a["created"], reverse=True)
    urls = []
    for lang in LANGS:
        d = DOCS / lang
        d.mkdir(parents=True, exist_ok=True)
        items = [a for a in pub if a.get(lang) and not stale(a, lang)]
        for a in items:
            key = sport_key(cfg, a)
            related = ([r for r in items if r is not a and sport_key(cfg, r) == key] + [r for r in items if r is not a])
            seen, rel = set(), []
            for r in related:
                if id(r) not in seen:
                    seen.add(id(r))
                    rel.append(r)
            latest = [r for r in items if r is not a][:5]
            (d / f"{a['slug']}.html").write_text(_article_page(cfg, a, lang, rel[:3], latest, wire), encoding="utf-8")
            urls.append(f"{lang}/{a['slug']}.html")
            for o in a.get("old_slugs") or []:          # renamed story: old links (Telegram, shares) still work
                if o != a["slug"]:
                    (d / f"{o}.html").write_text(_redirect_page(a["slug"]), encoding="utf-8")
        (d / "index.html").write_text(_home_page(cfg, lang, items[:60], wire), encoding="utf-8")
        for k in NAV_ORDER:
            if k in (cfg.get("columnists") or {}):
                sec_items = [a for a in items if sport_key(cfg, a) == k]
                (d / section_file(k)).write_text(_section_page(cfg, lang, k, sec_items[:60], wire), encoding="utf-8")
                if sec_items:
                    urls.append(f"{lang}/{section_file(k)}")
        (d / "feed.xml").write_text(_rss(cfg, lang, items), encoding="utf-8")
        (d / "about.html").write_text(_about_page(cfg, lang), encoding="utf-8")
        urls.append(f"{lang}/about.html")
        from . import legal
        email = (cfg["site"].get("contact_email") or "").strip()
        how = (f'<a href="mailto:{E(email)}">{E(email)}</a>' if email else
               (f'<a href="https://t.me/{E(cfg["site"]["telegram_" + lang])}">Telegram</a>' if cfg["site"].get("telegram_" + lang)
                else legal.NO_CONTACT[lang]))
        for key, store, extra in (("editorial", legal.EDITORIAL, {}), ("privacy", legal.PRIVACY, {}),
                                  ("terms", legal.TERMS, {}), ("contact", legal.CONTACT, {"how": how})):
            (d / f"{key}.html").write_text(_legal_page(cfg, lang, key, store, **extra), encoding="utf-8")
            urls.append(f"{lang}/{key}.html")
        if byline_mode(cfg) != "pen_names":
            (d / "author.html").write_text(_author_page(cfg, lang, items), encoding="utf-8")
            urls.append(f"{lang}/author.html")
        urls.append(f"{lang}/index.html")
    (DOCS / "index.html").write_text(ROOT_INDEX.format(name=E(cfg["site"]["name"])), encoding="utf-8")
    base = _base(cfg)
    if base:
        (DOCS / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                          + "".join(f"<url><loc>{base}/{u}</loc></url>" for u in urls) + "</urlset>", encoding="utf-8")
        (DOCS / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    # Review page with drafts — OFF by default because a GitHub Pages site is public.
    if cfg["publish"].get("drafts_on_site", False):
        shutil.copy(TEMPLATE_DIR / "dashboard.html", DOCS / "review.html")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        write_json(DOCS / "articles.json", {"site": cfg["site"], "repo": repo,
                                            "publish_workflow": f"https://github.com/{repo}/actions/workflows/publish.yml" if repo else "",
                                            "articles": all_articles[:300]})
    else:
        for f in ("review.html", "articles.json"):
            (DOCS / f).unlink(missing_ok=True)
    log.info("Website built: %d published stories, %d pages", len(pub), len(urls))
