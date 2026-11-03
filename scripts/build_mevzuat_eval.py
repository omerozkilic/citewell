"""Build a runnable eval dataset for Turkish legislation PDFs (mevzuat.gov.tr).

Questions in ``examples/eval/mevzuat-questions.jsonl`` name a law number and an
article ("Madde N"). Page numbers differ between PDF versions, so this script
finds, in *your* downloaded PDFs, the page(s) each article spans, using the
same text extraction as `citewell ingest`.

    uv run python scripts/build_mevzuat_eval.py data/mevzuat -o data/mevzuat-eval.jsonl
    uv run citewell eval data/mevzuat-eval.jsonl -c mevzuat -r vector,keyword,hybrid,hybrid+rerank --markdown

PDFs are matched to laws by the law number in the filename
(``1.5.4857.pdf``, ``is-kanunu-4857.pdf`` …).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from citewell.loaders import iter_files, load_file
from citewell.models import Page

# "Madde 15 -", "MADDE 1 –" … but not "Geçici Madde 1 -" / "Ek Madde 2 -".
ARTICLE_RE = re.compile(r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])(Geçici|Ek)?\s*Madde\s+(\d+)\s*[-–—]", re.IGNORECASE)
LAW_NO_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
DEFAULT_QUESTIONS = Path(__file__).resolve().parent.parent / "examples" / "eval" / "mevzuat-questions.jsonl"


def article_starts(pages: list[Page]) -> dict[int, tuple[int, int]]:
    """Map article number -> (page, char offset) of its first heading (main articles only)."""
    starts: dict[int, tuple[int, int]] = {}
    for page in pages:
        if page.number is None:
            continue
        for m in ARTICLE_RE.finditer(page.text):
            if m.group(1):  # Geçici / Ek madde
                continue
            num = int(m.group(2))
            starts.setdefault(num, (page.number, m.start()))
    return starts


def article_pages(starts: dict[int, tuple[int, int]], article: int, top_margin: int = 80) -> list[int]:
    """Pages spanned by ``article``: from its heading to where the next article begins."""
    if article not in starts:
        return []
    first, _ = starts[article]
    following = sorted((p, off) for n, (p, off) in starts.items() if (p, off) > starts[article])
    if not following:
        return [first]
    next_page, next_off = following[0]
    # If the next article opens at the very top of a page, this one ended on the previous page.
    last = next_page - 1 if next_off < top_margin else next_page
    return list(range(first, max(first, last) + 1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf_dir", type=Path, help="Folder you ingested (sources are relative to it).")
    ap.add_argument("-q", "--questions", type=Path, default=DEFAULT_QUESTIONS)
    ap.add_argument("-o", "--output", type=Path, default=Path("data/mevzuat-eval.jsonl"))
    ap.add_argument("-c", "--collection", default="mevzuat")
    args = ap.parse_args(argv)

    questions = [
        json.loads(line)
        for line in args.questions.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    wanted = {str(q["law"]) for q in questions}

    laws: dict[str, tuple[str, dict[int, tuple[int, int]]]] = {}
    for path, source in iter_files([args.pdf_dir]):
        if path.suffix.lower() != ".pdf":
            continue
        # Only law numbers used by the questions count, so dates like "30-09-2021" are ignored.
        found = [n for n in LAW_NO_RE.findall(path.stem) if n in wanted]
        if not found:
            print(
                f"{source}: skipped (no law number from the question set in the file name)", file=sys.stderr
            )
            continue
        law = found[-1]
        doc = load_file(path, source)
        laws[law] = (source, article_starts(doc.pages))
        print(f"{source}: law {law}, {len(laws[law][1])} articles found", file=sys.stderr)

    written = skipped = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for q in questions:
            if str(q["law"]) not in laws:
                skipped += 1
                continue
            source, starts = laws[str(q["law"])]
            pages = article_pages(starts, int(q["article"]))
            if not pages:
                print(f"  ! {q['id']}: Madde {q['article']} not found in {source}", file=sys.stderr)
                skipped += 1
                continue
            item = {
                "id": q["id"],
                "query": q["query"],
                "relevant": [{"source": source, "pages": pages}],
                "collection": args.collection,
                "tags": [*q.get("tags", []), f"law:{q['law']}", f"madde:{q['article']}"],
            }
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += 1
    print(
        f"wrote {written} questions to {args.output} ({skipped} skipped: law PDF or article missing)",
        file=sys.stderr,
    )
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
