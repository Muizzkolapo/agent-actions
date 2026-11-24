"""Each instance of a branch included with `as:` reads its own siblings by their short names.

One branch, `round`, is included twice: `c` reads `spec_a` and `c2` reads `spec_b` through
the input `spec`. One tool function and one prompt serve both instances. The tool `review`
reads `data["write"]`, and the prompt of `judge` reads `{{ write.text }}`; each must get
the output of its own instance's `write`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_PAUSED
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

WORKFLOW = "groups"

TOOLS = """\
from typing import Any

from agent_actions import udf_tool


def _text(data: Any, key: str) -> str:
    return str(((data or {}).get(key) or {}).get("text"))


@udf_tool
def spec_a(data: Any, *args) -> list[dict]:
    return [{"text": "A-" + _text(data, "source")}]


@udf_tool
def spec_b(data: Any, *args) -> list[dict]:
    return [{"text": "B-" + _text(data, "source")}]


@udf_tool
def round_write(data: Any, *args) -> list[dict]:
    return [{"text": "w(" + _text(data, "spec") + ")"}]


@udf_tool
def round_review(data: Any, *args) -> list[dict]:
    return [{"seen": _text(data, "write"), "keys": ",".join(sorted(data or {}))}]
"""

TEXT_SCHEMA = "name: {name}\nfields:\n  - id: text\n    type: string\n"
REVIEW_SCHEMA = """\
name: reviewed
fields:
  - id: seen
    type: string
  - id: keys
    type: string
"""
VERDICT_SCHEMA = """\
name: verdict
fields:
  - id: verdict
    type: string
"""

PROMPTS = """\
{prompt Judge}
Judge {{ write.text }} against {{ spec.text }}.
{end_prompt}
"""

BRANCH = """\
branch: round
description: Write from a spec, then review and judge what was written
inputs:
  spec: The specification
outputs: [review, judge]
actions:
  - name: write
    kind: tool
    impl: round_write
    intent: Write
    schema: written
    dependencies: [spec]
    context_scope: { observe: [spec.text] }
  - name: review
    kind: tool
    impl: round_review
    intent: Review
    schema: reviewed
    dependencies: [write]
    context_scope: { observe: [write.text] }
  - name: judge
    intent: Judge
    prompt: $groups.Judge
    schema: verdict
    dependencies: [write]
    context_scope: { observe: [write.text, spec.text] }
"""

CONFIG = """\
name: groups
description: "One branch included twice"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: m
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: spec_a
    kind: tool
    impl: spec_a
    intent: Spec A
    schema: spec_text
    context_scope: {{ observe: [source.text] }}
  - name: spec_b
    kind: tool
    impl: spec_b
    intent: Spec B
    schema: spec_text
    context_scope: {{ observe: [source.text] }}
  - include: round
    as: c
    inputs: {{ spec: spec_a }}
  - include: round
    as: c2
    inputs: {{ spec: spec_b }}
"""


def _project(base: Path, run_mode: str) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    schemas = root / "schema" / WORKFLOW
    schemas.mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "branches").mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
        'tool_path: ["tools"]\n'
    )
    for name in ("spec_text", "written"):
        (schemas / f"{name}.yml").write_text(TEXT_SCHEMA.format(name=name))
    (schemas / "reviewed.yml").write_text(REVIEW_SCHEMA)
    (schemas / "verdict.yml").write_text(VERDICT_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    (root / "branches" / "round.yml").write_text(BRANCH)
    (root / "tools" / WORKFLOW / "round_tools.py").write_text(TOOLS)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG.format(run_mode=run_mode))
    (directory / "agent_io" / "staging" / "rows.json").write_text(
        json.dumps([{"text": "one"}, {"text": "two"}])
    )
    return root


def _run(root: Path, *extra: str) -> str:
    result = run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        *extra,
        env={"OPENAI_API_KEY": "sk-not-used"},
    )
    output = result.stdout + result.stderr
    if result.returncode == EXIT_PAUSED:
        assert "run again" in output, output
    else:
        assert result.returncode == 0, output
        assert "run again" not in output, output
    return output


def _backend(root: Path):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _outputs(root: Path, action: str) -> list[dict]:
    backend = _backend(root)
    try:
        return [
            record["content"][action]
            for path in backend.list_target_files(action)
            for record in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _prompts(root: Path, action: str) -> list[str]:
    backend = _backend(root)
    try:
        return sorted(trace["compiled_prompt"] for trace in backend.get_prompt_traces(action))
    finally:
        backend.close()


def test_a_tool_in_instance_c2_gets_the_output_of_c2_write_under_its_short_name(tmp_path):
    root = _project(tmp_path, "online")

    _run(root, "--fresh")

    for prefix, spec in (("c", "A"), ("c2", "B")):
        reviews = _outputs(root, f"{prefix}__review")
        assert sorted(review["seen"] for review in reviews) == [
            f"w({spec}-one)",
            f"w({spec}-two)",
        ]
        assert {review["keys"] for review in reviews} == {"write"}


def test_an_llm_prompt_in_instance_c2_reads_c2_write_online(tmp_path):
    root = _project(tmp_path, "online")

    _run(root, "--fresh")

    assert [prompt.strip() for prompt in _prompts(root, "c2__judge")] == [
        "Judge w(B-one) against B-one.",
        "Judge w(B-two) against B-two.",
    ]
    assert [prompt.strip() for prompt in _prompts(root, "c__judge")] == [
        "Judge w(A-one) against A-one.",
        "Judge w(A-two) against A-two.",
    ]


def _batch_prompts(root: Path) -> list[str]:
    state = root / ".agac" / "batch_state"
    if not state.is_dir():
        return []
    return [
        task["prompt"]
        for path in sorted(state.glob("*.json"))
        for task in json.loads(path.read_text())["tasks"]
    ]


@pytest.mark.parametrize("instance, spec", [("c", "A"), ("c2", "B")])
def test_an_llm_prompt_in_each_instance_reads_its_own_write_in_the_batch_request(
    tmp_path, instance, spec
):
    root = _project(tmp_path, "batch")

    sent: list[str] = []
    output = _run(root, "--fresh")
    sent += _batch_prompts(root)
    for _ in range(6):
        if "run again" not in output:
            break
        output = _run(root)
        sent += _batch_prompts(root)
    assert "run again" not in output, output

    judged = sorted({text.strip() for text in sent if f"against {spec}-" in text})
    assert judged == [
        f"Judge w({spec}-one) against {spec}-one.",
        f"Judge w({spec}-two) against {spec}-two.",
    ]
    other = "A" if spec == "B" else "B"
    assert not any(f"w({other}-" in text for text in judged)
    assert len(_outputs(root, f"{instance}__judge")) == 2
