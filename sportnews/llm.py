"""One interface over the AI providers: Gemini (free tier), Claude (paid) or mock (no key, for testing).

generate(cfg, system, prompt, search) -> (text, sources)
"""
from __future__ import annotations

import os
import re
import time

from .common import log

_MODEL_CACHE: dict[str, str] = {}
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


def _resolve_gemini(client, wanted: str) -> str:
    if wanted not in ("auto", "auto-lite"):
        return wanted
    if wanted in _MODEL_CACHE:
        return _MODEL_CACHE[wanted]
    names = []
    try:
        for m in client.models.list():
            if "generateContent" in (getattr(m, "supported_actions", None) or ["generateContent"]):
                names.append(m.name)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not list Gemini models (%s); using alias", e)
    chosen = pick_gemini_model(names, lite=wanted == "auto-lite") or (
        "gemini-flash-lite-latest" if wanted == "auto-lite" else "gemini-flash-latest")
    _MODEL_CACHE[wanted] = chosen
    log.info("Gemini model for %s: %s", wanted, chosen)
    return chosen


def _gemini(cfg: dict, system: str, prompt: str, search: bool) -> tuple[str, list[dict], str]:
    from google import genai
    from google.genai import types

    gcfg = cfg["ai"]["gemini"]
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    tools = [types.Tool(google_search=types.GoogleSearch())] if (search and gcfg.get("google_search", True)) else None
    models = [_resolve_gemini(client, gcfg.get("model", "auto")), _resolve_gemini(client, gcfg.get("fallback_model", "auto-lite"))]
    last_err = None
    for attempt, model in enumerate(models + models[-1:]):
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, tools=tools, temperature=0.7,
                                                   max_output_tokens=cfg["ai"].get("max_output_tokens", 12000)))
            text = resp.text or ""
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
            last_err = e
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                log.warning("Free quota hit on %s — trying fallback after a pause", model)
                time.sleep(30 if attempt else 5)
            elif "503" in msg or "UNAVAILABLE" in msg or "500" in msg:
                log.warning("Gemini busy (%s) — retrying", model)
                time.sleep(20)
            else:
                raise
    raise RuntimeError(f"Gemini failed after retries: {last_err}")


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
