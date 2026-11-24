"""Talking Points on the website: a page per language and a box on the home page.

Built from data/trending.json ("board", "spotlight" and "local", written by the trending radar every 4 hours).
No AI and no visitor data: each talking point shows how many independent outlets cover it, our source label,
the outlets' links, and share links so readers can discuss it on Facebook, WhatsApp, X, Telegram, VK or Weibo.
Share links are plain links: nothing loads from those services until a reader clicks one.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from html import escape as E

from .common import DATA, read_json

PAGE = "talking-points.html"

T = {
    "en": {"spot": "{s} Spotlight", "spot_note": "{n} {s} talking points right now. The spotlight moves between sports so every sport gets its turn.", "local": "Kun Khmer & Cambodia", "local_note": "Trending stories from Cambodian sport.", "other": "Other sports", "all_f": "All", "next": "next update around", "filter": "Filter by sport", "nav": "Talking Points", "title": "Talking Points",
           "intro": "What the sports world is talking about right now, ranked by how many independent news outlets are covering it.",
           "updated": "Updated every 4 hours · last update", "combat": "Combat Watch",
           "combat_note": "MMA, boxing, kickboxing, Muay Thai and Kun Khmer. Kun Khmer is always listed.",
           "wide": "Widely reported", "conf": "Confirmed", "unconf": "Unconfirmed", "outlets": "outlets", "outlet": "source",
           "since": "Trending since", "sources": "Sources", "discuss": "Discuss", "story": "Read our story",
           "copy": "Copy link", "copied": "Copied",
           "how": "How we label a talking point", "how_wide": "5 or more independent outlets",
           "how_conf": "2 to 4 independent outlets", "how_unconf": "Only 1 source so far. Treat it as a rumour.",
           "how_note": "Labels count news outlets, not opinions. Betting and tipster sites are never counted. "
                       "What readers say on social media is their own view, not Bang Sport Daily's.",
           "all": "All talking points", "empty": "No talking points right now. The next update is within 4 hours.",
           "box": "Talking Points", "box_note": "Most-covered stories right now", "share_on": "Share and discuss on",
           "desc": "The sport stories most covered by independent news outlets right now, updated every 4 hours."},
    "zh": {"spot": "{s}聚焦", "spot_note": "此刻共有 {n} 个{s}热议话题。聚焦栏目在各项目之间轮换。", "local": "高棉拳与柬埔寨", "local_note": "柬埔寨体育的热议新闻。", "other": "其他项目", "all_f": "全部", "next": "下次更新约", "filter": "按项目筛选", "nav": "热议话题", "title": "热议话题",
           "intro": "体育圈此刻在谈论什么——按报道该话题的独立新闻媒体数量排序。",
           "updated": "每 4 小时更新 · 最近更新", "combat": "格斗观察",
           "combat_note": "综合格斗、拳击、踢拳、泰拳与高棉拳。高棉拳话题始终列出。",
           "wide": "广泛报道", "conf": "已证实", "unconf": "未证实", "outlets": "家媒体", "outlet": "个来源",
           "since": "热议开始于", "sources": "来源", "discuss": "参与讨论", "story": "阅读我们的报道",
           "copy": "复制链接", "copied": "已复制",
           "how": "我们如何标注话题", "how_wide": "5 家或以上独立媒体报道", "how_conf": "2 至 4 家独立媒体报道",
           "how_unconf": "目前仅 1 个来源，请视为传闻。",
           "how_note": "标注只统计新闻媒体数量，不代表观点。博彩与竞猜网站从不计入。读者在社交媒体上的言论仅代表其个人观点。",
           "all": "查看全部热议话题", "empty": "暂无热议话题，4 小时内更新。",
           "box": "热议话题", "box_note": "此刻报道最多的体育新闻", "share_on": "分享并讨论",
           "desc": "此刻被最多独立新闻媒体报道的体育新闻，每 4 小时更新。"},
    "ru": {"spot": "В центре внимания: {s}", "spot_note": "Сейчас {n} тем по разделу «{s}». Раздел в центре внимания меняется, чтобы каждый вид спорта получил своё место.", "local": "Кун кхмер и Камбоджа", "local_note": "Обсуждаемые новости камбоджийского спорта.", "other": "Другие виды", "all_f": "Все", "next": "следующее обновление около", "filter": "Фильтр по видам спорта", "nav": "Темы дня", "title": "Темы дня",
           "intro": "О чём сейчас говорит спортивный мир: темы по числу независимых СМИ, которые о них пишут.",
           "updated": "Обновляется каждые 4 часа · последнее обновление", "combat": "Единоборства",
           "combat_note": "ММА, бокс, кикбоксинг, муай-тай и кун кхмер. Кун кхмер показываем всегда.",
           "wide": "Широко освещается", "conf": "Подтверждено", "unconf": "Не подтверждено", "outlets": "СМИ", "outlet": "источник",
           "since": "В топе с", "sources": "Источники", "discuss": "Обсудить", "story": "Читать наш материал",
           "copy": "Скопировать ссылку", "copied": "Скопировано",
           "how": "Как мы отмечаем темы", "how_wide": "5 и более независимых СМИ", "how_conf": "от 2 до 4 независимых СМИ",
           "how_unconf": "Пока только 1 источник. Считайте это слухом.",
           "how_note": "Отметки считают СМИ, а не мнения. Сайты ставок и прогнозов не учитываются. "
                       "Мнения читателей в соцсетях — их собственные, а не Bang Sport Daily.",
           "all": "Все темы дня", "empty": "Сейчас тем нет. Следующее обновление — в течение 4 часов.",
           "box": "Темы дня", "box_note": "Самые обсуждаемые в СМИ новости", "share_on": "Поделиться и обсудить",
           "desc": "Спортивные новости, о которых сейчас пишет больше всего независимых СМИ. Обновление каждые 4 часа."},
}

# share services in the order each edition's readers use most (Facebook, X, WhatsApp blocked in mainland China;
# Facebook and X blocked in Russia)
SERVICES = {"en": ["facebook", "whatsapp", "x", "telegram"], "zh": ["weibo", "telegram", "x"],
            "ru": ["telegram", "vk", "whatsapp"]}
NAMES = {"facebook": "Facebook", "whatsapp": "WhatsApp", "x": "X", "telegram": "Telegram", "vk": "VK", "weibo": "Weibo"}


def _share_url(service: str, url: str, text: str) -> str:
    u, t = urllib.parse.quote(url, safe=""), urllib.parse.quote(text, safe="")
    return {"facebook": f"https://www.facebook.com/sharer/sharer.php?u={u}",
            "whatsapp": f"https://wa.me/?text={t}%20{u}",
            "x": f"https://x.com/intent/post?text={t}&url={u}",
            "telegram": f"https://t.me/share/url?url={u}&text={t}",
            "vk": f"https://vk.com/share.php?url={u}&title={t}",
            "weibo": f"https://service.weibo.com/share/share.php?url={u}&title={t}"}[service]


def label(n: int, lang: str) -> tuple[str, str]:
    s = T[lang]
    if n >= 5:
        return "tp-wide", f'{s["wide"]} · {n} {s["outlets"]}'
    if n >= 2:
        return "tp-conf", f'{s["conf"]} · {n} {s["outlets"]}'
    return "tp-unconf", f'{s["unconf"]} · 1 {s["outlet"]}'


def load() -> dict:
    return read_json(DATA / "trending.json", {})


def _stories_by_key(articles: list[dict]) -> dict:
    return {a["trending_key"]: a for a in articles if a.get("trending_key") and a.get("status") == "published"}


def _time(iso: str | None, lang: str) -> str:
    """<time> with a plain fallback; the page's script turns it into "5 hours ago" in the reader's language."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return f'<time class="ago" datetime="{E(d.isoformat())}">{d.strftime("%d %b, %H:%M")} UTC</time>'


def _sport_name(cfg, key: str | None, lang: str) -> str:
    if not key:
        return T[lang]["other"]
    from .site import section_name
    return section_name(cfg, key, lang)


def _filters(cfg, lang: str, stories: list[dict]) -> str:
    """Sport tabs with counts, in the site's section order; plain buttons (a small script shows/hides cards)."""
    from .site import NAV_ORDER
    s = T[lang]
    counts: dict[str, int] = {}
    for st in stories:
        k = st.get("sport") or "other"
        counts[k] = counts.get(k, 0) + 1
    if len(counts) < 2:
        return ""
    order = ([k for k in NAV_ORDER if k in counts] + [k for k in counts if k not in NAV_ORDER and k != "other"]
             + (["other"] if "other" in counts else []))
    chips = f'<button type="button" class="tp-chip on" data-f="all" aria-pressed="true">{E(s["all_f"])} <b>{len(stories)}</b></button>'
    chips += "".join(f'<button type="button" class="tp-chip" data-f="{E(k)}" aria-pressed="false">'
                     f'{E(_sport_name(cfg, None if k == "other" else k, lang))} <b>{counts[k]}</b></button>' for k in order)
    return f'<div class="tp-filters" role="group" aria-label="{E(s["filter"])}">{chips}</div>'


def _since(st: dict) -> str | None:
    """The earlier of: first seen by our radar, the lead outlet's publication time."""
    vals = []
    for v in (st.get("first_seen"), st.get("published")):
        try:
            d = datetime.fromisoformat(v)
            vals.append(d if d.tzinfo else d.replace(tzinfo=timezone.utc))
        except (TypeError, ValueError):
            pass
    return min(vals).isoformat() if vals else None


def _discuss(cfg, lang: str, url: str, text: str) -> str:
    s = T[lang]
    links = "".join(f'<a class="sh-{svc}" href="{E(_share_url(svc, url, text))}" target="_blank" rel="noopener nofollow">{NAMES[svc]}</a>'
                    for svc in SERVICES[lang])
    return (f'<details class="tp-discuss"><summary>{E(s["discuss"])}</summary><div class="tp-menu" role="group" '
            f'aria-label="{E(s["share_on"])}"><span>{E(s["share_on"])}</span>{links}'
            f'<button type="button" data-copy-url="{E(url)}" data-done="{E(s["copied"])}">{E(s["copy"])}</button></div></details>')


def _item(cfg, lang: str, rank: int, st: dict, ours: dict | None, base: str) -> str:
    s = T[lang]
    cls, lab = label(st["outlets"], lang)
    anchor = f'tp-{st["key"]}'
    story_url = f'{base}/{lang}/{ours["slug"]}' if ours and base else ""
    page_url = f"{base}/{lang}/talking-points#{anchor}" if base else f"#{anchor}"
    title = (ours or {}).get(lang, {}).get("headline") if ours else None
    title = title or st["title"]
    refs = st.get("refs") or []
    src = ", ".join(f'<a href="{E(r["link"])}" target="_blank" rel="noopener nofollow">{E(r["source"])}</a>' for r in refs[:4])
    more = f' +{len(refs) - 4}' if len(refs) > 4 else ""
    kun = '<span class="tp-kun">Kun Khmer</span>' if st.get("kun_khmer") else ""
    sport = E(_sport_name(cfg, st.get("sport"), lang))
    return (f'<li class="tp-item" id="{anchor}" data-sport="{E(st.get("sport") or "other")}"><span class="tp-rank">{rank}</span><div class="tp-body">'
            f'<div class="tp-meta">{kun}<span class="tp-sport k-{E(st.get("sport") or "default")}">{sport}</span>'
            f'<span class="tp-label {cls}">{E(lab)}</span><span class="tp-since">{E(s["since"])} {_time(_since(st), lang)}</span></div>'
            f'<h2>{E(title)}</h2><p class="tp-src">{E(s["sources"])}: {src}{more}</p>'
            f'<div class="tp-actions">{_discuss(cfg, lang, story_url or page_url, title)}'
            + (f'<a class="tp-story" href="{E(ours["slug"])}.html">{E(s["story"])}</a>' if ours else "")
            + "</div></div></li>")


def page_body(cfg, lang: str, data: dict, articles: list[dict], base: str) -> str:
    s = T[lang]
    ours = _stories_by_key(articles)
    stories = (data.get("board") or {}).get(lang) or []
    items = "".join(_item(cfg, lang, i, st, ours.get(st["key"]), base) for i, st in enumerate(stories, 1))
    spot = (data.get("spotlight") or {}).get(lang) or {}
    local = (data.get("local") or {}).get(lang) or []
    sitems = "".join(_item(cfg, lang, i, st, ours.get(st["key"]), base) for i, st in enumerate(spot.get("items") or [], 1))
    litems = "".join(_item(cfg, lang, i, st, ours.get(st["key"]), base) for i, st in enumerate(local, 1))
    spot_html = ""
    if sitems:
        name = _sport_name(cfg, spot["sport"], lang)
        spot_html = (f'<section class="tp-spot k-{E(spot["sport"])}"><h2>{E(s["spot"].format(s=name))}</h2>'
                     f'<p>{E(s["spot_note"].format(n=spot.get("total") or len(spot["items"]), s=name))}</p>'
                     f'<ol class="tp-list tp-dark">{sitems}</ol></section>')
    local_html = (f'<section class="tp-local"><h2>{E(s["local"])}</h2><p>{E(s["local_note"])}</p>'
                  f'<ol class="tp-list tp-dark">{litems}</ol></section>') if litems else ""
    main = (f'<ol class="tp-list">{items}</ol>' if items else f'<p class="empty">{E(s["empty"])}</p>')
    return f"""<div class="wrap tp-head"><h1>{E(s["title"])}</h1><p class="tp-intro">{E(s["intro"])}</p>
<p class="tp-upd">{E(s["updated"])} {_time(data.get("updated"), lang)} <span class="tp-clock" data-at="{E(data.get("updated") or "")}"></span>
 · {E(s["next"])} <span class="tp-next" data-at="{E(data.get("updated") or "")}"></span></p></div>
<div class="wrap homegrid tp-grid"><div class="maincol">{_filters(cfg, lang, stories)}{main}</div>
<aside class="rail">
{local_html}{spot_html}
<section class="box tp-how"><h4 class="boxh">{E(s["how"])}</h4>
<p><span class="tp-label tp-wide">{E(s["wide"])}</span> {E(s["how_wide"])}</p>
<p><span class="tp-label tp-conf">{E(s["conf"])}</span> {E(s["how_conf"])}</p>
<p><span class="tp-label tp-unconf">{E(s["unconf"])}</span> {E(s["how_unconf"])}</p>
<p class="note">{E(s["how_note"])}</p></section>
</aside></div>
{SCRIPT}"""


def home_box(cfg, lang: str, data: dict, articles: list[dict]) -> str:
    """The Talking Points box in the home page's right column: top 5 plus the first Kun Khmer item."""
    s = T[lang]
    stories = ((data.get("board") or {}).get(lang) or [])[:5]
    if not stories:
        return ""
    kun = next(iter((data.get("local") or {}).get(lang) or []), None)
    rows = ""
    for i, st in enumerate(stories, 1):
        cls, lab = label(st["outlets"], lang)
        rows += (f'<li><a href="talking-points.html#tp-{E(st["key"])}"><b>{i}</b><span>{E(st["title"])}'
                 f'<em class="tp-label {cls}">{E(lab)}</em></span></a></li>')
    if kun:
        rows += (f'<li class="tp-kunrow"><a href="talking-points.html#tp-{E(kun["key"])}"><b>KH</b><span>'
                 f'<em class="tp-kun">Kun Khmer</em> {E(kun["title"])}</span></a></li>')
    return (f'<section class="tp-box"><h4><span class="tp-dot" aria-hidden="true"></span>{E(s["box"])}</h4>'
            f'<p>{E(s["box_note"])} · {_time(data.get("updated"), lang)}</p><ol>{rows}</ol>'
            f'<a class="tp-all" href="talking-points.html">{E(s["all"])} →</a></section>')


SCRIPT = """<script>
(function(){var l=document.documentElement.lang||'en',f;try{f=new Intl.RelativeTimeFormat(l,{numeric:'auto'})}catch(e){return}
document.querySelectorAll('time.ago').forEach(function(t){var m=(Date.now()-new Date(t.getAttribute('datetime')))/60000;if(isNaN(m))return;
t.textContent=m<60?f.format(-Math.max(1,Math.round(m)),'minute'):m<2880?f.format(-Math.round(m/60),'hour'):f.format(-Math.round(m/1440),'day')});
document.querySelectorAll('[data-copy-url]').forEach(function(b){b.addEventListener('click',function(){var u=b.getAttribute('data-copy-url');
(navigator.clipboard?navigator.clipboard.writeText(u):Promise.reject()).then(function(){b.textContent=b.dataset.done}).catch(function(){prompt('',u)})})});
var tf={hour:'2-digit',minute:'2-digit'};
document.querySelectorAll('.tp-clock').forEach(function(c){var d=new Date(c.dataset.at);if(!isNaN(d))c.textContent='('+d.toLocaleTimeString(l,tf)+')'});
document.querySelectorAll('.tp-next').forEach(function(c){var d=new Date(c.dataset.at);if(isNaN(d))return;c.textContent=new Date(d.getTime()+4*3600000).toLocaleTimeString(l,tf)});
document.querySelectorAll('.tp-filters').forEach(function(g){var bs=g.querySelectorAll('.tp-chip'),list=g.parentNode.querySelector('.tp-list');
bs.forEach(function(b){b.addEventListener('click',function(){var f=b.dataset.f;bs.forEach(function(x){var on=x===b;x.classList.toggle('on',on);x.setAttribute('aria-pressed',on)});
list.querySelectorAll('.tp-item').forEach(function(it){it.hidden=!(f==='all'||it.dataset.sport===f)})})})});
document.querySelectorAll('.tp-discuss').forEach(function(d){d.addEventListener('toggle',function(){if(d.open)document.querySelectorAll('.tp-discuss[open]').forEach(function(o){if(o!==d)o.open=false})})});
})();
</script>"""
