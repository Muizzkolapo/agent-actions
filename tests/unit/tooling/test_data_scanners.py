"""Tests for data scanners: scan_logs, extract_run_events.

Also covers SQLiteBackend.scan_data() prompt trace attachment
and namespace unwrapping.
"""

from __future__ import annotations

import builtins
import json
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.tooling.docs.scanner.data_scanners import (
    EVENT_PROBLEM_LIMIT,
    EVENT_TAIL_LIMIT,
    extract_run_events,
    scan_logs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_events(path: Path, count: int, event_type: str = "CLIArgumentParsingEvent") -> None:
    """Write `count` minimal JSONL event lines to `path`."""
    with open(path, "w", encoding="utf-8") as f:
        for i in range(count):
            record = {
                "event_type": event_type,
                "meta": {"invocation_id": f"inv-{i}", "timestamp": "2024-01-01"},
                "data": {"command": "run"},
            }
            f.write(json.dumps(record) + "\n")


def _action_event(action_name: str) -> dict:
    return {
        "event_type": "ActionCompleteEvent",
        "meta": {"action_name": action_name},
        "data": {"action_name": action_name, "execution_time": 1.0, "record_count": 5},
    }


# ---------------------------------------------------------------------------
# scan_logs
# ---------------------------------------------------------------------------


class TestScanLogs:
    def test_scan_logs_returns_recent_invocations(self, tmp_path):
        """scan_logs returns correct data and caps recent invocations at 10."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        _write_events(events_path, 50)
        result = scan_logs(tmp_path)
        assert isinstance(result["recent_invocations"], list)
        assert len(result["recent_invocations"]) <= 10  # capped at last 10

    def test_scan_logs_returns_the_event_tail(self, tmp_path):
        """The project-level log reaches the Log Explorer, not only its two projections."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        _write_events(logs_dir / "events.json", 3)

        rows = scan_logs(tmp_path)["events"]

        assert [r["seq"] for r in rows] == [0, 1, 2]
        assert rows[0]["meta"]["invocation_id"] == "inv-0"

    def test_scan_logs_ignores_a_row_carrying_its_own_seq(self, tmp_path):
        """Ids are built from the assigned position; a row must not repoint its own."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        with open(logs_dir / "events.json", "w") as f:
            f.write(json.dumps({"event_type": "E", "seq": 999, "meta": {}}) + "\n")
            f.write(json.dumps({"event_type": "E", "meta": {}}) + "\n")

        rows = scan_logs(tmp_path)["events"]

        assert [r["seq"] for r in rows] == [0, 1]

    def test_scan_logs_event_tail_is_bounded(self, tmp_path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        _write_events(logs_dir / "events.json", EVENT_TAIL_LIMIT + 7)

        rows = scan_logs(tmp_path)["events"]

        assert len(rows) == EVENT_TAIL_LIMIT
        assert rows[0]["seq"] == 7

    def test_scan_logs_keeps_diagnostic_rows(self, tmp_path):
        """The explorer hides diagnostics behind a toggle; it cannot show what the
        scanner dropped."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        with open(logs_dir / "events.json", "w") as f:
            f.write(json.dumps({"event_type": "E", "diagnostic": True, "meta": {}}) + "\n")
            f.write(json.dumps({"event_type": "E", "diagnostic": False, "meta": {}}) + "\n")

        rows = scan_logs(tmp_path)["events"]

        assert [r["diagnostic"] for r in rows] == [True, False]

    def test_scan_logs_event_tail_empty_without_a_log(self, tmp_path):
        assert scan_logs(tmp_path)["events"] == []

    def test_scan_logs_reads_all_events(self, tmp_path):
        """scan_logs reads the entire file with no line cap."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        # Write enough events that the old 100k cap would have truncated
        _write_events(events_path, 200)
        result = scan_logs(tmp_path)
        # All 200 unique invocations were seen, last 10 returned
        assert len(result["recent_invocations"]) == 10

    def test_scan_logs_missing_logs_dir(self, tmp_path):
        """scan_logs returns empty structure when logs/ does not exist."""
        result = scan_logs(tmp_path)
        assert result["events_path"] is None
        assert result["recent_invocations"] == []

    def test_scan_logs_missing_events_file(self, tmp_path):
        """scan_logs returns empty structure when events.json does not exist."""
        (tmp_path / "logs").mkdir()
        result = scan_logs(tmp_path)
        assert result["events_path"] is None


# ---------------------------------------------------------------------------
# extract_run_events — action metrics
# ---------------------------------------------------------------------------


class TestRunEventsActionMetrics:
    def test_returns_metrics_for_known_events(self, tmp_path):
        """extract_run_events parses ActionCompleteEvent correctly."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_action_event("my_action")) + "\n")
        result = extract_run_events(events_path).action_metrics
        assert "my_action" in result
        assert result["my_action"]["execution_time"] == 1.0


# ---------------------------------------------------------------------------
# extract_run_events — runtime warnings
# ---------------------------------------------------------------------------


def _warn_event(action_name: str, message: str, level: str = "warn") -> dict:
    return {
        "event_type": "LogEvent",
        "code": "X000",
        "level": level,
        "message": message,
        "meta": {
            "timestamp": "2026-04-03T09:44:13Z",
            "action_name": action_name,
        },
        "data": {},
    }


class TestRunEventsRuntimeWarnings:
    def test_captures_warn_level(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("my_action", "All records filtered")) + "\n")

        result = extract_run_events(events_path).runtime_warnings

        assert len(result) == 1
        assert result[0]["level"] == "warn"
        assert result[0]["message"] == "All records filtered"
        assert result[0]["action_name"] == "my_action"

    def test_captures_error_level(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("act", "Something broke", level="error")) + "\n")

        result = extract_run_events(events_path).runtime_warnings

        assert len(result) == 1
        assert result[0]["level"] == "error"

    def test_ignores_info_and_debug(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("a", "info msg", level="info")) + "\n")
            f.write(json.dumps(_warn_event("b", "debug msg", level="debug")) + "\n")

        result = extract_run_events(events_path).runtime_warnings

        assert result == []

    def test_mixed_levels(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("a", "ok", level="info")) + "\n")
            f.write(json.dumps(_warn_event("b", "bad", level="warn")) + "\n")
            f.write(json.dumps(_warn_event("c", "worse", level="error")) + "\n")
            f.write(json.dumps(_action_event("d")) + "\n")  # not a warn/error

        result = extract_run_events(events_path).runtime_warnings

        assert len(result) == 2
        assert result[0]["action_name"] == "b"
        assert result[1]["action_name"] == "c"

    def test_missing_file_returns_empty(self, tmp_path):
        result = extract_run_events(tmp_path / "nonexistent.json").runtime_warnings
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path):
        events_path = tmp_path / "events.json"
        events_path.write_text("")
        result = extract_run_events(events_path).runtime_warnings
        assert result == []

    def test_malformed_json_lines_skipped(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps(_warn_event("a", "real warning")) + "\n")
            f.write("{truncated\n")

        result = extract_run_events(events_path).runtime_warnings

        assert len(result) == 1
        assert result[0]["action_name"] == "a"

    def test_blank_lines_skipped(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write("\n")
            f.write("  \n")
            f.write(json.dumps(_warn_event("a", "found it")) + "\n")

        result = extract_run_events(events_path).runtime_warnings

        assert len(result) == 1


class TestRunEventsMetricsEnrichment:
    """Tests for enriched action metrics: latency, provider, model, cache, disposition."""

    def _write_events(self, path: Path, events: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    def test_llm_response_extracts_latency_and_provider(self, tmp_path):
        """LLMResponseEvent populates avg latency, provider, and model."""
        events_path = tmp_path / "events.json"
        self._write_events(
            events_path,
            [
                {
                    "event_type": "LLMResponseEvent",
                    "meta": {"action_name": "classify"},
                    "data": {
                        "action_name": "classify",
                        "latency_ms": 200.0,
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                    },
                },
                {
                    "event_type": "LLMResponseEvent",
                    "meta": {"action_name": "classify"},
                    "data": {
                        "action_name": "classify",
                        "latency_ms": 400.0,
                        "provider": "anthropic",
                        "model": "claude-sonnet",
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                    },
                },
            ],
        )
        result = extract_run_events(events_path).action_metrics
        m = result["classify"]
        assert m["latency_ms"] == 300.0  # average of 200 and 400
        assert m["provider"] == "openai"  # first event wins, not overwritten
        assert m["model"] == "gpt-4o-mini"
        assert "llm_request_count" not in m  # internal field must be stripped

    def test_result_collection_extracts_exhausted(self, tmp_path):
        """ResultCollectionCompleteEvent populates exhausted_count."""
        events_path = tmp_path / "events.json"
        self._write_events(
            events_path,
            [
                {
                    "event_type": "ResultCollectionCompleteEvent",
                    "meta": {"action_name": "summarize"},
                    "data": {
                        "action_name": "summarize",
                        "total_success": 8,
                        "total_failed": 1,
                        "total_filtered": 2,
                        "total_skipped": 3,
                        "total_exhausted": 4,
                    },
                },
            ],
        )
        result = extract_run_events(events_path).action_metrics
        m = result["summarize"]
        assert m["exhausted_count"] == 4
        assert m["filtered_count"] == 2
        assert m["skipped_count"] == 3

    def test_cache_miss_events_counted(self, tmp_path):
        """CacheMissEvent increments cache_miss_count per action."""
        events_path = tmp_path / "events.json"
        self._write_events(
            events_path,
            [
                {
                    "event_type": "CacheMissEvent",
                    "meta": {"action_name": "extract"},
                    "data": {"cache_type": "prompt_cache", "key": "k1"},
                },
                {
                    "event_type": "CacheMissEvent",
                    "meta": {"action_name": "extract"},
                    "data": {"cache_type": "prompt_cache", "key": "k2"},
                },
            ],
        )
        result = extract_run_events(events_path).action_metrics
        assert result["extract"]["cache_miss_count"] == 2

    def test_no_llm_events_leaves_defaults(self, tmp_path):
        """Action with no LLM events has zero latency and null provider."""
        events_path = tmp_path / "events.json"
        self._write_events(events_path, [_action_event("tool_action")])
        result = extract_run_events(events_path).action_metrics
        m = result["tool_action"]
        assert m["latency_ms"] == 0.0
        assert m["provider"] is None
        assert m["model"] is None
        assert m["cache_miss_count"] == 0


# ---------------------------------------------------------------------------
# SQLiteBackend.scan_data — prompt trace attachment
# ---------------------------------------------------------------------------


def _create_test_db(db_path: Path, *, with_traces: bool = False) -> None:
    """Create a minimal SQLite DB with source/target data and optionally prompt_trace."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE source_data (source_guid TEXT, relative_path TEXT, data TEXT)")
    conn.execute(
        "CREATE TABLE target_data "
        "(action_name TEXT, relative_path TEXT, data TEXT, record_count INTEGER)"
    )
    # Insert one target record with known source_guid and target_id
    record = json.dumps(
        [{"source_guid": "guid-001", "target_id": "tid-001", "issue_type": "bug", "lineage": []}]
    )
    conn.execute(
        "INSERT INTO target_data VALUES (?, ?, ?, ?)",
        ("classify", "issues.json", record, 1),
    )
    # Insert a source row for count
    conn.execute(
        "INSERT INTO source_data VALUES (?, ?, ?)",
        ("guid-001", "issues.json", "{}"),
    )

    if with_traces:
        conn.execute(
            "CREATE TABLE prompt_trace ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  action_name TEXT NOT NULL,"
            "  record_id TEXT NOT NULL,"
            "  source_guid TEXT,"
            "  run_id TEXT,"
            "  attempt INTEGER NOT NULL DEFAULT 0,"
            "  compiled_prompt TEXT NOT NULL,"
            "  llm_context TEXT,"
            "  response_text TEXT,"
            "  model_name TEXT,"
            "  model_vendor TEXT,"
            "  run_mode TEXT,"
            "  prompt_length INTEGER,"
            "  context_length INTEGER,"
            "  response_length INTEGER,"
            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,"
            "  UNIQUE(action_name, record_id, attempt)"
            ")"
        )
        conn.execute(
            "INSERT INTO prompt_trace "
            "(action_name, record_id, source_guid, attempt, compiled_prompt, response_text, "
            " model_name, model_vendor, run_mode, prompt_length, response_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "classify",
                "tid-001",
                "guid-001",
                0,
                "You are a classifier...",
                '[{"issue_type":"bug"}]',
                "llama3.2:latest",
                "ollama_local",
                "batch",
                200,
                25,
            ),
        )
    conn.commit()
    conn.close()


def _scan_readonly(db_path: Path) -> dict | None:
    """Helper: open a readonly backend, scan, and close."""
    backend = SQLiteBackend.create_readonly(db_path)
    try:
        return backend.scan_data()
    finally:
        backend.close()


class TestScanSqliteReadonlyTraceAttachment:
    """Verify scan_data joins prompt_trace to preview records."""

    def test_trace_attached_when_table_exists(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path, with_traces=True)

        result = _scan_readonly(db_path)
        assert result is not None
        records = result["nodes"]["classify"]["preview"]
        assert len(records) == 1

        trace = records[0].get("_trace")
        assert trace is not None
        assert trace["compiled_prompt"] == "You are a classifier..."
        assert trace["response_text"] == '[{"issue_type":"bug"}]'
        assert trace["model_name"] == "llama3.2:latest"
        assert trace["run_mode"] == "batch"
        assert trace["attempt"] == 0

    def test_no_trace_when_table_missing(self, tmp_path):
        """Old DBs without prompt_trace table should not crash."""
        db_path = tmp_path / "test.db"
        _create_test_db(db_path, with_traces=False)

        result = _scan_readonly(db_path)
        assert result is not None
        records = result["nodes"]["classify"]["preview"]
        assert len(records) == 1
        assert "_trace" not in records[0]

    def test_no_trace_when_record_has_no_identity(self, tmp_path):
        """Records with neither target_id nor parent_target_id get no trace."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE source_data (source_guid TEXT, relative_path TEXT, data TEXT)")
        conn.execute(
            "CREATE TABLE target_data "
            "(action_name TEXT, relative_path TEXT, data TEXT, record_count INTEGER)"
        )
        # Record without source_guid
        record = json.dumps([{"value": "hello"}])
        conn.execute(
            "INSERT INTO target_data VALUES (?, ?, ?, ?)",
            ("act", "f.json", record, 1),
        )
        conn.execute("INSERT INTO source_data VALUES (?, ?, ?)", ("x", "f.json", "{}"))
        conn.execute(
            "CREATE TABLE prompt_trace ("
            "  id INTEGER PRIMARY KEY, action_name TEXT, record_id TEXT,"
            "  source_guid TEXT, run_id TEXT,"
            "  attempt INTEGER DEFAULT 0, compiled_prompt TEXT,"
            "  llm_context TEXT, response_text TEXT, model_name TEXT,"
            "  model_vendor TEXT, run_mode TEXT, prompt_length INTEGER,"
            "  context_length INTEGER, response_length INTEGER,"
            "  created_at TEXT, UNIQUE(action_name, record_id, attempt))"
        )
        conn.commit()
        conn.close()

        result = _scan_readonly(db_path)
        assert result is not None
        records = result["nodes"]["act"]["preview"]
        assert len(records) == 1
        assert "_trace" not in records[0]

    def test_latest_attempt_wins(self, tmp_path):
        """When multiple attempts exist, only the latest is attached."""
        db_path = tmp_path / "test.db"
        _create_test_db(db_path, with_traces=True)

        # Add a second attempt with different response
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO prompt_trace "
            "(action_name, record_id, source_guid, attempt, compiled_prompt, response_text, "
            " model_name, run_mode, prompt_length, response_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "classify",
                "tid-001",
                "guid-001",
                1,
                "You are a classifier (retry)...",
                '[{"issue_type":"feature_request"}]',
                "llama3.2:latest",
                "batch",
                250,
                35,
            ),
        )
        conn.commit()
        conn.close()

        result = _scan_readonly(db_path)
        records = result["nodes"]["classify"]["preview"]
        trace = records[0]["_trace"]
        assert trace["attempt"] == 1
        assert "retry" in trace["compiled_prompt"]


class TestScanSqliteNamespaceUnwrap:
    """Verify scan_data unwraps namespaced content per action."""

    def test_preview_records_show_action_fields(self, tmp_path):
        """Preview records should have unwrapped content for the action."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE source_data (source_guid TEXT, relative_path TEXT, data TEXT)")
        conn.execute(
            "CREATE TABLE target_data "
            "(action_name TEXT, relative_path TEXT, data TEXT, record_count INTEGER)"
        )
        namespaced_record = {
            "source_guid": "g1",
            "content": {
                "extract": {"question": "What?", "answer": "Yes"},
                "classify": {"genre": "fiction"},
            },
        }
        conn.execute(
            "INSERT INTO target_data VALUES (?, ?, ?, ?)",
            ("extract", "data.json", json.dumps([namespaced_record]), 1),
        )
        conn.execute("INSERT INTO source_data VALUES (?, ?, ?)", ("g1", "data.json", "{}"))
        conn.commit()
        conn.close()

        result = _scan_readonly(db_path)
        records = result["nodes"]["extract"]["preview"]
        assert len(records) == 1
        # content should be unwrapped to show extract's fields
        assert records[0]["content"] == {"question": "What?", "answer": "Yes"}
        assert records[0]["source_guid"] == "g1"

    def test_flat_content_records_unchanged(self, tmp_path):
        """Records without namespaced content pass through unchanged."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE source_data (source_guid TEXT, relative_path TEXT, data TEXT)")
        conn.execute(
            "CREATE TABLE target_data "
            "(action_name TEXT, relative_path TEXT, data TEXT, record_count INTEGER)"
        )
        flat_record = {
            "source_guid": "g1",
            "content": {"genre": "fiction", "confidence": 0.9},
        }
        conn.execute(
            "INSERT INTO target_data VALUES (?, ?, ?, ?)",
            ("classify", "data.json", json.dumps([flat_record]), 1),
        )
        conn.execute("INSERT INTO source_data VALUES (?, ?, ?)", ("g1", "data.json", "{}"))
        conn.commit()
        conn.close()

        result = _scan_readonly(db_path)
        records = result["nodes"]["classify"]["preview"]
        assert len(records) == 1
        assert records[0]["content"] == {"genre": "fiction", "confidence": 0.9}


# ---------------------------------------------------------------------------
# extract_run_events — event stream tail
# ---------------------------------------------------------------------------


def _stream_event(seq: int, level: str = "info") -> dict:
    return {
        "event_type": "ActionCompleteEvent",
        "code": "A002",
        "level": level,
        "category": "action",
        "diagnostic": False,
        "message": f"{seq}/12 OK step_{seq} in 1.00s",
        "meta": {
            "timestamp": f"2026-09-22T10:06:{seq % 60:02d}.000Z",
            "invocation_id": "inv1",
            "correlation_id": None,
            "workflow_name": "wf",
        },
        "data": {"action_name": f"step_{seq}", "execution_time": 1.0},
    }


class TestRunEventsStream:
    def test_rows_are_returned_verbatim_in_file_order(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            for i in range(3):
                f.write(json.dumps(_stream_event(i)) + "\n")

        rows = extract_run_events(events_path).events

        assert rows == [{**_stream_event(i), "seq": i} for i in range(3)]

    def test_seq_survives_the_tail_window(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            for i in range(EVENT_TAIL_LIMIT + 5):
                f.write(json.dumps(_stream_event(i)) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows[:3]] == [5, 6, 7]

    def test_tail_is_bounded(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            for i in range(EVENT_TAIL_LIMIT + 40):
                f.write(json.dumps(_stream_event(i)) + "\n")

        rows = extract_run_events(events_path).events

        assert len(rows) == EVENT_TAIL_LIMIT
        assert rows[-1]["data"]["action_name"] == f"step_{EVENT_TAIL_LIMIT + 39}"

    def test_malformed_lines_do_not_consume_a_seq(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps(_stream_event(0)) + "\n")
            f.write("\n")
            f.write(json.dumps(_stream_event(1)) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows] == [0, 1]

    def test_missing_file_returns_no_events(self, tmp_path):
        assert extract_run_events(tmp_path / "nope.json").events == []

    def test_diagnostic_rows_are_kept(self, tmp_path):
        """The explorer hides diagnostics by default; it cannot hide what was dropped."""
        events_path = tmp_path / "events.json"
        diagnostic = _stream_event(0, level="debug")
        diagnostic["diagnostic"] = True
        with open(events_path, "w") as f:
            f.write(json.dumps(diagnostic) + "\n")

        rows = extract_run_events(events_path).events

        assert len(rows) == 1
        assert rows[0]["diagnostic"] is True

    def test_a_row_carrying_its_own_seq_does_not_win(self, tmp_path):
        """Real logs carry keys beyond BaseEvent.to_dict(); one named seq would
        silently repoint every id built from it."""
        events_path = tmp_path / "events.json"
        row = _stream_event(0)
        row["seq"] = 999
        with open(events_path, "w") as f:
            f.write(json.dumps(row) + "\n")
            f.write(json.dumps(_stream_event(1)) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows] == [0, 1]

    def test_a_line_that_is_not_an_object_is_skipped(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write("[1, 2, 3]\n")
            f.write(json.dumps(_stream_event(0)) + "\n")
            f.write('"a string"\n')

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows] == [0]


class TestRunEventsProblemRetention:
    """Warnings and errors are rare and often old. A window that is only the most
    recent N rows is 90% debug and holds none of them, which leaves the page that
    exists to answer "what went wrong" answering nothing."""

    def test_an_old_error_survives_a_flood_of_later_debug(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            error = _stream_event(0, level="error")
            f.write(json.dumps(error) + "\n")
            for i in range(1, EVENT_TAIL_LIMIT + 50):
                f.write(json.dumps(_stream_event(i, level="debug")) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows if r["level"] == "error"] == [0]

    def test_problem_retention_is_bounded(self, tmp_path):
        """Problems older than the recency window come from their own budget, and
        that budget keeps the newest of them."""
        events_path = tmp_path / "events.json"
        older = EVENT_PROBLEM_LIMIT + 30
        with open(events_path, "w") as f:
            for i in range(older):
                f.write(json.dumps(_stream_event(i, level="warn")) + "\n")
            for i in range(older, older + EVENT_TAIL_LIMIT):
                f.write(json.dumps(_stream_event(i, level="debug")) + "\n")

        rows = extract_run_events(events_path).events
        warns = [r["seq"] for r in rows if r["level"] == "warn"]

        assert len(warns) == EVENT_PROBLEM_LIMIT
        assert warns[-1] == older - 1
        assert warns[0] == older - EVENT_PROBLEM_LIMIT

    def test_a_flood_of_warnings_does_not_evict_the_errors(self, tmp_path):
        """Warnings outnumber errors by ~780:1 in a real log. On one shared budget
        the common level sets the boundary and the rare one falls off it."""
        events_path = tmp_path / "events.json"
        errors = list(range(5))
        with open(events_path, "w") as f:
            for i in errors:
                f.write(json.dumps(_stream_event(i, level="error")) + "\n")
            start = len(errors)
            for i in range(start, start + EVENT_PROBLEM_LIMIT + 200):
                f.write(json.dumps(_stream_event(i, level="warn")) + "\n")
            tail_start = start + EVENT_PROBLEM_LIMIT + 200
            for i in range(tail_start, tail_start + EVENT_TAIL_LIMIT):
                f.write(json.dumps(_stream_event(i, level="debug")) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows if r["level"] == "error"] == errors

    def test_each_problem_level_keeps_its_own_budget(self, tmp_path):
        """Neither level may spend the other's share."""
        events_path = tmp_path / "events.json"
        over = EVENT_PROBLEM_LIMIT + 40
        with open(events_path, "w") as f:
            seq = 0
            for _ in range(over):
                f.write(json.dumps(_stream_event(seq, level="error")) + "\n")
                seq += 1
                f.write(json.dumps(_stream_event(seq, level="warn")) + "\n")
                seq += 1
            for i in range(seq, seq + EVENT_TAIL_LIMIT):
                f.write(json.dumps(_stream_event(i, level="debug")) + "\n")

        rows = extract_run_events(events_path).events

        assert len([r for r in rows if r["level"] == "error"]) == EVENT_PROBLEM_LIMIT
        assert len([r for r in rows if r["level"] == "warn"]) == EVENT_PROBLEM_LIMIT

    def test_the_window_is_returned_in_file_order(self, tmp_path):
        """A problem inside the recency window must not jump ahead of older rows:
        the merge reverses each log assuming file order, so a scrambled window
        changes which rows a tight budget admits, not just how they display."""
        events_path = tmp_path / "events.json"
        total = EVENT_TAIL_LIMIT + 10
        old_problem, recent_problem = 3, total - 100
        with open(events_path, "w") as f:
            for i in range(total):
                level = "error" if i in (old_problem, recent_problem) else "debug"
                f.write(json.dumps(_stream_event(i, level=level)) + "\n")

        seqs = [r["seq"] for r in extract_run_events(events_path).events]

        assert seqs == sorted(seqs)
        assert seqs[:3] == [old_problem, total - EVENT_TAIL_LIMIT, total - EVENT_TAIL_LIMIT + 1]
        assert recent_problem in seqs

    def test_rows_are_not_duplicated_when_a_problem_is_also_recent(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_stream_event(0, level="error")) + "\n")
            f.write(json.dumps(_stream_event(1, level="info")) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows] == [0, 1]

    def test_level_totals_cover_the_whole_file_not_the_window(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            for i in range(EVENT_TAIL_LIMIT + 10):
                f.write(json.dumps(_stream_event(i, level="debug")) + "\n")
            f.write(json.dumps(_stream_event(9001, level="error")) + "\n")

        result = extract_run_events(events_path)

        assert result.level_counts["debug"] == EVENT_TAIL_LIMIT + 10
        assert result.level_counts["error"] == 1

    def test_scan_logs_counts_and_retains_the_same_way(self, tmp_path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        with open(logs_dir / "events.json", "w") as f:
            f.write(json.dumps(_stream_event(0, level="error")) + "\n")
            for i in range(1, EVENT_TAIL_LIMIT + 20):
                f.write(json.dumps(_stream_event(i, level="debug")) + "\n")

        logs = scan_logs(tmp_path)

        assert [r["seq"] for r in logs["events"] if r["level"] == "error"] == [0]
        assert logs["level_counts"]["error"] == 1
        assert logs["level_counts"]["debug"] == EVENT_TAIL_LIMIT + 19

    def test_a_read_that_fails_partway_keeps_what_it_read(self, tmp_path):
        """A log truncated mid-write still described every row it did yield, and
        the per-workflow scan keeps its partial window in the same situation."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        with open(events_path, "w") as f:
            for i in range(3):
                f.write(json.dumps(_stream_event(i, level="error")) + "\n")

        real_open = builtins.open
        seen = {"n": 0}

        def failing_open(file, *args, **kwargs):
            if str(file) == str(events_path):
                seen["n"] += 1
                handle = real_open(file, *args, **kwargs)

                class Truncated:
                    def __enter__(self):
                        return self

                    def __exit__(self, *exc):
                        handle.close()
                        return False

                    def __iter__(self):
                        yield next(iter(handle))
                        raise OSError("disk went away")

                return Truncated()
            return real_open(file, *args, **kwargs)

        builtins.open = failing_open
        try:
            logs = scan_logs(tmp_path)
        finally:
            builtins.open = real_open

        assert seen["n"] == 1
        assert [r["seq"] for r in logs["events"]] == [0]
        assert logs["level_counts"] == {"error": 1}

    def test_a_row_with_no_level_is_not_counted_under_one(self, tmp_path):
        """A missing level counted under `None` serialises as the string "null"
        and is then folded into info by the reader, inflating that total."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps({"event_type": "E", "meta": {}, "data": {}}) + "\n")
            f.write(json.dumps(_stream_event(1, level="info")) + "\n")

        counts = extract_run_events(events_path).level_counts

        assert counts == {"info": 1}

    def test_a_row_with_no_timestamp_does_not_abort_the_window(self, tmp_path):
        """A row may carry a meta object with no timestamp in it. The merge sorts
        on that value, and None against str is a TypeError that takes the whole
        catalog build down with it."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(
                json.dumps({"event_type": "E", "level": "error", "meta": {}, "data": {}}) + "\n"
            )
            f.write(json.dumps(_stream_event(1, level="info")) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows] == [0, 1]

    def test_a_row_whose_meta_is_not_an_object_is_skipped(self, tmp_path):
        """Rows are read back from disk; one malformed row must not abort the build."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps({"event_type": "E", "meta": "nope", "data": {}}) + "\n")
            f.write(json.dumps({"event_type": "E", "meta": {}, "data": [1, 2]}) + "\n")
            f.write(json.dumps(_stream_event(0)) + "\n")

        rows = extract_run_events(events_path).events

        assert [r["seq"] for r in rows] == [0]
