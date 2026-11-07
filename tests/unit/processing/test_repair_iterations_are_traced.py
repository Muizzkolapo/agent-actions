"""Each provider call a repair loop makes is traced: its own prompt beside its own response.

Prepare stores the first prompt as attempt 0. Every repair iteration after it sends a new
prompt, the previous response and the failed rules appended, and that prompt is stored as
the next attempt with the response it drew. A response the loop discards is kept.
"""

from types import SimpleNamespace

import pytest

from agent_actions.config.types import RunMode
from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.task_preparer import write_trace_row
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

NEEDS_TWO = Suite(
    name="s",
    expectations=[{"id": "count", "type": "item_count", "field": "ideas", "params": {"min": 2}}],
)


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _context(backend):
    return SimpleNamespace(
        agent_name="summarize",
        agent_config={"model_name": "mock", "model_vendor": "agac-provider"},
        storage_backend=backend,
        mode=RunMode.ONLINE,
        workflow_metadata=None,
    )


def _task():
    return SimpleNamespace(
        should_execute=True,
        is_passthrough=False,
        original_content={},
        passthrough_fields={},
        formatted_prompt="PROMPT",
        llm_context={"page": "p"},
        target_id="r1",
        source_guid="g1",
    )


def _invoke(monkeypatch, backend, service, responses):
    """Prepare's attempt-0 row, then the strategy, answering call n with responses[n]."""
    prompts: list[str] = []

    def fake_call(self, task, ctx, prompt):
        prompts.append(prompt)
        return responses[len(prompts) - 1], True

    monkeypatch.setattr(OnlineStrategy, "_call_llm", fake_call)
    context, task = _context(backend), _task()
    write_trace_row(
        context,
        record_id=task.target_id,
        source_guid=task.source_guid,
        prompt=task.formatted_prompt,
        llm_context=task.llm_context,
        attempt=0,
    )
    OnlineStrategy(expectation_service=service).invoke(task, context)
    return prompts, backend.get_prompt_traces("summarize", "r1")


def _always_short(n):
    return [{"ideas": [f"r{i}"]} for i in range(n)]


def test_each_repair_attempt_has_its_own_row(monkeypatch, backend):
    service = ExpectationService(NEEDS_TWO, repair="auto", max_iterations=3)

    prompts, rows = _invoke(monkeypatch, backend, service, _always_short(3))

    assert [row["attempt"] for row in rows] == [0, 1, 2]
    assert [row["compiled_prompt"] for row in rows] == prompts
    assert [row["response_text"] for row in rows] == [
        '{"ideas": ["r0"]}',
        '{"ideas": ["r1"]}',
        '{"ideas": ["r2"]}',
    ]


def test_the_repair_prompt_holds_the_previous_response(monkeypatch, backend):
    service = ExpectationService(NEEDS_TWO, repair="auto", max_iterations=3)

    _, rows = _invoke(monkeypatch, backend, service, _always_short(3))

    assert rows[0]["compiled_prompt"] == "PROMPT"
    assert "## Your previous output failed validation" in rows[1]["compiled_prompt"]
    assert '{"ideas": ["r0"]}' in rows[1]["compiled_prompt"]
    assert '{"ideas": ["r1"]}' in rows[2]["compiled_prompt"]


def test_fail_policy_keeps_every_response(monkeypatch, backend):
    service = ExpectationService(NEEDS_TWO, repair="auto", max_iterations=3, on_exhausted="fail")

    _, rows = _invoke(monkeypatch, backend, service, _always_short(3))

    assert [(row["attempt"], row["response_text"]) for row in rows] == [
        (0, '{"ideas": ["r0"]}'),
        (1, '{"ideas": ["r1"]}'),
        (2, '{"ideas": ["r2"]}'),
    ]


def test_a_first_pass_writes_one_row(monkeypatch, backend):
    service = ExpectationService(NEEDS_TWO, repair="auto", max_iterations=3)

    prompts, rows = _invoke(monkeypatch, backend, service, [{"ideas": ["a", "b"]}])

    assert prompts == ["PROMPT"]
    assert [(row["attempt"], row["response_text"]) for row in rows] == [
        (0, '{"ideas": ["a", "b"]}')
    ]


def test_no_expect_writes_one_row(monkeypatch, backend):
    prompts, rows = _invoke(monkeypatch, backend, None, [{"ideas": ["a"]}])

    assert prompts == ["PROMPT"]
    assert [(row["attempt"], row["response_text"]) for row in rows] == [(0, '{"ideas": ["a"]}')]


def test_a_repair_row_carries_the_records_identity_and_model(monkeypatch, backend):
    service = ExpectationService(NEEDS_TWO, repair="auto", max_iterations=2)

    _, rows = _invoke(monkeypatch, backend, service, _always_short(2))

    first, repair = rows
    for key in ("source_guid", "model_name", "model_vendor", "run_mode", "llm_context"):
        assert repair[key] == first[key], key
    assert (repair["source_guid"], repair["model_name"]) == ("g1", "mock")
