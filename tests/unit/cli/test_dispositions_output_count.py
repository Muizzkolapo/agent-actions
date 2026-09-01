"""`agac dispositions` shows what an action produced, not only what it consumed.

A disposition is one row per input record per action, so an action that expands
or collapses records has a disposition count that legitimately differs from the
number of records it wrote. Shown alone, the smaller number reads as data loss.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from agent_actions.cli.dispositions import DispositionsCommand
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "test.db"), workflow_name="test_workflow")
    b.initialize()
    return b


def _render(backend, actions: list[str]) -> str:
    cmd = DispositionsCommand("test_workflow", action=None, quarantined=False)
    buf = StringIO()
    cmd.console = Console(file=buf, force_terminal=False, width=200)
    cmd._show_summary(backend, actions)
    return buf.getvalue()


def _row(output: str, action: str) -> dict[str, str]:
    """The rendered row for one action, keyed by its column header."""
    # Rich draws the header row with a heavy bar and the body with a light one.
    header: list[str] | None = None
    for line in output.splitlines():
        sep = "┃" if "┃" in line else "│" if "│" in line else None
        if sep is None:
            continue
        cells = [c.strip() for c in line.split(sep)[1:-1]]
        if header is None:
            header = cells
        elif cells and cells[0] == action:
            return dict(zip(header, cells, strict=True))
    raise AssertionError(f"no row rendered for {action!r} in:\n{output}")


def _output_column(row: dict[str, str]) -> str:
    """The cell holding the stored record count.

    The header is pinned: the reference page's sample output and prose both
    name it, so a rename here silently drifts the docs from the code.
    """
    assert "Records" in row, f"no Records column: {sorted(row)}"
    return row["Records"]


def _seed(backend, action: str, *, inputs: int, outputs: int) -> None:
    for i in range(inputs):
        backend.set_disposition(action, f"{action}-g{i}", "success")
    if outputs:
        backend.write_target(
            action,
            "out.json",
            [{"source_guid": f"{action}-o{i}"} for i in range(outputs)],
            force_full=True,
        )


class TestOutputCountIsShown:
    def test_an_expansion_shows_what_it_produced(self, backend):
        """The live shape: one input fanned out to five records, one row."""
        _seed(backend, "flatten", inputs=1, outputs=5)

        row = _row(_render(backend, ["flatten"]), "flatten")
        assert _output_column(row) == "5", row

    def test_a_collapse_shows_fewer_records_than_inputs(self, backend):
        """The other direction: five inputs consumed, three records written."""
        _seed(backend, "tag_concept", inputs=5, outputs=3)

        row = _row(_render(backend, ["tag_concept"]), "tag_concept")
        assert _output_column(row) == "3", row

    def test_the_counts_are_distinguishable(self, backend):
        """Consumed and produced must be separate cells — showing one twice
        would make an expansion look like it lost records."""
        _seed(backend, "flatten", inputs=1, outputs=5)

        row = _row(_render(backend, ["flatten"]), "flatten")
        assert row["Total"] == "1", row
        assert _output_column(row) == "5", row

    def test_an_action_that_produced_nothing_reads_as_zero(self, backend):
        """Every input failed: no target_data row exists. The column must say
        so rather than blank out or crash."""
        for i in range(3):
            backend.set_disposition("classify", f"g{i}", "failed", reason="LLM error")

        row = _row(_render(backend, ["classify"]), "classify")
        assert _output_column(row) == "0", row
        assert row["Failed"] == "3", row

    def test_the_header_names_the_column(self, backend):
        _seed(backend, "flatten", inputs=1, outputs=5)

        row = _row(_render(backend, ["flatten"]), "flatten")
        _output_column(row)  # raises with the header list if absent

    def test_each_action_gets_its_own_count(self, backend):
        """Rendering one action at a time cannot catch a lookup that returns
        the same number for every row."""
        _seed(backend, "flatten", inputs=1, outputs=5)
        _seed(backend, "tag_concept", inputs=5, outputs=3)

        output = _render(backend, ["flatten", "tag_concept"])
        assert _output_column(_row(output, "flatten")) == "5"
        assert _output_column(_row(output, "tag_concept")) == "3"

    def test_an_unavailable_count_is_not_reported_as_zero(self, backend):
        """A broken lookup rendered as 0 would show an action that fanned one
        record into five as having produced nothing — the exact reading this
        column exists to prevent, and worse than omitting it."""
        _seed(backend, "flatten", inputs=1, outputs=5)

        class Broken:
            def __getattr__(self, name):
                return getattr(backend, name)

            def get_storage_stats(self):
                raise RuntimeError("storage stats unavailable")

        row = _row(_render(Broken(), ["flatten"]), "flatten")
        assert _output_column(row) != "0", (
            f"an unavailable count must not be indistinguishable from zero: {row}"
        )

    def test_the_reader_is_told_why_the_counts_differ(self, backend):
        """The column is only half the fix — a bare second number invites the
        same misreading it was added to stop."""
        _seed(backend, "flatten", inputs=1, outputs=5)

        output = _render(backend, ["flatten"])
        assert "consumed" in output and "stored" in output, output

    def test_the_note_does_not_blame_expansion_alone(self, backend):
        """An action whose output is simply not written yet — a batch in
        flight, an interrupted run — also shows a lower number. Naming
        expansion as the only cause would explain that state wrongly, which is
        worse than not explaining it."""
        for i in range(500):
            backend.set_disposition("classify", f"g{i}", "deferred")

        output = _render(backend, ["classify"])
        assert _output_column(_row(output, "classify")) == "0"
        assert "flight" in output, f"the in-flight case is unexplained:\n{output}"
