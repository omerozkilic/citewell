"""Keep model loading offline once models are cached.

``huggingface_hub`` reads ``HF_HUB_OFFLINE`` once, at import time. Even with
``local_files_only=True`` some code paths in transformers / sentence-transformers
still call the Hub API (model info, safetensors conversions …). So before the
first import we check whether every model Citewell needs is already in the local
cache and, if so, switch the Hub client to offline mode for this process.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def hub_cache_dir() -> Path:
    """Resolve the Hugging Face cache directory exactly like ``huggingface_hub.constants``."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.path.expandvars(os.environ["HF_HUB_CACHE"])).expanduser()
    if os.environ.get("HUGGINGFACE_HUB_CACHE"):
        return Path(os.path.expandvars(os.environ["HUGGINGFACE_HUB_CACHE"])).expanduser()
    default_home = os.path.join(os.path.expanduser("~"), ".cache")
    hf_home = os.environ.get("HF_HOME") or os.path.join(
        os.environ.get("XDG_CACHE_HOME", default_home), "huggingface"
    )
    return Path(os.path.expandvars(hf_home)).expanduser() / "hub"


def is_model_cached(model_name: str) -> bool:
    """True if a snapshot of ``model_name`` exists locally (or it is a local directory)."""
    if Path(model_name).expanduser().is_dir():
        return True
    snapshots = hub_cache_dir() / f"models--{model_name.replace('/', '--')}" / "snapshots"
    try:
        return any(p.is_dir() and any(p.iterdir()) for p in snapshots.iterdir())
    except OSError:
        return False


def offline_requested() -> bool:
    return any(
        os.environ.get(v, "").strip().lower() in _TRUE for v in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    )


def prefer_offline(model_names: Iterable[str]) -> bool:
    """Enable ``HF_HUB_OFFLINE`` if all models are cached. Returns whether offline mode is on.

    The user's explicit choice always wins: an existing ``HF_HUB_OFFLINE`` value is left alone.
    """
    if "HF_HUB_OFFLINE" in os.environ or "TRANSFORMERS_OFFLINE" in os.environ:
        return offline_requested()
    names = [n for n in model_names if n]
    if not names or not all(is_model_cached(n) for n in names):
        return False
    if "huggingface_hub" in sys.modules:
        # Too late for this process: the Hub client already read its configuration.
        log.debug("huggingface_hub already imported; cannot switch to offline mode")
        return False
    os.environ["HF_HUB_OFFLINE"] = "1"
    log.debug("all models cached (%s); Hugging Face Hub offline mode enabled", ", ".join(names))
    return True
