"""REST API (FastAPI) with the MCP Streamable HTTP endpoint mounted at ``/mcp``."""

import contextlib
import hmac
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from citewell import __version__
from citewell.app import Citewell
from citewell.db import SchemaMismatchError
from citewell.loaders import SUPPORTED_SUFFIXES
from citewell.mcp_server import build_server
from citewell.models import (
    ChunkRecord,
    Collection,
    DocumentInfo,
    IngestResult,
    QuoteCheck,
    SearchResponse,
)
from citewell.search import SearchRequest
from citewell.store import NotFoundError

log = logging.getLogger(__name__)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    collections: list[str] | None = None
    rerank: bool | None = None
    source_prefix: str | None = None


class VerifyBody(BaseModel):
    quote: str = Field(min_length=1, max_length=4000)
    chunk_id: str | None = None
    source: str | None = None
    collections: list[str] | None = None


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
    """Pure ASGI middleware so it also protects the mounted MCP app (which streams)."""

    def __init__(self, app: ASGIApp, token: str, exempt: tuple[str, ...] = ("/health",)):
        self.app = app
        self.token = token.encode()
        self.exempt = exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"")
        scheme, _, value = auth.partition(b" ")
        if scheme.lower() != b"bearer" or not hmac.compare_digest(value.strip(), self.token):
            response = JSONResponse({"detail": "invalid or missing bearer token"}, status_code=401)
            response.headers["WWW-Authenticate"] = "Bearer"
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


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

    @api.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

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

    @api.post("/v1/search", response_model=SearchResponse, tags=["search"])
    def search(body: SearchBody, cw: Svc) -> SearchResponse:
        return cw.search.search(
            SearchRequest(
                query=body.query,
                top_k=body.top_k,
                mode=body.mode,
                collections=body.collections,
                rerank=body.rerank,
                source_prefix=body.source_prefix,
            )
        )

    @api.get("/v1/search", response_model=SearchResponse, tags=["search"])
    def search_get(
        cw: Svc,
        q: Annotated[str, Query(min_length=1, max_length=2000)],
        k: Annotated[int, Query(ge=1, le=50)] = 5,
        mode: Literal["hybrid", "vector", "keyword"] = "hybrid",
        collection: Annotated[list[str] | None, Query()] = None,
        rerank: bool | None = None,
    ) -> SearchResponse:
        return cw.search.search(
            SearchRequest(query=q, top_k=k, mode=mode, collections=collection, rerank=rerank)
        )

    @api.post("/v1/verify", response_model=QuoteCheck, tags=["search"])
    def verify(body: VerifyBody, cw: Svc) -> QuoteCheck:
        return cw.verifier.verify(
            body.quote, chunk_id=body.chunk_id, source=body.source, collections=body.collections
        )

    @api.get("/v1/chunks/{chunk_id}", response_model=list[ChunkRecord], tags=["chunks"])
    def get_chunk(
        chunk_id: str, cw: Svc, context: Annotated[int, Query(ge=0, le=5)] = 0
    ) -> list[ChunkRecord]:
        return cw.store.neighbours(chunk_id, window=context)

    @api.get("/v1/collections", response_model=list[Collection], tags=["collections"])
    def list_collections(cw: Svc) -> list[Collection]:
        return cw.store.list_collections()

    @api.post("/v1/collections", response_model=Collection, status_code=201, tags=["collections"])
    def create_collection(body: CollectionBody, cw: Svc) -> Collection:
        return cw.store.ensure_collection(body.name, body.language, body.description)

    @api.delete("/v1/collections/{name}", status_code=204, tags=["collections"])
    def delete_collection(name: str, cw: Svc) -> None:
        if not cw.store.delete_collection(name):
            raise HTTPException(404, f"collection not found: {name}")

    @api.get("/v1/documents", response_model=list[DocumentInfo], tags=["documents"])
    def list_documents(cw: Svc, collection: str | None = None) -> list[DocumentInfo]:
        return cw.store.list_documents(collection)

    @api.delete("/v1/documents", status_code=204, tags=["documents"])
    def delete_document(cw: Svc, collection: str, source: str) -> None:
        if not cw.store.delete_document(collection, source):
            raise HTTPException(404, "document not found")

    @api.post("/v1/documents", response_model=IngestResult, tags=["documents"])
    async def upload_document(
        cw: Svc,
        file: Annotated[UploadFile, File(description="PDF, Markdown, TXT, HTML or DOCX")],
        collection: Annotated[str | None, Form()] = None,
        language: Annotated[Literal["turkish", "english", "simple"] | None, Form()] = None,
        force: Annotated[bool, Form()] = False,
    ) -> IngestResult:
        name = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
        if not any(name.lower().endswith(s) for s in SUPPORTED_SUFFIXES):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported file type: {name}")
        limit = settings.max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large")
        return await run_in_threadpool(cw.ingest.ingest_bytes, data, name, collection, language, force)

    if mcp_app is not None:
        # Mounted last so that it only receives /mcp (all other routes match first).
        api.mount("/", mcp_app)

    if settings.api_token is not None:
        api.add_middleware(BearerAuthMiddleware, token=settings.api_token.get_secret_value())

    return api
