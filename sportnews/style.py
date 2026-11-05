"""Learn the author's voice from ebook samples in voice/samples/ and write voice/style_profile.md."""
from __future__ import annotations

from .common import VOICE, load_config, log

PROMPT = """Below are excerpts from {author}'s own ebook writing. Study them closely and write a STYLE PROFILE
that another writer could follow to sound exactly like {author} when writing English sport columns about world sport.

Cover, with short concrete bullets and 2-3 SHORT example sentences quoted from the samples:
- Voice & point of view, tone, emotional register
- How chapters/stories open and close
- Paragraph and sentence rhythm, typical length
- Favourite devices (questions, scenes, proverbs, lists, personal anecdotes, data)
- Characteristic vocabulary and expressions
- How the author mixes personal experience with facts
- Things the author never does
Finish with a "Structure I like" numbered template and a "Never" list (always include: never invent quotes or facts).
Output only the markdown profile, starting with "# My Writing Voice (style profile)".

<samples>
{samples}
</samples>"""


def _read_sample(path) -> str:
    suf = path.suffix.lower()
    if suf in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suf == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    if suf == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            log.warning("Install pypdf to read %s", path.name)
            return ""
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
    return ""


def build_style(max_chars: int = 120_000) -> str:
    cfg = load_config()
    files = sorted(p for p in (VOICE / "samples").glob("*") if p.is_file() and not p.name.startswith("."))
    if not files:
        raise SystemExit("Put your ebook chapters (.txt/.md/.docx/.pdf) in voice/samples/ first.")
    chunks, total = [], 0
    for p in files:
        t = _read_sample(p).strip()
        if not t:
            continue
        t = t[: max_chars - total]
        chunks.append(f"--- {p.name} ---\n{t}")
        total += len(t)
        if total >= max_chars:
            break
    from . import llm
    if llm.provider(cfg) == "mock":
        raise SystemExit("Set GEMINI_API_KEY (free) or ANTHROPIC_API_KEY first.")
    profile, _, _ = llm.generate(cfg, "You are an expert editor and writing coach.",
                                 PROMPT.format(author=cfg["site"]["author"], samples="\n\n".join(chunks)))
    profile = profile.strip()
    (VOICE / "style_profile.md").write_text(profile + "\n", encoding="utf-8")
    log.info("Style profile written from %d sample files (%d chars).", len(chunks), total)
    return profile
