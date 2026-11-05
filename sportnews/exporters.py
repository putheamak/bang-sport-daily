"""Markdown files + ebook-style Word (.docx) exports, daily and monthly."""
from __future__ import annotations

import re
from pathlib import Path

from .common import OUTPUT, load_articles, log

LANGS = ("en", "zh", "ru")
TYPE_LABEL = {
    "news": {"en": "News", "zh": "新闻", "ru": "Новости"},
    "history": {"en": "On this day", "zh": "历史上的今天", "ru": "В этот день"},
    "athlete_story": {"en": "Athlete story", "zh": "人物故事", "ru": "История спортсмена"},
}
SOURCES = {"en": "Sources", "zh": "来源", "ru": "Источники"}


def label(kind: str, lang: str) -> str:
    return TYPE_LABEL.get(kind, {}).get(lang, kind)


def article_markdown(a: dict, lang: str) -> str:
    L = a.get(lang, {})
    out = [f"# {L.get('headline', '')}", ""]
    if L.get("subheadline"):
        out += [f"*{L['subheadline']}*", ""]
    out += [f"**{label(a['type'], lang)}** · {a['date']}", "", L.get("body_markdown", ""), ""]
    if a.get("sources"):
        out += ["---", f"**{SOURCES[lang]}**", ""] + [f"- [{s['title']}]({s['url']})" for s in a["sources"]]
    return "\n".join(out).strip() + "\n"


def _font(par, lang: str) -> None:
    from docx.oxml.ns import qn
    if lang != "zh":
        return
    for run in par.runs:
        rpr = run._element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = rpr.makeelement(qn("w:rFonts"), {})
            rpr.append(rf)
        rf.set(qn("w:eastAsia"), "Microsoft YaHei")


def _add_md(doc, md: str, lang: str) -> None:
    for block in re.split(r"\n\s*\n", md.strip()):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            _font(doc.add_heading(block.lstrip("#").strip(), level=2), lang)
            continue
        p = doc.add_paragraph()
        for part in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", block.replace("\n", " ")):
            if part:
                run = p.add_run(part.strip("*") if part.startswith("*") else part)
                run.bold = part.startswith("**")
                run.italic = part.startswith("*") and not part.startswith("**")
        _font(p, lang)


def build_docx(path: Path, title: str, subtitle: str, items: list[dict], langs=LANGS) -> Path:
    import docx
    from docx.enum.text import WD_BREAK
    from docx.shared import Pt

    doc = docx.Document()
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(title, level=0)
    doc.add_paragraph(subtitle)
    for a in items:
        for lang in langs:
            L = a.get(lang)
            if not L:
                continue
            doc.paragraphs[-1].add_run().add_break(WD_BREAK.PAGE)
            _font(doc.add_heading(L.get("headline", ""), level=1), lang)
            if L.get("subheadline"):
                p = doc.add_paragraph()
                p.add_run(L["subheadline"]).italic = True
                _font(p, lang)
            _font(doc.add_paragraph(f"{label(a['type'], lang)} · {a['date']}"), lang)
            _add_md(doc, L.get("body_markdown", ""), lang)
        if a.get("sources"):
            doc.add_paragraph("Sources / 来源 / Источники:")
            for s in a["sources"]:
                doc.add_paragraph(f"{s['title']} — {s['url']}", style="List Bullet")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def export_day(cfg: dict, date: str, items: list[dict]) -> None:
    if not items:
        return
    day = OUTPUT / date
    day.mkdir(parents=True, exist_ok=True)
    if cfg["publish"].get("markdown", True):
        for a in items:
            for lang in LANGS:
                if a.get(lang):
                    (day / f"{a['type']}-{a['slug']}.{lang}.md").write_text(article_markdown(a, lang), encoding="utf-8")
    if cfg["publish"].get("docx", True):
        build_docx(day / f"bang-sport-daily-{date}.docx", cfg["site"]["name"], date, items)
    log.info("Exported %d articles to %s", len(items), day)


def compile_book(cfg: dict, month: str, status: str | None = None, lang: str | None = None) -> Path:
    """Compile a month of stories (e.g. 2026-11) into one ebook-style .docx, oldest first."""
    items = [a for a in load_articles() if a["date"].startswith(month) and (status is None or a["status"] == status)]
    items.sort(key=lambda a: (a["date"], a["created"]))
    suffix = f"-{lang}" if lang else ""
    path = OUTPUT / "books" / f"bang-sport-{month}{suffix}.docx"
    build_docx(path, cfg["site"]["name"], f"{month} · {cfg['site']['author']}", items, (lang,) if lang else LANGS)
    log.info("Book with %d stories: %s", len(items), path)
    return path
