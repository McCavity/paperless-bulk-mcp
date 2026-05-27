"""Tests for the read-side list_documents tool."""

from __future__ import annotations

import httpx
import respx

import server


@respx.mock
def test_list_documents_with_tag_filter(base_url: str) -> None:
    """Filtering by tag_id hits Paperless with ?tags__id=<id> and returns
    a compact shape (count + returned + results with id/title/added/tags)."""
    route = respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {
                        "id": 101,
                        "title": "Stadtwerke Abrechnung 2025",
                        "added": "2026-05-26T08:30:00Z",
                        "correspondent": 5,
                        "document_type": 3,
                        "tags": [9, 42],
                    },
                    {
                        "id": 102,
                        "title": "Stromrechnung 03/2026",
                        "added": "2026-05-25T19:12:00Z",
                        "correspondent": 5,
                        "document_type": 3,
                        "tags": [9],
                    },
                ],
            },
        )
    )

    result = server.list_documents(tag_id=9, limit=20)

    assert route.called
    # Server-side filter must use Paperless' tags__id parameter.
    sent = route.calls.last.request
    assert sent.url.params.get("tags__id") == "9"
    assert sent.url.params.get("page_size") == "20"
    assert sent.url.params.get("ordering") == "-added"

    assert result == {
        "count": 2,
        "returned": 2,
        "results": [
            {
                "id": 101,
                "title": "Stadtwerke Abrechnung 2025",
                "added": "2026-05-26",
                "correspondent": 5,
                "document_type": 3,
                "tags": [9, 42],
            },
            {
                "id": 102,
                "title": "Stromrechnung 03/2026",
                "added": "2026-05-25",
                "correspondent": 5,
                "document_type": 3,
                "tags": [9],
            },
        ],
    }


@respx.mock
def test_list_documents_empty_result(base_url: str) -> None:
    """Empty result returns count=0, returned=0, results=[] — no crash."""
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = server.list_documents(tag_id=99)

    assert result == {"count": 0, "returned": 0, "results": []}


@respx.mock
def test_list_documents_paperless_error(base_url: str) -> None:
    """A 4xx from Paperless is surfaced as ok=False with status + error,
    matching the bulk_edit error shape."""
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(401, text="Authentication credentials were not provided.")
    )

    result = server.list_documents(tag_id=9)

    assert result["ok"] is False
    assert result["status"] == 401
    assert "Authentication" in result["error"]


@respx.mock
def test_list_documents_combined_filters(base_url: str) -> None:
    """tag_id + correspondent_id + document_type_id all flow through as
    Paperless filter params."""
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_documents(
        tag_id=9, correspondent_id=5, document_type_id=3, limit=50
    )

    sent = respx.calls.last.request
    assert sent.url.params.get("tags__id") == "9"
    assert sent.url.params.get("correspondent__id") == "5"
    assert sent.url.params.get("document_type__id") == "3"
    assert sent.url.params.get("page_size") == "50"


@respx.mock
def test_list_documents_limit_clamped_to_max(base_url: str) -> None:
    """Limits above 100 are clamped down — keeps the LLM-context shape
    reasonable and avoids accidental DB-wide pulls."""
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_documents(tag_id=9, limit=9999)

    assert respx.calls.last.request.url.params.get("page_size") == "100"


@respx.mock
def test_list_documents_no_filters_works(base_url: str) -> None:
    """Calling with no filters at all is allowed — returns most-recent
    documents up to limit."""
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_documents(limit=5)

    sent = respx.calls.last.request
    assert "tags__id" not in sent.url.params
    assert "correspondent__id" not in sent.url.params
    assert sent.url.params.get("page_size") == "5"
