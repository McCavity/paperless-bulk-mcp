"""paperless-bulk-mcp — Bulk write operations for Paperless-ngx via MCP.

Companion to PaperCortex (read-only search MCP). Where PaperCortex finds
documents, this server changes them — using Paperless' native
`bulk_edit` endpoint for batch tag / correspondent / type updates.

Why `bulk_edit` and not PUT/PATCH?
  - PUT requires the full document body; for OCR'd docs with control
    characters the body parse can fail (see KI-OS Lerneintrag 2026-05-14).
  - `bulk_edit` takes only IDs + the operation — no document body needed.
  - Atomic per-batch, fewer round-trips.

Transport: stdio. Registered as user-scope MCP in ~/.claude.json.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Load .env from the directory the server file lives in (not CWD), so it
# works regardless of how the MCP host launches us.
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))

PAPERLESS_URL = os.environ.get("PAPERLESS_URL", "").rstrip("/")
PAPERLESS_TOKEN = os.environ.get("PAPERLESS_TOKEN", "")
PAPERLESS_TIMEOUT = float(os.environ.get("PAPERLESS_TIMEOUT", "60"))

if not PAPERLESS_URL or not PAPERLESS_TOKEN:
    # Fail fast on stderr — the MCP host shows this in logs.
    print(
        "paperless-bulk-mcp: PAPERLESS_URL and PAPERLESS_TOKEN must be set "
        "(via .env next to server.py, or the host's env block).",
        file=sys.stderr,
    )
    sys.exit(1)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Token {PAPERLESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("paperless-bulk")


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Smoke test: confirm we can reach Paperless and the token is valid.

    Returns the API root payload (lists of available endpoints) plus a
    `reachable: True` marker. Use this first when something feels broken.
    """
    with httpx.Client(timeout=PAPERLESS_TIMEOUT) as client:
        resp = client.get(f"{PAPERLESS_URL}/api/", headers=_headers())
        resp.raise_for_status()
        body = resp.json()

    return {
        "reachable": True,
        "url": PAPERLESS_URL,
        "endpoints": sorted(body.keys()) if isinstance(body, dict) else [],
    }


# ---------------------------------------------------------------------------
# Future tools (will be added as we hash out the tool list with the user)
# ---------------------------------------------------------------------------
# - bulk_add_tag(document_ids, tag_id)
# - bulk_remove_tag(document_ids, tag_id)
# - bulk_set_correspondent(document_ids, correspondent_id)
# - bulk_set_document_type(document_ids, document_type_id)
# - bulk_set_storage_path(document_ids, storage_path_id)
# - bulk_delete(document_ids)
# - bulk_redo_ocr(document_ids)
# Plus a few find_*_by_name helpers to avoid clients having to know IDs.


if __name__ == "__main__":
    mcp.run()
