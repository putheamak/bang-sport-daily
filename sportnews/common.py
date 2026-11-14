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


def log_to_file(name: str = "last_run.log") -> None:
    """Also write this run's log to data/<name> (committed, so problems can be diagnosed from the repo)."""
    DATA.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(DATA / name, mode="w", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)


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


def site_url(cfg: dict) -> str:
    """SITE_URL env > custom domain > GitHub repo (owner.github.io/repo) when running in Actions > config site.url.
    The custom domain wins over the repo address so every workflow (also those without SITE_URL) links to it."""
    u = os.environ.get("SITE_URL", "").strip()
    dom = (cfg.get("site", {}).get("custom_domain") or "").strip().strip("/")
    if not u and dom:
        u = dom if dom.startswith("http") else f"https://{dom}"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not u and repo and "/" in repo:
        owner, name = repo.split("/", 1)
        u = f"https://{owner.lower()}.github.io/{name}"
    u = u or cfg["site"].get("url", "")
    return "" if "YOUR-GITHUB-USERNAME" in u else u.rstrip("/")
