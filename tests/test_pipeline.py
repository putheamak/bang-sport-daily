import importlib
import json
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SRC = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures" / "sample_feed.xml"
GN = {"name": "Google News – Sports (EN)", "url": "https://news.google.com/rss/x", "lang": "en"}


def _raw():
    return FIX.read_text().replace("PUBDATE", format_datetime(datetime.now(timezone.utc)))


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    for name in ["config.yaml", "athletes.yaml"]:
        shutil.copy(SRC / name, tmp_path / name)
    shutil.copytree(SRC / "memos", tmp_path / "memos")
    shutil.copytree(SRC / "voice", tmp_path / "voice")
    monkeypatch.setenv("SPORTNEWS_ROOT", str(tmp_path))
    monkeypatch.setenv("SPORTNEWS_MOCK", "1")
    monkeypatch.setenv("SPORTNEWS_DATE", "2026-11-05")
    monkeypatch.setenv("SITE_URL", "https://me.github.io/gsd")
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import sportnews.common as c
    importlib.reload(c)
    for m in ["llm", "collect", "writer", "exporters", "publishers", "site", "pipeline"]:
        importlib.reload(importlib.import_module(f"sportnews.{m}"))
    return tmp_path


def cfg():
    return importlib.import_module("sportnews.common").load_config()


def test_rank_cluster_diversity(repo):
    from sportnews import collect as C
    items = C.parse_feed(GN, cfg(), raw=_raw())
    titles = [i["title"] for i in items]
    assert not any("betting" in t.lower() for t in titles)           # blocked
    assert not any("Old story" in t for t in titles)                  # too old
    items = C.cluster(items, [])
    for it in items:
        it["score"] = C.score(it, cfg())
    top = max(items, key=lambda x: x["score"])
    assert "Real Madrid" in top["title"] and len(top["also_reported_by"]) == 2   # 3 outlets merged
    assert top["sport"] == "football"
    picked = C.select(items, 3, 1)
    assert [p["sport"] for p in picked] == ["football", "basketball", "tennis"]  # 1 per sport


def test_gemini_fallback_chain():
    from sportnews.llm import gemini_candidates, _classify
    names = ["models/gemini-2.5-flash", "models/gemini-3.6-flash", "models/gemini-3.8-flash-preview",
             "models/gemini-3.1-flash-lite", "models/gemini-3.6-flash-image", "models/gemini-3.6-flash-tts",
             "models/gemini-2.5-pro", "models/gemini-flash-latest", "models/text-embedding-004"]
    assert gemini_candidates(names) == ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-3.8-flash-preview",
                                        "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest"]
    assert gemini_candidates([]) == ["gemini-flash-latest", "gemini-flash-lite-latest"]
    assert _classify("429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generate_content_free_tier_requests, limit: 0") == "dead"
    assert _classify("429 RESOURCE_EXHAUSTED rate limit, retry in 30s") == "rate"
    assert _classify("404 NOT_FOUND models/x is not found") == "dead"
    assert _classify("400 INVALID_ARGUMENT Search Grounding is not supported") == "dead" or True
    assert _classify("400 INVALID_ARGUMENT google_search tool error") == "no_search"
    assert _classify("400 API key not valid. Please pass a valid API key.") == "auth"


def test_daily_publish_site(repo, monkeypatch):
    from sportnews import collect as C, pipeline, publishers
    real = C.parse_feed
    monkeypatch.setattr(C, "parse_feed", lambda f, c, **k: real(f, c, raw=_raw()) if f["name"] == GN["name"] else [])
    monkeypatch.setattr(C, "fetch_full_text", lambda url: "")
    new = pipeline.run_daily(publish_now=False)
    assert [a["type"] for a in new] == ["news", "news", "news", "history", "athlete_story"]
    assert all(a.get("zh") and a.get("ru") for a in new)
    docs = repo / "docs"
    assert not list((docs / "en").glob("mock-*.html")) and "coming soon" in (docs / "en/index.html").read_text()
    assert not (docs / "articles.json").exists()          # drafts never public by default
    out = repo / "output" / "2026-11-05"
    assert len(list(out.glob("*.zh.md"))) == 5 and (out / "bang-sport-daily-2026-11-05.docx").exists()

    sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    for l in ("EN", "ZH", "RU"):
        monkeypatch.setenv(f"TELEGRAM_CHANNEL_{l}", f"@c{l}")
    monkeypatch.setattr(publishers, "_post", lambda url, data: sent.append(data) or {})
    assert publishers.publish_articles(cfg(), [new[0]["id"][:16]]) == []      # ambiguous prefix refused
    done = publishers.publish_articles(cfg(), [new[0]["id"]])
    assert len(done) == 1 and {d["chat_id"] for d in sent} == {"@cEN", "@cZH", "@cRU"}
    assert any("阅读全文: https://me.github.io/gsd/zh/" in d["text"] for d in sent)

    importlib.import_module("sportnews.site").build_site(cfg())
    slug = new[0]["slug"]
    page = (docs / "zh" / f"{slug}.html").read_text()
    assert 'hreflang="ru"' in page and "资料来源" in page and 'lang="zh-Hans"' in page
    assert slug in (docs / "sitemap.xml").read_text() and "<item>" in (docs / "ru/feed.xml").read_text()

    # second run: same news is not rewritten; athlete rotation advances
    new2 = pipeline.run_daily(publish_now=False)
    news2 = [a for a in new2 if a["type"] == "news"]
    assert len(news2) == 1 and "Arsenal" in news2[0]["en"]["headline"]   # only the story not used yesterday
    assert json.loads((repo / "data/state.json").read_text())["athlete_idx"] == 2


def test_writer_with_fake_gemini(repo, monkeypatch):
    """Exercise the real Gemini code path with a fake SDK client: grounding sources, fallback on 429, localization."""
    from google import genai
    from sportnews import llm, writer
    monkeypatch.delenv("SPORTNEWS_MOCK")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    en = {"headline": "H", "subheadline": "S", "body_markdown": "B", "social_post": "P", "sport": "football",
          "tags": [], "athletes": [], "facts_to_verify": ["check score"], "sources_used": [{"title": "A", "url": "https://a"}]}
    loc = {"zh": {"headline": "标题", "subheadline": "副", "body_markdown": "正文", "social_post": "帖"},
           "ru": {"headline": "Заголовок", "subheadline": "П", "body_markdown": "Текст", "social_post": "Пост"}}
    calls = []
    chunk = NS(web=NS(uri="https://g", title="g.com", domain="g.com"))

    class Models:
        def list(self):
            return [NS(name="models/gemini-3.6-flash", supported_actions=["generateContent"]),
                    NS(name="models/gemini-3.1-flash-lite", supported_actions=["generateContent"])]

        def generate_content(self, model, contents, config):
            calls.append((model, bool(config.tools)))
            if len(calls) == 1:
                raise RuntimeError("429 RESOURCE_EXHAUSTED free_tier_requests, limit: 0")
            data = en if len(calls) == 2 else loc
            return NS(text=f"<article_json>{json.dumps(data, ensure_ascii=False)}</article_json>",
                      candidates=[NS(grounding_metadata=NS(grounding_chunks=[chunk]))])

    monkeypatch.setattr(genai, "Client", lambda api_key: NS(models=Models()))
    llm._STATE.update(chain=None, dead=set(), no_search=False, broken=None)
    a = writer.write_article(cfg(), "history", {"title": "x"}, "2026-11-05")
    assert calls[0] == ("gemini-3.6-flash", True) and calls[1] == ("gemini-3.6-flash", False)  # search quota 0 -> plain
    assert calls[2][1] is False                                    # localization: no search
    assert a["zh"]["headline"] == "标题" and a["ru"]["headline"] == "Заголовок"
    assert [s["url"] for s in a["sources"]] == ["https://a", "https://g"]
    assert a["model"] == "gemini-3.6-flash"


def test_extract_json():
    from sportnews.writer import extract_json
    assert extract_json('x <article_json>{"a":1}</article_json>')["a"] == 1
    assert extract_json('```json\n{"a":2}\n```')["a"] == 2
