"""A retry resuming a halt asks again only the records the halted action never answered.

The halted action never stored the file it halted in; what it answered before the halt
sat in checkpoint rows. The retry deleted them along with every other checkpoint row of
the action, so the records it had `success` for were asked and paid for again (1316).
"""

import pytest

from agent_actions.errors import exhaustion_halt
from agent_actions.llm.providers.tools import client as tool_client
from tests.integration.test_a_retry_resumes_a_halt_in_full import (
    _halted,
    _retry,
    _run,
    _status,
)
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    _stored_guids,
    chained,  # noqa: F401
    project,  # noqa: F401
)


@pytest.fixture
def counted_calls(monkeypatch):
    """`enrich`'s tool, halting the action at its third call on the first run only."""
    run_tool = tool_client.execute_user_defined_function
    calls: list[int] = []
    runs = {"n": 0}

    def faulty(udf_name, *args, **kwargs):
        if udf_name == "tag_density":
            calls.append(runs["n"])
            if runs["n"] == 0 and len(calls) == 3:
                raise exhaustion_halt("Retry exhausted after 2 attempts (on_exhausted=raise)")
        return run_tool(udf_name, *args, **kwargs)

    monkeypatch.setattr(tool_client, "execute_user_defined_function", faulty)
    yield calls, runs


def test_the_resume_asks_the_records_past_the_halt_and_no_other(chained, counted_calls):  # noqa: F811
    calls, runs = counted_calls
    assert _run("--fresh").exit_code != 0
    assert _status(chained) == "failed" and _halted(chained)
    runs["n"] = 1

    result = _retry()

    assert result.exit_code == 0, result.output
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)
    assert len(_stored_guids(chained, SECOND)) == RECORDS
    # Two were answered before the halt; the halting record and the three past it remain.
    assert calls.count(1) == RECORDS - 2, calls
