"""Tests for delete_correspondent — destructive cleanup tool."""

from __future__ import annotations

import httpx
import respx

import server


@respx.mock
def test_delete_correspondent_success(base_url: str) -> None:
    """DELETE /api/correspondents/{id}/ returns 204 — translate to ok=True."""
    route = respx.delete(f"{base_url}/api/correspondents/201/").mock(
        return_value=httpx.Response(204)
    )

    result = server.delete_correspondent(201)

    assert route.called
    assert result == {"ok": True, "status": 204, "id": 201}


@respx.mock
def test_delete_correspondent_not_found(base_url: str) -> None:
    """404 returns ok=False with status + error — no crash."""
    respx.delete(f"{base_url}/api/correspondents/9999/").mock(
        return_value=httpx.Response(404, text='{"detail":"Not found."}')
    )

    result = server.delete_correspondent(9999)

    assert result["ok"] is False
    assert result["status"] == 404
    assert "Not found" in result["error"]


@respx.mock
def test_delete_correspondent_in_use_returns_error(base_url: str) -> None:
    """Paperless returns 409 / 400 if correspondent still referenced — surface it."""
    respx.delete(f"{base_url}/api/correspondents/5/").mock(
        return_value=httpx.Response(400, text='{"detail":"Cannot delete: documents reference this correspondent."}')
    )

    result = server.delete_correspondent(5)

    assert result["ok"] is False
    assert result["status"] == 400
