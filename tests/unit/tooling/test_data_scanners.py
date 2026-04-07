"""Regression tests for I-5: scan_logs() and extract_action_metrics() 100k-line cap.

Also covers scan_sqlite_readonly prompt trace attachment (spec 015).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agent_actions.tooling.docs.scanner.data_scanners import (
    extract_action_metrics,
    extract_runtime_warnings,
    scan_logs,
    scan_sqlite_readonly,
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


class TestScanLogsLineCap:
    def test_scan_logs_returns_data_within_limit(self, tmp_path):
        """scan_logs returns correct data when under the line limit."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        _write_events(events_path, 50)
        result = scan_logs(tmp_path)
        assert isinstance(result["recent_invocations"], list)
        assert len(result["recent_invocations"]) <= 10  # capped at last 10

    def test_scan_logs_emits_warning_at_limit(self, tmp_path, capfd):
        """scan_logs emits a warning when the 100k-line cap is hit."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        # Write 100_001 lines so islice stops at 100_000 and the cap warning fires
        _write_events(events_path, 100_001)
        scan_logs(tmp_path)
        captured = capfd.readouterr()
        assert "line limit" in captured.err, (
            "Expected a 'line limit' warning on stderr when 100k-line cap is reached"
        )

    def test_scan_logs_no_warning_below_limit(self, tmp_path, capfd):
        """scan_logs does NOT emit a line-limit warning for small files."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        _write_events(events_path, 10)
        scan_logs(tmp_path)
        captured = capfd.readouterr()
        assert "line limit" not in captured.err

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
# extract_action_metrics
# ---------------------------------------------------------------------------


class TestExtractActionMetricsLineCap:
    def test_returns_metrics_for_known_events(self, tmp_path):
        """extract_action_metrics parses ActionCompleteEvent correctly."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_action_event("my_action")) + "\n")
        result = extract_action_metrics(events_path)
        assert "my_action" in result
        assert result["my_action"]["execution_time"] == 1.0

    def test_emits_warning_at_limit(self, tmp_path, capfd):
        """extract_action_metrics emits a warning when the 100k-line cap is hit."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            for i in range(100_001):
                f.write(json.dumps(_action_event(f"action_{i}")) + "\n")
        extract_action_metrics(events_path)
        captured = capfd.readouterr()
        assert "line limit" in captured.err

    def test_no_warning_below_limit(self, tmp_path, capfd):
        """extract_action_metrics does NOT warn for small files."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_action_event("act")) + "\n")
        extract_action_metrics(events_path)
        captured = capfd.readouterr()
        assert "line limit" not in captured.err


# ---------------------------------------------------------------------------
# extract_runtime_warnings
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


class TestExtractRuntimeWarnings:
    def test_captures_warn_level(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("my_action", "All records filtered")) + "\n")

        result = extract_runtime_warnings(events_path)

        assert len(result) == 1
        assert result[0]["level"] == "warn"
        assert result[0]["message"] == "All records filtered"
        assert result[0]["action_name"] == "my_action"

    def test_captures_error_level(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("act", "Something broke", level="error")) + "\n")

        result = extract_runtime_warnings(events_path)

        assert len(result) == 1
        assert result[0]["level"] == "error"

    def test_ignores_info_and_debug(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("a", "info msg", level="info")) + "\n")
            f.write(json.dumps(_warn_event("b", "debug msg", level="debug")) + "\n")

        result = extract_runtime_warnings(events_path)

        assert result == []

    def test_mixed_levels(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_warn_event("a", "ok", level="info")) + "\n")
            f.write(json.dumps(_warn_event("b", "bad", level="warn")) + "\n")
            f.write(json.dumps(_warn_event("c", "worse", level="error")) + "\n")
            f.write(json.dumps(_action_event("d")) + "\n")  # not a warn/error

        result = extract_runtime_warnings(events_path)

        assert len(result) == 2
        assert result[0]["action_name"] == "b"
        assert result[1]["action_name"] == "c"

    def test_missing_file_returns_empty(self, tmp_path):
        result = extract_runtime_warnings(tmp_path / "nonexistent.json")
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path):
        events_path = tmp_path / "events.json"
        events_path.write_text("")
        result = extract_runtime_warnings(events_path)
        assert result == []

    def test_malformed_json_lines_skipped(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps(_warn_event("a", "real warning")) + "\n")
            f.write("{truncated\n")

        result = extract_runtime_warnings(events_path)

        assert len(result) == 1
        assert result[0]["action_name"] == "a"

    def test_blank_lines_skipped(self, tmp_path):
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write("\n")
            f.write("  \n")
            f.write(json.dumps(_warn_event("a", "found it")) + "\n")

        result = extract_runtime_warnings(events_path)

        assert len(result) == 1

    def test_emits_warning_at_line_limit(self, tmp_path, capfd):
        """Logs a warning when the 100k line cap is reached."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            for i in range(100_001):
                f.write(json.dumps(_warn_event(f"a_{i}", f"warn {i}")) + "\n")

        extract_runtime_warnings(events_path)
        captured = capfd.readouterr()
        assert "line limit" in captured.err


class TestExtractActionMetricsEnrichment:
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
        result = extract_action_metrics(events_path)
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
        result = extract_action_metrics(events_path)
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
        result = extract_action_metrics(events_path)
        assert result["extract"]["cache_miss_count"] == 2

    def test_no_llm_events_leaves_defaults(self, tmp_path):
        """Action with no LLM events has zero latency and null provider."""
        events_path = tmp_path / "events.json"
        self._write_events(events_path, [_action_event("tool_action")])
        result = extract_action_metrics(events_path)
        m = result["tool_action"]
        assert m["latency_ms"] == 0.0
        assert m["provider"] is None
        assert m["model"] is None
        assert m["cache_miss_count"] == 0


# ---------------------------------------------------------------------------
# scan_sqlite_readonly — prompt trace attachment
# ---------------------------------------------------------------------------


def _create_test_db(db_path: Path, *, with_traces: bool = False) -> None:
    """Create a minimal SQLite DB with source/target data and optionally prompt_trace."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE source_data (source_guid TEXT, relative_path TEXT, data TEXT)")
    conn.execute(
        "CREATE TABLE target_data "
        "(action_name TEXT, relative_path TEXT, data TEXT, record_count INTEGER)"
    )
    # Insert one target record with a known source_guid
    record = json.dumps([{"source_guid": "guid-001", "issue_type": "bug", "lineage": []}])
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
            "(action_name, record_id, attempt, compiled_prompt, response_text, "
            " model_name, model_vendor, run_mode, prompt_length, response_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "classify",
                "guid-001",
                0,
                "You are a classifier...",
                '[{"issue_type":"bug"}]',
                "llama3.2:latest",
                "ollama",
                "batch",
                200,
                25,
            ),
        )
    conn.commit()
    conn.close()


class TestScanSqliteReadonlyTraceAttachment:
    """Verify scan_sqlite_readonly joins prompt_trace to preview records."""

    def test_trace_attached_when_table_exists(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path, with_traces=True)

        result = scan_sqlite_readonly(db_path, "test_workflow")
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

        result = scan_sqlite_readonly(db_path, "test_workflow")
        assert result is not None
        records = result["nodes"]["classify"]["preview"]
        assert len(records) == 1
        assert "_trace" not in records[0]

    def test_no_trace_when_no_matching_guid(self, tmp_path):
        """Records without source_guid should not get traces."""
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
            "  attempt INTEGER DEFAULT 0, compiled_prompt TEXT,"
            "  llm_context TEXT, response_text TEXT, model_name TEXT,"
            "  model_vendor TEXT, run_mode TEXT, prompt_length INTEGER,"
            "  context_length INTEGER, response_length INTEGER,"
            "  created_at TEXT, UNIQUE(action_name, record_id, attempt))"
        )
        conn.commit()
        conn.close()

        result = scan_sqlite_readonly(db_path, "test_wf")
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
            "(action_name, record_id, attempt, compiled_prompt, response_text, "
            " model_name, run_mode, prompt_length, response_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "classify",
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

        result = scan_sqlite_readonly(db_path, "test_workflow")
        records = result["nodes"]["classify"]["preview"]
        trace = records[0]["_trace"]
        assert trace["attempt"] == 1
        assert "retry" in trace["compiled_prompt"]
