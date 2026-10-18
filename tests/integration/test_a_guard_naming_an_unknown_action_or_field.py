"""A guard naming an action that does not exist, or a field its upstream's schema lacks,
is refused before the run (1516).

Pre-flight checked a guard's references only under the legacy `field` key, while an
expanded guard carries its clause under `clause`, so `nosuch.severity == 'high'` and
`merge_alternatives.sevrity == 'high'` passed. Neither name is on any record, so the
guard filtered every record and the run exited 0 having produced nothing below it.
Pre-flight now reads the clause and checks each `namespace.field` it names the way it
checks a prompt's references.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from tests._support.agac_cli import REPO, run_agac

WORKFLOW = "w"
PAGES = [
    {"page_id": "p1", "page_content": "two"},
    {"page_id": "p2", "page_content": "one"},
]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "A guard on an upstream action's field"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {mode}
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: merge_alternatives
    kind: tool
    intent: "Produce"
    schema: fix1516_merge_out
    impl: fix1516_produce
    context_scope: {{ observe: [source.page_content] }}
  - name: consumer
    intent: "Consume"
    dependencies: [merge_alternatives]
    schema: fix1516_consumer_out
    prompt: "Say {{{{ merge_alternatives.severity }}}}"
    context_scope: {{ observe: [merge_alternatives.*] }}
    guard: {{ condition: "{condition}", on_false: filter }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def fix1516_produce(data: Any, *args) -> list[dict]:
    return [{{"severity": "high"{extra}}}]
"""

_MERGE_SCHEMA = """\
name: fix1516_merge_out
fields:
  - id: severity
    type: string
{open}"""

_CONSUMER_SCHEMA = """\
name: fix1516_consumer_out
fields:
  - id: summary
    type: string
"""


def _project(tmp_path: Path, condition: str, mode: str = "online", open_schema=False) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(mode=mode, condition=condition)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "fix1516_merge_out.yml").write_text(
        _MERGE_SCHEMA.format(open="additionalProperties: true\n" if open_schema else "")
    )
    (root / "schema" / WORKFLOW / "fix1516_consumer_out.yml").write_text(_CONSUMER_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    extra = ', "extra": data["source"]["page_content"]' if open_schema else ""
    (root / "tools" / WORKFLOW / "fix1516_produce.py").write_text(_TOOL.format(extra=extra))
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> str:
    outputs = []
    args = ["run", "-a", WORKFLOW, "--fresh"]
    for _ in range(4):
        result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
        output = result.stdout + result.stderr
        outputs.append(output)
        assert result.returncode == 0, "\n".join(outputs)
        if "run again" not in output:
            return "\n".join(outputs)
        args = ["run", "-a", WORKFLOW]
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _consumer_dispositions(project: Path) -> list[str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition where action_name = 'consumer'"
        )
        return sorted(disposition for (disposition,) in rows)
    finally:
        con.close()


def _refused(project: Path, *args: str) -> str:
    result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    if store.exists() and list(store.glob("*.db")):
        assert _consumer_dispositions(project) == [], output
    return output


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_guard_naming_an_action_that_does_not_exist_is_refused(tmp_path, mode):
    project = _project(tmp_path, "nosuch.severity == 'high'", mode)

    output = _refused(project, "run", "-a", WORKFLOW, "--fresh")

    assert "Referenced action 'nosuch' does not exist in workflow" in output, output
    assert "Location: guard" in output, output


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_guard_naming_a_field_the_schema_lacks_is_refused(tmp_path, mode):
    project = _project(tmp_path, "merge_alternatives.sevrity == 'high'", mode)

    output = _refused(project, "run", "-a", WORKFLOW, "--fresh")

    assert "Field 'sevrity' not found in action 'merge_alternatives' output schema" in output
    assert "Did you mean: severity?" in output, output


def test_a_misspelt_action_is_answered_with_the_closest_name(tmp_path):
    project = _project(tmp_path, "merge_alternative.severity == 'high'")

    output = _refused(project, "inspect", "-a", WORKFLOW)

    assert "Referenced action 'merge_alternative' does not exist in workflow" in output
    assert "Did you mean 'merge_alternatives'?" in output, output


def test_a_misspelt_field_under_is_null_is_refused(tmp_path):
    """`IS NULL` treats a name it cannot resolve as null, so this kept every record."""
    project = _project(tmp_path, "merge_alternatives.sevrity IS NULL")

    output = _refused(project, "inspect", "-a", WORKFLOW)

    assert "Field 'sevrity' not found in action 'merge_alternatives' output schema" in output


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("condition", "passed"),
    [
        ("merge_alternatives.severity == 'high'", ["success", "success"]),
        ("merge_alternatives.severity IS NULL", []),
        ("source.page_content == 'two' and merge_alternatives.severity != 'low'", ["success"]),
    ],
)
def test_a_guard_on_a_real_field_still_runs(tmp_path, mode, condition, passed):
    project = _project(tmp_path, condition, mode)

    _run_to_the_end(project)

    assert [d for d in _consumer_dispositions(project) if d == "success"] == passed


def test_a_field_an_open_schema_does_not_list_still_runs(tmp_path):
    """A schema with `additionalProperties` admits fields it does not name."""
    project = _project(tmp_path, "merge_alternatives.extra == 'two'", open_schema=True)

    _run_to_the_end(project)

    assert [d for d in _consumer_dispositions(project) if d == "success"] == ["success"]


def _versioned_project(tmp_path: Path, guards: dict[str, str]) -> Path:
    root = tmp_path / "fanin"
    shutil.copytree(REPO / "examples" / "map_reduce_fanin_check", root)
    config = root / "agent_workflow/map_reduce_fanin_check/agent_config/map_reduce_fanin_check.yml"
    workflow = yaml.safe_load(config.read_text())
    for action in workflow["actions"]:
        if action["name"] in guards:
            action["guard"] = {"condition": guards[action["name"]], "on_false": "filter"}
    config.write_text(yaml.safe_dump(workflow, sort_keys=False))
    (root / ".env").write_text("GEMINI_API_KEY=not-used\n")
    return root


def test_a_guard_naming_a_version_base_is_pointed_at_its_branches(tmp_path):
    """Records below a version merge carry `vote_1` and `vote_2`, never `vote`."""
    project = _versioned_project(tmp_path, {"merge_votes": "vote.vote == 'keep'"})

    result = run_agac(project, "inspect", "-a", "map_reduce_fanin_check")

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Referenced action 'vote' does not exist in workflow" in output, output
    assert "Did you mean 'vote_1' or 'vote_2'?" in output, output


def test_guards_on_branches_versions_and_framework_namespaces_pass(tmp_path):
    project = _versioned_project(
        tmp_path,
        {
            "merge_votes": "vote_1.vote == 'keep' and vote_2.vote == 'keep'",
            "vote": "voter_id == 1 and split_words.word != ''",
            "split_words": "source.text != '' and workflow.name != ''",
        },
    )

    result = run_agac(project, "inspect", "-a", "map_reduce_fanin_check")

    assert result.returncode == 0, result.stdout + result.stderr
