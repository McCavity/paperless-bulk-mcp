"""pytest fixtures for paperless-bulk-mcp.

Stubs env vars BEFORE server.py is imported (the module fails fast at import
time if PAPERLESS_URL / PAPERLESS_TOKEN are missing). All tests use respx to
mock the httpx layer — no live Paperless calls.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Stub env before importing server. Must run BEFORE pytest collects test
# modules that import `server` at module top.
os.environ.setdefault("PAPERLESS_URL", "http://paperless.test:8000")
os.environ.setdefault("PAPERLESS_TOKEN", "test-token-deadbeef")
os.environ.setdefault("PAPERLESS_TIMEOUT", "5")

# Add repo root to sys.path so `import server` works from tests/
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def base_url() -> str:
    return os.environ["PAPERLESS_URL"]


@pytest.fixture
def auth_header() -> str:
    return f"Token {os.environ['PAPERLESS_TOKEN']}"
