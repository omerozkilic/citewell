"""REST API (FastAPI) with the MCP Streamable HTTP endpoint mounted at ``/mcp``."""

import contextlib
import hmac
import logging
import math
import time
from collections.abc import AsyncIterator
from datetime import date
from importlib import resources
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Send
from starlette.types import Scope as Scope_

from citewell import __version__
from citewell.app import Citewell
from citewell.audit import AuditLog
from citewell.auth import (
    ADMIN,
    UNRESTRICTED,
    ForbiddenError,
    Scope,
    current_scope,
    hash_token,
    reset_scope,
    set_scope,
)
from citewell.citations import CiteFormat, render
from citewell.config import MAX_QUERY_CHARS
from citewell.db import SchemaMismatchError
from citewell.loaders import SUPPORTED_SUFFIXES
from citewell.mcp_server import build_server
from citewell.metrics import Metrics
from citewell.models import (
    ChunkRecord,
    Collection,
    DocumentInfo,
    IngestResult,
    QuoteCheck,
    SearchFilters,
    SearchResponse,
    normalise_tags,
)
from citewell.openai_compat import (
    ChatRequest,
    completion,
    model_list,
    render_answer,
    stream_events,
)
from citewell.ratelimit import RateLimiter
from citewell.search import SearchRequest
from citewell.store import NotFoundError, QueryTimeoutError

log = logging.getLogger(__name__)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    collections: list[str] | None = None
    rerank: bool | None = None
    source_prefix: str | None = None
    filters: SearchFilters | None = None


class VerifyBody(BaseModel):
    quote: str = Field(min_length=1, max_length=4000)
    chunk_id: str | None = None
    source: str | None = None
    collections: list[str] | None = None


class CiteBody(BaseModel):
    chunk_ids: list[str] = Field(min_length=1, max_length=100)
    format: CiteFormat = "bibtex"
    quotes: bool = Field(default=False, description="Markdown only: no quotes are known for plain chunk ids.")


class CollectionBody(BaseModel):
    name: str
    language: Literal["turkish", "english", "simple"] = "turkish"
    description: str | None = None


class Health(BaseModel):
    status: str
    version: str
    database: str
    embedding_model: str


class BearerAuthMiddleware:
    """Pure ASGI middleware so it also protects the mounted MCP app (which streams).

    A request is accepted with the ``CITEWELL_API_TOKEN`` (unrestricted) or with an active scoped token
    from ``citewell tokens create``. While neither is configured the server is open, as before.
    """

    def __init__(
        self,
        app: ASGIApp,
        cw: Citewell,
        token: str | None = None,
        exempt: tuple[str, ...] = ("/health",),
    ):
        self.app = app
        self.cw = cw
        self.limiter = RateLimiter(cw.settings.rate_limit_per_minute)
        self.audit = AuditLog(cw.settings.audit_log)
        self.token = token.encode() if token is not None else None
        self.exempt = exempt

    def _authenticate(self, presented: bytes | None) -> Scope | None:
        if presented and self.token is not None and hmac.compare_digest(presented, self.token):
            return ADMIN
        if presented:
            scope = self.cw.store.token_scope(hash_token(presented.decode("utf-8", "replace")))
            if scope is not None:
                return scope
        if self.token is None and not self.cw.store.has_active_tokens():
            return UNRESTRICTED
        return None

    async def __call__(self, scope: Scope_, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt:
            await self.app(scope, receive, send)
            return
        status_code = 500
        caller: Scope | None = None

        async def send_logged(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            caller = await self._handle(scope, receive, send_logged)
        finally:
            if self.audit.enabled:
                client = scope.get("client")
                await run_in_threadpool(
                    self.audit.record,
                    caller.token_name if caller else None,
                    scope["method"],
                    scope["path"],
                    status_code,
                    client[0] if client else None,
                )

    async def _handle(self, scope: Scope_, receive: Receive, send: Send) -> Scope | None:
        """Authenticate, rate-limit and forward the request; returns the caller (None if rejected)."""
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"")
        scheme, _, value = auth.partition(b" ")
        presented = value.strip() if scheme.lower() == b"bearer" else None
        caller = await run_in_threadpool(self._authenticate, presented)
        if caller is None:
            response = JSONResponse({"detail": "invalid or missing bearer token"}, status_code=401)
            response.headers["WWW-Authenticate"] = "Bearer"
            await response(scope, receive, send)
            return None
        client = scope.get("client")
        retry_after = self.limiter.check(caller.token_name or (client[0] if client else "unknown"))
        if retry_after is not None:
            limited = JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
            limited.headers["Retry-After"] = str(math.ceil(retry_after) or 1)
            await limited(scope, receive, send)
            return caller
        reset = set_scope(caller)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_scope(reset)
        return caller


UI_ASSETS = {
    "/ui/": ("index.html", "text/html"),
    "/ui/app.js": ("app.js", "text/javascript"),
    "/ui/style.css": ("style.css", "text/css"),
}
UI_PATHS = ("/ui", *UI_ASSETS)
UI_HEADERS = {
    # Scripts and styles only from this server, no inline code, nothing embedded elsewhere.
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


def _ui_response(name: str, media_type: str) -> Response:
    data = resources.files("citewell").joinpath("ui", name).read_bytes()
    return Response(data, media_type=f"{media_type}; charset=utf-8", headers=UI_HEADERS)


class MetricsMiddleware:
    """Counts HTTP requests and their duration, labelled by route template (never the raw path)."""

    def __init__(self, app: ASGIApp, metrics: Metrics):
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope_, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        status_code = 500

        async def send_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_status)
        finally:
            route = getattr(scope.get("route"), "path", None)
            if route in (None, "/"):  # unmatched, or the mounted MCP app
                route = "/mcp" if scope["path"] == "/mcp" else "other"
            self.metrics.counter(
                "citewell_http_requests_total",
                "HTTP requests.",
                method=scope["method"],
                route=route,
                status=str(status_code),
            )
            self.metrics.observe(
                "citewell_http_request_duration_seconds",
                "HTTP request duration.",
                time.perf_counter() - t0,
                route=route,
            )


def create_app(citewell: Citewell | None = None, mount_mcp: bool = True) -> FastAPI:
    cw = citewell or Citewell()
    settings = cw.settings
    mcp = build_server(cw) if mount_mcp else None
    mcp_app = None
    if mcp is not None:
        security = None
        if settings.allowed_hosts or settings.host in ("127.0.0.1", "localhost", "::1"):
            hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *settings.allowed_hosts]
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts],
            )
        mcp_app = mcp.streamable_http_app(
            streamable_http_path="/mcp",
            transport_security=security,
            host=settings.host,
            stateless_http=True,
            json_response=True,
        )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            cw.check_schema()
        except SchemaMismatchError as exc:
            log.warning("%s", exc)
        if mcp is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield
        cw.close()

    api = FastAPI(
        title="Citewell",
        version=__version__,
        summary="Citation-grounded document memory for AI assistants.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    def service() -> Citewell:
        return cw

    Svc = Annotated[Citewell, Depends(service)]

    @api.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @api.exception_handler(ForbiddenError)
    async def _forbidden(_: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @api.exception_handler(QueryTimeoutError)
    async def _timeout(_: Request, exc: QueryTimeoutError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=504)

    @api.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    if settings.ui:
        # Static files only: they hold no data, so a browser can load them before it has a token.
        # Everything the page does goes through the API, which still checks the token.
        for path, (name, media_type) in {"/ui": ("index.html", "text/html"), **UI_ASSETS}.items():

            def ui_file(name: str = name, media_type: str = media_type) -> Response:
                return _ui_response(name, media_type)

            api.add_api_route(path, ui_file, methods=["GET", "HEAD"], include_in_schema=False)

    @api.get("/health", response_model=Health, tags=["meta"])
    def health(cw: Svc) -> Health:
        try:
            meta = cw.store.meta()
            db_status = "ok" if meta else "uninitialised"
        except Exception as exc:
            log.warning("health check failed: %s", exc)
            db_status = "unreachable"
        return Health(
            status="ok" if db_status == "ok" else "degraded",
            version=__version__,
            database=db_status,
            embedding_model=cw.embedding_model_id,
        )

    if settings.metrics:

        @api.get("/metrics", include_in_schema=False, response_class=PlainTextResponse)
        def metrics_endpoint(cw: Svc) -> Response:
            if current_scope().collections is not None:  # names and sizes of every collection
                raise ForbiddenError("metrics need an unrestricted token")
            gauges: list[tuple[str, str, tuple[tuple[str, str], ...], float]] = [
                ("citewell_build_info", "Version of the running server.", (("version", __version__),), 1.0)
            ]
            for c in cw.store.list_collections():
                labels = (("collection", c.name),)
                gauges.append(("citewell_documents", "Documents per collection.", labels, c.document_count))
                gauges.append(("citewell_chunks", "Chunks per collection.", labels, c.chunk_count))
            return Response(cw.metrics.render(gauges), media_type="text/plain; version=0.0.4; charset=utf-8")

    @api.post("/v1/search", response_model=SearchResponse, tags=["search"])
    def search(body: SearchBody, cw: Svc) -> SearchResponse:
        return cw.search.search(
            SearchRequest(
                query=body.query,
                top_k=body.top_k,
                mode=body.mode,
                collections=current_scope().resolve(body.collections, settings.default_collection),
                rerank=body.rerank,
                source_prefix=body.source_prefix,
                filters=body.filters,
            )
        )

    @api.get("/v1/search", response_model=SearchResponse, tags=["search"])
    def search_get(
        cw: Svc,
        q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_CHARS)],
        k: Annotated[int, Query(ge=1, le=50)] = 5,
        mode: Literal["hybrid", "vector", "keyword"] = "hybrid",
        collection: Annotated[list[str] | None, Query()] = None,
        rerank: bool | None = None,
        type: Annotated[list[str] | None, Query(description="File extension, repeatable.")] = None,
        author: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        tag: Annotated[list[str] | None, Query(description="Required tag, repeatable.")] = None,
    ) -> SearchResponse:
        return cw.search.search(
            SearchRequest(
                query=q,
                top_k=k,
                mode=mode,
                collections=current_scope().resolve(collection, settings.default_collection),
                rerank=rerank,
                filters=SearchFilters(
                    file_types=type or [], author=author, date_from=date_from, date_to=date_to, tags=tag or []
                ),
            )
        )

    @api.post("/v1/verify", response_model=QuoteCheck, tags=["search"])
    def verify(body: VerifyBody, cw: Svc) -> QuoteCheck:
        scope = current_scope()
        if body.chunk_id:
            scope.require(cw.store.get_chunk(body.chunk_id).collection)
        return cw.verifier.verify(
            body.quote,
            chunk_id=body.chunk_id,
            source=body.source,
            collections=scope.resolve_all(body.collections),
        )

    @api.get("/v1/chunks/{chunk_id}", response_model=list[ChunkRecord], tags=["chunks"])
    def get_chunk(
        chunk_id: str, cw: Svc, context: Annotated[int, Query(ge=0, le=5)] = 0
    ) -> list[ChunkRecord]:
        rows = cw.store.neighbours(chunk_id, window=context)
        scope = current_scope()
        for row in rows:
            scope.require(row.collection)
        return rows

    @api.get("/v1/models", tags=["openai"], summary="Models for OpenAI-compatible clients")
    def list_models(cw: Svc) -> dict[str, Any]:
        scope = current_scope()
        return model_list([c.name for c in cw.store.list_collections() if scope.allows(c.name)])

    @api.post("/v1/chat/completions", tags=["openai"], summary="OpenAI-compatible chat (retrieval only)")
    def chat_completions(body: ChatRequest, cw: Svc) -> Response:
        """Returns the cited passages for the last user message as the assistant message. No LLM."""
        query = body.question()
        if len(query) > MAX_QUERY_CHARS:
            raise ValueError(f"the question is longer than {MAX_QUERY_CHARS} characters")
        name = body.collection()
        resp = cw.search.search(
            SearchRequest(
                query=query,
                top_k=body.top_k or settings.default_top_k,
                mode=body.mode or settings.default_mode,
                collections=current_scope().resolve([name or "*"], settings.default_collection),
                rerank=body.rerank,
            )
        )
        content = render_answer(resp)
        if body.stream:
            return StreamingResponse(
                stream_events(content, body.model),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(completion(content, body.model))

    @api.post(
        "/v1/cite",
        tags=["chunks"],
        response_class=PlainTextResponse,
        responses={
            200: {"content": {"application/x-bibtex": {}, "application/json": {}, "text/markdown": {}}}
        },
    )
    def cite(body: CiteBody, cw: Svc) -> Response:
        items = cw.store.cite_items(body.chunk_ids)
        scope = current_scope()
        for item in items:
            scope.require(item.collection)
        media = {"bibtex": "application/x-bibtex", "csl-json": "application/json", "md": "text/markdown"}
        return Response(render(items, body.format), media_type=f"{media[body.format]}; charset=utf-8")

    @api.get("/v1/collections", response_model=list[Collection], tags=["collections"])
    def list_collections(cw: Svc) -> list[Collection]:
        scope = current_scope()
        return [c for c in cw.store.list_collections() if scope.allows(c.name)]

    @api.post("/v1/collections", response_model=Collection, status_code=201, tags=["collections"])
    def create_collection(body: CollectionBody, cw: Svc) -> Collection:
        scope = current_scope()
        scope.require_write()
        scope.require(body.name)
        return cw.store.ensure_collection(body.name, body.language, body.description)

    @api.delete("/v1/collections/{name}", status_code=204, tags=["collections"])
    def delete_collection(name: str, cw: Svc) -> None:
        scope = current_scope()
        scope.require_write()
        scope.require(name)
        if not cw.store.delete_collection(name):
            raise HTTPException(404, f"collection not found: {name}")

    @api.get("/v1/documents", response_model=list[DocumentInfo], tags=["documents"])
    def list_documents(cw: Svc, collection: str | None = None) -> list[DocumentInfo]:
        scope = current_scope()
        if collection:
            scope.require(collection)
        return [d for d in cw.store.list_documents(collection) if scope.allows(d.collection)]

    @api.delete("/v1/documents", status_code=204, tags=["documents"])
    def delete_document(cw: Svc, collection: str, source: str) -> None:
        scope = current_scope()
        scope.require_write()
        scope.require(collection)
        if not cw.store.delete_document(collection, source):
            raise HTTPException(404, "document not found")

    @api.post("/v1/documents", response_model=IngestResult, tags=["documents"])
    async def upload_document(
        cw: Svc,
        file: Annotated[
            UploadFile, File(description="PDF, Markdown, TXT, HTML, DOCX, PPTX, XLSX, CSV, EPUB, EML")
        ],
        collection: Annotated[str | None, Form()] = None,
        language: Annotated[Literal["turkish", "english", "simple"] | None, Form()] = None,
        force: Annotated[bool, Form()] = False,
        tags: Annotated[list[str] | None, Form(description="Tag to attach, repeatable.")] = None,
    ) -> IngestResult:
        scope = current_scope()
        scope.require_write()
        scope.require(collection or settings.default_collection)
        name = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
        if not any(name.lower().endswith(s) for s in SUPPORTED_SUFFIXES):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported file type: {name}")
        limit = settings.max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large")
        return await run_in_threadpool(
            cw.ingest.ingest_bytes, data, name, collection, language, force, normalise_tags(tags or [])
        )

    if mcp_app is not None:
        # Mounted last so that it only receives /mcp (all other routes match first).
        api.mount("/", mcp_app)

    api.add_middleware(
        BearerAuthMiddleware,
        cw=cw,
        token=settings.api_token.get_secret_value() if settings.api_token is not None else None,
        exempt=("/health", *UI_PATHS) if settings.ui else ("/health",),
    )
    if settings.metrics:
        api.add_middleware(MetricsMiddleware, metrics=cw.metrics)  # added last = outermost: sees 401 and 429

    return api
