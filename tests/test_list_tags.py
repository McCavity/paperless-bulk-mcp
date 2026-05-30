"""Tests for list_tags — full inventory read."""

from __future__ import annotations

import httpx
import respx

import server


@respx.mock
def test_list_tags_returns_compact_shape(base_url: str) -> None:
    """GET /api/tags/ returns compact (id, name, document_count, color) shape.

    Color is included because it's a visual tag-affordance — operators often
    use color when they ask "which yellow tag was the rechnungs-tag?".
    """
    route = respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "results": [
                    {
                        "id": 9,
                        "name": "💡 Eingang",
                        "document_count": 22,
                        "color": "#fbbd08",
                        "match": "",
                        "matching_algorithm": 1,
                    },
                    {
                        "id": 5,
                        "name": "Familie",
                        "document_count": 87,
                        "color": "#2185d0",
                        "match": "",
                        "matching_algorithm": 1,
                    },
                    {
                        "id": 11,
                        "name": "Sozialversicherung",
                        "document_count": 14,
                        "color": "#21ba45",
                        "match": "",
                        "matching_algorithm": 1,
                    },
                ],
            },
        )
    )

    result = server.list_tags(limit=50)

    assert route.called
    sent = route.calls.last.request
    assert sent.url.params.get("page_size") == "50"
    assert sent.url.params.get("ordering") == "name"

    assert result == {
        "count": 3,
        "returned": 3,
        "results": [
            {"id": 9, "name": "💡 Eingang", "document_count": 22, "color": "#fbbd08"},
            {"id": 5, "name": "Familie", "document_count": 87, "color": "#2185d0"},
            {"id": 11, "name": "Sozialversicherung", "document_count": 14, "color": "#21ba45"},
        ],
    }


@respx.mock
def test_list_tags_empty(base_url: str) -> None:
    """Empty result handled without crash."""
    respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = server.list_tags()

    assert result == {"count": 0, "returned": 0, "results": []}


@respx.mock
def test_list_tags_error(base_url: str) -> None:
    """4xx surfaces as ok=False with status + error."""
    respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(401, text="Authentication credentials were not provided.")
    )

    result = server.list_tags()

    assert result["ok"] is False
    assert result["status"] == 401


@respx.mock
def test_list_tags_limit_clamped(base_url: str) -> None:
    """Limits above 200 clamp to 200."""
    respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_tags(limit=9999)

    assert respx.calls.last.request.url.params.get("page_size") == "200"


@respx.mock
def test_list_tags_missing_color(base_url: str) -> None:
    """Tag without a color (legacy data) survives — color falls back to None."""
    respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [{"id": 1, "name": "OldTag", "document_count": 3}],
            },
        )
    )

    result = server.list_tags()

    assert result["results"] == [
        {"id": 1, "name": "OldTag", "document_count": 3, "color": None}
    ]
