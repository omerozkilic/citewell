## What & why

<!-- What does this change and why? Link issues: "Closes #123". -->

## How was it tested?

- [ ] `uv run pytest` (with `CITEWELL_TEST_DATABASE_URL` set for DB tests)
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
- [ ] `scripts/check_patch_coverage.sh` reports ≥ 95 % (Codecov's `patch` check; needs `CITEWELL_TEST_DATABASE_URL`)
- [ ] Retrieval quality unchanged or improved (`citewell eval examples/eval/tr-sample.jsonl`), if search/chunking changed

## Checklist

- [ ] PR title follows [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` …)
- [ ] Docs / ADR updated if behaviour or architecture changed
