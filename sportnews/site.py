"""Static public website (GitHub Pages): /en /zh /ru article pages, home pages, RSS, sitemap, optional review page.

Only PUBLISHED stories appear on the public site.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
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
            out.append(f"<h2>{_inline(b.lstrip('#').strip())}</h2>")
        elif re.match(r"^[-*] ", b):
            lis = [_inline(re.sub(r"^[-*]\s*", "", ln)) for ln in b.splitlines()]
            out.append("<ul>" + "".join("<li>" + x + "</li>" for x in lis) + "</ul>")
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
    t = re.sub(r"[#*>\[\]]|\(https?://[^)]+\)", "", md or "")
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


def _page(cfg, lang, title, desc, body, alternates: dict[str, str], canonical: str, extra_head: str = "") -> str:
    css_href = "../style.css" if lang else "style.css"
    base = _base(cfg)
    alt = "".join(f'<link rel="alternate" hreflang="{HTML_LANG[l]}" href="{base}/{p}">' for l, p in alternates.items()) if base else ""
    switch = "".join(
        f'<a href="../{p}" class="{"on" if l == lang else ""}" hreflang="{HTML_LANG[l]}">{LANG_LABEL[l]}</a>'
        for l, p in alternates.items())
    home = f"../{lang}/index.html"
    return f"""<!doctype html>
<html lang="{HTML_LANG[lang]}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
{f'<link rel="canonical" href="{base}/{canonical}">' if base else ''}{alt}
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:type" content="article">
<link rel="alternate" type="application/rss+xml" href="feed.xml" title="RSS">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&family=PT+Serif:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{css_href}">
{extra_head}
</head>
<body class="l-{lang}">
<header class="mast"><div class="wrap">
  <a class="brand" href="{home}"><span class="mark">●</span>{E(_site_name(cfg, lang))}</a>
  <nav class="langs">{switch}</nav>
</div><div class="wrap tag">{E(_tagline(cfg, lang))}</div></header>
<main class="wrap">{body}</main>
<footer class="wrap foot"><span>© {datetime.now().year} {E(cfg['site']['author'])} · {E(_site_name(cfg, lang))}</span>
<span><a href="about.html">{UI[lang]['about']}</a> · <a href="feed.xml">{UI[lang]['rss']}</a></span></footer>
</body></html>"""


def _card(a, lang, prefix=""):
    L = a[lang]
    return (f'<a class="card t-{a["type"]}" href="{prefix}{a["slug"]}.html" data-type="{a["type"]}">'
            f'<span class="kick">{E(label(a["type"], lang))}{" · " + E(a.get("sport", "")) if a.get("sport") and lang == "en" else ""}</span>'
            f'<h3>{E(L["headline"])}</h3><p>{E(L.get("subheadline") or _plain(L.get("body_markdown", "")))}</p>'
            f'<time>{a["date"]}</time></a>')


def columnist(cfg, a) -> dict:
    """Pick the pen-name columnist for an article: by type (history/athlete) or detected sport."""
    cols = cfg.get("columnists") or {}
    if a["type"] in cols and a["type"] != "news":
        return cols[a["type"]]
    from .collect import detect_sport
    sport = detect_sport(f"{a.get('sport', '')} {a.get('en', {}).get('headline', '')}", cfg.get("sports", {}))
    if not sport and a.get("sport"):
        low = a["sport"].lower()
        sport = next((k for k in cols if k in low or low in k), None)
        if not sport and any(w in low for w in ("box", "mma", "ufc", "wrest", "judo", "fight")):
            sport = "combat"
        if not sport and any(w in low for w in ("athlet", "swim", "skat", "gymn", "badminton", "table tennis", "volley")):
            sport = "olympic"
    return cols.get(sport) or cols.get("default") or {"en": cfg["site"]["author"]}


def byline_name(cfg, a, lang) -> str:
    c = columnist(cfg, a)
    return c.get(lang) or c.get("en") or cfg["site"]["author"]


def _article_page(cfg, a, lang, related):
    L = a[lang]
    alternates = {l: f"{l}/{a['slug']}.html" for l in LANGS if a.get(l)}
    src = "".join(f'<li><a href="{E(s["url"])}" rel="noopener nofollow" target="_blank">{E(s["title"])}</a></li>' for s in a.get("sources", []))
    rel = "".join(_card(r, lang) for r in related)
    ld = json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "headline": L["headline"][:110],
                     "datePublished": a.get("published_at") or a["created"], "inLanguage": HTML_LANG[lang],
                     "author": {"@type": "Person", "name": byline_name(cfg, a, lang),
                                "description": "Pen name (AI-assisted), edited by " + cfg["site"]["author"]},
                     "publisher": {"@type": "Organization", "name": cfg["site"]["name"]}}, ensure_ascii=False)
    body = f"""<article class="story t-{a['type']}">
<div class="kick">{E(label(a['type'], lang))} · <time>{a['date']}</time></div>
<h1>{E(L['headline'])}</h1>
{f'<p class="dek">{E(L["subheadline"])}</p>' if L.get('subheadline') else ''}
<div class="byline"><span class="who">{E(byline_name(cfg, a, lang))}</span> · {E(columnist(cfg, a).get('beat_' + lang, ''))}
<a class="pen" href="about.html">{E(UI[lang]['pen'].format(author=cfg['site']['author']))}</a></div>
<div class="prose">{md_to_html(L.get('body_markdown', ''))}</div>
<aside class="sources"><h4>{UI[lang]['sources']}</h4><ul>{src}</ul>
<p class="ai">{E(UI[lang]['ai'].format(author=byline_name(cfg, a, lang)))}</p></aside>
</article>
{f'<section class="more"><h2 class="sec">{UI[lang]["more"]}</h2><div class="grid">{rel}</div></section>' if rel else ''}"""
    return _page(cfg, lang, f"{L['headline']} — {_site_name(cfg, lang)}", L.get("subheadline") or _plain(L.get("body_markdown", "")),
                 body, alternates, f"{lang}/{a['slug']}.html",
                 f'<script type="application/ld+json">{ld}</script>')


def _home_page(cfg, lang, items):
    alternates = {l: f"{l}/index.html" for l in LANGS}
    if not items:
        body = f'<p class="empty">{UI[lang]["empty"]}</p>'
    else:
        lead, rest = items[0], items[1:]
        L = lead[lang]
        chips = "".join(f'<button data-f="{k}">{E(label(k, lang))}</button>' for k in ("news", "history", "athlete_story"))
        body = f"""<a class="lead t-{lead['type']}" href="{lead['slug']}.html">
<span class="kick">{E(label(lead['type'], lang))} · {lead['date']}</span><h1>{E(L['headline'])}</h1>
<p>{E(L.get('subheadline') or _plain(L.get('body_markdown', ''), 220))}</p></a>
<div class="filters"><button data-f="all" class="on">{UI[lang]['all']}</button>{chips}</div>
<h2 class="sec">{UI[lang]['latest']}</h2><div class="grid" id="grid">{''.join(_card(a, lang) for a in rest)}</div>
<script>document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.filters button').forEach(x=>x.classList.toggle('on',x===b));document.querySelectorAll('#grid .card').forEach(c=>c.hidden=b.dataset.f!=='all'&&c.dataset.type!==b.dataset.f)}})</script>"""
    return _page(cfg, lang, f"{_site_name(cfg, lang)} — {_tagline(cfg, lang)}", _tagline(cfg, lang), body, alternates, f"{lang}/index.html")


ABOUT = {
    "en": ("About Bang Sport Daily", """<p>Bang Sport Daily tells the stories of world sport — the news, the history and the people — in English, Chinese and Russian.</p>
<h2>How our stories are written</h2>
<p>Every story is drafted with the help of artificial intelligence, using reports from established news outlets as sources of facts. Each story lists its sources. Nothing is published until our editor, {author}, has reviewed and approved it.</p>
<h2>Our columnists are pen names</h2>
<p>Stories are signed with <strong>pen names</strong>, one for each sport. They are not real people: they are the voices of our AI-assisted writing, each focused on one beat, and all edited by {author}.</p>
<table>{rows}</table>
<h2>Corrections</h2><p>If you find a mistake, please tell us and we will correct it.</p>"""),
    "zh": ("关于棒体育日报", """<p>棒体育日报用中文、英文和俄文讲述世界体育——新闻、历史与人物。</p>
<h2>我们的文章如何写成</h2>
<p>每篇文章都在人工智能协助下起草，事实来自权威新闻媒体，并在文末列出来源。所有文章均经主编 {author} 审核批准后才会发布。</p>
<h2>我们的专栏作者是笔名</h2>
<p>文章以<strong>笔名</strong>署名，每个运动项目一位。他们不是真实人物，而是我们 AI 辅助写作的不同声音，全部由 {author} 编辑。</p>
<table>{rows}</table>
<h2>更正</h2><p>如发现错误，请告诉我们，我们会及时更正。</p>"""),
    "ru": ("О проекте Bang Sport Daily", """<p>Bang Sport Daily рассказывает о мировом спорте — новости, история и люди — на русском, английском и китайском языках.</p>
<h2>Как пишутся наши материалы</h2>
<p>Каждый материал готовится с помощью искусственного интеллекта на основе сообщений авторитетных СМИ; источники указаны в конце. Ничего не публикуется без проверки и одобрения редактора — {author}.</p>
<h2>Наши колумнисты — псевдонимы</h2>
<p>Материалы подписаны <strong>псевдонимами</strong> — по одному на каждый вид спорта. Это не реальные люди, а голоса нашего текста, созданного с помощью ИИ; всё редактирует {author}.</p>
<table>{rows}</table>
<h2>Исправления</h2><p>Если вы нашли ошибку, сообщите нам — мы её исправим.</p>"""),
}


def _about_page(cfg, lang):
    title, body = ABOUT[lang]
    cols = cfg.get("columnists") or {}
    rows = "".join(f"<tr><td><strong>{E(c.get(lang) or c.get('en', ''))}</strong></td><td>{E(c.get('beat_' + lang, ''))}</td></tr>"
                   for k, c in cols.items() if k != "default")
    html_body = f'<article class="story"><h1>{E(title)}</h1><div class="prose about">' + body.format(author=E(cfg["site"]["author"]), rows=rows) + "</div></article>"
    return _page(cfg, lang, f"{title} — {_site_name(cfg, lang)}", title, html_body,
                 {l: f"{l}/about.html" for l in LANGS}, f"{lang}/about.html")


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
<main class="wrap"><h1 class="brand big"><span class="mark">●</span>{name}</h1>
<div class="choose"><a href="en/index.html">English</a><a href="zh/index.html">中文</a><a href="ru/index.html">Русский</a></div></main>
<script>try{{var l=(navigator.language||'en').slice(0,2);var m={{zh:'zh',ru:'ru',uk:'ru',be:'ru',kk:'ru'}}[l]||'en';
if(!sessionStorage.getItem('picked')){{sessionStorage.setItem('picked','1');location.replace(m+'/index.html')}}}}catch(e){{}}</script></body></html>"""


def build_site(cfg: dict) -> None:
    if not cfg["publish"].get("website", True):
        return
    for l in LANGS:
        shutil.rmtree(DOCS / l, ignore_errors=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE_DIR / "site.css", DOCS / "style.css")
    (DOCS / ".nojekyll").write_text("")
    all_articles = load_articles()
    pub = [a for a in all_articles if a["status"] == "published"]
    pub.sort(key=lambda a: a.get("published_at") or a["created"], reverse=True)
    urls = []
    for lang in LANGS:
        d = DOCS / lang
        d.mkdir(parents=True, exist_ok=True)
        items = [a for a in pub if a.get(lang)]
        for i, a in enumerate(items):
            related = [r for r in items if r is not a][:3]
            (d / f"{a['slug']}.html").write_text(_article_page(cfg, a, lang, related), encoding="utf-8")
            urls.append(f"{lang}/{a['slug']}.html")
        (d / "index.html").write_text(_home_page(cfg, lang, items[:60]), encoding="utf-8")
        (d / "feed.xml").write_text(_rss(cfg, lang, items), encoding="utf-8")
        (d / "about.html").write_text(_about_page(cfg, lang), encoding="utf-8")
        urls.append(f"{lang}/about.html")
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
