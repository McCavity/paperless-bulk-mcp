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
# Internal helpers
# ---------------------------------------------------------------------------


def _bulk_edit(
    method: str,
    document_ids: list[int],
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST to /api/documents/bulk_edit/ with the given method + parameters.

    All bulk_* tools delegate to this helper. Empty document_ids returns
    an error rather than calling Paperless (which would 400 anyway).
    """
    if not document_ids:
        return {"ok": False, "error": "document_ids must not be empty"}

    body = {
        "documents": document_ids,
        "method": method,
        "parameters": parameters or {},
    }

    with httpx.Client(timeout=PAPERLESS_TIMEOUT) as client:
        resp = client.post(
            f"{PAPERLESS_URL}/api/documents/bulk_edit/",
            headers=_headers(),
            json=body,
        )

    if resp.status_code >= 400:
        return {
            "ok": False,
            "status": resp.status_code,
            "error": resp.text[:500],
            "method": method,
            "count": len(document_ids),
        }

    # Paperless returns 200 with a result body on success. Some methods
    # (redo_ocr) return only a task acknowledgement; that's still ok.
    try:
        response_body = resp.json() if resp.text else None
    except ValueError:
        response_body = resp.text[:200]

    return {
        "ok": True,
        "status": resp.status_code,
        "method": method,
        "count": len(document_ids),
        "response": response_body,
    }


def _find_by_name(endpoint: str, name: str, limit: int = 5) -> dict[str, Any]:
    """GET /api/<endpoint>/?name__icontains=<name> and return ID matches.

    Always server-side filter, never grep page 1 (KI-OS Lerneintrag
    2026-05-22 — Stadtwerke-Duplikat-Vorfall).
    """
    with httpx.Client(timeout=PAPERLESS_TIMEOUT) as client:
        resp = client.get(
            f"{PAPERLESS_URL}/api/{endpoint}/",
            headers=_headers(),
            params={"name__icontains": name, "page_size": max(limit * 2, 10)},
        )
        resp.raise_for_status()
        body = resp.json()

    matches = [
        {"id": r["id"], "name": r["name"]}
        for r in body.get("results", [])[:limit]
    ]
    return {
        "query": name,
        "total_matches": body.get("count", 0),
        "matches": matches,
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


# --- Resolvers (Name → ID) -------------------------------------------------


@mcp.tool()
def find_tag_by_name(name: str, limit: int = 5) -> dict[str, Any]:
    """Resolve a tag name (case-insensitive substring) to one or more IDs.

    Use this before bulk_add_tag / bulk_remove_tag / bulk_modify_tags —
    those take tag IDs, not names. If multiple tags match, pick the right
    ID yourself or refine the search.
    """
    return _find_by_name("tags", name, limit)


@mcp.tool()
def find_correspondent_by_name(name: str, limit: int = 5) -> dict[str, Any]:
    """Resolve a correspondent name (case-insensitive substring) to IDs.

    Use before bulk_set_correspondent. Also useful as a pre-flight check
    to avoid creating duplicate correspondents (always search before add).
    """
    return _find_by_name("correspondents", name, limit)


@mcp.tool()
def find_document_type_by_name(name: str, limit: int = 5) -> dict[str, Any]:
    """Resolve a document type name (case-insensitive substring) to IDs.

    Use before bulk_set_document_type.
    """
    return _find_by_name("document_types", name, limit)


# --- Tag operations --------------------------------------------------------


@mcp.tool()
def bulk_add_tag(document_ids: list[int], tag_id: int) -> dict[str, Any]:
    """Add a tag to N documents. Idempotent (re-adding has no effect)."""
    return _bulk_edit("add_tag", document_ids, {"tag": tag_id})


@mcp.tool()
def bulk_remove_tag(document_ids: list[int], tag_id: int) -> dict[str, Any]:
    """Remove a tag from N documents. Idempotent (a missing tag is fine)."""
    return _bulk_edit("remove_tag", document_ids, {"tag": tag_id})


@mcp.tool()
def bulk_modify_tags(
    document_ids: list[int],
    add_tags: list[int] | None = None,
    remove_tags: list[int] | None = None,
) -> dict[str, Any]:
    """Add and/or remove multiple tags in a single batch.

    Common case: processing the inbox — pass `remove_tags=[9]` (the
    💡 Eingang tag) plus optional `add_tags=[...]` for whatever the
    document should now carry. At least one of add_tags / remove_tags
    must be non-empty.
    """
    add = add_tags or []
    remove = remove_tags or []
    if not add and not remove:
        return {
            "ok": False,
            "error": "must specify at least one of add_tags or remove_tags",
        }
    return _bulk_edit(
        "modify_tags",
        document_ids,
        {"add_tags": add, "remove_tags": remove},
    )


# --- Set operations (correspondent / document_type / storage_path) ---------


@mcp.tool()
def bulk_set_correspondent(
    document_ids: list[int],
    correspondent_id: int | None,
) -> dict[str, Any]:
    """Assign a correspondent to N documents.

    Pass `correspondent_id=None` to clear the correspondent (sets it to
    unknown). Useful when reclassifying after a tag bereinigung.
    """
    return _bulk_edit(
        "set_correspondent",
        document_ids,
        {"correspondent": correspondent_id},
    )


@mcp.tool()
def bulk_set_document_type(
    document_ids: list[int],
    document_type_id: int | None,
) -> dict[str, Any]:
    """Assign a document type to N documents. Pass None to clear."""
    return _bulk_edit(
        "set_document_type",
        document_ids,
        {"document_type": document_type_id},
    )


@mcp.tool()
def bulk_set_storage_path(
    document_ids: list[int],
    storage_path_id: int | None,
) -> dict[str, Any]:
    """Assign a storage path to N documents. Pass None to clear."""
    return _bulk_edit(
        "set_storage_path",
        document_ids,
        {"storage_path": storage_path_id},
    )


# --- OCR -------------------------------------------------------------------


@mcp.tool()
def bulk_redo_ocr(document_ids: list[int]) -> dict[str, Any]:
    """Re-run OCR for N documents.

    Runs asynchronously on the Paperless side — the response only confirms
    the job was queued, not that OCR is complete. Use sparingly: each
    redo costs CPU on the Paperless host.
    """
    return _bulk_edit("redo_ocr", document_ids, {})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    mcp.run()
