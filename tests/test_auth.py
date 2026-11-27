"""Token scopes: pure logic that needs no database."""

from __future__ import annotations

import pytest

from citewell import auth
from citewell.auth import UNRESTRICTED, ForbiddenError, Scope


def test_unrestricted_scope_passes_everything_through() -> None:
    assert UNRESTRICTED.allows("anything")
    UNRESTRICTED.require("anything")
    UNRESTRICTED.require_write()
    assert UNRESTRICTED.resolve(None, "default") is None
    assert UNRESTRICTED.resolve(["a", "*"], "default") == ["a", "*"]
    assert UNRESTRICTED.resolve_all(None) is None
    assert UNRESTRICTED.resolve_all(["x"]) == ["x"]


def test_scoped_resolve() -> None:
    scope = Scope(collections=frozenset({"default", "hukuk"}), can_write=False)
    assert scope.resolve(None, "default") is None  # default collection is allowed: keep server default
    assert scope.resolve(None, "other") == ["default", "hukuk"]
    assert scope.resolve(["*"], "default") == ["default", "hukuk"]
    assert scope.resolve(["hukuk"], "default") == ["hukuk"]
    with pytest.raises(ForbiddenError, match="secret"):
        scope.resolve(["hukuk", "secret"], "default")
    assert scope.resolve_all(None) == ["default", "hukuk"]
    assert scope.resolve_all(["hukuk"]) == ["hukuk"]
    with pytest.raises(ForbiddenError):
        scope.resolve_all(["secret"])


def test_read_only_scope_rejects_writes() -> None:
    with pytest.raises(ForbiddenError, match="read-only"):
        Scope(collections=frozenset({"a"}), can_write=False).require_write()
    Scope(collections=frozenset({"a"}), can_write=True).require_write()


def test_current_scope_defaults_to_unrestricted_and_resets() -> None:
    assert auth.current_scope() is UNRESTRICTED
    narrow = Scope(collections=frozenset({"a"}))
    handle = auth.set_scope(narrow)
    assert auth.current_scope() is narrow
    auth.reset_scope(handle)
    assert auth.current_scope() is UNRESTRICTED


def test_tokens_are_random_and_hashed() -> None:
    a, b = auth.new_token(), auth.new_token()
    assert a != b and a.startswith("cw_") and len(a) > 40
    assert auth.hash_token(a) == auth.hash_token(a) != auth.hash_token(b)
    assert a not in auth.hash_token(a)
