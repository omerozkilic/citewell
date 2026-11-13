#!/usr/bin/env bash
# Patch coverage of your branch, measured like Codecov does: only the lines this branch changes.
#
#   CITEWELL_TEST_DATABASE_URL=postgresql://citewell:citewell@localhost:5432/citewell_test \
#     scripts/check_patch_coverage.sh [base-branch] [minimum-percent]
#
# Codecov's `patch` status fails a PR when the changed lines are covered less than the project is
# (about 92 %), so the default minimum here is 95 % to leave a margin. It lists every uncovered
# changed line. A test database is required: without it the database-backed code looks uncovered
# here although CI covers it, and the number is wrong.
set -euo pipefail

base="${1:-origin/main}"
minimum="${2:-95}"
report="$(mktemp -t citewell-cov.XXXXXX.xml)"
trap 'rm -f "$report"' EXIT

if [ -z "${CITEWELL_TEST_DATABASE_URL:-}" ]; then
  echo "error: set CITEWELL_TEST_DATABASE_URL (a throwaway pgvector database, see CONTRIBUTING.md)." >&2
  exit 2
fi

git fetch -q origin "${base#origin/}" 2>/dev/null || true
uv run pytest -q --cov --cov-report="xml:${report}" --cov-report=
uv run diff-cover "$report" --compare-branch="$base" --fail-under="$minimum"
