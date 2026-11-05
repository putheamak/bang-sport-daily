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
        if wanted not in ("auto", "auto-lite"):
            chain = [wanted] + [c for c in chain if c != wanted]
        _STATE["chain"] = chain
        log.info("Gemini models available: %d · fallback chain: %s", len(names), " > ".join(chain))
    return [m for m in _STATE["chain"] if m not in _STATE["dead"]]


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


def _gemini(cfg: dict, system: str, prompt: str, search: bool) -> tuple[str, list[dict], str]:
    from google import genai
    from google.genai import types

    gcfg = cfg["ai"]["gemini"]
    if _STATE["broken"]:
        raise RuntimeError("Skipped — Gemini already failed on every model this run: " + _STATE["broken"])
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    errors = []
    for _round in range(2):
        chain = _chain(client, cfg)
        if not chain:
            break
        for model in chain:
            use_search = search and gcfg.get("google_search", True) and not _STATE["no_search"]
            for attempt in range(3):
                tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
                try:
                    resp = client.models.generate_content(
                        model=model, contents=prompt,
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
                    time.sleep(gcfg.get("pause_seconds", 8))
                    return text, sources, model
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    kind = _classify(msg)
                    errors.append(f"{model}: {kind}: {msg[:200]}")
                    log.warning("Gemini %s failed [%s]%s: %s", model, kind, " (with search)" if use_search else "", msg[:400])
                    if kind == "auth":
                        _STATE["broken"] = "API key rejected"
                        raise RuntimeError("Gemini API key rejected — check the GEMINI_API_KEY secret") from e
                    if kind == "no_search" and use_search:
                        _STATE["no_search"] = True
                        use_search = False
                        continue
                    if kind == "dead" and use_search and "429" in msg:
                        use_search = False      # the search quota may be the part that is 0 — try plain once
                        continue
                    if kind == "dead":
                        _STATE["dead"].add(model)
                        break
                    if kind in ("rate", "busy") and attempt == 0:
                        time.sleep(40 if kind == "rate" else 20)
                        continue
                    if kind == "other" and use_search and attempt == 0:
                        use_search = False   # retry once without search
                        continue
                    break
        if _round == 0:
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


def generate(cfg: dict, system: str, prompt: str, search: bool = False) -> tuple[str, list[dict], str]:
    p = provider(cfg)
    if p == "gemini":
        return _gemini(cfg, system, prompt, search)
    if p == "claude":
        return _claude(cfg, system, prompt, search)
    raise RuntimeError("mock provider has no generate(); writer handles mock mode")
