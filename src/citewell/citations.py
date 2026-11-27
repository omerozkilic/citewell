"""Export citations as BibTeX, CSL-JSON or Markdown footnotes (offline, no LLM).

Each cited *passage* becomes one entry, built from what Citewell stores about its document (file,
title, author, date) and the passage location (printed page label when there is one, PDF page,
section) plus the chunk id, which lets anyone find the exact passage again.
"""

import json
import re
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel

from citewell.text import fold

CiteFormat = Literal["bibtex", "csl-json", "md"]
FORMATS: tuple[CiteFormat, ...] = ("bibtex", "csl-json", "md")


class CiteItem(BaseModel):
    """One cited passage."""

    chunk_id: str
    source: str
    title: str | None = None
    author: str | None = None
    doc_date: date | None = None
    page: int | None = None
    page_label: str | None = None
    section: str | None = None
    collection: str = "default"
    quote: str | None = None

    @property
    def pages(self) -> str | None:
        """The page as printed: the label if it differs from the PDF page number, else the number."""
        if self.page is None:
            return None
        return self.page_label if self.page_label and self.page_label != str(self.page) else str(self.page)

    @property
    def display_title(self) -> str:
        return self.title or self.source

    def location(self) -> str:
        """``s. 12``, ``s. iv (PDF s. 4)``, ``§ Section`` or an empty string."""
        if self.page is not None:
            if self.page_label and self.page_label != str(self.page):
                return f"s. {self.page_label} (PDF s. {self.page})"
            return f"s. {self.page}"
        return f"§ {self.section}" if self.section else ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-") or "document"


def cite_key(item: CiteItem) -> str:
    """Stable key, unique per passage: file name, page and the start of the chunk id."""
    stem = item.source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    page = f"-p{_slug(item.pages)}" if item.pages else ""
    return f"{_slug(stem)}{page}-{item.chunk_id[:6]}"


# ------------------------------------------------------------------------- BibTeX

_BIBTEX_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}


def _bibtex_value(text: str) -> str:
    out = "".join(_BIBTEX_ESCAPES.get(c, c) for c in text)
    return out.replace("{", r"\{").replace("}", r"\}")


def to_bibtex(items: Sequence[CiteItem]) -> str:
    entries = []
    for item in items:
        fields = {"title": item.display_title}
        if item.author:
            fields["author"] = item.author
        if item.doc_date:
            fields["year"] = str(item.doc_date.year)
            fields["date"] = item.doc_date.isoformat()
        if item.pages:
            fields["pages"] = item.pages
        extras = []
        if item.page is None and item.section:
            extras.append(f"§ {item.section}")
        elif item.page is not None and item.pages != str(item.page):
            extras.append(f"PDF page {item.page}")  # `pages` holds the printed label
        fields["note"] = "; ".join([*extras, f"chunk {item.chunk_id}"])
        fields["file"] = item.source
        body = ",\n".join(f"  {k} = {{{_bibtex_value(v)}}}" for k, v in fields.items())
        entries.append(f"@misc{{{cite_key(item)},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


# ------------------------------------------------------------------------ CSL-JSON


def to_csl_json(items: Sequence[CiteItem]) -> str:
    out: list[dict[str, object]] = []
    for item in items:
        entry: dict[str, object] = {"id": cite_key(item), "type": "document", "title": item.display_title}
        if item.author:
            entry["author"] = [{"literal": item.author}]
        if item.doc_date:
            entry["issued"] = {"date-parts": [[item.doc_date.year, item.doc_date.month, item.doc_date.day]]}
        if item.pages:
            entry["page"] = item.pages
        if item.section:
            entry["section"] = item.section
        entry["source"] = item.source
        entry["note"] = f"chunk {item.chunk_id}"
        out.append(entry)
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------- Markdown footnotes


def to_markdown(items: Sequence[CiteItem], with_quotes: bool = False) -> str:
    """Footnote definitions ``[^1]: …`` in input order (cite them in the text as ``[^1]``)."""
    lines = []
    for n, item in enumerate(items, start=1):
        parts = [f"*{item.display_title}*"]
        if item.author:
            parts.append(item.author)
        if item.doc_date:
            parts.append(str(item.doc_date.year))
        if loc := item.location():
            parts.append(loc)
        line = f"[^{n}]: {', '.join(parts)} (`{item.source}`, chunk `{item.chunk_id}`)."
        if with_quotes and item.quote:
            line += f' "{" ".join(item.quote.split())}"'
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def render(items: Sequence[CiteItem], fmt: CiteFormat, with_quotes: bool = False) -> str:
    if fmt == "bibtex":
        return to_bibtex(items)
    if fmt == "csl-json":
        return to_csl_json(items)
    if fmt == "md":
        return to_markdown(items, with_quotes)
    raise ValueError(f"format must be one of {', '.join(FORMATS)}")
