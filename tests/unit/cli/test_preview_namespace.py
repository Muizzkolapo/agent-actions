"""Tests for preview CLI namespace unwrapping (specs 092, 142).

Verifies that _unwrap_records and all display formats correctly show
action-specific fields instead of raw namespace keys, including
guard-skipped actions (null namespace).
"""

import json

from agent_actions.cli.preview import PreviewCommand, _is_tombstone

NAMESPACED_RECORDS = [
    {
        "source_guid": "g1",
        "content": {
            "classify": {"genre": "fiction", "confidence": 0.9},
            "summarize": {"summary": "A book"},
        },
    },
    {
        "source_guid": "g2",
        "content": {
            "classify": {"genre": "nonfiction", "confidence": 0.8},
            "summarize": {"summary": "A paper"},
        },
    },
]

GUARD_SKIPPED_RECORDS = [
    {
        "source_guid": "g1",
        "content": {
            "classify": {"genre": "fiction"},
            "review": None,
        },
        "_state": "guard_skipped",
        "metadata": {"reason": "guard_skip", "agent_type": "tombstone"},
    },
    {
        "source_guid": "g2",
        "content": {
            "classify": {"genre": "nonfiction"},
            "review": {"quality": "good"},
        },
        "_state": "processed",
    },
]


class TestIsTombstone:
    """_is_tombstone detects non-content records via _state."""

    def test_guard_skipped_state(self):
        assert _is_tombstone({"_state": "guard_skipped"}) is True

    def test_cascade_skipped_state(self):
        assert _is_tombstone({"_state": "cascade_skipped"}) is True

    def test_failed_state(self):
        assert _is_tombstone({"_state": "failed"}) is True

    def test_exhausted_state(self):
        assert _is_tombstone({"_state": "exhausted"}) is True

    def test_processed_state_is_not_tombstone(self):
        assert _is_tombstone({"_state": "processed"}) is False

    def test_active_state_is_not_tombstone(self):
        assert _is_tombstone({"_state": "active"}) is False

    def test_missing_state_is_not_tombstone(self):
        assert _is_tombstone({"content": {"field": "value"}}) is False


class TestUnwrapRecords:
    """PreviewCommand._unwrap_records replaces namespaced content."""

    def _cmd(self, action: str = "classify") -> PreviewCommand:
        return PreviewCommand(workflow="test_wf", action=action)

    def test_unwraps_namespaced_content(self):
        result = self._cmd("classify")._unwrap_records(NAMESPACED_RECORDS)
        assert result[0]["content"] == {"genre": "fiction", "confidence": 0.9}
        assert result[0]["source_guid"] == "g1"

    def test_leaves_flat_content_unchanged(self):
        records = [{"content": {"genre": "fiction"}, "source_guid": "g1"}]
        result = self._cmd("classify")._unwrap_records(records)
        assert result[0] is records[0]

    def test_no_action_returns_records_unchanged(self):
        cmd = PreviewCommand(workflow="test_wf", action=None)
        result = cmd._unwrap_records(NAMESPACED_RECORDS)
        assert result is NAMESPACED_RECORDS

    def test_does_not_mutate_original(self):
        original_content = {
            "classify": {"genre": "fiction"},
            "summarize": {"summary": "..."},
        }
        records = [{"source_guid": "g1", "content": original_content}]
        result = self._cmd("classify")._unwrap_records(records)
        assert result[0]["content"] == {"genre": "fiction"}
        assert records[0]["content"] is original_content

    def test_non_dict_records_pass_through(self):
        records = ["plain string", 42]
        result = self._cmd("classify")._unwrap_records(records)
        assert result == ["plain string", 42]

    def test_guard_skipped_null_namespace_yields_empty_content(self):
        """Guard-skipped action (content[action]=None) → empty dict."""
        records = [
            {"source_guid": "g1", "content": {"classify": None, "extract": {"x": 1}}},
        ]
        result = self._cmd("classify")._unwrap_records(records)
        assert result[0]["content"] == {}
        assert result[0]["source_guid"] == "g1"

    def test_guard_skipped_does_not_mutate_original(self):
        original_content = {"classify": None, "extract": {"x": 1}}
        records = [{"source_guid": "g1", "content": original_content}]
        self._cmd("classify")._unwrap_records(records)
        assert original_content["classify"] is None

    def test_mixed_skipped_and_normal_records(self):
        """Batch with both skipped and normal records."""
        result = self._cmd("review")._unwrap_records(GUARD_SKIPPED_RECORDS)
        assert result[0]["content"] == {}
        assert result[0]["_state"] == "guard_skipped"
        assert result[1]["content"] == {"quality": "good"}


class TestShowTableNamespaceUnwrap:
    """_show_table displays unwrapped field names and values."""

    def test_table_columns_are_field_names_not_action_names(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="classify")
        records = cmd._unwrap_records(NAMESPACED_RECORDS)
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "genre" in output
        assert "confidence" in output
        assert "classify" not in output
        assert "summarize" not in output

    def test_table_values_from_action_namespace(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="extract")
        records = cmd._unwrap_records(
            [
                {"content": {"extract": {"question": "What is AI?", "answer": "ML subset"}}},
            ]
        )
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "What is AI?" in output
        assert "ML subset" in output

    def test_flat_content_still_works(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="classify")
        records = cmd._unwrap_records(
            [
                {"content": {"genre": "fiction", "confidence": 0.9}},
            ]
        )
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "genre" in output
        assert "fiction" in output


class TestGuardSkippedDisplay:
    """Display methods render guard-skipped records with _state as label."""

    def test_table_shows_state_as_label(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="review")
        records = cmd._unwrap_records(GUARD_SKIPPED_RECORDS)
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "[guard-skipped]" in output
        assert "good" in output  # non-skipped record renders normally

    def test_table_skipped_row_does_not_pollute_columns(self, capsys):
        """Tombstone records should not contribute keys to column headers."""
        cmd = PreviewCommand(workflow="test_wf", action="review")
        records = cmd._unwrap_records(GUARD_SKIPPED_RECORDS)
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "quality" in output  # column from normal record
        assert "_state" not in output
        assert "metadata" not in output

    def test_cascade_skipped_renders_as_tombstone(self, capsys):
        """cascade_skipped state renders with _state as label."""
        records = [
            {"content": {}, "_state": "cascade_skipped"},
            {"content": {"name": "Alice"}, "_state": "processed"},
        ]
        cmd = PreviewCommand(workflow="test_wf", action=None)
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "[cascade-skipped]" in output
        assert "Alice" in output

    def test_json_shows_real_record_structure(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="review")
        records = cmd._unwrap_records(GUARD_SKIPPED_RECORDS)
        cmd._show_json(records)
        output = capsys.readouterr().out
        assert '"guard_skipped"' in output
        assert '"guard_skip"' in output
        assert "quality" in output

    def test_raw_shows_empty_content_with_metadata(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="review")
        records = cmd._unwrap_records(GUARD_SKIPPED_RECORDS)
        cmd._show_raw(records)
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert parsed[0]["content"] == {}
        assert parsed[0]["_state"] == "guard_skipped"
        assert parsed[0]["metadata"]["reason"] == "guard_skip"
        assert parsed[1]["content"] == {"quality": "good"}


class TestJsonRawNamespaceUnwrap:
    """json and raw formats also show unwrapped fields."""

    def test_json_shows_action_fields(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="classify")
        records = cmd._unwrap_records(NAMESPACED_RECORDS)
        cmd._show_json(records)
        output = capsys.readouterr().out
        # Rich Syntax adds line numbers; check content presence
        assert '"genre"' in output
        assert '"fiction"' in output
        assert '"summarize"' not in output

    def test_raw_shows_action_fields(self, capsys):
        cmd = PreviewCommand(workflow="test_wf", action="classify")
        records = cmd._unwrap_records(NAMESPACED_RECORDS)
        cmd._show_raw(records)
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert parsed[0]["content"] == {"genre": "fiction", "confidence": 0.9}
