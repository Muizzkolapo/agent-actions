"""An action reads only what is upstream of it through its dependencies (1228).

A record carries the namespace of every action it passed through, so an action can
read an action it names only in its context scope when that action is upstream of
its input. One that ran beside or after it read null on every run, with no error,
and one on a parallel branch was read only while that branch happened to finish
first. The run order counted the name as a dependency and the level loop did not, so
the reader could also run before the action it named, and an action failed, reset
and run again left that reader completed with what it had read.

Three tool actions in a chain, `flatten` -> `mid` -> `final`, over three staged
records, and `late`, which names some of them. Every command is a real `agac run`.
"""

import json
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.llm.providers.tools import client as tool_client
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
PAGES = [f"page {i}" for i in range(3)]

TOOLS = """import json
from typing import Any

from agent_actions import udf_tool


def _summary(data, namespace, key="summary"):
    return ((data or {}).get(namespace) or {}).get(key)


@udf_tool
def step_mid(data: Any, *args) -> list[dict]:
    return [{"summary": f"mid:{_summary(data, 'source', 'page_content')}", "exam_density": "low"}]


@udf_tool
def step_final(data: Any, *args) -> list[dict]:
    return [{"summary": f"final:{_summary(data, 'mid')}", "exam_density": "low"}]


@udf_tool
def step_side(data: Any, *args) -> list[dict]:
    seen = next((v for v in (data or {}).values() if isinstance(v, dict)), {})
    return [{"summary": f"side:{seen.get('summary')}", "exam_density": "low"}]


@udf_tool
def step_late(data: Any, *args) -> list[dict]:
    return [{"summary": json.dumps(data, sort_keys=True), "exam_density": "low"}]
"""


def _action(name, impl, dependencies, observe):
    return (
        f"  - name: {name}\n"
        f"    kind: tool\n"
        f"    dependencies: [{', '.join(dependencies)}]\n"
        f'    intent: "{name}"\n'
        f"    schema: tool_action_output\n"
        f"    impl: {impl}\n"
        f"    context_scope: {{ observe: [{', '.join(observe)}] }}\n"
        f"    expect: {{ repair: none }}\n"
    )


CHAIN = _action(
    "mid", "step_mid", ["flatten"], ["flatten.summary", "source.page_content"]
) + _action("final", "step_final", ["mid"], ["mid.summary"])
# A second branch off `flatten`, one action longer than mid -> final.
BRANCH = (
    _action("b", "step_side", ["flatten"], ["flatten.summary"])
    + _action("c", "step_side", ["b"], ["b.summary"])
    + _action("d", "step_side", ["c"], ["c.summary"])
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(json.dumps([{"page_content": p} for p in PAGES]))
    # Named for this file alone: discovery skips a module name already imported, so a
    # name another test uses would run that test's tools.
    (root / "tools" / WORKFLOW / "reads_upstream.py").write_text(TOOLS)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    return root


def _late(project, dependencies, observe, *, extra=""):
    """Add mid -> final after flatten, *extra*, and `late` naming what *observe* names."""
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().rstrip("\n")
        + "\n"
        + CHAIN
        + extra
        + _action("late", "step_late", dependencies, observe)
    )
    return project


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _status(project, action):
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


def _ran_anything(project):
    return (project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json").exists()


def _what_late_read(project, namespace):
    """Per page, what `late` was handed for *namespace*'s summary."""
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        rows = [
            r for f in backend.list_target_files("late") for r in backend.read_target("late", f)
        ]
    finally:
        backend.close()
    seen = {}
    for row in rows:
        content = row["content"]
        handed = json.loads(content["late"]["summary"])
        seen[content["source"]["page_content"]] = (handed.get(namespace) or {}).get("summary")
    return dict(sorted(seen.items()))


@contextmanager
def _mid_fails():
    run_tool = tool_client.execute_user_defined_function

    def failing(udf_name, input_data, *args, **kwargs):
        if udf_name == "step_mid":
            raise RuntimeError("the tool blew up")
        return run_tool(udf_name, input_data, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(tool_client, "execute_user_defined_function", failing)
        yield


def _assert_refused(result, project, named):
    assert result.exit_code != 0, result.output
    assert f"late: names '{named}'" in result.output, result.output
    assert "is not upstream of it through its dependencies" in result.output, result.output
    assert f"Add '{named}' to its dependencies" in result.output, result.output
    assert not _ran_anything(project), "the run started before refusing"


class TestANameOutsideTheLineageIsRefused:
    def test_an_action_that_runs_after_the_reader(self, project):
        """`final` is two levels below `flatten`, so `late` ran first and read null."""
        _late(project, ["flatten"], ["flatten.summary", "final.summary"])

        _assert_refused(_run("--fresh"), project, "final")

    def test_an_action_at_the_readers_own_level(self, project):
        """`mid` runs beside `late`. Failed and run again, it left `late` completed with
        what it read before, while `final`, which depends on it, ran again."""
        _late(project, ["flatten"], ["flatten.summary", "mid.summary"])

        _assert_refused(_run("--fresh"), project, "mid")

    def test_an_action_on_another_branch_that_happens_to_run_earlier(self, project):
        """`late` reads `d`'s records, which are stored after `final`'s, and a stored
        record is rejoined with the actions of every earlier level. So `late` read
        `final` here, but only while the d-branch stays the longer one."""
        _late(project, ["d"], ["d.summary", "final.summary"], extra=BRANCH)

        _assert_refused(_run("--fresh"), project, "final")


class TestANameUpstreamOfTheInputIsRead:
    def test_through_the_actions_it_depends_on(self, project):
        _late(project, ["final"], ["final.summary", "mid.summary"])

        result = _run("--fresh")

        assert result.exit_code == 0, result.output
        assert _what_late_read(project, "mid") == {p: f"mid:{p}" for p in PAGES}

    def test_when_the_reader_depends_on_it_as_well(self, project):
        _late(project, ["flatten", "final"], ["flatten.summary", "final.summary"])

        result = _run("--fresh")

        assert result.exit_code == 0, result.output
        assert _what_late_read(project, "final") == {p: f"final:mid:{p}" for p in PAGES}

    def test_a_reader_of_a_failed_action_runs_again_once_it_succeeds(self, project):
        """Why the startup reset needs nothing of its own: a failed action skips every
        action downstream of it, which includes everything that may name it, and a
        skipped action is put back to pending with it."""
        _late(project, ["final"], ["final.summary", "mid.summary"])
        with _mid_fails():
            _run("--fresh")
        assert (_status(project, "mid"), _status(project, "late")) == ("failed", "skipped")

        result = _run()

        assert result.exit_code == 0, result.output
        assert _status(project, "late") == "completed"
        assert _what_late_read(project, "mid") == {p: f"mid:{p}" for p in PAGES}
