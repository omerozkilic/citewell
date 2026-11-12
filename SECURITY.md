# Security Policy

## Supported versions

Citewell is pre-1.0. Security fixes are released for the latest minor version only.

| Version | Supported |
|---|---|
| latest `0.x` | ✅ |
| older | ❌ |

## Reporting a vulnerability

**Please do not open a public issue.** Report privately via
[GitHub Security Advisories](https://github.com/omerozkilic/citewell/security/advisories/new).

You can expect an acknowledgement within 3 business days and a status update within 10 business
days. Once a fix is available we will publish an advisory and credit you (unless you prefer
otherwise).

## Threat model and hardening notes

Citewell is designed to run **locally or inside a trusted network**. Things to keep in mind:

- **Retrieved text is untrusted.** Documents can contain prompt-injection payloads
  ("ignore previous instructions…"). Citewell returns passages verbatim and its MCP server is
  **read-only by design** — there are no ingest/delete tools, so a malicious document cannot make an
  assistant modify your index through Citewell. The server instructions tell assistants to treat
  passage content as data. Still, only ingest documents you are willing to show to your assistant.
- **Network exposure.** By default the server binds to `127.0.0.1` and the Docker Compose file
  publishes ports on `127.0.0.1` only. The HTTP MCP endpoint validates `Host`/`Origin` headers against
  DNS-rebinding attacks. If you expose Citewell beyond localhost, set `CITEWELL_API_TOKEN` (bearer
  auth for REST and MCP) and put it behind TLS.
- **Query limits.** Search queries are capped at 2000 characters and `top_k` at `CITEWELL_MAX_TOP_K` on
  both REST and MCP, and every search runs under `CITEWELL_STATEMENT_TIMEOUT_MS` (default 15 s), so a
  single expensive query cannot hold a database connection indefinitely.
- **Container.** The Compose service runs as a non-root user with a read-only root filesystem, all Linux
  capabilities dropped and `no-new-privileges`; only `/models` (volume) and `/tmp` are writable.
- **Parser limits.** PDFs above `CITEWELL_MAX_DOCUMENT_PAGES` and DOCX files that unpack beyond
  `CITEWELL_MAX_UNPACKED_MB` or compress beyond `CITEWELL_MAX_ZIP_RATIO` are rejected before parsing.
- **OCR.** When enabled (`CITEWELL_OCR=auto`), pages are rendered in-process and recognised by a local
  `tesseract` subprocess with a per-page timeout and a per-document page cap. Nothing is sent over the
  network. OCR text is approximate and is marked as such (`ocr_pages`).
- **Models.** Citewell never enables `trust_remote_code` (a test enforces it). Set
  `CITEWELL_EMBEDDING_REVISION` / `CITEWELL_RERANKER_REVISION` to a commit hash (printed by
  `citewell models download`) so a model update on the Hub cannot silently change behaviour.
- **Uploads.** `POST /v1/documents` accepts only supported extensions and enforces
  `CITEWELL_MAX_UPLOAD_MB`. Filenames are reduced to their basename. PDF parsing uses `pypdf`; keep
  dependencies up to date (Dependabot is enabled).
- **Database credentials.** The defaults in `compose.yaml` are for local development. Change
  `CITEWELL_DB_PASSWORD` for anything else.
- **Supply chain.** CI runs `pip-audit` on the locked dependencies (on every dependency change and weekly)
  and scans the Docker image with Trivy (HIGH/CRITICAL, fixable only). Each release attaches a CycloneDX
  SBOM, and the wheel, sdist and container image carry build-provenance attestations. Verify with
  `gh attestation verify <file> --repo omerozkilic/citewell` or, for the image,
  `gh attestation verify oci://ghcr.io/omerozkilic/citewell:<version> --repo omerozkilic/citewell`.
- **Offline operation.** After `citewell models download`, set `HF_HUB_OFFLINE=1` to guarantee that no
  network calls are made to model hubs. Citewell itself never calls an LLM or any external API.
