"""A retry naming a row an expansion made, with another expansion below it.

An expansion keeps the staged record its input came from as ``parent_source_guid``,
so the rows of a second expansion name that record, which is no input of theirs. The
gate handing untouched rows back to the rewrite could not trace them to the row the
retry named, kept them, and the rerun wrote two new rows beside the two kept: the
output grew by two on every retry, exit 0, with only a warning. Each such row lists
the input that made it in ``producer_source_guids``, which is how it is placed now.

Driven through the `agac` CLI, since every caller narrows the input before the gate
sees it.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    WORKFLOW,
    _fail,
    _record_ids,
    project,  # noqa: F401
)
from tests.integration.test_retry_of_an_expanding_action import (
    _rows,
    diamond,  # noqa: F401
    expanding,  # noqa: F401
)

# Not `split.py` or `split_again.py`: tool discovery imports by module name, so two
# fixtures writing one basename serve the second the first one's module.
SPLIT2_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def split_once_more(data: Any, *args) -> list[dict]:
    summary = str((data or {}).get("summary", ""))
    return [{"summary": f"{summary} ~{half}", "exam_density": "high"} for half in (1, 2)]
"""

SPLIT2_ACTION = """  - name: split2
    kind: tool
    dependencies: [split]
    intent: "Split again"
    schema: tool_action_output
    impl: split_once_more
    context_scope: { observe: [split.summary] }
    expect: { repair: none }
"""

WARNING = "cannot be attributed"


@pytest.fixture
def two_mints(expanding):  # noqa: F811
    """flatten → split → split2: six records, twelve rows of split, 24 of split2."""
    config = expanding / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SPLIT2_ACTION)
    (expanding / "tools" / WORKFLOW / "split_once_more.py").write_text(SPLIT2_TOOL)
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    assert len(_rows(expanding, "split2")) == RECORDS * 4
    return expanding


def _made_by(rows: list[dict], guid: str) -> set[str]:
    return {r["source_guid"] for r in rows if r.get("producer_source_guids") == [guid]}


def _retry(project, *args: str):  # noqa: F811
    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, *args])
    assert result.exit_code == 0, result.output
    return result


def test_the_premise_a_row_of_the_second_mint_names_no_input_of_its_action_as_parent(two_mints):
    """Without this the rest could pass against a gate that reads the parent field."""
    split_ids = {r["source_guid"] for r in _rows(two_mints, "split")}
    rows = _rows(two_mints, "split2")
    assert not {r.get("parent_source_guid") for r in rows} & split_ids
    assert all(len(r.get("producer_source_guids") or ()) == 1 for r in rows)


@pytest.mark.parametrize("failed_at", ["split", "split2"])
class TestRetryingARowOfTheFirstMint:
    def test_its_rows_below_are_replaced_and_nothing_grows(self, two_mints, failed_at):
        selected = _rows(two_mints, "split")[0]["source_guid"]
        before = _rows(two_mints, "split2")
        stale = _made_by(before, selected)
        others = {r["source_guid"] for r in before} - stale
        assert len(stale) == 2
        _fail(two_mints, selected, failed_at)

        result = _retry(two_mints, "--record", selected)

        after = _rows(two_mints, "split2")
        assert len(after) == RECORDS * 4
        assert stale.isdisjoint(r["source_guid"] for r in after), "a replaced row was kept"
        assert len(_made_by(after, selected)) == 2
        assert others <= {r["source_guid"] for r in after}, "an untouched row was lost"
        assert WARNING not in result.output

    def test_a_second_retry_does_not_grow_it_either(self, two_mints, failed_at):
        selected = _rows(two_mints, "split")[0]["source_guid"]
        for _ in range(2):
            _fail(two_mints, selected, failed_at)
            _retry(two_mints, "--record", selected)

        assert len(_rows(two_mints, "split2")) == RECORDS * 4

    def test_a_plain_run_afterwards_changes_nothing(self, two_mints, failed_at):
        selected = _rows(two_mints, "split")[0]["source_guid"]
        _fail(two_mints, selected, failed_at)
        _retry(two_mints, "--record", selected)
        settled = sorted(r["source_guid"] for r in _rows(two_mints, "split2"))

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert sorted(r["source_guid"] for r in _rows(two_mints, "split2")) == settled


PUBLISH_ACTION = """  - name: publish
    dependencies: [split2]
    intent: "Publish"
    run_mode: batch
    model_vendor: agac-provider
    schema: tool_action_output
    prompt: $tool_action.Restate
    context_scope: { observe: [split2.summary] }
    expect: { repair: none }
"""

PUBLISH_PROMPT = """{prompt Restate}
Restate this summary verbatim.
## SUMMARY
{{ split2.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""


@pytest.fixture
def batch_below(two_mints, monkeypatch):
    """A batch LLM action reading split2, one row per row of split2."""
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    config = two_mints / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + PUBLISH_ACTION)
    (two_mints / "prompt_store" / f"{WORKFLOW}.md").write_text(PUBLISH_PROMPT)
    for _ in range(3):
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])
        assert result.exit_code == 0, result.output
        if len(_rows(two_mints, "publish")) == RECORDS * 4:
            break
    assert len(_rows(two_mints, "publish")) == RECORDS * 4
    return two_mints


def test_a_batch_action_below_answers_the_replaced_rows_once(batch_below):
    selected = _rows(batch_below, "split")[0]["source_guid"]
    _fail(batch_below, selected, "split")

    for _ in range(3):
        _retry(batch_below, "--record", selected)
        if len(_rows(batch_below, "publish")) >= RECORDS * 4:
            break
    split2 = {r["source_guid"] for r in _rows(batch_below, "split2")}
    published = _rows(batch_below, "publish")

    assert len(split2) == RECORDS * 4
    assert len(published) == RECORDS * 4
    assert {r["source_guid"] for r in published} == split2


def test_a_retry_of_every_failure_replaces_the_rows_too(two_mints):
    """`agac retry` without --record names the failed row the same way."""
    selected = _rows(two_mints, "split")[0]["source_guid"]
    stale = _made_by(_rows(two_mints, "split2"), selected)
    _fail(two_mints, selected, "split2")

    result = _retry(two_mints)

    after = _rows(two_mints, "split2")
    assert len(after) == RECORDS * 4
    assert stale.isdisjoint(r["source_guid"] for r in after)
    assert WARNING not in result.output


def test_retrying_a_row_of_the_first_mint_leaves_the_diamond_its_size(diamond):  # noqa: F811
    """`combine` reads `flatten` and `split`; its rows name the `flatten` record."""
    selected = _rows(diamond, "split")[0]["source_guid"]
    before = _rows(diamond, "combine")
    stale = _made_by(before, selected)
    assert len(stale) == 2
    _fail(diamond, selected, "split")

    result = _retry(diamond, "--record", selected)

    after = _rows(diamond, "combine")
    assert len(after) == len(before)
    assert stale.isdisjoint(r["source_guid"] for r in after)
    assert len(_made_by(after, selected)) == 2
    assert WARNING not in result.output


# A FILE tool turning each pair of records into one row that keeps the first one's
# identity. Its `producer_source_guids` names only the second (#1438): the row's own
# identity accounts for the first.
PAIR_TOOL = """from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def pair_up(data: Any, *args) -> Any:
    rows = list(data or [])
    return FileUDFResult(
        [
            {
                "source_index": [index, index + 1],
                "data": {"summary": f"pair {index}", "exam_density": "high"},
            }
            for index in range(0, len(rows) - 1, 2)
        ]
    )
"""

PAIR_ACTION = """  - name: pairs
    kind: tool
    granularity: File
    dependencies: [flatten]
    intent: "Pair"
    schema: tool_action_output
    impl: pair_up
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


@pytest.fixture
def pairs_in_two_files(project):  # noqa: F811
    staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": f"page {i}"} for i in range(4)])
    )
    staging.joinpath("more.json").write_text(
        json.dumps([{"page_content": f"more {i}"} for i in range(4)])
    )
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + PAIR_ACTION)
    (project / "tools" / WORKFLOW / "pair_up.py").write_text(PAIR_TOOL)
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return project


def test_a_file_row_keeping_one_inputs_identity_survives_a_repair_of_another_file(
    pairs_in_two_files,
):
    rows = _rows(pairs_in_two_files, "pairs")
    assert len(rows) == 4
    kept_identity = [r for r in rows if r.get("producer_source_guids")]
    assert len(kept_identity) == 4, "the premise: each row keeps one input and names one more"
    flatten_rows = _rows(pairs_in_two_files, ACTION)
    file_of = {r["source_guid"]: r["content"]["source"]["page_content"] for r in flatten_rows}
    selected = next(g for g, page in file_of.items() if page.startswith("more"))
    untouched = {r["source_guid"]: r for r in rows if file_of[r["source_guid"]].startswith("page")}
    assert len(untouched) == 2
    _fail(pairs_in_two_files, selected, ACTION)

    _retry(pairs_in_two_files, "--record", selected)

    after = _rows(pairs_in_two_files, "pairs")
    assert len(after) == 4
    held = {r["source_guid"]: r for r in after}
    for guid, row in untouched.items():
        assert held.get(guid, {}).get("content") == row["content"], f"row {guid} was lost"
    assert set(_record_ids(pairs_in_two_files, ACTION)) >= {selected}
