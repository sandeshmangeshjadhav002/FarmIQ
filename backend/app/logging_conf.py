"""Centralised logging configuration."""
from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level)
    # Quiet noisy libraries; keep our own logs visible.
    for noisy in ("urllib3", "httpx", "httpcore", "watchfiles", "anyio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("supabase").setLevel(logging.INFO)
