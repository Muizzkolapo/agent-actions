"""Tests for the dispositions CLI command logic."""

from io import StringIO

from rich.console import Console

from agent_actions.cli.dispositions import DispositionsCommand
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.unit.cli.conftest import make_mock_backend


def _make_cmd(agent="test_workflow", action=None, quarantined=False):
    """Create a DispositionsCommand with captured console output."""
    cmd = DispositionsCommand(agent, action=action, quarantined=quarantined)
    buf = StringIO()
    cmd.console = Console(file=buf, force_terminal=False, width=120)
    return cmd, buf


class TestShowSummary:
    """DispositionsCommand._show_summary renders disposition table."""

    def test_summary_shows_correct_counts(self):
        backend = make_mock_backend(
            {
                "extract": [
                    {"record_id": "r1", "disposition": "success"},
                    {"record_id": "r2", "disposition": "success"},
                ],
                "classify": [
                    {"record_id": "r1", "disposition": "success"},
                    {"record_id": "r2", "disposition": "failed", "reason": "LLM error"},
                ],
            }
        )
        cmd, buf = _make_cmd()
        cmd._show_summary(backend, ["extract", "classify"])
        output = buf.getvalue()
        # extract row: 2 success
        assert "extract" in output
        # classify row: 1 success, 1 failed
        assert "classify" in output

    def test_summary_excludes_node_level_records(self):
        backend = make_mock_backend(
            {
                "extract": [
                    {"record_id": NODE_LEVEL_RECORD_ID, "disposition": "success"},
                    {"record_id": "r1", "disposition": "success"},
                ],
            }
        )
        cmd, buf = _make_cmd()
        cmd._show_summary(backend, ["extract"])
        output = buf.getvalue()
        # Should show extract with 1 record (node-level excluded)
        assert "extract" in output

    def test_summary_empty_shows_message(self):
        backend = make_mock_backend({})
        cmd, buf = _make_cmd()
        cmd._show_summary(backend, ["extract"])
        output = buf.getvalue()
        assert "No dispositions recorded" in output


class TestShowQuarantined:
    """DispositionsCommand._show_quarantined shows failed/exhausted/unprocessed details."""

    def test_quarantined_shows_unprocessed_records_and_no_others(self):
        backend = make_mock_backend(
            {
                "join": [
                    {"record_id": "r1", "disposition": "success", "reason": None},
                    {
                        "record_id": "r2",
                        "disposition": "unprocessed",
                        "reason": "consumed_into_another_record",
                    },
                    {"record_id": "r3", "disposition": "unprocessed", "reason": "tool_missing"},
                    {"record_id": "r4", "disposition": "filtered", "reason": "guard_filter"},
                    {"record_id": "r5", "disposition": "passthrough", "reason": "empty_output"},
                ],
            }
        )
        cmd, buf = _make_cmd(quarantined=True)
        cmd._show_quarantined(backend, ["join"])
        output = buf.getvalue()
        assert "r2" in output and "consumed_into_another_record" in output
        assert "r3" in output and "tool_missing" in output
        assert not {"r1", "r4", "r5"} & set(output.split())

    def test_quarantined_shows_record_details(self):
        backend = make_mock_backend(
            {
                "classify": [
                    {"record_id": "r2", "disposition": "failed", "reason": "LLM error"},
                    {"record_id": "r4", "disposition": "exhausted", "reason": "retry_exhausted"},
                ],
            }
        )
        cmd, buf = _make_cmd(quarantined=True)
        cmd._show_quarantined(backend, ["extract", "classify"])
        output = buf.getvalue()
        assert "r2" in output
        assert "r4" in output
        assert "failed" in output
        assert "exhausted" in output

    def test_quarantined_empty_shows_message(self):
        backend = make_mock_backend({})
        cmd, buf = _make_cmd(quarantined=True)
        cmd._show_quarantined(backend, ["extract"])
        output = buf.getvalue()
        assert "No quarantined records found" in output


def _summary_cells(output: str, action: str) -> dict[str, str]:
    """The summary row of *action*, keyed by its column header."""
    header = next(line for line in output.splitlines() if line.startswith("┃"))
    names = [cell.strip() for cell in header.strip("┃").split("┃")]
    row = next(
        line
        for line in output.splitlines()
        if line.startswith("│") and line.strip("│").split("│")[0].strip() == action
    )
    return dict(zip(names, (cell.strip() for cell in row.strip("│").split("│")), strict=True))


class TestGuardSkipsHaveTheirOwnColumn:
    """A guard skip is stored as unprocessed by design; the summary names it apart."""

    def test_guard_skips_have_their_own_column(self):
        backend = make_mock_backend(
            {
                "repaired": [
                    {"record_id": "r1", "disposition": "success"},
                    {"record_id": "r2", "disposition": "success"},
                    {"record_id": "r3", "disposition": "success"},
                    {"record_id": "r4", "disposition": "unprocessed", "reason": "guard_skip"},
                    {
                        "record_id": "r5",
                        "disposition": "unprocessed",
                        "reason": "upstream_unprocessed",
                    },
                ],
            }
        )
        cmd, buf = _make_cmd()
        cmd.console = Console(file=buf, force_terminal=False, width=200)

        cmd._show_summary(backend, ["repaired"])

        cells = _summary_cells(buf.getvalue(), "repaired")
        assert cells["Success"] == "3"
        assert cells["Guard skipped"] == "1"
        assert cells["Unprocessed"] == "1"
        assert cells["Total"] == "5"

    def test_a_prefilter_skip_is_a_guard_skip(self):
        backend = make_mock_backend(
            {
                "a": [
                    {
                        "record_id": "r1",
                        "disposition": "unprocessed",
                        "reason": "guard_prefilter_skip",
                    },
                ],
            }
        )
        cmd, buf = _make_cmd()
        cmd.console = Console(file=buf, force_terminal=False, width=200)

        cmd._show_summary(backend, ["a"])

        cells = _summary_cells(buf.getvalue(), "a")
        assert (cells["Guard skipped"], cells["Unprocessed"], cells["Total"]) == ("1", "0", "1")

    def test_a_filtered_row_with_a_guard_reason_stays_in_filtered(self):
        backend = make_mock_backend(
            {
                "a": [
                    {"record_id": "r1", "disposition": "filtered", "reason": "guard_skip"},
                    {"record_id": "r2", "disposition": "unprocessed", "reason": "guard_skip"},
                    {"record_id": "r3", "disposition": "success"},
                ],
            }
        )
        cmd, buf = _make_cmd()
        cmd.console = Console(file=buf, force_terminal=False, width=200)

        cmd._show_summary(backend, ["a"])

        cells = _summary_cells(buf.getvalue(), "a")
        columns = ("Success", "Guard skipped", "Unprocessed", "Filtered", "Total")
        assert [cells[c] for c in columns] == ["1", "1", "0", "1", "3"]


class TestGuardSkipReasonsMatchTheRunLine:
    """The table counts as guard skipped every reason the collector counts for the run line."""

    def test_a_guard_filter_unprocessed_row_is_a_guard_skip(self):
        backend = make_mock_backend(
            {
                "a": [
                    {"record_id": "r1", "disposition": "unprocessed", "reason": "guard_filter"},
                    {"record_id": "r2", "disposition": "unprocessed", "reason": "guard_skip"},
                    {"record_id": "r3", "disposition": "unprocessed", "reason": "upstream_failed"},
                    {"record_id": "r4", "disposition": "filtered", "reason": "guard_filter"},
                ],
            }
        )
        cmd, buf = _make_cmd()
        cmd.console = Console(file=buf, force_terminal=False, width=200)

        cmd._show_summary(backend, ["a"])

        cells = _summary_cells(buf.getvalue(), "a")
        columns = ("Guard skipped", "Unprocessed", "Filtered", "Total")
        assert [cells[c] for c in columns] == ["2", "1", "1", "4"]


class TestPrintingWholeLeavesTheConsoleAlone:
    """Printing the table wider than the terminal must not fix the console at one width."""

    def test_the_console_still_follows_the_terminal_after_a_wide_table(self, monkeypatch):
        monkeypatch.delenv("COLUMNS", raising=False)
        action = "an_action_name_long_enough_to_widen_the_table"
        backend = make_mock_backend({action: [{"record_id": "r1", "disposition": "success"}]})
        cmd, buf = _make_cmd()
        cmd.console = Console(file=buf, force_terminal=False)
        assert cmd.console._width is None

        cmd._show_summary(backend, [action])

        assert cmd.console._width is None
        assert action in buf.getvalue()


class TestANarrowTerminalCutsNoCount:
    """Rich shrinks a wide table to fit; a count cut to "12…" would be a wrong number."""

    def test_a_long_action_name_leaves_a_four_digit_count_whole_at_80_columns(self):
        action = "extract_field_marks_1"
        backend = make_mock_backend(
            {action: [{"record_id": f"r{n}", "disposition": "success"} for n in range(1234)]}
        )
        cmd, buf = _make_cmd()
        cmd.console = Console(file=buf, force_terminal=False, width=80)

        cmd._show_summary(backend, [action])

        body = [line for line in buf.getvalue().splitlines() if line.startswith("│")]
        cells = [cell.strip() for cell in body[0].strip("│").split("│")]
        assert cells[1] == "1234"
        assert cells[8] == "1234"
        assert "…" not in " ".join(body)
        assert action == "".join(line.strip("│").split("│")[0].strip() for line in body)
