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


# Hard upper bound on list_documents result size. Keeps LLM context windows
# sane and prevents accidental DB-wide pulls. If users hit this regularly,
# open an issue for proper pagination.
_LIST_DOCUMENTS_MAX_LIMIT = 100


def _list_documents(
    tag_id: int | None = None,
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
    limit: int = 20,
    ordering: str = "-added",
) -> dict[str, Any]:
    """GET /api/documents/ with server-side filters, return a compact shape.

    Never grep page 1 — every filter goes as a Paperless query param. Result
    is trimmed to id/title/added/correspondent/document_type/tags so it fits
    in an LLM context window; the caller can follow up via PaperCortex or
    direct API for full document bodies.
    """
    capped_limit = max(1, min(limit, _LIST_DOCUMENTS_MAX_LIMIT))

    params: dict[str, str | int] = {
        "page_size": capped_limit,
        "ordering": ordering,
    }
    if tag_id is not None:
        params["tags__id"] = tag_id
    if correspondent_id is not None:
        params["correspondent__id"] = correspondent_id
    if document_type_id is not None:
        params["document_type__id"] = document_type_id

    with httpx.Client(timeout=PAPERLESS_TIMEOUT) as client:
        resp = client.get(
            f"{PAPERLESS_URL}/api/documents/",
            headers=_headers(),
            params=params,
        )

    if resp.status_code >= 400:
        return {
            "ok": False,
            "status": resp.status_code,
            "error": resp.text[:500],
        }

    body = resp.json()
    results = [
        {
            "id": d["id"],
            "title": d.get("title", ""),
            # Trim the ISO timestamp to date — sub-second precision is noise
            # for the inbox-status use case.
            "added": (d.get("added") or "")[:10],
            "correspondent": d.get("correspondent"),
            "document_type": d.get("document_type"),
            "tags": d.get("tags", []),
        }
        for d in body.get("results", [])
    ]
    return {
        "count": body.get("count", 0),
        "returned": len(results),
        "results": results,
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


# --- Reads (filter + list, NOT full-text search) ---------------------------


# Module-level cache of the inbox tag ID once resolved via API. None means
# "not yet resolved" — env var lookup happens first regardless.
_INBOX_TAG_ID_CACHE: int | None = None


def _reset_inbox_tag_cache() -> None:
    """Clear the module-level inbox-tag-id cache. Test hook."""
    global _INBOX_TAG_ID_CACHE
    _INBOX_TAG_ID_CACHE = None


def _resolve_inbox_tag_id() -> dict[str, Any]:
    """Return {"ok": True, "tag_id": int} or {"ok": False, "error": str}.

    Resolution order:
      1. PAPERLESS_INBOX_TAG_ID env var (cheap, no roundtrip)
      2. Cached value from a previous resolution this process
      3. /api/tags/?name__icontains=eingang — must match exactly one tag.
         Ambiguous or missing → error pointing the user at the env var.
    """
    global _INBOX_TAG_ID_CACHE

    env_value = os.environ.get("PAPERLESS_INBOX_TAG_ID", "").strip()
    if env_value:
        try:
            return {"ok": True, "tag_id": int(env_value)}
        except ValueError:
            return {
                "ok": False,
                "error": (
                    f"PAPERLESS_INBOX_TAG_ID is set but not an integer: "
                    f"{env_value!r}"
                ),
            }

    if _INBOX_TAG_ID_CACHE is not None:
        return {"ok": True, "tag_id": _INBOX_TAG_ID_CACHE}

    with httpx.Client(timeout=PAPERLESS_TIMEOUT) as client:
        resp = client.get(
            f"{PAPERLESS_URL}/api/tags/",
            headers=_headers(),
            params={"name__icontains": "eingang", "page_size": 10},
        )

    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": (
                f"Tag lookup failed ({resp.status_code}): {resp.text[:200]}. "
                f"Set PAPERLESS_INBOX_TAG_ID to skip the name lookup."
            ),
        }

    matches = resp.json().get("results", [])
    if len(matches) == 0:
        return {
            "ok": False,
            "error": (
                "No inbox tag found (searched for 'eingang' case-insensitively). "
                "Set PAPERLESS_INBOX_TAG_ID in .env to the correct tag ID."
            ),
        }
    if len(matches) > 1:
        names = ", ".join(f"{m['name']!r} (id={m['id']})" for m in matches)
        return {
            "ok": False,
            "error": (
                f"Inbox tag is ambiguous — {len(matches)} candidates: {names}. "
                f"Set PAPERLESS_INBOX_TAG_ID in .env to pick the right one."
            ),
        }

    tag_id = int(matches[0]["id"])
    _INBOX_TAG_ID_CACHE = tag_id
    return {"ok": True, "tag_id": tag_id}


@mcp.tool()
def list_inbox(limit: int = 20) -> dict[str, Any]:
    """List documents currently in the inbox (tagged with the Eingang tag).

    Returns the same compact shape as list_documents. Use this at session
    start to see whether there are unprocessed documents that need tags /
    correspondent / type set.

    The inbox tag ID is resolved in this order:
      1. PAPERLESS_INBOX_TAG_ID env (preferred — no roundtrip).
      2. One-time lookup via /api/tags/?name__icontains=eingang. Cached
         for the rest of the process.

    If the name lookup is ambiguous (multiple "Eingang*" tags) or finds no
    match, the tool returns an error with the candidate list — set the env
    var explicitly in that case.
    """
    resolved = _resolve_inbox_tag_id()
    if not resolved.get("ok"):
        return resolved
    return _list_documents(tag_id=resolved["tag_id"], limit=limit)


@mcp.tool()
def list_documents(
    tag_id: int | None = None,
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
    limit: int = 20,
    ordering: str = "-added",
) -> dict[str, Any]:
    """List documents matching one or more server-side filters.

    Returns a compact shape suitable for an LLM context window:

        {
          "count": <total matching>,
          "returned": <items in this batch>,
          "results": [{"id", "title", "added", "correspondent", "document_type", "tags"}, ...]
        }

    Use this for inventory questions ("what's in the inbox?",
    "everything from Stadtwerke this year?"). For full-text search of
    document *content*, use PaperCortex (the read-side companion MCP).

    Parameters
    ----------
    tag_id, correspondent_id, document_type_id
        Optional filters by ID — combine freely. Pass `None` to skip.
    limit
        Max documents to return. Clamped to 100 (LLM-context safety).
    ordering
        Paperless ordering string. Default `-added` = newest first.
        Other useful values: `-created`, `title`, `-modified`.
    """
    return _list_documents(
        tag_id=tag_id,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        limit=limit,
        ordering=ordering,
    )


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
