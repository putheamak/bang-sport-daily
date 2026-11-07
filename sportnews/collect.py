"""Pull global sport news from free RSS feeds, detect the sport, cluster duplicates and rank by importance.

Importance = how many outlets cover the story (coverage) x sport weight + big-event boost + freshness.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
from rapidfuzz import fuzz

from .common import SEEN, log, read_json, short_hash, write_json

UA = "BangSportDaily/1.0 (+https://github.com)"
TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None


def detect_sport(text: str, sports: dict) -> str | None:
    text = text.lower()
    best, hits = None, 0
    for name, spec in sports.items():
        n = sum(1 for k in spec.get("keywords", []) if k in text)
        if n > hits:
            best, hits = name, n
    return best


def parse_feed(feed: dict, cfg: dict, max_age_hours: int = 36, raw: bytes | str | None = None) -> list[dict]:
    """Parse one feed. `raw` lets tests pass fixture content."""
    try:
        parsed = feedparser.parse(raw if raw is not None else feed["url"], agent=UA)
    except Exception as e:  # noqa: BLE001
        log.warning("Feed failed %s: %s", feed["name"], e)
        return []
    if parsed.get("bozo") and not parsed.entries:
        log.warning("Feed unreadable %s: %s", feed["name"], parsed.get("bozo_exception"))
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    block = [b.lower() for b in cfg.get("block", [])]
    items = []
    for e in parsed.entries:
        pub = _published(e)
        if pub and pub < cutoff:
            continue
        title = _clean(e.get("title", ""))
        source = feed["name"]
        if "news.google.com" in feed.get("url", "") and " - " in title:   # "Headline - Publisher"
            title, source = title.rsplit(" - ", 1)
        summary = _clean(e.get("summary", ""))[:800]
        text = f"{title} {summary}".lower()
        if not title or any(b in text for b in block):
            continue
        items.append({
            "id": short_hash(e.get("link", "") + title),
            "title": title, "summary": summary, "link": e.get("link", ""),
            "source": source, "feed": feed["name"], "lang": feed.get("lang", "en"),
            "published": pub.isoformat() if pub else None,
            "sport": detect_sport(text, cfg.get("sports", {})),
        })
    log.info("%-32s %3d items", feed["name"], len(items))
    return items


def cluster(items: list[dict], seen_titles: list[str], threshold: int = 72) -> list[dict]:
    """Merge the same story reported by several outlets; drop stories already written before."""
    out: list[dict] = []
    for it in sorted(items, key=lambda x: x["published"] or "", reverse=True):
        t = it["title"].lower()
        if any(fuzz.token_set_ratio(t, s) >= 85 for s in seen_titles):
            continue
        dup = next((o for o in out if o["lang"] == it["lang"] and fuzz.token_set_ratio(t, o["title"].lower()) >= threshold), None)
        if dup:
            if it["source"] != dup["source"] and all(r["source"] != it["source"] for r in dup.get("also_reported_by", [])):
                dup.setdefault("also_reported_by", []).append({"source": it["source"], "link": it["link"], "title": it["title"]})
            dup["sport"] = dup["sport"] or it["sport"]
            continue
        out.append(dict(it))
    return out


def score(item: dict, cfg: dict) -> float:
    sports = cfg.get("sports", {})
    weight = sports.get(item["sport"], {}).get("weight", 0.4) if item["sport"] else 0.4
    if weight <= 0:
        return 0
    coverage = 1 + len(item.get("also_reported_by", []))
    text = f"{item['title']} {item['summary']}".lower()
    boost = sum(1.5 for k in cfg.get("boost", []) if k in text)
    fresh = 0.0
    if item["published"]:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(item["published"])).total_seconds() / 3600
        fresh = max(0.0, 1.5 - age_h / 16)
    return round(weight * coverage + boost + fresh, 2)


def select(items: list[dict], n: int, max_per_sport: int) -> list[dict]:
    picked, per = [], {}
    for it in sorted(items, key=lambda x: -x["score"]):
        key = it["sport"] or "other"
        if per.get(key, 0) >= max_per_sport:
            continue
        picked.append(it)
        per[key] = per.get(key, 0) + 1
        if len(picked) >= n:
            break
    return picked


def fetch_full_text(url: str, limit: int = 6000) -> str:
    """Best-effort article body extraction for direct publisher links (used as facts only)."""
    if not url or "news.google.com" in url:
        return ""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        return (trafilatura.extract(downloaded) or "")[:limit] if downloaded else ""
    except Exception as e:  # noqa: BLE001
        log.info("Full-text extraction failed for %s: %s", url, e)
        return ""


_LAST: list[dict] = []


WIRE_CLICKBAIT = re.compile(
    r"[!！]|you won'?t believe|shocking|jaw[- ]dropping|insane|mind[- ]blowing|what happened next|"
    r"шок|сенсаци|вы не поверите|невероятн|скандал|самородок|"
    r"震惊|竟然|惊呆|万万没想到|太离谱|炸裂|重磅", re.I)


def _src_key(name: str) -> str:
    """One key per outlet, so 'Championat' and 'https://www.championat.ru/' count as the same source."""
    k = re.sub(r"^https?://(www\.)?|/+$", "", (name or "").lower().strip())
    k = re.sub(r"\.(ru|com|cn|com\.cn|co\.uk|net|org)$", "", k)
    for cyr, lat in (("чемпионат", "championat"), ("спорт-экспресс", "sport-express"), ("риа новости", "ria")):
        k = k.replace(cyr, lat)
    for brand in ("championat", "sport-express", "sports.ru", "ria", "bbc", "guardian", "sky sports", "espn",
                  "新华", "人民", "中国新闻", "中新", "央视", "新浪"):
        if brand in k:
            return brand
    return k


def _src_name(name: str) -> str:
    """Show a web address as a plain outlet name (https://www.championat.ru/ -> championat.ru)."""
    return re.sub(r"^https?://(www\.)?|/+$", "", name or "") if (name or "").startswith("http") else name


MAJOR_MEDIA = re.compile(
    r"bbc|guardian|sky sports|espn|reuters|associated press|\bap\b|al jazeera|nbc sports|cbs sports|cnn|the athletic|"
    r"the independent|telegraph|the times|marca|as\.com|l'équipe|gazzetta|kicker|fifa|uefa|olympics|"
    r"新华|央视|cctv|人民|新浪|腾讯|澎湃|中国新闻|中新|体坛|懂球帝|olympic|"
    r"championat|чемпионат|спорт-экспресс|sport-express|тасс|риа|матч|sports\.ru|советский спорт|рбк|коммерсант", re.I)


def mix_sources(items: list[dict], n: int = 12, per_source: int = 2) -> list[dict]:
    """Pick headlines from many different major outlets: major media first, at most `per_source` per outlet,
    taken in turn (BBC, Guardian, Sky, ...) so no single outlet fills the box."""
    def pick(pool, out, used):
        groups: dict[str, list] = {}
        for i in pool:
            groups.setdefault(_src_key(i.get("source", "")), []).append(i)
        rnd = 0
        while len(out) < n and any(len(g) > rnd for g in groups.values()):
            for src, g in groups.items():
                if len(out) >= n:
                    break
                if len(g) > rnd and used.get(src, 0) < per_source:
                    out.append(g[rnd]); used[src] = used.get(src, 0) + 1
            rnd += 1
    out, used = [], {}
    pick([i for i in items if MAJOR_MEDIA.search(i.get("source", ""))], out, used)
    pick([i for i in items if not MAJOR_MEDIA.search(i.get("source", "")) and i not in out], out, used)
    return out


def save_wire(cfg: dict, per_lang: int = 12) -> None:
    """Save today's top headlines per language (links to the original outlets) for the 'Around the world' box."""
    from .common import DATA
    if not _LAST:
        return
    from .standards import BETTING
    wire = {"_updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for lang in ("en", "zh", "ru"):
        items = mix_sources([i for i in _LAST if i["lang"] == lang and not BETTING.search(i["title"])
                             and not WIRE_CLICKBAIT.search(i["title"])], per_lang)
        wire[lang] = [{"title": i["title"], "source": _src_name(i["source"]), "link": i["link"], "sport": i.get("sport"),
                       "published": i.get("published")} for i in items]
    write_json(DATA / "wire.json", wire)


def collect(cfg: dict) -> list[dict]:
    seen = read_json(SEEN, {"titles": []})
    items: list[dict] = []
    for feed in cfg.get("feeds", []):
        items.extend(parse_feed(feed, cfg))
    items = cluster(items, seen["titles"][-2000:])
    for it in items:
        it["score"] = score(it, cfg)
    items = [i for i in items if i["score"] > 0]
    items.sort(key=lambda x: -x["score"])
    _LAST[:] = items
    log.info("Candidate stories after clustering: %d", len(items))
    return items


def mark_seen(titles: list[str]) -> None:
    seen = read_json(SEEN, {"titles": []})
    seen["titles"] = (seen["titles"] + [t.lower() for t in titles])[-4000:]
    write_json(SEEN, seen)
