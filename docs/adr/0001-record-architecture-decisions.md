# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

Citewell is a portfolio-grade open-source project. Design trade-offs (storage, retrieval, protocol,
security) should be explainable to contributors and reviewers long after they were made.

## Decision

We keep lightweight Architecture Decision Records (Michael Nygard format) in `docs/adr/`, numbered
sequentially, one decision per file. Significant changes to architecture require a new ADR; an ADR is
never rewritten after acceptance — it is superseded by a new one.

## Consequences

- Reviewers can see *why*, not only *what*.
- Small overhead per significant change.
