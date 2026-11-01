"""A page served for one file's review cannot end or answer the next file's (1604).

Each file is reviewed on a new server at the same port. The page's writes carry the
session it was served with; a write carrying another one is refused and changes nothing.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

from agent_actions.llm.providers.hitl.server import SESSION_HEADER, HitlServer


def _server(port: int = 3001, records: int = 1) -> HitlServer:
    context = [{"value": i} for i in range(records)] if records > 1 else {"value": 1}
    return HitlServer(port=port, instructions="Review", context_data=context, timeout=30)


def _reviews(count: int) -> dict:
    return {"record_reviews": [{"hitl_status": "approved", "user_comment": ""}] * count}


def test_each_server_has_its_own_session_and_serves_it_to_its_page():
    first, second = _server(), _server()
    assert first.session_id != second.session_id

    client = first.app.test_client()
    page = client.get("/").get_data(as_text=True)
    assert f'<meta name="hitl-session" content="{first.session_id}">' in page
    assert client.get("/api/session").get_json() == {"session": first.session_id}


def test_a_shutdown_from_another_session_is_refused_and_leaves_the_review_open():
    server = _server()
    client = server.app.test_client()

    stale = client.post("/api/shutdown", headers={SESSION_HEADER: "earlier-file"}, json={})
    unsigned = client.post("/api/shutdown", json={})

    for response in (stale, unsigned):
        assert response.status_code == 409
        assert response.get_json()["stale_session"] is True
    assert not server.shutdown_requested
    assert not server.response_event.is_set()
    assert server.response is None


def test_a_shutdown_from_this_session_ends_it_as_timed_out():
    server = _server()
    client = server.app.test_client()

    response = client.post("/api/shutdown", headers={SESSION_HEADER: server.session_id}, json={})

    assert response.status_code == 200
    assert server.response["hitl_status"] == "timeout"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/submit", _reviews(2)),
        ("/api/review-record", {"index": 0, "hitl_status": "approved"}),
    ],
)
def test_a_write_from_another_session_changes_nothing(path, body):
    server = _server(records=2)
    client = server.app.test_client()

    response = client.post(path, headers={SESSION_HEADER: "earlier-file"}, json=body)

    assert response.status_code == 409
    assert server.record_reviews == [None, None]
    assert not server.response_event.is_set()


def test_a_submit_from_this_session_or_without_one_is_taken():
    for headers in ({SESSION_HEADER: "this"}, {}):
        server = _server(records=2)
        server.session_id = "this"
        response = server.app.test_client().post("/api/submit", headers=headers, json=_reviews(2))
        assert response.status_code == 200
        assert server.response["hitl_status"] == "approved"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _review_over_http(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/submit",
            data=json.dumps(_reviews(1)).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=5).read()
            return
        except OSError:
            time.sleep(0.05)


def test_the_next_file_binds_the_port_the_last_one_released():
    """The reviewer's tab waits on this port; a socket left open moved the next file off it."""
    port = _free_port()
    first = HitlServer(port=port, instructions="Review", context_data={"value": 1}, timeout=30)
    reviewer = threading.Thread(target=_review_over_http, args=(port,), daemon=True)
    reviewer.start()

    assert first.start_and_wait()["hitl_status"] == "approved"
    reviewer.join(timeout=5)

    second = HitlServer(port=port, instructions="Review", context_data={"value": 2}, timeout=30)
    assert second._find_available_port() == port
