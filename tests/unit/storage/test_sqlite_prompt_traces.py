"""Unit tests for SQLite prompt trace storage."""

import json

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    """Create an initialized SQLite backend."""
    db_path = str(tmp_path / "test.db")
    b = SQLiteBackend(db_path, "test_workflow")
    b.initialize()
    return b


# ---------------------------------------------------------------------------
# write + read round-trip
# ---------------------------------------------------------------------------


class TestWriteAndRead:
    def test_write_and_read_trace(self, backend):
        backend.write_prompt_trace(
            action_name="extract",
            record_id="rec-001",
            compiled_prompt="Analyze this text: hello world",
            llm_context=json.dumps({"source": {"text": "hello world"}}),
            model_name="gpt-4",
            model_vendor="openai",
        )
        traces = backend.get_prompt_traces("extract")
        assert len(traces) == 1
        t = traces[0]
        assert t["action_name"] == "extract"
        assert t["record_id"] == "rec-001"
        assert t["attempt"] == 0
        assert t["compiled_prompt"] == "Analyze this text: hello world"
        assert json.loads(t["llm_context"]) == {"source": {"text": "hello world"}}
        assert t["model_name"] == "gpt-4"
        assert t["model_vendor"] == "openai"
        assert t["prompt_length"] == len("Analyze this text: hello world")
        assert t["response_text"] is None

    def test_filter_by_record_id(self, backend):
        backend.write_prompt_trace("act", "rec-1", "prompt1")
        backend.write_prompt_trace("act", "rec-2", "prompt2")

        traces = backend.get_prompt_traces("act", record_id="rec-1")
        assert len(traces) == 1
        assert traces[0]["record_id"] == "rec-1"

    def test_empty_result_for_missing_action(self, backend):
        assert backend.get_prompt_traces("nonexistent") == []


# ---------------------------------------------------------------------------
# Response update
# ---------------------------------------------------------------------------


class TestResponseUpdate:
    def test_update_response(self, backend):
        backend.write_prompt_trace("act", "rec-1", "prompt text")
        backend.update_prompt_trace_response("act", "rec-1", '{"result": "ok"}')

        traces = backend.get_prompt_traces("act", record_id="rec-1")
        assert traces[0]["response_text"] == '{"result": "ok"}'
        assert traces[0]["response_length"] == len('{"result": "ok"}')

    def test_update_nonexistent_trace_is_noop(self, backend):
        # Should not raise
        backend.update_prompt_trace_response("act", "rec-missing", '{"result": "ok"}')
        assert backend.get_prompt_traces("act") == []


# ---------------------------------------------------------------------------
# Attempt column
# ---------------------------------------------------------------------------


class TestAttemptColumn:
    def test_multiple_attempts_preserved(self, backend):
        backend.write_prompt_trace("act", "rec-1", "prompt v1", attempt=0)
        backend.write_prompt_trace("act", "rec-1", "prompt v2 with feedback", attempt=1)

        traces = backend.get_prompt_traces("act", record_id="rec-1")
        assert len(traces) == 2
        assert traces[0]["attempt"] == 0
        assert traces[0]["compiled_prompt"] == "prompt v1"
        assert traces[1]["attempt"] == 1
        assert traces[1]["compiled_prompt"] == "prompt v2 with feedback"

    def test_update_response_targets_specific_attempt(self, backend):
        backend.write_prompt_trace("act", "rec-1", "prompt v1", attempt=0)
        backend.write_prompt_trace("act", "rec-1", "prompt v2", attempt=1)
        backend.update_prompt_trace_response("act", "rec-1", "response v2", attempt=1)

        traces = backend.get_prompt_traces("act", record_id="rec-1")
        assert traces[0]["response_text"] is None  # attempt 0 unchanged
        assert traces[1]["response_text"] == "response v2"  # attempt 1 updated


# ---------------------------------------------------------------------------
# Size cap truncation
# ---------------------------------------------------------------------------


class TestSizeCap:
    def test_field_under_cap_stored_as_is(self, backend):
        context = json.dumps({"key": "x" * 1000})
        backend.write_prompt_trace("act", "rec-1", "prompt", llm_context=context)
        traces = backend.get_prompt_traces("act")
        assert traces[0]["llm_context"] == context

    def test_field_over_cap_truncated(self, backend):
        huge_context = "x" * (1_048_576 + 100)  # Just over 1MB
        backend.write_prompt_trace("act", "rec-1", "prompt", llm_context=huge_context)

        traces = backend.get_prompt_traces("act")
        stored = json.loads(traces[0]["llm_context"])
        assert stored["__truncated__"] is True
        assert stored["original_length"] == len(huge_context)
        assert "partial" not in stored  # No partial field

    def test_response_over_cap_truncated(self, backend):
        huge_response = "r" * (1_048_576 + 50)
        backend.write_prompt_trace("act", "rec-1", "prompt", response_text=huge_response)

        traces = backend.get_prompt_traces("act")
        stored = json.loads(traces[0]["response_text"])
        assert stored["__truncated__"] is True

    def test_length_columns_reflect_original_size(self, backend):
        """Length columns should record original size, not truncated stub size."""
        original_size = 1_048_576 + 200
        huge_context = "x" * original_size
        backend.write_prompt_trace("act", "rec-1", "prompt", llm_context=huge_context)

        traces = backend.get_prompt_traces("act")
        assert traces[0]["context_length"] == original_size


# ---------------------------------------------------------------------------
# clear_prompt_traces
# ---------------------------------------------------------------------------


class TestClearTraces:
    def test_clear_by_action(self, backend):
        backend.write_prompt_trace("act1", "rec-1", "p1")
        backend.write_prompt_trace("act2", "rec-2", "p2")

        deleted = backend.clear_prompt_traces("act1")
        assert deleted == 1
        assert len(backend.get_prompt_traces("act1")) == 0
        assert len(backend.get_prompt_traces("act2")) == 1

    def test_clear_all(self, backend):
        backend.write_prompt_trace("act1", "rec-1", "p1")
        backend.write_prompt_trace("act2", "rec-2", "p2")

        deleted = backend.clear_prompt_traces()
        assert deleted == 2
        assert len(backend.get_prompt_traces("act1")) == 0
        assert len(backend.get_prompt_traces("act2")) == 0


# ---------------------------------------------------------------------------
# get_prompt_trace_summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_returns_stats(self, backend):
        backend.write_prompt_trace("act", "rec-1", "prompt text", llm_context='{"a": 1}')
        backend.write_prompt_trace("act", "rec-2", "prompt text", llm_context='{"b": 2}')

        summary = backend.get_prompt_trace_summary("act")
        assert summary is not None
        assert summary["action_name"] == "act"
        assert summary["trace_count"] == 2
        assert summary["compiled_prompt"] == "prompt text"
        assert summary["avg_prompt_length"] == len("prompt text")

    def test_summary_returns_none_for_missing(self, backend):
        assert backend.get_prompt_trace_summary("nonexistent") is None


# ---------------------------------------------------------------------------
# preview_prompt_traces (pagination)
# ---------------------------------------------------------------------------


class TestPreview:
    def test_pagination(self, backend):
        for i in range(25):
            backend.write_prompt_trace("act", f"rec-{i:03d}", f"prompt {i}")

        page1 = backend.preview_prompt_traces("act", limit=10, offset=0)
        assert page1["total_count"] == 25
        assert len(page1["records"]) == 10
        assert page1["records"][0]["record_id"] == "rec-000"

        page3 = backend.preview_prompt_traces("act", limit=10, offset=20)
        assert len(page3["records"]) == 5

    def test_empty_action(self, backend):
        result = backend.preview_prompt_traces("nonexistent")
        assert result["total_count"] == 0
        assert result["records"] == []


# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_action_name_rejected(self, backend):
        with pytest.raises(ValueError, match="Empty"):
            backend.write_prompt_trace("", "rec-1", "prompt")

    def test_empty_record_id_rejected(self, backend):
        with pytest.raises(ValueError, match="Empty"):
            backend.write_prompt_trace("act", "", "prompt")

    def test_path_traversal_rejected(self, backend):
        with pytest.raises(ValueError, match="traversal"):
            backend.write_prompt_trace("../evil", "rec-1", "prompt")


# ---------------------------------------------------------------------------
# Overwrite on re-run (INSERT OR REPLACE)
# ---------------------------------------------------------------------------


class TestOverwrite:
    def test_same_key_overwrites(self, backend):
        backend.write_prompt_trace("act", "rec-1", "prompt v1", attempt=0)
        backend.write_prompt_trace("act", "rec-1", "prompt v2", attempt=0)

        traces = backend.get_prompt_traces("act", record_id="rec-1")
        assert len(traces) == 1
        assert traces[0]["compiled_prompt"] == "prompt v2"


# ---------------------------------------------------------------------------
# get_storage_stats includes trace data
# ---------------------------------------------------------------------------


class TestStorageStats:
    def test_stats_include_traces(self, backend):
        backend.write_prompt_trace("act1", "rec-1", "p1")
        backend.write_prompt_trace("act1", "rec-2", "p2")
        backend.write_prompt_trace("act2", "rec-3", "p3")

        stats = backend.get_storage_stats()
        assert stats["trace_count"] == 3
        assert stats["trace_stats"] == {"act1": 2, "act2": 1}
