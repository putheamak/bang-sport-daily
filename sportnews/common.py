"""Shared helpers: paths, config loading, JSON store, logging."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(os.environ.get("SPORTNEWS_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
DOCS = ROOT / "docs"
MEMOS = ROOT / "memos"
VOICE = ROOT / "voice"

log = logging.getLogger("sportnews")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_athletes() -> list[dict]:
    p = ROOT / "athletes.yaml"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def today(cfg: dict | None = None) -> str:
    tz = ZoneInfo((cfg or {}).get("site", {}).get("timezone", "Asia/Phnom_Penh"))
    return os.environ.get("SPORTNEWS_DATE") or datetime.now(tz).strftime("%Y-%m-%d")


def now_iso(cfg: dict | None = None) -> str:
    tz = ZoneInfo((cfg or {}).get("site", {}).get("timezone", "Asia/Phnom_Penh"))
    return datetime.now(tz).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:60] or "item"


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


# ---------- article store (data/articles.json) ----------
ARTICLES = DATA / "articles.json"
SEEN = DATA / "seen.json"
STATE = DATA / "state.json"


def load_articles() -> list[dict]:
    return read_json(ARTICLES, [])


def save_articles(items: list[dict]) -> None:
    items.sort(key=lambda a: (a.get("date", ""), a.get("created", "")), reverse=True)
    write_json(ARTICLES, items)
