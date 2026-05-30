"""Tests for list_correspondents — full inventory read."""

from __future__ import annotations

import httpx
import respx

import server


@respx.mock
def test_list_correspondents_returns_compact_shape(base_url: str) -> None:
    """GET /api/correspondents/ returns compact (id, name, document_count) shape."""
    route = respx.get(f"{base_url}/api/correspondents/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "results": [
                    {
                        "id": 71,
                        "name": "Stadtwerke Bad Vilbel",
                        "document_count": 8,
                        "last_correspondence": "2026-05-29",
                        "match": "",
                        "matching_algorithm": 1,
                    },
                    {
                        "id": 28,
                        "name": "Techniker Krankenkasse",
                        "document_count": 12,
                        "last_correspondence": "2026-05-29",
                        "match": "",
                        "matching_algorithm": 1,
                    },
                    {
                        "id": 5,
                        "name": "Allianz",
                        "document_count": 22,
                        "last_correspondence": "2026-05-14",
                        "match": "",
                        "matching_algorithm": 1,
                    },
                ],
            },
        )
    )

    result = server.list_correspondents(limit=50)

    assert route.called
    sent = route.calls.last.request
    assert sent.url.params.get("page_size") == "50"
    assert sent.url.params.get("ordering") == "name"

    assert result == {
        "count": 3,
        "returned": 3,
        "results": [
            {"id": 71, "name": "Stadtwerke Bad Vilbel", "document_count": 8},
            {"id": 28, "name": "Techniker Krankenkasse", "document_count": 12},
            {"id": 5, "name": "Allianz", "document_count": 22},
        ],
    }


@respx.mock
def test_list_correspondents_empty(base_url: str) -> None:
    """Empty result handled without crash."""
    respx.get(f"{base_url}/api/correspondents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = server.list_correspondents()

    assert result == {"count": 0, "returned": 0, "results": []}


@respx.mock
def test_list_correspondents_error(base_url: str) -> None:
    """4xx surfaces as ok=False with status + error."""
    respx.get(f"{base_url}/api/correspondents/").mock(
        return_value=httpx.Response(401, text="Authentication credentials were not provided.")
    )

    result = server.list_correspondents()

    assert result["ok"] is False
    assert result["status"] == 401
    assert "Authentication" in result["error"]


@respx.mock
def test_list_correspondents_limit_clamped(base_url: str) -> None:
    """Limits above 200 clamp to 200 — correspondents are smaller payloads than docs."""
    respx.get(f"{base_url}/api/correspondents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_correspondents(limit=9999)

    assert respx.calls.last.request.url.params.get("page_size") == "200"


@respx.mock
def test_list_correspondents_custom_ordering(base_url: str) -> None:
    """ordering parameter flows through (e.g. -document_count for top-N)."""
    respx.get(f"{base_url}/api/correspondents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_correspondents(ordering="-document_count")

    assert respx.calls.last.request.url.params.get("ordering") == "-document_count"
