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
