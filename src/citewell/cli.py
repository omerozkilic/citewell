"""Command line interface: ``citewell init | ingest | search | serve | mcp | eval | …``."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from citewell import __version__
from citewell.config import Settings, get_settings

if TYPE_CHECKING:
    from citewell.app import Citewell

app = typer.Typer(
    name="citewell",
    help="Citation-grounded document memory for AI assistants. Offline, MCP-native, Turkish-ready.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
collections_app = typer.Typer(help="Manage collections.", no_args_is_help=True)
documents_app = typer.Typer(help="Manage ingested documents.", no_args_is_help=True)
models_app = typer.Typer(help="Manage local models.", no_args_is_help=True)
app.add_typer(collections_app, name="collections")
app.add_typer(documents_app, name="documents")
app.add_typer(models_app, name="models")

# Human output goes to stderr so stdout stays clean for --json and for MCP stdio.
console = Console(stderr=True)
out = Console()

Mode = Literal["hybrid", "vector", "keyword"]
Lang = Literal["turkish", "english", "simple"]


def _setup_logging(settings: Settings) -> None:
    # Always log to stderr: stdout carries --json output and the MCP stdio channel.
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _citewell() -> Citewell:
    from citewell.app import Citewell

    settings = get_settings()
    _setup_logging(settings)
    return Citewell(settings)


def _fail(msg: str, code: int = 1) -> typer.Exit:
    console.print(f"[bold red]error:[/] {msg}")
    return typer.Exit(code)


def _version(value: bool) -> None:
    if value:
        out.print(f"citewell {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", "-V", callback=_version, is_eager=True, help="Show version and exit.")
    ] = False,
) -> None:
    """Citewell CLI."""


# ---------------------------------------------------------------------------- init


@app.command()
def init() -> None:
    """Create the pgvector extension and database schema (safe to re-run)."""
    cw = _citewell()
    try:
        applied = cw.init_db()
    except Exception as exc:
        raise _fail(str(exc)) from exc
    finally:
        cw.close()
    if applied:
        console.print(f"[green]✓[/] applied migrations: {', '.join(applied)}")
    else:
        console.print("[green]✓[/] database is up to date")
    console.print(f"  embedding model: [bold]{cw.embedding_model_id}[/] ({cw.settings.embedding_dim}-d)")


# -------------------------------------------------------------------------- ingest


@app.command()
def ingest(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to ingest.", exists=True)],
    collection: Annotated[str | None, typer.Option("--collection", "-c", help="Target collection.")] = None,
    language: Annotated[
        Lang | None, typer.Option("--language", "-l", help="Text-search language for a new collection.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Re-ingest even if unchanged.")] = False,
    recursive: Annotated[bool, typer.Option(help="Recurse into directories.")] = True,
) -> None:
    """Load, chunk, embed and store documents. Unchanged files are skipped by content hash."""
    from citewell.models import IngestResult

    cw = _citewell()
    counts: dict[str, int] = {}
    total_chunks = 0
    style = {"ingested": "green", "unchanged": "dim", "skipped": "yellow", "error": "red"}

    def report(res: IngestResult) -> None:
        nonlocal total_chunks
        counts[res.status] = counts.get(res.status, 0) + 1
        total_chunks += res.chunks
        extra = f" {res.chunks} chunks" if res.chunks else ""
        msg = f" — {res.message}" if res.message else ""
        console.print(f"[{style.get(res.status, 'white')}]{res.status:>9}[/] {res.source}{extra}{msg}")

    try:
        cw.check_schema()
        with console.status("loading embedding model…"):
            _ = cw.embedder
        cw.ingest.ingest_paths(
            paths, collection, language, force=force, recursive=recursive, on_result=report
        )
    except Exception as exc:
        raise _fail(str(exc)) from exc
    finally:
        cw.close()
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "no supported files found"
    console.print(f"[bold]done:[/] {summary}; {total_chunks} new chunks")
    if counts.get("error"):
        raise typer.Exit(2)


# -------------------------------------------------------------------------- search


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    k: Annotated[int, typer.Option("-k", "--top-k", help="Number of results.")] = 5,
    mode: Annotated[Mode, typer.Option("--mode", "-m")] = "hybrid",
    collection: Annotated[
        list[str] | None, typer.Option("--collection", "-c", help="Repeatable; '*' for all.")
    ] = None,
    rerank: Annotated[bool | None, typer.Option("--rerank/--no-rerank")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the raw JSON response.")] = False,
    full: Annotated[bool, typer.Option("--full", help="Show full chunk text instead of the quote.")] = False,
) -> None:
    """Search ingested documents and print cited passages."""
    from citewell.search import SearchRequest

    cw = _citewell()
    try:
        cw.check_schema()
        resp = cw.search.search(
            SearchRequest(query=query, top_k=k, mode=mode, collections=collection, rerank=rerank)
        )
    except Exception as exc:
        raise _fail(str(exc)) from exc
    finally:
        cw.close()
    if as_json:
        out.print_json(resp.model_dump_json())
        return
    if not resp.hits:
        console.print("[yellow]no results[/]")
        return
    for h in resp.hits:
        loc = f"s. {h.page}" if h.page is not None else (h.section or "")
        where = f", {loc}" if loc else ""
        out.print(
            f"[bold cyan][{h.rank}][/] [bold]{h.source}[/]{where}  [dim]{h.chunk_id} · {h.score:.4f}[/]"
        )
        out.print(f"    {h.text if full else h.quote}\n", highlight=False)
    rr = " +rerank" if resp.reranked else ""
    console.print(f"[dim]{len(resp.hits)} results · mode={resp.mode}{rr} · {resp.took_ms:.0f} ms[/]")


# --------------------------------------------------------------------------- serve


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address (default from CITEWELL_HOST).")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default from CITEWELL_PORT).")] = None,
    no_mcp: Annotated[bool, typer.Option("--no-mcp", help="Do not mount the MCP endpoint at /mcp.")] = False,
    init_db: Annotated[bool, typer.Option("--init", help="Apply migrations before starting.")] = False,
) -> None:
    """Run the REST API (and the MCP Streamable HTTP endpoint at /mcp)."""
    import uvicorn

    from citewell.api import create_app
    from citewell.app import Citewell

    settings = get_settings()
    if host:
        settings.host = host
    if port:
        settings.port = port
    _setup_logging(settings)
    cw = Citewell(settings)
    if init_db:
        try:
            applied = cw.init_db()
        except Exception as exc:
            raise _fail(str(exc)) from exc
        if applied:
            console.print(f"[green]✓[/] applied migrations: {', '.join(applied)}")
    api = create_app(cw, mount_mcp=not no_mcp)
    console.print(f"[green]citewell[/] REST: http://{settings.host}:{settings.port}/docs")
    if not no_mcp:
        console.print(f"[green]citewell[/] MCP : http://{settings.host}:{settings.port}/mcp")
    uvicorn.run(api, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


@app.command()
def mcp(
    transport: Annotated[
        Literal["stdio", "http"], typer.Option(help="stdio for Claude Desktop/Code, Cursor.")
    ] = "stdio",
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
) -> None:
    """Run the MCP server (stdio by default)."""
    from citewell.app import Citewell
    from citewell.mcp_server import build_server

    settings = get_settings()
    _setup_logging(settings)  # stderr only: stdout is the MCP channel
    cw = Citewell(settings)
    try:
        cw.check_schema()
    except Exception as exc:
        raise _fail(str(exc)) from exc
    server = build_server(cw)
    try:
        if transport == "stdio":
            server.run("stdio")
        else:
            server.run(
                "streamable-http",
                host=host or settings.host,
                port=port or settings.port,
                stateless_http=True,
                json_response=True,
            )
    finally:
        cw.close()


# ---------------------------------------------------------------------------- eval


@app.command("eval")
def eval_cmd(
    dataset: Annotated[Path, typer.Argument(help="JSONL eval dataset.", exists=True, dir_okay=False)],
    k: Annotated[int, typer.Option("-k", help="Cut-off for the metrics.")] = 5,
    runs: Annotated[
        str, typer.Option("--runs", "-r", help="Comma separated: vector,keyword,hybrid,hybrid+rerank")
    ] = "vector,keyword,hybrid",
    collection: Annotated[str | None, typer.Option("--collection", "-c")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write a JSON report here.")] = None,
    markdown: Annotated[bool, typer.Option("--markdown", help="Print a Markdown table.")] = False,
    fail_under: Annotated[
        float | None, typer.Option(help="Exit non-zero if hybrid Recall@k is below this (for CI).")
    ] = None,
) -> None:
    """Evaluate retrieval quality: Recall@k, MRR, page hit rate and latency."""
    from citewell.evaluation import RunConfig, load_dataset, report_markdown, run_eval

    try:
        configs = [RunConfig.parse(s) for s in runs.split(",") if s.strip()]
        queries = load_dataset(dataset)
    except ValueError as exc:
        raise _fail(str(exc)) from exc
    cw = _citewell()
    reports = []
    try:
        cw.check_schema()
        for cfg in configs:
            with console.status(f"running {cfg.label} on {len(queries)} queries…"):
                reports.append(run_eval(cw.search, queries, cfg, k=k, default_collection=collection))
    except Exception as exc:
        raise _fail(str(exc)) from exc
    finally:
        cw.close()

    table = Table(title=f"Citewell eval · {dataset.name} · {len(queries)} queries · k={k}")
    for col in ("run", f"Recall@{k}", f"MRR@{k}", f"Hit@{k}", f"Page hit@{k}", "p50 ms", "p95 ms"):
        table.add_column(col, justify="left" if col == "run" else "right")
    for r in reports:
        table.add_row(
            r.label,
            f"{r.recall_at_k:.3f}",
            f"{r.mrr_at_k:.3f}",
            f"{r.hit_at_k:.3f}",
            "–" if r.page_hit_at_k is None else f"{r.page_hit_at_k:.3f}",
            f"{r.latency_p50_ms:.0f}",
            f"{r.latency_p95_ms:.0f}",
        )
    console.print(table)
    if markdown:
        out.print(report_markdown(reports), highlight=False)
    if output:
        payload = {
            "dataset": str(dataset),
            "k": k,
            "embedding_model": cw.embedding_model_id,
            "runs": [{**r.summary(), "per_query": [asdict(q) for q in r.queries]} for r in reports],
        }
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]✓[/] report written to {output}")
    if fail_under is not None:
        target = next((r for r in reports if r.label == "hybrid"), reports[-1])
        if target.recall_at_k < fail_under:
            raise _fail(f"{target.label} Recall@{k}={target.recall_at_k:.3f} < {fail_under}", code=3)


# ---------------------------------------------------------------------- collections


@collections_app.command("list")
def collections_list(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """List collections."""
    cw = _citewell()
    try:
        cols = cw.store.list_collections()
    finally:
        cw.close()
    if as_json:
        out.print_json(json.dumps([c.model_dump(mode="json") for c in cols]))
        return
    table = Table("name", "language", "documents", "chunks", "description")
    for c in cols:
        table.add_row(c.name, c.language, str(c.document_count), str(c.chunk_count), c.description or "")
    out.print(table)


@collections_app.command("create")
def collections_create(
    name: str,
    language: Annotated[Lang, typer.Option("--language", "-l")] = "turkish",
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
) -> None:
    """Create a collection (or update its description)."""
    cw = _citewell()
    try:
        c = cw.store.ensure_collection(name, language, description)
    except ValueError as exc:
        raise _fail(str(exc)) from exc
    finally:
        cw.close()
    console.print(f"[green]✓[/] collection [bold]{c.name}[/] ({c.language})")


@collections_app.command("delete")
def collections_delete(
    name: str, yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False
) -> None:
    """Delete a collection and all of its documents."""
    if not yes:
        typer.confirm(f"Delete collection '{name}' and all its documents?", abort=True)
    cw = _citewell()
    try:
        ok = cw.store.delete_collection(name)
    finally:
        cw.close()
    if not ok:
        raise _fail(f"collection not found: {name}")
    console.print(f"[green]✓[/] deleted {name}")


# ------------------------------------------------------------------------ documents


@documents_app.command("list")
def documents_list(
    collection: Annotated[str | None, typer.Option("--collection", "-c")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List ingested documents."""
    cw = _citewell()
    try:
        docs = cw.store.list_documents(collection)
    finally:
        cw.close()
    if as_json:
        out.print_json(json.dumps([d.model_dump(mode="json") for d in docs]))
        return
    table = Table("collection", "source", "title", "pages", "chunks")
    for d in docs:
        table.add_row(d.collection, d.source, d.title or "", str(d.page_count or "–"), str(d.chunk_count))
    out.print(table)


@documents_app.command("delete")
def documents_delete(
    source: str,
    collection: Annotated[str | None, typer.Option("--collection", "-c")] = None,
) -> None:
    """Delete one document (by its source path) from a collection."""
    cw = _citewell()
    try:
        ok = cw.store.delete_document(collection or cw.settings.default_collection, source)
    finally:
        cw.close()
    if not ok:
        raise _fail("document not found")
    console.print(f"[green]✓[/] deleted {source}")


# --------------------------------------------------------------------------- models


@models_app.command("download")
def models_download(
    reranker: Annotated[
        bool, typer.Option("--reranker/--no-reranker", help="Also fetch the reranker.")
    ] = True,
) -> None:
    """Download the configured embedding (and reranker) model into the local cache.

    Run once with internet access; afterwards Citewell works fully offline
    (set HF_HUB_OFFLINE=1 to make sure nothing is fetched).
    """
    from citewell.embeddings import build_embedder
    from citewell.rerank import build_reranker

    s = get_settings()
    _setup_logging(s)
    if s.embedding_backend == "hash":
        console.print("embedding backend is 'hash' — nothing to download")
    else:
        with console.status(f"downloading {s.embedding_model}…"):
            emb = build_embedder(s.embedding_backend, s.embedding_model, s.embedding_dim, device="cpu")
        console.print(f"[green]✓[/] {emb.name} ({emb.dim}-d)")
    if reranker and s.reranker_backend == "sentence-transformers":
        with console.status(f"downloading {s.reranker_model}…"):
            rr = build_reranker(s.reranker_backend, s.reranker_model, device="cpu")
        if rr is not None:
            console.print(f"[green]✓[/] {rr.name}")


# --------------------------------------------------------------------------- doctor


@app.command()
def doctor() -> None:
    """Check configuration, database, pgvector and models."""
    from citewell import db as dbmod
    from citewell.app import Citewell

    s = get_settings()
    ok = True

    def line(status: bool | None, label: str, detail: str = "") -> None:
        icon = {True: "[green]✓[/]", False: "[red]✗[/]", None: "[yellow]![/]"}[status]
        console.print(f"{icon} {label}{': ' + detail if detail else ''}")

    line(True, "citewell", __version__)
    line(True, "python", sys.version.split()[0])
    cw = Citewell(s)
    try:
        with cw.store.conn() as conn:
            server = conn.execute("SHOW server_version").fetchone()
            line(True, "postgresql", str(server[0]) if server else "?")
            v = dbmod.pgvector_version(conn)
            if v:
                line(True, "pgvector", ".".join(map(str, v)) + ("" if v >= (0, 8) else " (≥0.8 recommended)"))
            else:
                line(False, "pgvector", "extension not installed — run `citewell init`")
                ok = False
        try:
            cw.check_schema()
            line(True, "schema", f"{cw.embedding_model_id} ({s.embedding_dim}-d)")
        except dbmod.SchemaMismatchError as exc:
            line(False, "schema", str(exc))
            ok = False
    except Exception as exc:
        line(False, "database", f"{type(exc).__name__}: {exc}")
        ok = False
    finally:
        cw.close()

    if s.embedding_backend == "hash":
        line(None, "embeddings", "hash backend (testing only, not semantic)")
    else:
        try:
            import sentence_transformers  # noqa: F401

            line(True, "embeddings", f"{s.embedding_model} via sentence-transformers")
        except ImportError:
            line(False, "embeddings", "sentence-transformers missing: pip install 'citewell[models]'")
            ok = False
    line(
        True if s.reranker_backend != "none" else None, "reranker", f"{s.reranker_backend} {s.reranker_model}"
    )
    line(True if s.api_token else None, "api token", "set" if s.api_token else "not set (fine for localhost)")
    if not ok:
        raise typer.Exit(1)


def run() -> None:
    """Console entry point: turn expected operational errors into one-line messages."""
    from citewell.db import DatabaseUnavailableError, SchemaMismatchError

    try:
        app(standalone_mode=True)
    except (DatabaseUnavailableError, SchemaMismatchError) as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":  # pragma: no cover
    run()
