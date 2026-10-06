"""A record a guard filters is removed only from what is downstream of the filter (1292).

A guard `on_false: filter` makes a record dead for its action and for everything below
it through `dependencies`, and a fan-in must not take it back from a branch that did not
filter it. Every action at a later level was treated as below it: one on another
branch, or under another start node, lost the record, completed and exited 0, with no
disposition for it. Under batch that reader then held no row, so every later run found
it completed with no output, ran it again and lost the records again.

The run stored every action of every earlier level as upstream of each action. The
filter was subtracted over that list, and delta storage rejoined each row with the
namespaces of every action on it.

Three staged pages through `flatten` -> `mid` -> `final`, and `b`, which filters.
Every command is a real `agac run`; under batch, each one in its own process.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_a_reader_with_a_batch_out_follows_an_upstream_edit import (
    _config,
    _guids,
    _run,
    _run_to_the_end,
    _statuses,
)
from tests.integration.test_retry_selection_under_batch import (
    RECORDS,
    _project,
)
from tests.integration.test_retry_selection_under_batch import (
    WORKFLOW as BATCH_WORKFLOW,
)

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
PAGES = [f"page {i}" for i in range(3)]

FILTER_ALL = "source.page_content == 'none'"
FILTER_PAGE_1 = "source.page_content != 'page 1'"

TOOLS = """import json
from typing import Any

from agent_actions import udf_tool


@udf_tool
def below_step(data: Any, *args) -> list[dict]:
    return [{"summary": json.dumps(data, sort_keys=True), "exam_density": "low"}]
"""


def _action(name, dependencies, observe, guard=None):
    return (
        f"  - name: {name}\n"
        f"    kind: tool\n"
        f"    dependencies: [{', '.join(dependencies)}]\n"
        f'    intent: "{name}"\n'
        f"    schema: tool_action_output\n"
        f"    impl: below_step\n"
        f"    context_scope: {{ observe: [{', '.join(observe)}] }}\n"
        f"    expect: {{ repair: none }}\n"
        + (f'    guard: {{ condition: "{guard}", on_false: filter }}\n' if guard else "")
    )


MID = _action("mid", ["flatten"], ["flatten.summary"])
FINAL = _action("final", ["mid"], ["mid.summary"])
CHAIN = MID + FINAL


def _sibling(guard):
    """`b` beside `mid`, under `flatten`; `final` is below `mid` only."""
    return CHAIN + _action("b", ["flatten"], ["flatten.summary"], guard)


def _start_node(guard):
    """`b` reads the staged pages itself; nothing below `flatten` is below it."""
    return CHAIN + _action("b", [], ["source.page_content"], guard)


def _fan_in(guard):
    """`b` -> `c` beside `mid`, and `final` reads both branches."""
    return (
        MID
        + _action("b", ["flatten"], ["flatten.summary"], guard)
        + _action("c", ["b"], ["b.summary"])
        + _action("final", ["mid", "c"], ["mid.summary", "c.summary"])
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(json.dumps([{"page_content": p} for p in PAGES]))
    # Named for this file alone: discovery skips a module name already imported.
    (root / "tools" / WORKFLOW / "filter_only_below.py").write_text(TOOLS)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    return root


def _workflow(project, actions):
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + actions)
    return project


def _run_online(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _stored(project, action):
    """What `action` reads back, row by row: (page, namespaces on the row)."""
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        rows = [
            r for f in backend.list_target_files(action) for r in backend.read_target(action, f)
        ]
    finally:
        backend.close()
    return sorted((r["content"]["source"]["page_content"], sorted(r["content"])) for r in rows)


def _pages(project, action):
    return [page for page, _ in _stored(project, action)]


class TestAFilterOnAnotherBranchRemovesNothing:
    @pytest.mark.parametrize("guard", [FILTER_ALL, FILTER_PAGE_1], ids=["every", "one"])
    def test_a_sibling_branch_keeps_every_record(self, project, guard):
        """`final` is below `mid`, not `b`: it read `b`'s filter as its own and held
        nothing when `b` filtered everything."""
        _workflow(project, _sibling(guard))

        result = _run_online("--fresh")

        assert result.exit_code == 0, result.output
        assert _pages(project, "mid") == PAGES
        assert _pages(project, "final") == PAGES, result.output
        assert "filtered by an upstream guard" not in result.output

    def test_the_readers_of_another_start_node_keep_every_record(self, project):
        """`b` reads the staged pages beside `flatten`, so it is upstream of nothing."""
        _workflow(project, _start_node(FILTER_PAGE_1))

        result = _run_online("--fresh")

        assert result.exit_code == 0, result.output
        assert _pages(project, "b") == ["page 0", "page 2"]
        assert _pages(project, "mid") == PAGES, result.output
        assert _pages(project, "final") == PAGES, result.output


class TestAFilterUpstreamStillHoldsAtAFanIn:
    def test_a_record_filtered_on_one_branch_does_not_come_back_through_the_other(self, project):
        """`b` is above `final` through `c` only; `mid` still carries page 1."""
        _workflow(project, _fan_in(FILTER_PAGE_1))

        result = _run_online("--fresh")

        assert result.exit_code == 0, result.output
        assert _pages(project, "mid") == PAGES
        assert _pages(project, "final") == ["page 0", "page 2"], result.output


class TestARecordReadsBackWithWhatIsUpstreamOfIt:
    """A row stored as a delta is rejoined with the namespaces upstream of it, so it
    reads back as the record the action wrote: a whole row of `final` never held `b`."""

    def test_a_sibling_branch_is_not_rejoined(self, project):
        _workflow(project, _sibling(None))

        result = _run_online("--fresh")

        assert result.exit_code == 0, result.output
        assert _stored(project, "final") == [
            (page, ["final", "flatten", "mid", "source"]) for page in PAGES
        ]

    def test_both_branches_of_a_fan_in_are(self, project):
        _workflow(project, _fan_in(None))

        result = _run_online("--fresh")

        assert result.exit_code == 0, result.output
        assert _stored(project, "final") == [
            (page, ["b", "c", "final", "flatten", "mid", "source"]) for page in PAGES
        ]


def _llm_action(name, dependencies, observe, prompt="$p.Publish", guard=None):
    return (
        f"  - name: {name}\n"
        f"    dependencies: [{', '.join(dependencies)}]\n"
        f'    intent: "{name}"\n'
        f"    schema: batch_field_rules_output\n"
        f"    prompt: {prompt}\n"
        f"    context_scope: {{ observe: [{', '.join(observe)}] }}\n"
        f"    expect: {{ repair: none }}\n"
        + (f"    guard: {{ condition: '{guard}', on_false: \"filter\" }}\n" if guard else "")
    )


BATCH_FILTER_ALL = 'source.page_content == "none"'
BATCH_FILTER_PAGE_0 = 'source.page_content != "page 0"'
BATCH_MID = _llm_action("mid", ["summarize"], ["summarize.summary"])
BATCH_FINAL = _llm_action("final", ["mid"], ["mid.summary", "summarize.summary"])
# shape -> (actions after `summarize`, how many records `final` keeps)
BATCH_SHAPES = {
    "sibling": (
        BATCH_MID
        + BATCH_FINAL
        + _llm_action("b", ["summarize"], ["summarize.summary"], guard=BATCH_FILTER_ALL),
        RECORDS,
    ),
    "start_node": (
        BATCH_MID
        + BATCH_FINAL
        + _llm_action(
            "b", [], ["source.page_content"], prompt="$p.Summarize", guard=BATCH_FILTER_PAGE_0
        ),
        RECORDS,
    ),
    "fan_in": (
        BATCH_MID
        + _llm_action("b", ["summarize"], ["summarize.summary"], guard=BATCH_FILTER_PAGE_0)
        + _llm_action("final", ["mid", "b"], ["mid.summary", "b.summary", "summarize.summary"]),
        RECORDS - 1,
    ),
}


@pytest.fixture
def batch_project(tmp_path):
    root = _project(tmp_path)
    staging = root / "agent_workflow" / BATCH_WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(RECORDS)])
    )
    return root


def _batch_workflow(project, shape):
    config = _config(project)
    config.write_text(config.read_text().rstrip("\n") + "\n" + BATCH_SHAPES[shape][0])
    return project


class TestUnderBatch:
    @pytest.mark.parametrize("shape", sorted(BATCH_SHAPES))
    def test_the_reader_loses_only_what_its_own_upstream_filtered(self, batch_project, shape):
        project = _batch_workflow(batch_project, shape)

        transcript = _run(project, "--fresh") + _run_to_the_end(project)

        assert len(_guids(project, "mid")) == RECORDS, transcript
        assert len(_guids(project, "final")) == BATCH_SHAPES[shape][1], transcript

    def test_a_later_run_finds_the_reader_complete(self, batch_project):
        """Holding no row, `final` read as completed with its output gone, and every
        later run ran it again over the records `b` filtered."""
        project = _batch_workflow(batch_project, "sibling")
        _run(project, "--fresh")
        _run_to_the_end(project)

        again = _run(project)

        assert "no output in storage" not in again, again
        assert _statuses(project)["final"] == ActionStatus.COMPLETED.value
        assert len(_guids(project, "final")) == RECORDS, again
