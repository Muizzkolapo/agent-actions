"""Tests for HITL approval server API behavior."""

import threading

from agent_actions.llm.providers.hitl.server import HitlServer


def _post(client, url, server, **kwargs):
    """POST helper that automatically injects the HITL session token."""
    headers = kwargs.pop("headers", {})
    headers["X-HITL-Token"] = server._session_token
    return client.post(url, headers=headers, **kwargs)


def test_reject_requires_comment_when_enabled():
    """Reject endpoint should enforce comment when requirement is enabled."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data={"value": 1},
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = _post(client, "/api/reject", server, json={"comment": ""})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert "required" in payload["error"].lower()
    assert server.response is None
    assert not server.response_event.is_set()


def test_reject_allows_empty_comment_when_disabled():
    """Reject endpoint should allow empty comment when requirement is disabled."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data={"value": 1},
        timeout=30,
        require_comment_on_reject=False,
    )
    client = server.app.test_client()

    response = _post(client, "/api/reject", server, json={"comment": ""})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert server.response is not None
    assert server.response["hitl_status"] == "rejected"
    assert server.response["user_comment"] == ""
    assert server.response["timestamp"].endswith("Z")
    assert server.response_event.is_set()


def test_context_endpoint_returns_full_file_payload():
    """Context endpoint should return the full file payload for navigation."""
    payload = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=payload,
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = client.get("/api/context")

    assert response.status_code == 200
    assert response.get_json() == payload


def test_index_includes_fields_json_view_toggle():
    """Approval page should expose both Fields and JSON view controls."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data={"value": 1},
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="view-fields-btn"' in html
    assert 'id="view-json-btn"' in html
    assert 'id="panel-fields"' in html
    assert 'id="panel-json"' in html


def test_review_record_persists_state_for_refresh():
    """Per-record decisions should be persisted server-side and returned by review-state."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/review-record",
        server,
        json={"index": 0, "hitl_status": "approved", "user_comment": "ok"},
    )
    assert response.status_code == 200

    response = client.get("/api/review-state")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["record_count"] == 2
    assert payload["record_reviews"][0]["hitl_status"] == "approved"
    assert payload["record_reviews"][1] is None


def test_submit_uses_persisted_review_state_when_payload_missing():
    """Submit should read previously saved per-record state when record_reviews is omitted."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    # Save only first review to simulate partial progress.
    _post(
        client,
        "/api/review-record",
        server,
        json={"index": 0, "hitl_status": "approved", "user_comment": "ok"},
    )
    response = _post(client, "/api/submit", server, json={"hitl_status": "approved"})
    assert response.status_code == 400
    assert "missing record 2" in response.get_json()["error"].lower()

    # Save second decision and submit again without explicit record_reviews payload.
    _post(
        client,
        "/api/review-record",
        server,
        json={"index": 1, "hitl_status": "rejected", "user_comment": "needs fix"},
    )
    response = _post(client, "/api/submit", server, json={"hitl_status": "rejected"})
    assert response.status_code == 200
    assert server.response is not None
    assert server.response["hitl_status"] == "rejected"
    assert len(server.response["record_reviews"]) == 2
    assert server.response["record_reviews"][1]["hitl_status"] == "rejected"


def test_submit_endpoint_rejects_missing_record_reject_comment():
    """Submit endpoint enforces reject comments when configured."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"value": 1}, {"value": 2}],
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/submit",
        server,
        json={
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": ""},
                {"hitl_status": "rejected", "user_comment": ""},
            ]
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert "record 2" in payload["error"].lower()


def test_submit_endpoint_sets_response_with_record_reviews():
    """Submit endpoint stores per-record decisions and inferred overall status."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"value": 1}, {"value": 2}],
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/submit",
        server,
        json={
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": "ok"},
                {"hitl_status": "rejected", "user_comment": "needs fix"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert server.response is not None
    assert server.response["hitl_status"] == "rejected"
    assert len(server.response["record_reviews"]) == 2
    assert server.response_event.is_set()


def test_submit_endpoint_uses_hitl_status_not_legacy_status():
    """Top-level `status` must not override explicit `hitl_status`."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data={"value": 1},
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/submit",
        server,
        json={
            "hitl_status": "approved",
            "status": "rejected",
            "record_reviews": [{"hitl_status": "approved", "status": "rejected"}],
        },
    )

    assert response.status_code == 200
    assert server.response is not None
    assert server.response["hitl_status"] == "approved"
    assert server.response["record_reviews"][0]["hitl_status"] == "approved"


def test_shutdown_endpoint_sets_flag_and_triggers_event():
    """Shutdown endpoint should set shutdown flag and trigger response event."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data={"value": 1},
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    # Ensure event not set initially
    assert not server.response_event.is_set()
    assert not server.shutdown_requested

    response = _post(client, "/api/shutdown", server, json={})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "shutting down" in payload["message"].lower()
    assert server.shutdown_requested is True
    # Event should be set to unblock workflow
    assert server.response_event.is_set()
    # Response should indicate timeout (since no real review happened)
    assert server.response["hitl_status"] == "timeout"


def test_server_startup_failure_signals_error(monkeypatch):
    """Test Flask startup failure unblocks workflow thread with error status."""
    import threading

    def fail_make_server(*args, **kwargs):
        raise OSError("address already in use")

    monkeypatch.setattr(
        "agent_actions.llm.providers.hitl.server.make_server",
        fail_make_server,
    )

    server = HitlServer(
        port=3001,
        instructions="Test",
        context_data={"value": 1},
        timeout=30,
    )

    # Ensure event not set initially
    assert not server.response_event.is_set()

    # Run server in thread (will fail deterministically)
    server_thread = threading.Thread(target=server._run_server, args=(3001,), daemon=True)
    server_thread.start()

    # Wait for error signal (should be fast)
    received = server.response_event.wait(timeout=2)

    # Should have received error response
    assert received is True
    assert server.response is not None
    assert server.response["hitl_status"] == "error"
    assert "failed to start" in server.response["user_comment"].lower()


def test_find_available_port_with_collision():
    """Test port search finds alternative when primary is occupied."""
    import socket

    # Block port 3001
    blocker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker_socket.bind(("127.0.0.1", 3001))

    try:
        server = HitlServer(
            port=3001,
            instructions="Test",
            context_data={"value": 1},
            timeout=30,
        )

        # Should find next available port
        actual_port = server._find_available_port()

        # Should have found 3002 (next port)
        assert actual_port == 3002

    finally:
        blocker_socket.close()


def test_find_available_port_exhaustion_raises_network_error():
    """Test port search raises NetworkError when all ports are occupied."""
    import socket

    # Block ports 3001-3005
    blocker_sockets = []
    for port in range(3001, 3006):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        blocker_sockets.append(sock)

    try:
        server = HitlServer(
            port=3001,
            instructions="Test",
            context_data={"value": 1},
            timeout=30,
        )

        # Should raise NetworkError with context
        try:
            server._find_available_port()
            assert False, "Expected NetworkError"
        except Exception as e:
            assert "Could not find available port" in str(e)
            assert hasattr(e, "context")
            assert "attempted_ports" in e.context

    finally:
        for sock in blocker_sockets:
            sock.close()


def test_shutdown_server_stops_serving():
    """Server thread should exit after _shutdown_server is called."""
    server = HitlServer(
        port=3099,
        instructions="Test shutdown",
        context_data={"value": 1},
        timeout=30,
    )

    server_thread = threading.Thread(
        target=server._run_server,
        args=(3099,),
        daemon=True,
    )
    server_thread.start()

    # Give server a moment to start listening
    server_thread.join(timeout=1.0)
    assert server_thread.is_alive(), "Server thread should be running"

    server._shutdown_server()

    # Server thread should exit promptly after shutdown
    server_thread.join(timeout=5.0)
    assert not server_thread.is_alive(), "Server thread should have stopped"


def test_approve_endpoint_sets_response_for_single_record():
    """POST /api/approve with single-record context should set approved response."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data={"value": 1},
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = _post(client, "/api/approve", server, json={"comment": "looks good"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert server.response is not None
    assert server.response["hitl_status"] == "approved"
    assert server.response_event.is_set()
    assert server.record_reviews[0]["hitl_status"] == "approved"


def test_approve_endpoint_rejects_multi_record():
    """POST /api/approve with multi-record context should return 400."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
        require_comment_on_reject=True,
    )
    client = server.app.test_client()

    response = _post(client, "/api/approve", server, json={"comment": "all good"})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert "multi-record" in payload["error"].lower()
    assert server.response is None


def test_reject_endpoint_rejects_multi_record():
    """POST /api/reject with multi-record context should return 400."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
        require_comment_on_reject=False,
    )
    client = server.app.test_client()

    response = _post(client, "/api/reject", server, json={"comment": "bad"})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert "multi-record" in payload["error"].lower()
    assert server.response is None


def test_review_record_rejects_non_integer_index():
    """POST /api/review-record with non-integer index should return 400."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/review-record",
        server,
        json={"index": "abc", "hitl_status": "approved"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert "integer" in payload["error"].lower()


def test_review_record_rejects_out_of_range_index():
    """POST /api/review-record with out-of-range index should return 400."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/review-record",
        server,
        json={"index": 99, "hitl_status": "approved"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert "out of range" in payload["error"].lower()


def test_review_record_rejects_missing_hitl_status():
    """POST /api/review-record with missing hitl_status should return 400."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/review-record",
        server,
        json={"index": 0},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert "hitl_status" in payload["error"].lower()


def test_review_record_rejects_when_no_records():
    """POST /api/review-record with context_data=None (record_count=0) should return 400."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=None,
        timeout=30,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/review-record",
        server,
        json={"index": 0, "hitl_status": "approved"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert "no records" in payload["error"].lower()


def test_make_terminal_response_ignores_duplicate():
    """Second call to _make_terminal_response should be a no-op."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data={"value": 1},
        timeout=30,
    )

    # First call sets the response
    server._make_terminal_response("approved", comment="first")
    assert server.response["hitl_status"] == "approved"
    assert server.response["user_comment"] == "first"
    first_timestamp = server.response["timestamp"]

    # Second call should be ignored
    server._make_terminal_response("timeout", comment="second")
    assert server.response["hitl_status"] == "approved"
    assert server.response["user_comment"] == "first"
    assert server.response["timestamp"] == first_timestamp


def test_start_and_wait_timeout_returns_timeout_status():
    """start_and_wait with short timeout should return timeout status."""
    server = HitlServer(
        port=3098,
        instructions="Test timeout",
        context_data={"value": 1},
        timeout=1,
    )

    result = server.start_and_wait()

    assert result is not None
    assert result["hitl_status"] == "timeout"
    assert server.response_event.is_set()


def test_submit_endpoint_preserves_top_level_comment():
    """Submit with a top-level comment field should populate user_comment in the response."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
        require_comment_on_reject=False,
    )
    client = server.app.test_client()

    response = _post(
        client,
        "/api/submit",
        server,
        json={
            "hitl_status": "approved",
            "comment": "Everything looks correct",
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": "ok"},
                {"hitl_status": "approved", "user_comment": "fine"},
            ],
        },
    )

    assert response.status_code == 200
    assert server.response is not None
    assert server.response["user_comment"] == "Everything looks correct"
