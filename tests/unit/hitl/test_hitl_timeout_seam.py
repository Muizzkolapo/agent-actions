"""The server's timeout response and the strategy's timeout report agree."""

from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.llm.providers.hitl.server import HitlServer
from agent_actions.processing.strategies.hitl import HITLStrategy
from agent_actions.processing.types import ProcessingContext


def _server():
    return HitlServer(
        port=3096,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}, {"id": 3}],
        timeout=1,
    )


def test_timed_out_server_response_drives_reviewed_count_in_error():
    server = _server()
    client = server.app.test_client()
    resp = client.post("/api/review-record", json={"index": 0, "hitl_status": "approved"})
    assert resp.status_code == 200

    response = server.start_and_wait()

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
        {"source_guid": "sg-3", "content": {"id": 3}},
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with (
        patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            return_value=(response, True),
        ),
        pytest.raises(AgentActionsError, match="1/3 records reviewed"),
    ):
        HITLStrategy().invoke(input_data, context)


def test_non_timeout_terminal_response_keeps_explicit_payload_only():
    server = _server()
    client = server.app.test_client()
    resp = client.post("/api/review-record", json={"index": 0, "hitl_status": "approved"})
    assert resp.status_code == 200

    server._make_terminal_response("error", "server failed")

    assert server.response["hitl_status"] == "error"
    assert "record_reviews" not in server.response
