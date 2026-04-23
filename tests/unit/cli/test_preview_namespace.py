"""Tests for preview CLI namespace unwrapping (spec 092).

Verifies that _show_table and _unwrap_content correctly display
action-specific fields instead of raw namespace keys.
"""

from agent_actions.cli.preview import PreviewCommand


class TestUnwrapContent:
    """PreviewCommand._unwrap_content extracts action-specific fields."""

    def _cmd(self, action: str = "classify") -> PreviewCommand:
        return PreviewCommand(workflow="test_wf", action=action)

    def test_unwraps_namespaced_content(self):
        record = {
            "source_guid": "g1",
            "content": {
                "classify": {"genre": "fiction", "confidence": 0.9},
                "summarize": {"summary": "A book about..."},
            },
        }
        result = self._cmd("classify")._unwrap_content(record)
        assert result == {"genre": "fiction", "confidence": 0.9}

    def test_returns_flat_content_unchanged(self):
        """Pre-namespace records with flat content dict pass through."""
        record = {
            "source_guid": "g1",
            "content": {"genre": "fiction", "confidence": 0.9},
        }
        result = self._cmd("classify")._unwrap_content(record)
        # "classify" is not a key in content, so return content as-is
        assert result == {"genre": "fiction", "confidence": 0.9}

    def test_falls_back_when_action_not_in_content(self):
        """When the previewed action is not a namespace key, return full content."""
        record = {
            "content": {"other_action": {"field": "value"}},
        }
        result = self._cmd("classify")._unwrap_content(record)
        assert result == {"other_action": {"field": "value"}}

    def test_returns_record_when_no_content_key(self):
        """Records without a content key return the full record."""
        record = {"question": "What?", "answer": "Yes"}
        result = self._cmd("classify")._unwrap_content(record)
        assert result == {"question": "What?", "answer": "Yes"}

    def test_returns_record_when_content_not_dict(self):
        """Non-dict content values return the full record."""
        record = {"content": "plain string", "other": 1}
        result = self._cmd("classify")._unwrap_content(record)
        assert result == {"content": "plain string", "other": 1}

    def test_no_action_returns_full_content(self):
        """When action is None, return full content dict."""
        cmd = PreviewCommand(workflow="test_wf", action=None)
        record = {
            "content": {
                "classify": {"genre": "fiction"},
                "summarize": {"summary": "..."},
            },
        }
        result = cmd._unwrap_content(record)
        assert "classify" in result
        assert "summarize" in result


class TestShowTableNamespaceUnwrap:
    """_show_table uses _unwrap_content for column keys and row values."""

    def test_table_columns_are_field_names_not_action_names(self, capsys):
        """Column headers should be 'genre', 'confidence' — not 'classify', 'summarize'."""
        cmd = PreviewCommand(workflow="test_wf", action="classify")
        records = [
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
        cmd._show_table(records)
        output = capsys.readouterr().out

        # Action-specific field names should appear as column headers
        assert "genre" in output
        assert "confidence" in output

        # Namespace action names should NOT appear as column headers
        assert "classify" not in output
        assert "summarize" not in output

    def test_table_values_from_action_namespace(self, capsys):
        """Row values should come from the action's namespace, not the wrapper."""
        cmd = PreviewCommand(workflow="test_wf", action="extract")
        records = [
            {
                "content": {
                    "extract": {"question": "What is AI?", "answer": "ML subset"},
                },
            },
        ]
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "What is AI?" in output
        assert "ML subset" in output

    def test_table_with_flat_content_still_works(self, capsys):
        """Backward compat: flat content records render correctly."""
        cmd = PreviewCommand(workflow="test_wf", action="classify")
        records = [
            {"content": {"genre": "fiction", "confidence": 0.9}},
        ]
        cmd._show_table(records)
        output = capsys.readouterr().out
        assert "genre" in output
        assert "fiction" in output
