# Contributing to Citewell

Thanks for your interest! Bug reports, eval queries, docs fixes and code are all welcome.
Türkçe katkılar da memnuniyetle karşılanır — issue ve PR'ları Türkçe açabilirsiniz.

## Development setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker (for PostgreSQL + pgvector).

```bash
git clone https://github.com/omerozkilic/citewell && cd citewell
uv sync --group dev                      # add --extra models for real embedding models
docker compose up -d db                  # PostgreSQL 17 + pgvector on localhost:5432
```

Database tests use a separate database:

```bash
docker compose exec db createdb -U citewell citewell_test
export CITEWELL_TEST_DATABASE_URL=postgresql://citewell:citewell@localhost:5432/citewell_test
uv run pytest --cov
```

Without `CITEWELL_TEST_DATABASE_URL` the database tests are skipped and only unit tests run.

### Fast local loop without model downloads

`CITEWELL_EMBEDDING_BACKEND=hash` and `CITEWELL_RERANKER_BACKEND=lexical` replace the neural
models with deterministic lexical stand-ins. They are **not** semantic and exist for tests, CI and
plumbing checks only.

```bash
export CITEWELL_EMBEDDING_BACKEND=hash CITEWELL_RERANKER_BACKEND=lexical
uv run citewell init
uv run citewell ingest examples/corpus
uv run citewell eval examples/eval/tr-sample.jsonl -r vector,keyword,hybrid,hybrid+rerank
```

## Quality gates (CI runs all of these)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src            # strict mode
uv run pytest --cov --cov-fail-under=85
```

Optional: `uvx pre-commit install` to run ruff on every commit.

## Releases and the MCP Registry

Releases are cut by merging the release-please PR: it bumps the version, tags it and publishes to PyPI and
ghcr.io. `server.json` (the listing for the [MCP Registry](https://registry.modelcontextprotocol.io)) is bumped
by the same PR, and `tests/test_server_json.py` checks it against the registry schema, the PyPI package and the
README. The registry verifies the *published* PyPI README for the `mcp-name:` marker, so list a version only
after it is on PyPI:

```bash
brew install mcp-publisher              # or the release binary, see the registry quickstart
mcp-publisher login github              # the name io.github.omerozkilic/citewell needs this account
mcp-publisher publish                   # run in the repository root, at the released tag
```

Quickstart and troubleshooting: <https://modelcontextprotocol.io/registry/quickstart>.

## Eval baselines

CI compares `citewell eval` with the files in `examples/eval/baselines/` and fails when Recall@k, MRR@k
or page hit drop by more than 0.02. After an intentional retrieval change, refresh them with the same
settings CI uses (hash embeddings, lexical reranker, the `examples/corpus*` documents ingested) and
commit the diff together with the change:

```bash
CITEWELL_EMBEDDING_BACKEND=hash CITEWELL_RERANKER_BACKEND=lexical \
  uv run citewell eval examples/eval/tr-sample.jsonl -r vector,keyword,hybrid,hybrid+rerank \
  --write-baseline examples/eval/baselines/tr-sample.json
CITEWELL_EMBEDDING_BACKEND=hash CITEWELL_RERANKER_BACKEND=lexical \
  uv run citewell eval examples/eval/tr-sample-ascii.jsonl -r keyword,hybrid \
  --write-baseline examples/eval/baselines/tr-sample-ascii.json
```

## Changing retrieval behaviour

If you touch chunking, loaders, ranking or fusion, include before/after numbers from
`citewell eval` (ideally with `BAAI/bge-m3`) in the PR description. New eval queries for
`examples/eval/*.jsonl` are very welcome, especially Turkish ones with tricky morphology.

## Architecture decisions

Significant design changes need an ADR in [`docs/adr/`](docs/adr/). Copy
[`docs/adr/template.md`](docs/adr/template.md), number it sequentially and link it from the PR.

## Commits and releases

- Use [Conventional Commits](https://www.conventionalcommits.org/) for PR titles: `feat:`, `fix:`,
  `docs:`, `perf:`, `refactor:`, `test:`, `ci:`, `chore:`. PRs are squash-merged, so the title becomes
  the commit message.
- [release-please](https://github.com/googleapis/release-please) turns those commits into a release PR
  with a changelog; merging it tags the release and publishes to PyPI and GHCR.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating you agree to
uphold it.
