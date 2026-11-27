"""Scoped API tokens: which collections a caller may read and whether it may write.

The ``CITEWELL_API_TOKEN`` environment token and any local use (CLI, stdio MCP) are unrestricted.
Tokens created with ``citewell tokens create`` are stored hashed and carry a ``Scope``. The HTTP
middleware puts the caller's scope in a context variable, and the REST routes and MCP tools read it
from there, so one implementation covers both transports.
"""

import contextvars
import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass

from mcp.server.mcpserver.exceptions import ResourceError, ToolError

TOKEN_PREFIX = "cw_"  # noqa: S105  (a label, not a credential)


class ForbiddenError(PermissionError, ToolError, ResourceError):
    """The token's scope does not allow this request (HTTP 403).

    Also an MCP ``ToolError``/``ResourceError`` so that clients see the reason instead of the SDK's
    generic "error executing tool".
    """


@dataclass(frozen=True, slots=True)
class Scope:
    """What a caller may do. ``collections=None`` means every collection."""

    collections: frozenset[str] | None = None
    can_write: bool = True
    token_name: str | None = None

    def allows(self, collection: str) -> bool:
        return self.collections is None or collection in self.collections

    def require_write(self) -> None:
        if not self.can_write:
            raise ForbiddenError("this token is read-only")

    def require(self, collection: str) -> None:
        if not self.allows(collection):
            raise ForbiddenError(f"token may not access collection: {collection}")

    def resolve(self, requested: Sequence[str] | None, default: str) -> list[str] | None:
        """Collections a search may touch.

        ``None`` keeps the server's default-collection behaviour when that collection is allowed;
        ``["*"]`` expands to everything the token may read; named collections must all be allowed.
        """
        if self.collections is None:
            return None if requested is None else list(requested)
        allowed = sorted(self.collections)
        if requested is None:
            return None if default in self.collections else allowed
        if "*" in requested:
            return allowed
        for name in requested:
            self.require(name)
        return list(requested)

    def resolve_all(self, requested: Sequence[str] | None) -> list[str] | None:
        """Like ``resolve`` for operations that default to *every* collection (quote verification)."""
        if self.collections is None:
            return None if requested is None else list(requested)
        return self.resolve(requested or ["*"], default="")


UNRESTRICTED = Scope()

_current: contextvars.ContextVar[Scope] = contextvars.ContextVar("citewell_scope", default=UNRESTRICTED)


def current_scope() -> Scope:
    return _current.get()


def set_scope(scope: Scope) -> contextvars.Token[Scope]:
    return _current.set(scope)


def reset_scope(token: contextvars.Token[Scope]) -> None:
    _current.reset(token)


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # Tokens are 256-bit random values, so a plain fast hash is enough (no salt or stretching needed).
    return hashlib.sha256(token.encode()).hexdigest()
