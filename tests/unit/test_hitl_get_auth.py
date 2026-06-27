"""HITL GET endpoints must require `X-HITL-Token` to match the POSTs.

`GET /` additionally accepts a one-shot `?bootstrap=<token>` query that
the launcher hands the user; the browser's JS strips it from the address
bar before any further request runs.
"""

from __future__ import annotations

import pytest

from agent_actions.llm.providers.hitl.server import HitlServer


@pytest.fixture()
def server():
    return HitlServer(
        port=0,
        instructions="Test instructions",
        context_data={"name": "test", "db_password": "s3cret"},
        timeout=5,
    )


@pytest.fixture()
def client(server):
    server.app.config["TESTING"] = True
    return server.app.test_client()


# ── GET / ──────────────────────────────────────────────────────────────


def test_get_root_without_token_returns_401(client):
    """`GET /` returns 401 when neither X-HITL-Token nor ?bootstrap is supplied."""
    resp = client.get("/")
    assert resp.status_code == 401


def test_get_root_with_wrong_bootstrap_returns_401(client):
    resp = client.get("/?bootstrap=not-the-real-token")
    assert resp.status_code == 401


def test_get_root_with_bootstrap_query_returns_html(client, server):
    """First page load comes in with ?bootstrap=<token>; the response must
    be 200 + HTML."""
    resp = client.get(f"/?bootstrap={server._session_token}")
    assert resp.status_code == 200
    assert b"<html" in resp.data.lower()


def test_get_root_with_bootstrap_does_not_embed_token_in_body(client, server):
    """The token MUST NOT appear anywhere in the rendered HTML body.

    The browser reads the token from the URL bootstrap parameter and strips it
    via history.replaceState; server-rendered HTML must not re-leak it.
    """
    resp = client.get(f"/?bootstrap={server._session_token}")
    assert resp.status_code == 200
    assert server._session_token.encode() not in resp.data


def test_get_root_with_header_returns_html(client, server):
    """Reload-through-header path: a logged-in client sending X-HITL-Token
    via an XHR (e.g. AJAX-driven SPA reload) is honoured."""
    resp = client.get("/", headers={"X-HITL-Token": server._session_token})
    assert resp.status_code == 200


# ── GET /api/context ──────────────────────────────────────────────────


def test_get_api_context_without_token_returns_401(client):
    resp = client.get("/api/context")
    assert resp.status_code == 401


def test_get_api_context_with_bootstrap_query_returns_401(client, server):
    """`?bootstrap=` is only valid on `GET /`. The API endpoints must
    require the header so no leak path via referrer or browser history."""
    resp = client.get(f"/api/context?bootstrap={server._session_token}")
    assert resp.status_code == 401


def test_get_api_context_with_header_returns_200(client, server):
    resp = client.get("/api/context", headers={"X-HITL-Token": server._session_token})
    assert resp.status_code == 200


# ── GET /api/review-state ────────────────────────────────────────────


def test_get_api_review_state_without_token_returns_401(client):
    resp = client.get("/api/review-state")
    assert resp.status_code == 401


def test_get_api_review_state_with_header_returns_200(client, server):
    resp = client.get("/api/review-state", headers={"X-HITL-Token": server._session_token})
    assert resp.status_code == 200
