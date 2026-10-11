"""A tool written as the skill and the docs show reads the input the run hands it (1355).

Authors copy the tool code beside each workflow block. Here that code is taken from
the page as written and run by `agac run`: a record tool reading several actions, a
record tool merging the versions of one, and a FILE tool. Each reads what a tool
above it stored, so a line that reaches for a shape the run does not deliver raises
on every record and the run fails.

Only what the pages leave out is added: the imports, the actions above each tool,
and for the version merge a tool around the three lines the skill shows.
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import REPO, run_agac

SKILL = REPO / "agent_actions" / "skills" / "agac-agent-skills" / "SKILL.md"
GRANULARITY = REPO / "docs.agent-actions" / "docs" / "reference" / "execution" / "granularity.md"
WORKFLOW = "shown_tools"
_PYTHON = re.compile(r"^```python\n(.*?)^```", re.S | re.M)

CONFIG = """name: shown_tools
description: "Tools as the skill and the docs show them"
version: "1.0.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: check_quality
    kind: tool
    impl: fails_the_check
    intent: "Check"
    schema: { passed: boolean, reason: string }
    context_scope: { observe: [source.title] }
  - name: verify_accuracy
    kind: tool
    impl: passes_the_check
    intent: "Check"
    schema: { passed: boolean, reason: string }
    context_scope: { observe: [source.title] }
  - name: combine_results
    dependencies: [check_quality, verify_accuracy]
    kind: tool
    impl: combine_results
    intent: "Combine"
    schema: { has_failures: boolean, combined_issues: string }
    context_scope: { observe: [check_quality.*, verify_accuracy.*] }

  - name: evaluate
    kind: tool
    impl: says_yes
    intent: "Evaluate"
    versions: { param: evaluator_id, range: [1, 2, 3] }
    schema: { verdict: string, reasoning: string }
    context_scope: { observe: [source.title] }
  - name: aggregate_evaluations
    dependencies: [evaluate]
    kind: tool
    impl: aggregate_evaluations
    intent: "Agree"
    version_consumption: { source: evaluate, pattern: merge }
    schema: { final_verdict: string }
    context_scope: { observe: [evaluate.*] }

  - name: enrich_records
    kind: tool
    impl: names_the_record
    intent: "Enrich"
    schema: { canonical_id: string, title: string }
    context_scope: { observe: [source.id, source.title] }
  - name: deduplicate
    dependencies: [enrich_records]
    kind: tool
    impl: deduplicate_records
    intent: "Deduplicate"
    schema: { canonical_id: string, title: string }
    granularity: File
    context_scope: { observe: [enrich_records.*] }

  - name: extract_facts
    kind: tool
    impl: states_the_fact
    intent: "Extract"
    schema: { fact_text: string }
    context_scope: { observe: [source.id] }
  - name: deduplicate_facts
    dependencies: [extract_facts]
    kind: tool
    impl: deduplicate_facts
    intent: "Deduplicate"
    schema: { fact_text: string }
    granularity: File
    context_scope: { observe: [extract_facts.*] }
"""

ABOVE = """from typing import Any

from agent_actions import udf_tool
from agent_actions.config.schema import Granularity


@udf_tool()
def fails_the_check(data: dict[str, Any]) -> dict[str, Any]:
    return {"passed": False, "reason": "too short"}


@udf_tool()
def passes_the_check(data: dict[str, Any]) -> dict[str, Any]:
    return {"passed": True, "reason": ""}


@udf_tool()
def says_yes(data: dict[str, Any]) -> dict[str, Any]:
    return {"verdict": "yes", "reasoning": "it is"}


@udf_tool()
def names_the_record(data: dict[str, Any]) -> dict[str, Any]:
    return {"canonical_id": data["source"]["id"], "title": data["source"]["title"]}


@udf_tool()
def states_the_fact(data: dict[str, Any]) -> dict[str, Any]:
    return {"fact_text": "fact " + data["source"]["id"]}
"""

MERGE = """

@udf_tool()
def aggregate_evaluations(data: dict[str, Any]) -> dict[str, Any]:
%s
    return {"final_verdict": "/".join([v1, v2, v3])}
"""


def _shown(page: Path, naming: str) -> str:
    """The Python block of *page* that holds *naming*."""
    (block,) = [b for b in _PYTHON.findall(page.read_text(encoding="utf-8")) if naming in b]
    return block


def _stored(root: Path, action: str) -> list[dict]:
    """What *action* answered; a record a FILE tool did not return is kept with no answer."""
    workflow = root / "agent_workflow" / WORKFLOW
    backend = get_storage_backend(str(workflow), WORKFLOW)
    backend.initialize()
    try:
        answers = [r["content"][action] for r in backend.read_target(action, "items.json")]
        return [answer for answer in answers if answer is not None]
    finally:
        backend.close()


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("shown_tools")
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "schema").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\ntool_path: tools\n"
    )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG)
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps(
            [
                {"id": "a", "title": "First"},
                {"id": "a", "title": "First again"},
                {"id": "b", "title": "Second"},
            ]
        )
    )
    facts = _shown(GRANULARITY, "def deduplicate_facts")
    facts = facts.replace("from agent_actions import udf_tool\n", "")
    facts = facts.replace("from agent_actions.config.schema import Granularity\n", "")
    (root / "tools" / "shown.py").write_text(
        "\n\n".join(
            [
                ABOVE,
                _shown(SKILL, "def combine_results"),
                _shown(SKILL, "def deduplicate_records"),
                facts,
            ]
        )
        + MERGE % textwrap.indent(_shown(SKILL, 'data["evaluate_1"]'), "    ")
    )
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")
    return root, result


def test_the_run_finishes(run):
    _, result = run
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_record_tool_reads_each_action_under_its_name(run):
    root, _ = run
    combined = _stored(root, "combine_results")
    assert [c["combined_issues"] for c in combined] == ["too short"] * 3
    assert all(c["has_failures"] is True for c in combined)


def test_a_version_merge_reads_each_version_under_its_name(run):
    root, _ = run
    merged = _stored(root, "aggregate_evaluations")
    assert [m["final_verdict"] for m in merged] == ["yes/yes/yes"] * 3


def test_a_file_tool_reads_the_observed_fields(run):
    root, _ = run
    assert sorted(r["canonical_id"] for r in _stored(root, "deduplicate")) == ["a", "b"]
    assert sorted(r["fact_text"] for r in _stored(root, "deduplicate_facts")) == [
        "fact a",
        "fact b",
    ]
