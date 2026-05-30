"""Tests for merge_correspondents — composite cleanup tool.

The merge sequence is:
  1. Fetch all documents tagged with source correspondent
  2. Reassign them to target via bulk_set_correspondent
  3. Delete the empty source correspondent

Each leg has its own failure mode; the tool must surface partial failures so
the caller knows what landed and what didn't.
"""

from __future__ import annotations

import httpx
import respx

import server


@respx.mock
def test_merge_correspondents_happy_path(base_url: str) -> None:
    """Source has 2 documents → reassign to target → delete source."""
    docs_route = respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"id": 101, "title": "X", "added": "2026-05-01T00:00:00Z",
                     "correspondent": 201, "document_type": 1, "tags": []},
                    {"id": 102, "title": "Y", "added": "2026-05-02T00:00:00Z",
                     "correspondent": 201, "document_type": 1, "tags": []},
                ],
            },
        )
    )
    bulk_route = respx.post(f"{base_url}/api/documents/bulk_edit/").mock(
        return_value=httpx.Response(200, json={"result": "OK"})
    )
    delete_route = respx.delete(f"{base_url}/api/correspondents/201/").mock(
        return_value=httpx.Response(204)
    )

    result = server.merge_correspondents(source_id=201, target_id=71)

    assert docs_route.called
    # filter must use source correspondent
    assert docs_route.calls.last.request.url.params.get("correspondent__id") == "201"

    assert bulk_route.called
    bulk_body = bulk_route.calls.last.request.read().decode()
    assert "101" in bulk_body and "102" in bulk_body
    assert '"correspondent":71' in bulk_body.replace(" ", "")
    assert "set_correspondent" in bulk_body

    assert delete_route.called

    assert result == {
        "ok": True,
        "source_id": 201,
        "target_id": 71,
        "documents_moved": 2,
        "source_deleted": True,
    }


@respx.mock
def test_merge_correspondents_source_empty(base_url: str) -> None:
    """Source has zero documents → skip bulk_edit, still delete source."""
    docs_route = respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    # No bulk_edit call should happen
    bulk_route = respx.post(f"{base_url}/api/documents/bulk_edit/").mock(
        return_value=httpx.Response(200, json={"result": "OK"})
    )
    delete_route = respx.delete(f"{base_url}/api/correspondents/201/").mock(
        return_value=httpx.Response(204)
    )

    result = server.merge_correspondents(source_id=201, target_id=71)

    assert docs_route.called
    assert not bulk_route.called, "should skip bulk_edit when source is empty"
    assert delete_route.called

    assert result == {
        "ok": True,
        "source_id": 201,
        "target_id": 71,
        "documents_moved": 0,
        "source_deleted": True,
    }


@respx.mock
def test_merge_correspondents_same_id_rejected(base_url: str) -> None:
    """source_id == target_id is an obvious error — reject before any HTTP."""
    docs_route = respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = server.merge_correspondents(source_id=42, target_id=42)

    assert not docs_route.called
    assert result["ok"] is False
    assert "same" in result["error"].lower() or "identical" in result["error"].lower()


@respx.mock
def test_merge_correspondents_bulk_edit_fails(base_url: str) -> None:
    """If bulk_set_correspondent fails (e.g. target_id doesn't exist) the
    source must NOT be deleted — partial failure is surfaced."""
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"id": 101, "title": "X", "added": "2026-05-01T00:00:00Z",
                     "correspondent": 201, "document_type": 1, "tags": []},
                ],
            },
        )
    )
    respx.post(f"{base_url}/api/documents/bulk_edit/").mock(
        return_value=httpx.Response(400, text='{"detail":"correspondent does not exist"}')
    )
    delete_route = respx.delete(f"{base_url}/api/correspondents/201/").mock(
        return_value=httpx.Response(204)
    )

    result = server.merge_correspondents(source_id=201, target_id=9999)

    assert not delete_route.called, "delete must be skipped if bulk_edit failed"
    assert result["ok"] is False
    assert result["documents_moved"] == 0
    assert result["source_deleted"] is False
    assert "bulk_edit" in result["error"] or result["status"] == 400


@respx.mock
def test_merge_correspondents_delete_fails(base_url: str) -> None:
    """Bulk-edit succeeds but delete fails → ok=False, but reflect partial success."""
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"id": 101, "title": "X", "added": "2026-05-01T00:00:00Z",
                     "correspondent": 201, "document_type": 1, "tags": []},
                ],
            },
        )
    )
    respx.post(f"{base_url}/api/documents/bulk_edit/").mock(
        return_value=httpx.Response(200, json={"result": "OK"})
    )
    respx.delete(f"{base_url}/api/correspondents/201/").mock(
        return_value=httpx.Response(403, text="Forbidden")
    )

    result = server.merge_correspondents(source_id=201, target_id=71)

    assert result["ok"] is False
    assert result["documents_moved"] == 1  # this succeeded
    assert result["source_deleted"] is False
