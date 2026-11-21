"""One interface over the AI providers: Gemini (free tier), Claude (paid) or mock (no key, for testing).

generate(cfg, system, prompt, search) -> (text, sources)
"""
from __future__ import annotations

import os
import re
import time

from .common import log

EXCLUDE = ("image", "tts", "audio", "live", "embedding", "vision", "computer", "robotics", "thinking-exp", "learnlm")


def provider(cfg: dict) -> str:
    if os.environ.get("SPORTNEWS_MOCK") == "1":
        return "mock"
    p = cfg["ai"].get("provider", "gemini")
    if p == "gemini" and not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        return "mock"
    if p == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        return "mock"
    return p


# ------------------------------------------------------------------ Gemini
def _version(name: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def pick_gemini_model(names: list[str], lite: bool) -> str | None:
    """Choose the newest Flash (or Flash-Lite) model, preferring stable over preview."""
    cands = []
    for n in names:
        n = n.split("/")[-1]
        if "flash" not in n or any(x in n for x in EXCLUDE):
            continue
        if ("lite" in n) != lite:
            continue
        if n.endswith("-latest"):
            continue
        preview = any(x in n for x in ("preview", "exp"))
        cands.append((not preview, _version(n), -len(n), n))
    return max(cands)[3] if cands else None


def gemini_candidates(names: list[str]) -> list[str]:
    """Ordered fallback chain: stable Flash (newest first) -> preview Flash -> Flash-Lite -> aliases."""
    seen, out = set(), []
    def add(n):
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    flash = [n.split("/")[-1] for n in names]
    flash = [n for n in flash if "flash" in n and not any(x in n for x in EXCLUDE) and not n.endswith("-latest")]
    key = lambda n: (_version(n), -len(n))
    for lite in (False, True):
        group = [n for n in flash if ("lite" in n) == lite]
        for n in sorted([n for n in group if not any(x in n for x in ("preview", "exp"))], key=key, reverse=True)[:2]:
            add(n)
        for n in sorted([n for n in group if any(x in n for x in ("preview", "exp"))], key=key, reverse=True)[:1]:
            add(n)
    add("gemini-flash-latest")
    add("gemini-flash-lite-latest")
    return out


_STATE = {"chain": None, "dead": set(), "no_search": False, "broken": None}


# ---- daily quota memory (shared by all runs of the day through data/gemini_quota.json) ----
# The free quota resets at midnight Pacific time (15:00 in Cambodia). Once a model says its DAILY quota is
# used up, every later run that day skips it straight away instead of spending requests on certain failures.
def _quota_day() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def _quota() -> dict:
    if _STATE.get("quota") is None or _STATE["quota"].get("day") != _quota_day():
        from . import common
        q = common.read_json(common.DATA / "gemini_quota.json", {})
        if q.get("day") != _quota_day():
            q = {"day": _quota_day(), "exhausted": [], "no_search": False, "usage": {}}
        _STATE["quota"] = q
    return _STATE["quota"]


def _save_quota() -> None:
    from . import common
    try:
        common.write_json(common.DATA / "gemini_quota.json", _quota())
    except Exception as e:  # noqa: BLE001
        log.warning("Could not save Gemini quota file: %s", str(e)[:200])


def _count(model: str, ok: bool, resp=None) -> None:
    u = _quota()["usage"].setdefault(model, {"ok": 0, "fail": 0})
    u["ok" if ok else "fail"] += 1
    um = getattr(resp, "usage_metadata", None) if resp is not None else None
    if um is not None:
        u["in"] = u.get("in", 0) + (getattr(um, "prompt_token_count", 0) or 0)
        # thinking tokens are billed as output
        u["out"] = u.get("out", 0) + (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
    _save_quota()


def _price(model: str) -> tuple[float, float] | None:
    """US$ per 1M input / output tokens from config (ai.gemini.prices); None if unknown."""
    prices = (_STATE.get("prices") or {})
    for key in sorted(prices, key=len, reverse=True):
        if key in model:
            p = prices[key]
            return float(p[0]), float(p[1])
    return None


def _spend_cap_hit(msg: str) -> bool:
    """True when a 429 is the AI Studio project spend cap ("Your project has exceeded its monthly spending cap")."""
    m = msg.lower()
    return "spending cap" in m or "spend cap" in m


def _daily_limit(msg: str) -> bool:
    """True when a 429 is the per-DAY quota (waiting a minute will not help)."""
    m = msg.lower().replace("_", "")
    return "perday" in m or "per day" in m or "requestsperday" in m or "daily" in m


def usage_summary() -> str:
    q = _quota()
    parts, cost, known = [], 0.0, False
    for m, u in sorted(q["usage"].items()):
        bit = f"{m} {u['ok']} ok / {u['fail']} failed"
        if u.get("in") or u.get("out"):
            bit += f" ({u.get('in', 0):,} in / {u.get('out', 0):,} out tokens)"
            pr = _price(m)
            if pr:
                known = True
                cost += u.get("in", 0) / 1e6 * pr[0] + u.get("out", 0) / 1e6 * pr[1]
        parts.append(bit)
    out = f"Gemini today ({q['day']}, Pacific): " + ("; ".join(parts) if parts else "no requests")
    if known:
        out += f" · estimated cost if billed: US${cost:.3f}"
    if q["exhausted"]:
        out += " · daily quota used up: " + ", ".join(q["exhausted"])
    return out


def _log_summary() -> None:
    if _STATE.get("quota") and _STATE["quota"].get("usage"):
        log.info(usage_summary())


import atexit  # noqa: E402
atexit.register(_log_summary)


def _chain(client, cfg) -> list[str]:
    if _STATE["chain"] is None:
        wanted = cfg["ai"]["gemini"].get("model", "auto")
        names = []
        try:
            for m in client.models.list():
                if "generateContent" in (getattr(m, "supported_actions", None) or ["generateContent"]):
                    names.append(m.name)
        except Exception as e:  # noqa: BLE001
            log.warning("Could not list Gemini models: %s", str(e)[:300])
        chain = gemini_candidates(names)
        if not cfg["ai"]["gemini"].get("allow_lite", True):      # paid tier: Flash only, no weaker Lite drafts
            chain = [c for c in chain if "lite" not in c]
        if wanted not in ("auto", "auto-lite"):
            chain = [wanted] + [c for c in chain if c != wanted]
        _STATE["chain"] = chain
        log.info("Gemini models available: %d · fallback chain: %s", len(names), " > ".join(chain))
    skip = set(_STATE["dead"]) | set(_quota()["exhausted"])
    chain = [m for m in _STATE["chain"] if m not in skip]
    if _quota()["exhausted"] and not _STATE.get("told_skip"):
        _STATE["told_skip"] = True
        log.info("Skipping models whose daily free quota is used up: %s", ", ".join(_quota()["exhausted"]))
    return chain


def _classify(msg: str) -> str:
    m = msg.lower()
    if "429" in m or "resource_exhausted" in m or "quota" in m:
        return "dead" if ("limit: 0" in m or "free_tier" in m and "limit" in m and ": 0" in m) else "rate"
    if "404" in m or "not found" in m or "not supported" in m or "is not available" in m:
        return "dead"
    if ("400" in m or "invalid_argument" in m) and any(k in m for k in ("search", "tool", "grounding")):
        return "no_search"
    if "api key" in m or "api_key" in m or "permission" in m or "403" in m or "401" in m:
        return "auth"
    if any(k in m for k in ("500", "503", "unavailable", "internal", "deadline", "timeout")):
        return "busy"
    return "other"


def _gemini(cfg: dict, system: str, prompt: str, search: bool, images=None) -> tuple[str, list[dict], str]:
    from google import genai
    from google.genai import types

    gcfg = cfg["ai"]["gemini"]
    _STATE["prices"] = gcfg.get("prices") or {}
    if _STATE["broken"]:
        raise RuntimeError("Skipped — Gemini already failed on every model this run: " + _STATE["broken"])
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
                          http_options=types.HttpOptions(timeout=int(gcfg.get("request_timeout", 120)) * 1000))
    errors = []
    started = time.monotonic()
    budget = gcfg.get("call_budget_seconds", 480)      # give up on one call after ~8 minutes
    for _round in range(2):
        chain = _chain(client, cfg)
        if not chain:
            break
        for model in chain:
            if time.monotonic() - started > budget:
                errors.append("time budget used up (Gemini overloaded)")
                break
            use_search = search and gcfg.get("google_search", True) and not _STATE["no_search"] and not _quota()["no_search"]
            for attempt in range(3):
                tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
                try:
                    contents = ([prompt] + [types.Part.from_bytes(data=b, mime_type=m) for b, m in images]) if images else prompt
                    resp = client.models.generate_content(
                        model=model, contents=contents,
                        config=types.GenerateContentConfig(system_instruction=system, tools=tools, temperature=0.7,
                                                           max_output_tokens=cfg["ai"].get("max_output_tokens", 12000)))
                    text = resp.text or ""
                    if not text.strip():
                        raise RuntimeError("empty response (possibly blocked or out of tokens)")
                    sources = []
                    try:
                        gm = resp.candidates[0].grounding_metadata
                        for ch in (gm.grounding_chunks or []) if gm else []:
                            if ch.web and ch.web.uri:
                                sources.append({"title": ch.web.title or ch.web.domain or ch.web.uri, "url": ch.web.uri})
                    except (AttributeError, IndexError, TypeError):
                        pass
                    _count(model, True, resp)
                    time.sleep(gcfg.get("pause_seconds", 8))
                    return text, sources, model
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    kind = _classify(msg)
                    _count(model, False)
                    errors.append(f"{model}: {kind}{' +search' if use_search else ''}: {msg[:160]}")
                    if not _STATE.get("logged_full"):
                        _STATE["logged_full"] = True
                        log.warning("First Gemini error in full: %s", msg[:3000])
                    log.warning("Gemini %s failed [%s]%s: %s", model, kind, " (with search)" if use_search else "", msg[:200])
                    if _spend_cap_hit(msg):
                        # The AI Studio monthly spend cap applies to the whole project: every model and every retry
                        # will get the same answer until the 1st of next month (or until the cap is raised).
                        _STATE["broken"] = "monthly spend cap reached"
                        log.error("Gemini monthly spend cap reached — no more AI writing this month. "
                                  "Raise it in AI Studio > Spend > Monthly spend cap if you want more stories.")
                        raise RuntimeError("Gemini monthly spend cap reached (AI Studio > Spend)") from e
                    if "429" in msg and use_search:
                        # The Google Search grounding quota is separate and is often the one that is 0.
                        log.warning("Retrying %s WITHOUT Google Search", model)
                        _STATE["no_search"] = True
                        _quota()["no_search"] = True       # the search quota is daily: keep it off until the reset
                        _save_quota()
                        use_search = False
                        continue
                    if kind == "auth":
                        _STATE["broken"] = "API key rejected"
                        raise RuntimeError("Gemini API key rejected — check the GEMINI_API_KEY secret") from e
                    if kind == "no_search" and use_search:
                        _STATE["no_search"] = True
                        use_search = False
                        continue
                    if kind == "dead":
                        _STATE["dead"].add(model)
                        break
                    if kind == "rate":
                        # Gemini's 429 does not say whether the per-minute or the per-day limit was hit. We wait once
                        # (per-minute limits clear in under a minute); a second 429 means the day's quota is gone,
                        # so the model is skipped by every run until the reset at 15:00 Cambodia time.
                        waited = _STATE.setdefault("waited", set())
                        if _daily_limit(msg) or model in waited:
                            q = _quota()
                            if model not in q["exhausted"]:
                                q["exhausted"].append(model)
                                _save_quota()
                            log.warning("%s: daily free quota used up; skipped until 15:00 Cambodia time", model)
                            break
                        waited.add(model)
                        time.sleep(35)
                        continue
                    if kind == "busy" and attempt == 0:
                        time.sleep(20)
                        continue
                    if kind == "other" and use_search and attempt == 0:
                        use_search = False   # retry once without search
                        continue
                    break
        if not _chain(client, cfg):
            break                              # every model is out of quota for today: do not wait and retry
        if _round == 0 and time.monotonic() - started < budget:
            time.sleep(30)
    _STATE["broken"] = " | ".join(errors[-6:])
    raise RuntimeError("Gemini failed on every model: " + _STATE["broken"])


# ------------------------------------------------------------------ Claude (optional, paid)
def _claude(cfg: dict, system: str, prompt: str, search: bool) -> tuple[str, list[dict], str]:
    import anthropic

    c = cfg["ai"]["claude"]
    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": c.get("web_search_max_uses", 4)}] if search else []
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": prompt}]
    content = []
    for _ in range(6):
        kw = dict(model=c["model"], max_tokens=cfg["ai"].get("max_output_tokens", 12000), system=sys_blocks, messages=messages)
        if tools:
            kw["tools"] = tools
        resp = client.messages.create(**kw)
        content = resp.content
        if resp.stop_reason != "pause_turn":
            break
        messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": resp.content}]
    text = "".join(b.text for b in content if getattr(b, "type", "") == "text")
    sources = []
    for b in content:
        for ct in (getattr(b, "citations", None) or []):
            if getattr(ct, "url", None) and ct.url not in {s["url"] for s in sources}:
                sources.append({"title": getattr(ct, "title", "") or ct.url, "url": ct.url})
    return text, sources, c["model"]


def generate(cfg: dict, system: str, prompt: str, search: bool = False, images=None) -> tuple[str, list[dict], str]:
    """images: optional [(bytes, mime type)], e.g. the editor's screenshots (Gemini reads them)."""
    p = provider(cfg)
    if p == "gemini":
        return _gemini(cfg, system, prompt, search, images)
    if p == "claude":
        return _claude(cfg, system, prompt, search)
    raise RuntimeError("mock provider has no generate(); writer handles mock mode")
