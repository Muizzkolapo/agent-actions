"""Tests for HITL review state persistence (disk-backed recovery)."""

import json

from agent_actions.llm.providers.hitl.server import HitlServer


def _fingerprint(context_data):
    """Compute the same fingerprint the server would for given data."""
    return HitlServer._compute_data_fingerprint(context_data)


def _post(client, url, server, **kwargs):
    """POST helper that automatically injects the HITL session token."""
    headers = kwargs.pop("headers", {})
    headers["X-HITL-Token"] = server._session_token
    return client.post(url, headers=headers, **kwargs)


def _make_server(tmp_path, context_data=None, record_count=4):
    """Create a HitlServer wired to a state file in tmp_path."""
    if context_data is None:
        context_data = [{"id": i} for i in range(record_count)]
    state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
    server = HitlServer(
        port=3001,
        instructions="Review",
        context_data=context_data,
        timeout=30,
        require_comment_on_reject=False,
        state_file=state_file,
    )
    return server, state_file


class TestStateFileCreation:
    """State file is written after individual record reviews."""

    def test_state_file_created_on_review(self, tmp_path):
        server, state_file = _make_server(tmp_path)
        client = server.app.test_client()

        resp = _post(
            client,
            "/api/review-record",
            server,
            json={"index": 0, "hitl_status": "approved", "user_comment": ""},
        )
        assert resp.status_code == 200

        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["total_records"] == 4
        assert state["record_reviews"][0] == {"hitl_status": "approved", "user_comment": ""}
        assert state["record_reviews"][1] is None
        assert "last_updated" in state

    def test_state_file_updated_on_subsequent_reviews(self, tmp_path):
        server, state_file = _make_server(tmp_path)
        client = server.app.test_client()

        _post(
            client,
            "/api/review-record",
            server,
            json={"index": 0, "hitl_status": "approved", "user_comment": ""},
        )
        _post(
            client,
            "/api/review-record",
            server,
            json={"index": 2, "hitl_status": "rejected", "user_comment": "bad"},
        )

        state = json.loads(state_file.read_text())
        assert state["record_reviews"][0] == {"hitl_status": "approved", "user_comment": ""}
        assert state["record_reviews"][1] is None
        assert state["record_reviews"][2] == {"hitl_status": "rejected", "user_comment": "bad"}
        assert state["record_reviews"][3] is None


class TestStateLoading:
    """State is pre-populated from disk on server init."""

    def test_state_loaded_on_init(self, tmp_path):
        context_data = [{"id": i} for i in range(4)]
        state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": ""},
                {"hitl_status": "rejected", "user_comment": "needs work"},
                None,
                None,
            ],
            "total_records": 4,
            "data_fingerprint": _fingerprint(context_data),
            "last_updated": "2026-02-20T10:00:00Z",
        }
        state_file.write_text(json.dumps(state))

        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data=context_data,
            timeout=30,
            state_file=state_file,
        )

        assert server.record_reviews[0] == {"hitl_status": "approved", "user_comment": ""}
        assert server.record_reviews[1] == {"hitl_status": "rejected", "user_comment": "needs work"}
        assert server.record_reviews[2] is None
        assert server.record_reviews[3] is None

    def test_state_mismatch_ignored(self, tmp_path):
        """When total_records doesn't match, state is ignored."""
        state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": ""},
                None,
            ],
            "total_records": 2,
            "last_updated": "2026-02-20T10:00:00Z",
        }
        state_file.write_text(json.dumps(state))

        # Server has 4 records, but state file has 2
        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data=[{"id": i} for i in range(4)],
            timeout=30,
            state_file=state_file,
        )

        # All reviews should be None (state ignored)
        assert all(r is None for r in server.record_reviews)

    def test_corrupt_state_ignored(self, tmp_path):
        """Invalid JSON in state file should not prevent server startup."""
        state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{{not valid json")

        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data=[{"id": i} for i in range(4)],
            timeout=30,
            state_file=state_file,
        )

        assert all(r is None for r in server.record_reviews)

    def test_fingerprint_mismatch_ignored(self, tmp_path):
        """State is ignored when input data changed (same count, different content)."""
        old_data = [{"id": i} for i in range(4)]
        new_data = [{"id": i, "value": "changed"} for i in range(4)]
        state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": ""},
                None,
                None,
                None,
            ],
            "total_records": 4,
            "data_fingerprint": _fingerprint(old_data),
            "last_updated": "2026-02-20T10:00:00Z",
        }
        state_file.write_text(json.dumps(state))

        # Server gets new_data (different content, same count)
        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data=new_data,
            timeout=30,
            state_file=state_file,
        )

        # All reviews should be None (fingerprint mismatch)
        assert all(r is None for r in server.record_reviews)

    def test_non_dict_json_state_ignored(self, tmp_path):
        """Valid JSON that is not an object (e.g. a list) should be ignored."""
        state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps([1, 2, 3]))

        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data=[{"id": i} for i in range(4)],
            timeout=30,
            state_file=state_file,
        )

        assert all(r is None for r in server.record_reviews)


class TestStateDeletion:
    """State file is deleted on successful submit/approve/reject."""

    def test_state_deleted_on_submit(self, tmp_path):
        server, state_file = _make_server(tmp_path)
        client = server.app.test_client()

        # Review all records
        for i in range(4):
            _post(
                client,
                "/api/review-record",
                server,
                json={"index": i, "hitl_status": "approved", "user_comment": ""},
            )
        assert state_file.exists()

        # Submit
        resp = _post(client, "/api/submit", server, json={})
        assert resp.status_code == 200
        assert not state_file.exists()

    def test_state_deleted_on_approve_single_record(self, tmp_path):
        state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data={"value": 1},
            timeout=30,
            require_comment_on_reject=False,
            state_file=state_file,
        )
        client = server.app.test_client()

        # Review the single record to create state file
        _post(
            client,
            "/api/review-record",
            server,
            json={"index": 0, "hitl_status": "approved", "user_comment": ""},
        )
        assert state_file.exists()

        # Approve
        resp = _post(client, "/api/approve", server, json={})
        assert resp.status_code == 200
        assert not state_file.exists()

    def test_state_deleted_on_reject_single_record(self, tmp_path):
        state_file = tmp_path / "hitl" / ".hitl_reviews_test.json"
        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data={"value": 1},
            timeout=30,
            require_comment_on_reject=False,
            state_file=state_file,
        )
        client = server.app.test_client()

        # Review the single record to create state file
        _post(
            client,
            "/api/review-record",
            server,
            json={"index": 0, "hitl_status": "rejected", "user_comment": "no"},
        )
        assert state_file.exists()

        # Reject
        resp = _post(client, "/api/reject", server, json={"comment": "no"})
        assert resp.status_code == 200
        assert not state_file.exists()


class TestReviewRecordAfterSubmit:
    """Late review-record requests must not recreate the state file."""

    def test_review_record_rejected_after_submit(self, tmp_path):
        server, state_file = _make_server(tmp_path)
        client = server.app.test_client()

        # Review all records then submit
        for i in range(4):
            _post(
                client,
                "/api/review-record",
                server,
                json={"index": i, "hitl_status": "approved", "user_comment": ""},
            )
        _post(client, "/api/submit", server, json={})
        assert not state_file.exists()

        # Late review-record should be rejected with 409
        resp = _post(
            client,
            "/api/review-record",
            server,
            json={"index": 0, "hitl_status": "rejected", "user_comment": "late"},
        )
        assert resp.status_code == 409
        assert not state_file.exists()


class TestStateTimeout:
    """State file survives server timeout for later recovery."""

    def test_state_survives_timeout(self, tmp_path):
        server, state_file = _make_server(tmp_path)
        client = server.app.test_client()

        # Review 2 of 4 records
        _post(
            client,
            "/api/review-record",
            server,
            json={"index": 0, "hitl_status": "approved", "user_comment": ""},
        )
        _post(
            client,
            "/api/review-record",
            server,
            json={"index": 1, "hitl_status": "rejected", "user_comment": "fix"},
        )
        assert state_file.exists()

        # Simulate timeout via shutdown endpoint
        _post(client, "/api/shutdown", server, json={})

        # State file should still exist
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["record_reviews"][0] is not None
        assert state["record_reviews"][1] is not None
        assert state["record_reviews"][2] is None
        assert state["record_reviews"][3] is None


class TestNoStateFile:
    """Server works normally when no state_file is configured."""

    def test_no_state_file_no_error(self):
        server = HitlServer(
            port=3001,
            instructions="Review",
            context_data=[{"id": 0}],
            timeout=30,
        )
        client = server.app.test_client()

        resp = _post(
            client,
            "/api/review-record",
            server,
            json={"index": 0, "hitl_status": "approved", "user_comment": ""},
        )
        assert resp.status_code == 200
        # No crash, no state file created
