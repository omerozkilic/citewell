from __future__ import annotations

import pytest

from citewell.ratelimit import PRUNE_ABOVE, WINDOW_SECONDS, RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_disabled_limiter_never_blocks() -> None:
    limiter = RateLimiter(0)
    assert all(limiter.check("k") is None for _ in range(1000))


def test_sliding_window_blocks_then_recovers() -> None:
    clock = Clock()
    limiter = RateLimiter(3, clock)
    assert [limiter.check("a") for _ in range(3)] == [None, None, None]
    wait = limiter.check("a")
    assert wait == pytest.approx(WINDOW_SECONDS)
    assert limiter.check("b") is None  # keys are independent
    clock.now += 40
    assert limiter.check("a") == pytest.approx(WINDOW_SECONDS - 40)
    clock.now += WINDOW_SECONDS - 40
    assert limiter.check("a") is None  # the first hits have left the window


def test_negative_limit_means_off() -> None:
    assert RateLimiter(-5).check("x") is None


def test_idle_keys_are_pruned() -> None:
    clock = Clock()
    limiter = RateLimiter(1, clock)
    for i in range(PRUNE_ABOVE + 1):
        limiter.check(f"ip-{i}")
    clock.now += WINDOW_SECONDS + 1
    limiter.check("fresh")
    assert list(limiter._hits) == ["fresh"]
