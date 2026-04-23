"""Tests for preview CLI namespace unwrapping (spec 092).

Verifies that _unwrap_records and all display formats correctly show
action-specific fields instead of raw namespace keys.
"""

import json

from agent_actions.cli.preview import PreviewCommand

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
