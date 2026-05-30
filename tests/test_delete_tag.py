"""Tests for delete_tag — destructive cleanup tool."""

from __future__ import annotations

import httpx
import respx

import server


@respx.mock
def test_delete_tag_success(base_url: str) -> None:
    """DELETE /api/tags/{id}/ returns 204 — translate to ok=True."""
    route = respx.delete(f"{base_url}/api/tags/42/").mock(
        return_value=httpx.Response(204)
    )

    result = server.delete_tag(42)

    assert route.called
    assert result == {"ok": True, "status": 204, "id": 42}


@respx.mock
def test_delete_tag_not_found(base_url: str) -> None:
    """404 returns ok=False with status + error."""
    respx.delete(f"{base_url}/api/tags/9999/").mock(
        return_value=httpx.Response(404, text='{"detail":"Not found."}')
    )

    result = server.delete_tag(9999)

    assert result["ok"] is False
    assert result["status"] == 404
