"""Text utilities with Turkish-aware casing.

Python's ``str.lower`` maps ``I`` to ``i`` and ``İ`` to ``i̇`` (i + combining
dot), which is wrong for Turkish: ``I`` should become ``ı`` and ``İ`` should
become ``i``. PostgreSQL's full-text parser has the same problem under a
``C.UTF-8`` locale, so Citewell normalises text in Python before it is handed
to ``to_tsvector``.
"""

from __future__ import annotations

import re
import unicodedata

_TR_UPPER_MAP = str.maketrans({"I": "ı", "İ": "i"})
_WS_RE = re.compile(r"[ \t\f\v ]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
# Sentence boundary: punctuation followed by whitespace and an uppercase/digit start.
_SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[\"'“(\[]?[A-ZÇĞİÖŞÜ0-9])")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def tr_lower(text: str, language: str = "turkish") -> str:
    """Lowercase ``text`` respecting Turkish dotted/dotless ``i`` rules."""
    if language == "turkish":
        text = text.translate(_TR_UPPER_MAP)
    return text.lower()


def clean_text(text: str) -> str:
    """Normalise extracted text without changing its meaning.

    * Unicode NFC (PDF extractors often emit decomposed characters)
    * re-join words hyphenated across line breaks
    * collapse runs of spaces and excessive blank lines
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


_LINE_END_RE = re.compile(r"[.!?…:;]$")
_LIST_START_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s")


def reflow(text: str) -> str:
    """Join hard-wrapped lines (typical of PDF extraction) into paragraphs.

    A line break is kept when the previous line ends a sentence, the next line
    starts a list item, or the next line looks like a short heading.
    """
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        if not out or not line or not out[-1]:
            out.append(line)
            continue
        prev = out[-1]
        if _LINE_END_RE.search(prev) or _LIST_START_RE.match(line) or _looks_like_heading(prev):
            out.append(line)
        else:
            out[-1] = f"{prev} {line}"
    return "\n".join(out)


def _looks_like_heading(line: str) -> bool:
    return len(line) < 60 and not line.endswith((",", "-")) and (line[:1].isdigit() or line.istitle())


def split_sentences(text: str) -> list[str]:
    """Split text into sentences (good enough for Turkish and English prose)."""
    parts: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        parts.extend(s.strip() for s in _SENT_RE.split(para.replace("\n", " ")) if s.strip())
    return parts


def tokenize(text: str, language: str = "turkish") -> list[str]:
    return _WORD_RE.findall(tr_lower(text, language))


def _stem(token: str, prefix: int = 5) -> str:
    """Crude prefix stem: Turkish is agglutinative, so the first few
    characters are a surprisingly robust stand-in for the root."""
    return token[:prefix]


def best_quote(text: str, query: str, language: str = "turkish", max_chars: int = 320) -> str:
    """Return the sentence window of ``text`` that best matches ``query``.

    Used to give assistants a short, verbatim quote they can cite. The quote is
    always an exact substring-by-sentence of the source text, never generated.
    """
    sentences = split_sentences(text)
    if not sentences:
        return text[:max_chars]
    q_stems = {_stem(t) for t in tokenize(query, language) if len(t) > 1}
    if not q_stems:
        return _truncate(sentences[0], max_chars)

    def score(sentence: str) -> float:
        stems = {_stem(t) for t in tokenize(sentence, language)}
        return len(q_stems & stems) / (1 + 0.002 * len(sentence))

    best_idx = max(range(len(sentences)), key=lambda i: score(sentences[i]))
    quote = sentences[best_idx]
    # Grow the window with neighbours while it fits.
    lo, hi = best_idx, best_idx
    while True:
        grown = False
        if hi + 1 < len(sentences) and len(quote) + len(sentences[hi + 1]) + 1 <= max_chars:
            hi += 1
            quote = f"{quote} {sentences[hi]}"
            grown = True
        if lo - 1 >= 0 and len(quote) + len(sentences[lo - 1]) + 1 <= max_chars:
            lo -= 1
            quote = f"{sentences[lo]} {quote}"
            grown = True
        if not grown:
            break
    return _truncate(quote, max_chars)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    space = cut.rfind(" ")
    if space > max_chars * 0.6:
        cut = cut[:space]
    return cut.rstrip() + "…"
