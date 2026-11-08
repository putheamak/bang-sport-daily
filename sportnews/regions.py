"""Regional balance: which part of the world a story is about, and which region is behind its weekly target.

Targets live in config.yaml under `regions:` (shares of all stories over a rolling window, default 7 days).
The quota is a TARGET, never a reason to publish a weak story: if a region has no good candidate today,
the slot goes to the best story from the next region that is behind.
"""
from __future__ import annotations

import re
from datetime import date as Date, timedelta

ORDER = ["cambodia", "sea", "china", "russia", "global"]          # most specific first
LABEL = {"global": "Global", "china": "China", "russia": "Russia", "sea": "Southeast Asia", "cambodia": "Cambodia"}
DEFAULT_TARGETS = {"global": 45, "china": 15, "russia": 15, "sea": 15, "cambodia": 10}

_KW = {
    "cambodia": r"cambodia|cambodian|khmer|phnom penh|siem reap|svay rieng|visakha|boeung ket|preah khan reach|"
                r"angkor tiger|kun khmer|bokator|morodok techo|柬埔寨|金边|камбодж|пномпень",
    "sea": r"southeast asia|south-east asia|asean|\baff\b|mitsubishi electric cup|sea games|thailand|thai\b|bangkok|"
           r"buriram|vietnam|vietnamese|hanoi|ho chi minh|indonesia|indonesian|jakarta|persib|persija|malaysia|"
           r"malaysian|kuala lumpur|johor darul|philippines|filipino|manila|singapore|singaporean|myanmar|laos|lao\b|"
           r"brunei|timor-leste|muay thai|pacquiao|lee chong wei|ratchanok|"
           r"东南亚|泰国|越南|印尼|马来西亚|菲律宾|新加坡|юго-восточн|таиланд|вьетнам|индонези|малайзи|филиппин|сингапур",
    "china": r"\bchina\b|chinese|beijing|shanghai|guangzhou|shenzhen|chengdu|wuhan|hangzhou|\bcsl\b|super league china|"
             r"chinese super league|\bcba\b|hong kong|macau|taipei|"
             r"中国|国足|女足|女排|中超|中甲|CBA|全运|省运|北京|上海|广州|深圳|杭州|成都|武汉|香港|台北|"
             r"китай|китайск|пекин|шанха",
    "russia": r"russia|russian|moscow|st petersburg|saint petersburg|kazan|sochi|zenit|spartak|cska|lokomotiv|"
              r"dynamo moscow|krasnodar|\bkhl\b|\brpl\b|ovechkin|kaprizov|medvedev|rublev|khabib|"
              r"росси|русск|москв|петербург|казан|сочи|зенит|спартак|цска|локомотив|динамо|краснодар|кхл|рпл|"
              r"俄罗斯|莫斯科",
}
_RX = {k: re.compile(v, re.I) for k, v in _KW.items()}


def classify(text: str, lang: str = "en") -> str:
    """Region of a story from its title/summary. Russian- or Chinese-language items count for that country
    only when they are about it (an NBA story in Chinese is still 'global')."""
    t = text or ""
    for region in ORDER[:-1]:
        if _RX[region].search(t):
            return region
    return "global"


def targets(cfg: dict) -> dict:
    t = dict(DEFAULT_TARGETS)
    t.update({k: v for k, v in ((cfg or {}).get("regions") or {}).items() if k in DEFAULT_TARGETS})
    total = sum(t.values()) or 1
    return {k: v / total for k, v in t.items()}


def article_region(a: dict) -> str:
    if a.get("region") in DEFAULT_TARGETS:
        return a["region"]
    en = a.get("en") or {}
    return classify(" ".join([en.get("headline", ""), en.get("subheadline", ""), " ".join(a.get("tags") or [])]))


def counts(articles: list[dict], today: str, days: int = 7) -> dict:
    """Stories per region in the last `days` days (published + drafts waiting; rejected ones don't count)."""
    start = (Date.fromisoformat(today) - timedelta(days=days - 1)).isoformat()
    c = {k: 0 for k in DEFAULT_TARGETS}
    for a in articles:
        if a.get("status") == "rejected" or str(a.get("date", "")) < start:
            continue
        c[article_region(a)] += 1
    return c


def deficits(cfg: dict, c: dict, extra: int = 1) -> list[tuple[str, float]]:
    """Regions sorted by how far behind target they are, if `extra` more stories were written."""
    t = targets(cfg)
    total = sum(c.values()) + extra
    return sorted(((r, t[r] * total - c.get(r, 0)) for r in t), key=lambda x: -x[1])


def pick_balanced(cfg: dict, items: list[dict], n: int, c: dict, max_per_sport: int = 1,
                  min_share: float = 0.6) -> list[dict]:
    """Choose n news items, each time from the region furthest behind its target that has a good candidate.
    'Good' = score at least `min_share` (60%) of the best score available (quality first)."""
    c = dict(c)
    pool = sorted(items, key=lambda x: -x["score"])
    for it in pool:
        it.setdefault("region", classify(f"{it.get('title', '')} {it.get('summary', '')}", it.get("lang", "en")))
    picked, per_sport = [], {}
    while len(picked) < n:
        avail = [i for i in pool if i not in picked and per_sport.get(i.get("sport") or "other", 0) < max_per_sport]
        if not avail:
            break
        bar = avail[0]["score"] * min_share
        choice = None
        for region, gap in deficits(cfg, c):
            cand = [i for i in avail if i["region"] == region and i["score"] >= bar]
            if cand:
                choice = cand[0]
                break
        choice = choice or avail[0]
        picked.append(choice)
        per_sport[choice.get("sport") or "other"] = per_sport.get(choice.get("sport") or "other", 0) + 1
        c[choice["region"]] = c.get(choice["region"], 0) + 1
    return picked


def next_region(cfg: dict, c: dict) -> str:
    return deficits(cfg, c)[0][0]


def balance_line(cfg: dict, c: dict) -> str:
    total = sum(c.values()) or 1
    t = targets(cfg)
    return " · ".join(f"{LABEL[r]} {c.get(r, 0) * 100 // total}% (target {round(t[r] * 100)}%)"
                      for r in ["global", "china", "russia", "sea", "cambodia"])
