"""Timeout responses must carry the partial per-record review snapshot."""

from agent_actions.llm.providers.hitl.server import HitlServer


def _server():
    return HitlServer(
        port=3097,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}, {"id": 3}],
        timeout=1,
    )


def test_start_and_wait_timeout_includes_partial_reviews():
    server = _server()
    client = server.app.test_client()
    resp = client.post("/api/review-record", json={"index": 0, "hitl_status": "approved"})
    assert resp.status_code == 200

    result = server.start_and_wait()

    assert result["hitl_status"] == "timeout"
    reviews = result.get("record_reviews")
    assert isinstance(reviews, list)
    assert len(reviews) == 3
    assert reviews[0] == {"hitl_status": "approved", "user_comment": ""}
    assert reviews[1] is None
    assert reviews[2] is None


def test_shutdown_timeout_includes_partial_reviews():
    server = _server()
    client = server.app.test_client()
    resp = client.post(
        "/api/review-record",
        json={"index": 1, "hitl_status": "rejected", "user_comment": "not accurate"},
    )
    assert resp.status_code == 200

    resp = client.post("/api/shutdown")
    assert resp.status_code == 200

    assert server.response["hitl_status"] == "timeout"
    reviews = server.response.get("record_reviews")
    assert isinstance(reviews, list)
    assert len(reviews) == 3
    assert reviews[1]["hitl_status"] == "rejected"
    assert reviews[1]["user_comment"] == "not accurate"
    assert reviews[0] is None
    assert reviews[2] is None


def test_timeout_with_no_reviews_omits_snapshot():
    server = _server()

    result = server.start_and_wait()

    assert result["hitl_status"] == "timeout"
    assert "record_reviews" not in result
