"""The online result -> checkpoint funnel rejects a schema-echo namespace.

The executed-LLM path already rejects schema echoes in ``transform_with_passthrough``.
This seam is the backstop for every other branch: whatever plants a namespace shaped
like the compiled JSON Schema into a result (a no-LLM branch, a future code path, an
older code version), the funnel every result crosses before checkpoint/collection
must convert it to ``_parse_error`` and fail the record — never persist it as success.
"""

import pytest

from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.schema_echo import is_schema_echo


def _compiled_schema():
    compiled = compile_unified_schema(
        {"name": "InlineSchema", "fields": [{"id": "distractor_explanation_1", "type": "string"}]},
        "ollama_cloud",
    )
    assert is_schema_echo(compiled), "fixture must be a real schema-echo shape"
    return compiled


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "test.db"), "test_wf")
    b.initialize()
    yield b
    b.close()


def _context(backend, action="action_a"):
    return ProcessingContext(
        agent_config={},
        agent_name=action,
        storage_backend=backend,
        file_path="/out/output.json",
        output_directory="/out",
    )


def _drive(strategy, backend, result, monkeypatch, action="action_a"):
    """Run a single record through invoke with process_record forced to ``result``.

    Simulates a branch that assembles ``result`` (with whatever namespace) and lets
    the real invoke funnel + checkpoint path act on it.
    """
    monkeypatch.setattr(strategy, "process_record", lambda item, ctx, **kw: result)
    return strategy.invoke([{"source_guid": "g1"}], _context(backend, action))


class TestOnlineNoLLMSeam:
    def test_schema_echo_success_never_persists_as_success(self, backend, monkeypatch):
        """A success result carrying a schema-echo namespace is failed at the seam."""
        strategy = OnlineLLMStrategy(agent_config={}, agent_name="action_a")
        result = ProcessingResult.success(
            data=[{"source_guid": "g1", "content": {"action_a": _compiled_schema()}}],
            source_guid="g1",
        )
        results = _drive(strategy, backend, result, monkeypatch)

        assert results[0].status != ProcessingStatus.SUCCESS  # never a silent success

        disps = backend.get_disposition("action_a", record_id="g1")
        assert not any(d["disposition"] == "success" for d in disps)

    def test_schema_echo_namespace_is_sanitized_in_checkpoint(self, backend, monkeypatch):
        """If the failed record is checkpointed, its namespace is the parse-error sentinel."""
        strategy = OnlineLLMStrategy(agent_config={}, agent_name="action_a")
        result = ProcessingResult.success(
            data=[{"source_guid": "g1", "content": {"action_a": _compiled_schema()}}],
            source_guid="g1",
        )
        _drive(strategy, backend, result, monkeypatch)

        stored = backend.read_checkpoint_records("action_a", "output.json")
        assert stored, "the record must remain queryable, not be dropped"
        ns = stored[0]["content"]["action_a"]
        assert "_parse_error" in ns
        assert "title" not in ns and "properties" not in ns

    def test_clean_success_result_is_untouched(self, backend, monkeypatch):
        """A clean success result flows through the seam unchanged — no over-gating."""
        strategy = OnlineLLMStrategy(agent_config={}, agent_name="action_a")
        clean = {"distractor_explanation_1": "the real explanation"}
        result = ProcessingResult.success(
            data=[{"source_guid": "g1", "content": {"action_a": clean}}],
            source_guid="g1",
        )
        results = _drive(strategy, backend, result, monkeypatch)

        assert results[0].status == ProcessingStatus.SUCCESS
        stored = backend.read_checkpoint_records("action_a", "output.json")
        assert stored[0]["content"]["action_a"] == clean
