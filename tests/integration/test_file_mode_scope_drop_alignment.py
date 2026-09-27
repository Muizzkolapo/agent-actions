"""A record the context scope drops must not take the whole file down.

FILE mode hands ``prefilter_by_guard`` the scoped records and their pre-observe
originals, which must line up position for position. The scope drops any record
whose observed field it cannot resolve and the pipeline passed the list from
*before* those drops, so one unresolvable record failed the action outright.

Two dependencies is the easy way there — some records then carry both namespaces
and some only one — but one dependency and one incomplete record is enough.
"""

from copy import deepcopy
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.processing.unified import UnifiedProcessor
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    WORKFLOW,
    _backend,
    _disposition,
    _record_ids,
    _stored_records,
    project,  # noqa: F401
)

SECOND = "enrich"

# FILE mode hands the UDF the whole file's records and requires the input items
# back — a fresh dict is rejected as an unattributable output.
FILE_TOOL = """from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import Granularity


@udf_tool(granularity=Granularity.FILE)
def tag_every_record(data: Any, *args) -> list[dict]:
    for record in data or []:
        record["exam_density"] = "high"
        record["summary"] = str(record.get("summary") or "tagged")
    return data
"""

SECOND_ACTION = """  - name: enrich
    kind: tool
    granularity: File
    dependencies: [flatten]
    intent: "Tag"
    schema: tool_action_output
    impl: tag_every_record
    context_scope: {scope}
    expect: { repair: none }
""".replace("{scope}", "%s")

OBSERVE_ONLY = "{ observe: [flatten.summary] }"
OBSERVE_AND_DROP = "{ observe: [flatten.summary], drop: [flatten.exam_density] }"


def _declare_file_action(project, scope=OBSERVE_ONLY):  # noqa: F811
    """Append the FILE-granularity action without running it yet.

    Not run here: the fixture's tool fills the observed field for every record, so
    a run before the upstream is edited would leave nothing for the scope to drop.
    """
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + (SECOND_ACTION % scope))
    # Not `tag.py` or `file_tag.py`: tool discovery imports by module name and two
    # other fixtures already claim those, so the second module to load is served
    # the first one out of sys.modules and its UDF is never found.
    (project / "tools" / WORKFLOW / "aligned_tag.py").write_text(FILE_TOOL)
    return project


def _unobservable(project, record_id):  # noqa: F811
    """Leave *record_id*'s upstream row without the field the scope observes.

    What upstream drift looks like from below: the row is still stored and still
    terminal at its own action, but ``enrich``'s ``observe: [flatten.summary]``
    can no longer resolve against it, so the scope drops it.
    """
    backend = _backend(project)
    try:
        rows = backend._read_target_raw(ACTION, "pages.json")
        # Asserted, not assumed: a guid or shape drift would make this a silent
        # no-op and every test below would pass while pinning nothing.
        targeted = [r for r in rows if r.get("source_guid") == record_id]
        assert targeted, f"no stored row for {record_id} — the construction did not land"
        for row in targeted:
            del row["content"][ACTION]["summary"]
        backend._write_target_raw(ACTION, "pages.json", rows)
    finally:
        backend.close()


def _skip_reason(project, record_id, action):  # noqa: F811
    backend = _backend(project)
    try:
        rows = [r for r in backend.get_disposition(action) if r.get("record_id") == record_id]
        return rows[0]["reason"] if rows else None
    finally:
        backend.close()


@pytest.fixture
def one_unobservable(project):  # noqa: F811
    """Six upstream records, one of which the scope can no longer resolve."""
    _declare_file_action(project)
    dropped = _record_ids(project)[-1]
    _unobservable(project, dropped)
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])
    return project, dropped, result


class TestOneDroppedRecordDoesNotFailTheFile:
    def test_the_action_runs(self, one_unobservable):
        _project, _dropped, result = one_unobservable

        assert result.exit_code == 0, result.output

    def test_the_length_mismatch_is_not_reported(self, one_unobservable):
        """Named because the mismatch is the symptom the issue reported, and a
        run can exit non-zero for unrelated reasons."""
        _project, _dropped, result = one_unobservable

        assert "length mismatch" not in result.output

    def test_every_resolvable_record_is_processed(self, one_unobservable):
        """The point of the fix: the other five records are not collateral."""
        project, _dropped, _result = one_unobservable  # noqa: F811

        assert _stored_records(project, SECOND) == RECORDS - 1

    def test_the_unresolvable_record_alone_is_left_out(self, one_unobservable):
        """The reason, not just "not success": no disposition row at all would also
        satisfy a negative assertion, and that is a different outcome."""
        project, dropped, _result = one_unobservable  # noqa: F811

        assert _disposition(project, dropped, SECOND) == "skipped"
        assert _skip_reason(project, dropped, SECOND) == "observe_field_missing"

    def test_the_others_succeed(self, one_unobservable):
        """A count alone would pass if five records landed with a failed
        disposition, which is not the file completing."""
        project, dropped, _result = one_unobservable  # noqa: F811
        others = [r for r in _record_ids(project) if r != dropped]

        assert [_disposition(project, r, SECOND) for r in others] == ["success"] * (RECORDS - 1)


class TestTheControlRunWithNothingDropped:
    """So the tests above cannot pass by the action never having worked."""

    def test_all_six_records_are_processed(self, project):  # noqa: F811
        _declare_file_action(project)

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert _stored_records(project, SECOND) == RECORDS


class TestASkippedRecordNamesItsInputPosition:
    """What the pipeline pairs the two lists by. Positions index the input, so they
    stay usable against it however many records before them were dropped."""

    @staticmethod
    def _pass(records):
        from agent_actions.prompt.context.scope_application import (
            apply_context_scope_for_records,
        )

        return apply_context_scope_for_records(
            records, {"observe": ["d.x"]}, action_name="a2", source_data=None
        )

    def test_positions_index_the_input_not_the_skipped_list(self):
        """First and third dropped: 0 and 2. Numbering the skips instead gives 0 and 1
        and takes the wrong records out of the caller's second list."""
        records = [
            {"source_guid": "drop-a", "content": {"d": {}}},
            {"source_guid": "keep", "content": {"d": {"x": 1}}},
            {"source_guid": "drop-b", "content": {"d": {}}},
        ]

        _enriched, skipped = self._pass(records)

        assert [s["position"] for s in skipped] == [0, 2]

    def test_the_positions_left_over_are_the_records_that_survived(self):
        """The scope's own contract: the positions it did not report are exactly the
        records it returned. This reproduces the slice rather than observing the
        pipeline take it, so it pins the contract and not the caller — the pipeline's
        use of it is covered by the boundary tests below.
        """
        records = [
            {"source_guid": "drop-a", "content": {"d": {}}},
            {"source_guid": "keep", "content": {"d": {"x": 1}}},
            {"source_guid": "drop-b", "content": {"d": {}}},
        ]

        enriched, skipped = self._pass(records)
        dropped = {s["position"] for s in skipped}
        survivors = [r for at, r in enumerate(records) if at not in dropped]

        assert [r["source_guid"] for r in survivors] == [r["source_guid"] for r in enriched]

    def test_a_record_carrying_no_source_guid_still_names_its_position(self):
        """A record need not carry a guid, so a guid is not always an identity a
        caller can pair on. A position always is."""
        records = [{"content": {"d": {}}}, {"content": {"d": {"x": 1}}}]

        enriched, skipped = self._pass(records)

        assert [s["position"] for s in skipped] == [0]
        assert [s["source_guid"] for s in skipped] == [None]
        assert len(enriched) == 1

    def test_a_repeated_source_guid_is_still_separated_by_position(self):
        """Why the pairing is positional: a concatenated multi-dependency input can
        carry one guid three times, and the surviving-guid set is then ``{"same"}``
        either way — it cannot say which copy was dropped. The position can, and the
        middle copy is the one that has to go.
        """
        records = [
            {"source_guid": "same", "content": {"d": {"x": 1}}},
            {"source_guid": "same", "content": {"d": {}}},
            {"source_guid": "same", "content": {"d": {"x": 3}}},
        ]

        enriched, skipped = self._pass(records)

        assert {s["position"] for s in skipped} == {1}
        assert [r["content"]["d"] for r in enriched] == [{"x": 1}, {"x": 3}]

    def test_a_pass_that_drops_nothing_reports_no_positions(self):
        _enriched, skipped = self._pass([{"source_guid": "keep", "content": {"d": {"x": 1}}}])

        assert skipped == []


class TestTheListHandedToTheGuardIsThePreObserveOne:
    """Equal length is not the contract — ``original_data`` exists to carry the
    records as they were *before* the scope touched them, so the guard can restore
    what it removed. Handing over the scoped list instead makes the two lists the
    same length and the parameter pointless, and no length assertion can tell the
    difference. A dropped field can: the scope removes it from the records it
    returns and cannot remove it from the originals.
    """

    @staticmethod
    def _captured(project, at=-1):  # noqa: F811
        """*at* is which input record the scope can no longer resolve.

        Parametrized rather than always the last one: at the end, dropping the
        record and truncating the pre-observe list to the surviving length give the
        same answer, so a terminal drop cannot tell a position slice from a
        truncation. A drop in the middle pairs every record after it with the
        previous record's original.
        """
        _declare_file_action(project, scope=OBSERVE_AND_DROP)
        _unobservable(project, _record_ids(project)[at])
        seen: dict[str, list[dict]] = {}
        through = UnifiedProcessor.process

        def _capture(self, records, context, strategy, **kwargs):
            if kwargs.get("raw_records") is not None:
                seen["records"] = deepcopy(records)
                seen["raw"] = deepcopy(kwargs["raw_records"])
            return through(self, records, context, strategy, **kwargs)

        with patch.object(UnifiedProcessor, "process", _capture):
            result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])
        assert result.exit_code == 0, result.output
        assert seen, "the FILE-mode branch was never reached — nothing was captured"
        return seen

    def test_the_scoped_records_have_the_drop_applied(self, project):  # noqa: F811
        """The premise of the test below: the two lists really do differ here."""
        seen = self._captured(project)

        assert all("exam_density" not in r["content"][ACTION] for r in seen["records"])

    def test_the_pre_observe_records_still_carry_the_dropped_field(self, project):  # noqa: F811
        seen = self._captured(project)

        assert all("exam_density" in r["content"][ACTION] for r in seen["raw"])

    @pytest.mark.parametrize("at", [0, 2, -1])
    def test_both_lists_hold_the_same_records_in_the_same_order(self, project, at):  # noqa: F811
        """Asserted on the guids the pipeline actually paired, wherever the drop
        falls — a middle drop is the whole difference between taking the surviving
        positions and taking the first N."""
        seen = self._captured(project, at)

        assert [r["source_guid"] for r in seen["raw"]] == [
            r["source_guid"] for r in seen["records"]
        ]
        assert len(seen["raw"]) == RECORDS - 1

    @pytest.mark.parametrize("at", [0, 2, -1])
    def test_the_dropped_record_is_in_neither_list(self, project, at):  # noqa: F811
        """Equal, matching lists that both still hold the unresolvable record would
        satisfy the assertion above."""
        dropped_id = _record_ids(project)[at]
        seen = self._captured(project, at)

        assert dropped_id not in [r["source_guid"] for r in seen["raw"]]
        assert dropped_id not in [r["source_guid"] for r in seen["records"]]
