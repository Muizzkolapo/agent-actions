"""A reviewer's decision has to land on the record they reviewed.

The record index arrives as JSON, and ``isinstance(True, int)`` is true, so
``true`` passed the type check and the range check and filed the decision against
record 1 — answering success while the record the reviewer meant stayed
unreviewed.
"""

from agent_actions.llm.providers.hitl.server import HitlServer


def _client():
    server = HitlServer(
        port=3097,
        instructions="Review output",
        context_data=[{"id": 1}, {"id": 2}, {"id": 3}],
        timeout=1,
    )
    return server, server.app.test_client()


def _post(client, index):
    return client.post("/api/review-record", json={"index": index, "hitl_status": "approved"})


class TestABoolIsNotARecordIndex:
    def test_true_is_refused(self):
        server, client = _client()

        assert _post(client, True).status_code == 400

    def test_true_files_no_decision_against_record_one(self):
        server, client = _client()

        _post(client, True)

        assert server.record_reviews == [None, None, None]

    def test_false_is_refused(self):
        server, client = _client()

        assert _post(client, False).status_code == 400
        assert server.record_reviews == [None, None, None]


class TestTheIndexesThatStillWork:
    def test_a_real_index_is_still_accepted(self):
        server, client = _client()

        assert _post(client, 1).status_code == 200
        assert server.record_reviews[1] is not None
        assert server.record_reviews[0] is None

    def test_an_index_past_the_end_is_still_refused(self):
        server, client = _client()

        assert _post(client, 3).status_code == 400

    def test_a_negative_index_is_still_refused(self):
        server, client = _client()

        assert _post(client, -1).status_code == 400

    def test_a_string_index_is_still_refused(self):
        server, client = _client()

        assert _post(client, "1").status_code == 400
