"""Regression tests for VIOL-0098.

A second reviewer's POST /api/review-record for an already-staged record must
return 409 (before the fix it silently overwrote the prior reviewer's decision).
The same reviewer may still overwrite their own slot (change-of-mind).
"""

from __future__ import annotations

import pytest

from agent_actions.llm.providers.hitl.server import HitlServer


@pytest.fixture
def hitl_client():
    """A HITL server with two records under review, plus its test client."""
    server = HitlServer(
        port=3001,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}],
        timeout=30,
        require_comment_on_reject=False,
    )
    return server, server.app.test_client()


def _stage(client, *, index, status, reviewer_id):
    return client.post(
        "/api/review-record",
        json={"index": index, "hitl_status": status, "reviewer_id": reviewer_id},
    )


def test_second_reviewer_gets_409(hitl_client):
    server, client = hitl_client

    r1 = _stage(client, index=0, status="approved", reviewer_id="reviewer-A")
    assert r1.status_code == 200

    r2 = _stage(client, index=0, status="rejected", reviewer_id="reviewer-B")
    assert r2.status_code == 409
    body = r2.get_json()
    assert body["success"] is False
    assert body["reviewer_id"] == "reviewer-A"  # prior reviewer named
    assert body["staged_at"]  # non-empty timestamp of the prior decision


def test_conflict_does_not_overwrite_prior_decision(hitl_client):
    """The core security property: a rejected 409 leaves the prior decision intact."""
    server, client = hitl_client

    _stage(client, index=0, status="approved", reviewer_id="reviewer-A")
    _stage(client, index=0, status="rejected", reviewer_id="reviewer-B")

    assert server.record_reviews[0]["hitl_status"] == "approved"
    assert server.record_reviews[0]["reviewer_id"] == "reviewer-A"


def test_same_reviewer_can_overwrite(hitl_client):
    server, client = hitl_client

    _stage(client, index=0, status="approved", reviewer_id="reviewer-A")
    r = _stage(client, index=0, status="rejected", reviewer_id="reviewer-A")

    assert r.status_code == 200
    assert server.record_reviews[0]["hitl_status"] == "rejected"


def test_different_records_by_different_reviewers_do_not_conflict(hitl_client):
    """Conflict is per record index — two reviewers may each own a different record."""
    server, client = hitl_client

    assert _stage(client, index=0, status="approved", reviewer_id="reviewer-A").status_code == 200
    assert _stage(client, index=1, status="rejected", reviewer_id="reviewer-B").status_code == 200


def test_review_record_requires_reviewer_id(hitl_client):
    """reviewer_id is the overwrite discriminator — a missing one fails closed (400)."""
    server, client = hitl_client

    resp = client.post(
        "/api/review-record",
        json={"index": 0, "hitl_status": "approved"},
    )
    assert resp.status_code == 400
    assert "reviewer_id" in resp.get_json()["error"].lower()
    assert server.record_reviews[0] is None


def test_staged_entry_records_reviewer_and_timestamp(hitl_client):
    server, client = hitl_client

    _stage(client, index=0, status="approved", reviewer_id="reviewer-A")

    entry = server.record_reviews[0]
    assert entry["reviewer_id"] == "reviewer-A"
    assert entry["staged_at"].endswith("Z")
