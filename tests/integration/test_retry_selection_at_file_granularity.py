"""A repair must not take a record it never named through the context scope.

``ProcessingPipeline.process`` narrows to the repair's selection above
``apply_context_scope_for_records``, which writes a ``skipped`` disposition for
every record it drops. That is one of the pre-gate writers spec 603 enumerates,
and the only one with no test behind it. Reaching it takes a FILE-granularity
``kind: tool`` action — or a HITL one; the pipeline gates on either — whose
``context_scope`` can no longer read an observed field.
"""

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    WORKFLOW,
    _backend,
    _disposition,
    _fail,
    _record_ids,
    project,  # noqa: F401
)

SECOND = "enrich"

# FILE mode hands the UDF the whole file's records and requires the input items
# back — a fresh dict is rejected as an unattributable output.
FILE_TOOL = """from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import Granularity


@udf_tool(granularity=Granularity.FILE)
def tag_all(data: Any, *args) -> list[dict]:
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
    impl: tag_all
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


def _at_file_granularity(project):  # noqa: F811
    """Add a FILE-granularity tool action reading the first action's output."""
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    # Not `tag.py`: tool discovery imports by module name and another test's
    # fixture writes a `tag.py` of its own, so the second one to run is served
    # the first one's module out of `sys.modules` and its UDF is never found.
    (project / "tools" / WORKFLOW / "file_tag.py").write_text(FILE_TOOL)
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return project


def _unobservable(project, record_id):  # noqa: F811
    """Leave *record_id*'s upstream row without the field the scope observes.

    What upstream drift looks like from below: the row is still there and still
    terminal at this action, but ``enrich``'s ``observe: [flatten.summary]`` can
    no longer be resolved against it, so the scope drops it and writes
    ``skipped``. Constructed here because the fixture's tool fills the field for
    every record, so the suite otherwise never sees a scope drop at all.
    """
    backend = _backend(project)
    try:
        rows = backend._read_target_raw(ACTION, "pages.json")
        # Asserted, not assumed: a guid or shape drift would make this loop a silent
        # no-op and every test below would pass while pinning nothing.
        targeted = [r for r in rows if r.get("source_guid") == record_id]
        assert targeted, f"no stored row for {record_id} — the construction did not land"
        for row in targeted:
            del row["content"][ACTION]["summary"]
        backend._write_target_raw(ACTION, "pages.json", rows)
    finally:
        backend.close()


class TestTheContextScopeNeverSeesARecordTheRepairDidNotName:
    def test_an_unnamed_record_keeps_its_disposition(self, project):  # noqa: F811
        """The scope's `skipped` is terminal and is written above the gate, so a
        record it drops loses the result it already had."""
        project = _at_file_granularity(project)
        ids = _record_ids(project, ACTION)
        selected, unnamed = ids[0], ids[-1]
        _unobservable(project, unnamed)
        _fail(project, selected, SECOND)

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert retry.exit_code == 0, retry.output
        assert _disposition(project, unnamed, SECOND) == "success"

    def test_the_named_record_is_still_repaired(self, project):  # noqa: F811
        """The control: keeping the others must not come from the repair doing nothing."""
        project = _at_file_granularity(project)
        ids = _record_ids(project, ACTION)
        selected, unnamed = ids[0], ids[-1]
        _unobservable(project, unnamed)
        _fail(project, selected, SECOND)

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

        assert retry.exit_code == 0, retry.output
        assert _disposition(project, selected, SECOND) == "success"
