"""Tests for the list_inbox convenience wrapper."""

from __future__ import annotations

import os

import httpx
import pytest
import respx

import server


@pytest.fixture(autouse=True)
def _reset_inbox_cache():
    """Each test starts with a clean inbox-tag-id cache."""
    server._reset_inbox_tag_cache()
    yield
    server._reset_inbox_tag_cache()


@respx.mock
def test_list_inbox_uses_env_tag_id(base_url: str, monkeypatch) -> None:
    """If PAPERLESS_INBOX_TAG_ID is set, list_inbox uses it without a
    name-resolution roundtrip."""
    monkeypatch.setenv("PAPERLESS_INBOX_TAG_ID", "9")

    route = respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "id": 555,
                        "title": "Posteingang heute",
                        "added": "2026-05-27T07:00:00Z",
                        "correspondent": None,
                        "document_type": None,
                        "tags": [9],
                    }
                ],
            },
        )
    )

    result = server.list_inbox(limit=10)

    assert route.called
    assert route.calls.last.request.url.params.get("tags__id") == "9"
    assert result["count"] == 1
    assert result["results"][0]["id"] == 555


@respx.mock
def test_list_inbox_falls_back_to_name_resolution(base_url: str, monkeypatch) -> None:
    """Without PAPERLESS_INBOX_TAG_ID, list_inbox resolves the inbox tag
    by name via /api/tags/?name__icontains=eingang."""
    monkeypatch.delenv("PAPERLESS_INBOX_TAG_ID", raising=False)

    respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [{"id": 9, "name": "\U0001f4a1 Eingang"}],
            },
        )
    )
    docs_route = respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_inbox()

    assert docs_route.called
    assert docs_route.calls.last.request.url.params.get("tags__id") == "9"


@respx.mock
def test_list_inbox_caches_resolved_tag_id(base_url: str, monkeypatch) -> None:
    """The name-resolution roundtrip happens at most once per process —
    subsequent list_inbox calls reuse the cached tag ID."""
    monkeypatch.delenv("PAPERLESS_INBOX_TAG_ID", raising=False)

    tags_route = respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(
            200,
            json={"count": 1, "results": [{"id": 9, "name": "Eingang"}]},
        )
    )
    respx.get(f"{base_url}/api/documents/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    server.list_inbox()
    server.list_inbox()
    server.list_inbox()

    assert tags_route.call_count == 1


@respx.mock
def test_list_inbox_errors_when_inbox_tag_ambiguous(base_url: str, monkeypatch) -> None:
    """If multiple tags match 'eingang' (e.g. a stale "Eingang-archiv"
    sibling), abort with a clear error rather than guessing."""
    monkeypatch.delenv("PAPERLESS_INBOX_TAG_ID", raising=False)

    respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"id": 9, "name": "\U0001f4a1 Eingang"},
                    {"id": 88, "name": "Eingang-archiv"},
                ],
            },
        )
    )

    result = server.list_inbox()

    assert result["ok"] is False
    assert "ambiguous" in result["error"].lower()
    assert "PAPERLESS_INBOX_TAG_ID" in result["error"]


@respx.mock
def test_list_inbox_errors_when_inbox_tag_missing(base_url: str, monkeypatch) -> None:
    """If no tag matches 'eingang' at all, surface a clear actionable
    error (don't silently call /api/documents/ without a tag filter)."""
    monkeypatch.delenv("PAPERLESS_INBOX_TAG_ID", raising=False)

    respx.get(f"{base_url}/api/tags/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    result = server.list_inbox()

    assert result["ok"] is False
    assert "no inbox tag" in result["error"].lower()
    assert "PAPERLESS_INBOX_TAG_ID" in result["error"]
