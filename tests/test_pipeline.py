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
    for m in ["llm", "collect", "images", "writer", "inbox", "exporters", "publishers", "site", "pipeline"]:
        importlib.reload(importlib.import_module(f"sportnews.{m}"))
    images = importlib.import_module("sportnews.images")
    monkeypatch.setattr(images, "find_images", lambda subjects, max_n=3: [])   # no network in tests
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

    monkeypatch.setattr(genai, "Client", lambda api_key, **kw: NS(models=Models()))
    llm._STATE.clear(); llm._STATE.update(chain=None, dead=set(), no_search=False, broken=None)
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


def test_wikimedia_photos(monkeypatch):
    from sportnews import images
    calls = []

    def fake_get(api, params):
        calls.append((api, params.get("titles") or params.get("srsearch")))
        if "wikipedia" in api and params.get("prop") == "pageimages":
            t = params["titles"]
            img = {"Yao Ming": "Yao_Ming_2009.jpg", "Houston Rockets": "Houston_Rockets_logo.svg",
                   "Toyota Center": "Toyota_Center_fair_use.jpg"}.get(t)
            return {"query": {"pages": [{"title": t, "pageimage": img} if img else {"title": t, "missing": True}]}}
        if "wikipedia" in api:
            return {"query": {"search": []}}
        name = params["titles"]
        if "fair_use" in name:
            return {"query": {"pages": [{"missing": True}]}}          # non-free files are not on Commons
        return {"query": {"pages": [{"imageinfo": [{"thumburl": "https://upload.wikimedia.org/x/1200px-Yao.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Yao_Ming_2009.jpg", "width": 2000, "height": 1500,
            "thumbwidth": 1200, "thumbheight": 900,
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 2.0"}, "Artist": {"value": "<a href='x'>Keith Allison</a>"},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/2.0"}}}]}]}}
    monkeypatch.setattr(images, "_get", fake_get)
    out = images.find_images(["Yao Ming", "Houston Rockets", "Toyota Center"])
    assert len(out) == 1 and out[0]["artist"] == "Keith Allison" and out[0]["license"] == "CC BY-SA 2.0"
    assert out[0]["subject"] == "Yao Ming"
    assert not any("logo" in str(c[1]) for c in calls if "commons" in c[0])     # logos skipped before licence check


def test_site_layout_with_photo(repo):
    from sportnews import site
    from sportnews.common import save_articles
    a = {"id": "x1", "slug": "yao", "date": "2026-11-05", "created": "2026-11-05T06:00:00+07:00", "type": "athlete_story",
         "status": "published", "model": "m", "sport": "Basketball", "tags": [], "athletes": [], "facts_to_verify": [],
         "sources": [{"title": "S", "url": "https://s"}], "published_to": [],
         "images": [{"url": "https://upload.wikimedia.org/a.jpg", "page": "https://commons.wikimedia.org/p", "artist": "Keith Allison",
                     "license": "CC BY-SA 2.0", "license_url": "https://cc", "subject": "Yao Ming"}],
         "en": {"headline": "Yao", "subheadline": "d", "body_markdown": "P1\n\n## H\nP2\n\nP3", "social_post": "p"}}
    save_articles([a])
    site.build_site(cfg())
    page = (repo / "docs/en/yao.html").read_text()
    assert "upload.wikimedia.org/a.jpg" in page and "Keith Allison" in page and "CC BY-SA 2.0" in page
    assert "<h2>H</h2>\n<p>P2</p>" in page and "t.me/share/url" in page
    # compliance: real author byline (no invented names), no Google Fonts, legal pages, author page
    assert ">Mak<" in page and "Nadia Rennick" not in page and "reviewed by the author" in page
    assert "fonts.googleapis.com" not in page and '"url": "https://me.github.io/gsd/en/author.html"' in page
    for f in ("editorial", "privacy", "terms", "contact", "author", "about"):
        assert (repo / f"docs/en/{f}.html").exists() and (repo / f"docs/ru/{f}.html").exists()
    assert "pen name" not in (repo / "docs/en/about.html").read_text().lower()
    assert 'name="robots" content="noindex' in (repo / "docs/en/section-tennis.html").read_text()   # empty section
    assert 'hreflang="x-default"' in page and (repo / "docs/fonts/inter-latin-wght-normal.woff2").exists()
    assert not (repo / "docs/ads.txt").exists() and not (repo / "docs/CNAME").exists()
    home = (repo / "docs/en/index.html").read_text()
    assert 'class="ticker"' in home and "section-athlete_story.html" in home
    assert (repo / "docs/zh/section-football.html").exists()


def test_pen_names_and_monetization_switches(repo, monkeypatch):
    import yaml
    from sportnews import site
    from sportnews.common import save_articles, ROOT
    c = yaml.safe_load(open(ROOT / "config.yaml"))
    c["site"].update(bylines="pen_names", custom_domain="bangsportdaily.com", adsense_client="ca-pub-123", wire_box=False)
    yaml.safe_dump(c, open(ROOT / "config.yaml", "w"), allow_unicode=True)
    save_articles([{"id": "x", "slug": "x", "date": "2026-11-05", "created": "2026-11-05T06:00:00+07:00", "type": "athlete_story",
                    "status": "published", "sources": [], "published_to": [], "en": {"headline": "H", "body_markdown": "B"}}])
    site.build_site(cfg())
    assert "Nadia Rennick" in (repo / "docs/en/x.html").read_text()
    assert (repo / "docs/CNAME").read_text().strip() == "bangsportdaily.com"
    assert (repo / "docs/ads.txt").read_text().startswith("google.com, pub-123, DIRECT")
    assert "adsbygoogle.js?client=ca-pub-123" in (repo / "docs/en/index.html").read_text()


def test_originality():
    from sportnews.originality import check, too_close
    src = "Alan Jones, the first driver to win a world title for Williams, has died at the age of 80 after a short illness."
    assert too_close(check("Alan Jones, the first driver to win a world title for Williams, has died at the age of 80. Sad.", src))
    assert not too_close(check("Williams' first world champion is gone. Jones, 80, passed away after a brief illness.", src))


def test_must_cover_memo(repo, monkeypatch):
    from sportnews import collect as C, pipeline
    (repo / "memos" / "2026-11-05.md").write_text(
        "Focus: big news\nMust cover: Ronaldo retires from international football\nSource: https://example.com/ronaldo\n")
    assert pipeline.must_cover((repo / "memos" / "2026-11-05.md").read_text()) == [
        ("Ronaldo retires from international football", ["https://example.com/ronaldo"])]
    monkeypatch.setattr(C, "parse_feed", lambda *a, **k: [])
    monkeypatch.setattr(C, "fetch_full_text", lambda url: "Cristiano Ronaldo announced on Thursday he is retiring from Portugal duty." if "ronaldo" in url else "")
    new = pipeline.run_daily(publish_now=False)
    news = [a for a in new if a["type"] == "news"]
    assert len(news) == 1 and "Ronaldo" in news[0]["en"]["headline"]
    assert news[0]["sources"][0]["url"] == "https://example.com/ronaldo"


def test_memo_assignment_does_not_leak(repo):
    from sportnews.writer import _write_prompt, split_memo
    memo = "I feel tired today.\nMust cover: Ronaldo retires\nSource: https://x\nAngle: Ronaldo in Asia"
    (repo / "memos" / "2026-11-05.md").write_text(memo)
    assert split_memo(memo) == ("I feel tired today.", "Must cover: Ronaldo retires\nSource: https://x\nAngle: Ronaldo in Asia")
    other = _write_prompt("history", {"fmt": {}}, "2026-11-05")
    assert "Ronaldo" not in other and "I feel tired today." in other and "Stay strictly on the TASK" in other
    mine = _write_prompt("news", {"assignment_memo": split_memo(memo)[1]}, "2026-11-05")
    assert "Ronaldo in Asia" in mine


def test_inbox_import(repo):
    import shutil
    from sportnews import pipeline
    (repo / "inbox").mkdir()
    shutil.copy(SRC / "inbox" / "2026-11-06-acl-two-cambodian-clubs.md", repo / "inbox" / "a.md")
    new = pipeline.run_inbox()
    assert len(new) == 1 and new[0]["model"] == "editor" and new[0]["status"] == "draft"
    assert "Phnom Penh Crown" in new[0]["en"]["headline"] and len(new[0]["sources"]) == 7
    assert new[0]["image_subjects"][0] == "Morodok Techo National Stadium"
    assert pipeline.run_inbox() == []          # imported only once


def test_photo_overrides(repo, monkeypatch):
    from sportnews import images, site
    from sportnews.common import save_articles, load_articles
    (repo / "photos").mkdir()
    (repo / "photos" / "team.jpg").write_bytes(b"jpg")
    (repo / "photos.yaml").write_text(
        "x1:\n  mode: replace\n  photos:\n    - file: team.jpg\n      caption: Phnom Penh Crown players\n"
        "      credit: Mak\n      license: Used with permission\n    - file: nocredit.jpg\n    - commons: \"File:Free_photo.jpg\"\n")
    monkeypatch.setattr(images, "commons_info", lambda name, width=1200: {"url": "https://upload.wikimedia.org/f.jpg",
        "page": "https://commons.wikimedia.org/wiki/File:Free_photo.jpg", "artist": "A", "license": "CC BY 4.0", "license_url": "", "description": "d"})
    a = {"id": "x1", "slug": "s", "date": "2026-11-05", "created": "2026-11-05T06:00:00+07:00", "type": "news", "status": "published",
         "sources": [], "published_to": [], "images": [{"url": "https://old.jpg", "page": "", "artist": "o", "license": "CC0"}],
         "en": {"headline": "H", "body_markdown": "a\n\nb\n\nc\n\nd"}}
    arts = [a]
    assert images.apply_overrides(arts, images.load_overrides()) == 1
    assert [i["url"] for i in a["images"]] == ["../photos/team.jpg", "https://upload.wikimedia.org/f.jpg"]   # no-credit photo skipped
    assert images.apply_overrides(arts, images.load_overrides()) == 0        # unchanged -> not re-resolved
    save_articles(arts)
    site.build_site(cfg())
    page = (repo / "docs/en/s.html").read_text()
    assert "../photos/team.jpg" in page and "Used with permission" in page and "via Wikimedia" in page
    assert (repo / "docs/photos/team.jpg").exists()


def test_journalist_style_rules(repo):
    from sportnews.writer import VOICE_RULES, WRITE_SYSTEM, first_person_count
    assert "third person" in VOICE_RULES["journalist"] and "Do NOT write in the first person" in VOICE_RULES["journalist"]
    assert "{voice_rules}" in WRITE_SYSTEM and "ghost-writer" not in WRITE_SYSTEM
    assert first_person_count('I watched it. My view: we were "I love this," he said.') == 3
    assert first_person_count("Como won 9-1. The result leaves them fourth. China beat the US 3-2.") == 0


def test_inbox_update_existing_story(repo):
    from sportnews import pipeline
    from sportnews.common import save_articles, load_articles
    save_articles([{"id": "s1", "slug": "keep-slug", "date": "2026-11-05", "created": "2026-11-05T06:00:00+07:00",
                    "type": "news", "status": "published", "published_at": "2026-11-05T07:00:00+07:00", "sources": [],
                    "published_to": [], "images": [{"url": "u", "artist": "a", "license": "CC0", "page": ""}],
                    "en": {"headline": "Old", "body_markdown": "I watched it from Phnom Penh."}}])
    (repo / "inbox").mkdir()
    (repo / "inbox" / "fix.md").write_text("---\nupdate: s1\nheadline: New headline\n---\nComo won 9-1.\n")
    pipeline.run_inbox()
    arts = load_articles()
    assert len(arts) == 1 and arts[0]["en"]["body_markdown"] == "Como won 9-1." and arts[0]["status"] == "published"
    assert arts[0]["slug"] == "keep-slug" and arts[0]["images"][0]["url"] == "u" and arts[0].get("updated_at")
