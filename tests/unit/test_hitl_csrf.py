"""Tests for HITL server CSRF protection, context redaction, and CSP nonce."""

import json

import pytest

from agent_actions.llm.providers.hitl.server import HitlServer, _sanitize_context


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


# ── CSRF Token ──────────────────────────────────────────────────────────


class TestCSRFToken:
    def test_post_without_token_returns_403(self, client):
        resp = client.post(
            "/api/approve",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert b"session token" in resp.data.lower()

    def test_post_with_wrong_token_returns_403(self, client):
        resp = client.post(
            "/api/approve",
            data=json.dumps({}),
            content_type="application/json",
            headers={"X-HITL-Token": "wrong-token-value"},
        )
        assert resp.status_code == 403

    def test_post_with_correct_token_succeeds(self, client, server):
        resp = client.post(
            "/api/approve",
            data=json.dumps({}),
            content_type="application/json",
            headers={"X-HITL-Token": server._session_token},
        )
        assert resp.status_code == 200

    def test_post_form_encoded_returns_400(self, client, server):
        resp = client.post(
            "/api/approve",
            data="comment=hello",
            content_type="application/x-www-form-urlencoded",
            headers={"X-HITL-Token": server._session_token},
        )
        assert resp.status_code == 400
        assert b"application/json" in resp.data.lower()

    def test_post_without_origin_header_succeeds(self, client, server):
        """Missing Origin/Referer is allowed — token + JSON content-type suffice."""
        resp = client.post(
            "/api/approve",
            data=json.dumps({}),
            content_type="application/json",
            headers={"X-HITL-Token": server._session_token},
        )
        assert resp.status_code == 200

    def test_get_endpoints_do_not_require_token(self, client):
        resp = client.get("/api/review-state")
        assert resp.status_code == 200


# ── Context Redaction (SEC-05) ──────────────────────────────────────────


class TestContextRedaction:
    def test_sanitize_context_redacts_sensitive_keys(self):
        data = {
            "name": "test",
            "db_password": "s3cret",
            "api_key": "ak-123",
            "auth_token": "tok",
            "normal": "visible",
        }
        result = _sanitize_context(data)
        assert result["name"] == "test"
        assert result["normal"] == "visible"
        assert result["db_password"] == "***"
        assert result["api_key"] == "***"
        assert result["auth_token"] == "***"

    def test_sanitize_context_redacts_suffix_variants(self):
        data = {"db_secret": "x", "access_token": "y", "user_credential": "z"}
        result = _sanitize_context(data)
        assert result["db_secret"] == "***"
        assert result["access_token"] == "***"
        assert result["user_credential"] == "***"

    def test_sanitize_context_does_not_redact_benign_keys(self):
        data = {
            "primary_key": "pk-1",
            "keyboard": "qwerty",
            "monkey": "george",
            "token_count": 42,
            "secret_santa": "bob",
            "token_type": "bearer",
        }
        result = _sanitize_context(data)
        assert result["primary_key"] == "pk-1"
        assert result["keyboard"] == "qwerty"
        assert result["monkey"] == "george"
        assert result["token_count"] == 42
        assert result["secret_santa"] == "bob"
        assert result["token_type"] == "bearer"

    def test_sanitize_context_handles_nested_dicts(self):
        data = {"config": {"db_secret": "hidden", "name": "ok"}}
        result = _sanitize_context(data)
        assert result["config"]["db_secret"] == "***"
        assert result["config"]["name"] == "ok"

    def test_sanitize_context_handles_lists(self):
        data = [{"password": "pw", "x": 1}, {"y": 2}]
        result = _sanitize_context(data)
        assert result[0]["password"] == "***"
        assert result[0]["x"] == 1
        assert result[1]["y"] == 2

    def test_sanitize_context_passes_through_scalars(self):
        assert _sanitize_context("hello") == "hello"
        assert _sanitize_context(42) == 42
        assert _sanitize_context(None) is None

    def test_context_endpoint_redacts_sensitive_data(self, client, server):
        resp = client.get("/api/context")
        assert resp.status_code == 200
        body = resp.get_json()
        data = body["data"]
        assert data["name"] == "test"
        assert data["db_password"] == "***"


# ── CSP Nonce (SEC-06) ─────────────────────────────────────────────────


class TestCSPNonce:
    def test_index_page_has_csp_nonce_header(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "nonce-" in csp
        assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]

    def test_index_page_contains_nonce_attribute(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert 'nonce="' in html

    def test_index_page_contains_hitl_token(self, client, server):
        resp = client.get("/")
        html = resp.data.decode()
        assert server._session_token in html
