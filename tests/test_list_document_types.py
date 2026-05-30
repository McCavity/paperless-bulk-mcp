"""Tests for list_document_types — full inventory read."""

from __future__ import annotations

import httpx
import respx

import server


@respx.mock
def test_list_document_types_returns_compact_shape(base_url: str) -> None:
    """GET /api/document_types/ returns compact (id, name, document_count) shape."""
    route = respx.get(f"{base_url}/api/document_types/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {
                        "id": 1,
                        "name": "Rechnung",
                        "document_count": 412,
                        "match": "",
                        "matching_algorithm": 1,
                    },
                    {
                        "id": 7,
                        "name": "Korrespondenz",
                        "document_count": 188,
                        "match": "",
                        "matching_algorithm": 1,
                    },
                ],
            },
        )
    )

    result = server.list_document_types(limit=50)

    assert route.called
    sent = route.calls.last.request
    assert sent.url.params.get("page_size") == "50"
    assert sent.url.params.get("ordering") == "name"

    assert result == {
        "count": 2,
        "returned": 2,
        "results": [
            {"id": 1, "name": "Rechnung", "document_count": 412},
            {"id": 7, "name": "Korrespondenz", "document_count": 188},
        ],
    }


@respx.mock
def test_list_document_types_empty(base_url: str) -> None:
    """Empty result handled without crash."""
    respx.get(f"{base_url}/api/document_types/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = server.list_document_types()

    assert result == {"count": 0, "returned": 0, "results": []}


@respx.mock
def test_list_document_types_error(base_url: str) -> None:
    """4xx surfaces as ok=False with status + error."""
    respx.get(f"{base_url}/api/document_types/").mock(
        return_value=httpx.Response(403, text="Forbidden")
    )

    result = server.list_document_types()

    assert result["ok"] is False
    assert result["status"] == 403


@respx.mock
def test_list_document_types_limit_clamped(base_url: str) -> None:
    """Limits above 200 clamp to 200."""
    respx.get(f"{base_url}/api/document_types/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_document_types(limit=9999)

    assert respx.calls.last.request.url.params.get("page_size") == "200"
