"""A staged-input change, and --fresh, while a batch of the run is still open (#1921).

Between two commands of a paused run nothing holds the run lock. A file added to the
staged input reached the first action but never the actions after the batch; a file
removed was written back when the batch was collected; `--fresh` dropped the paid batch
with no word. A change is now answered or forgotten at every action, and `--fresh`
refuses until the batch is collected, unless `--abandon-in-flight` drops it on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "bat"

WORKFLOW_YML = """name: bat
description: "A tool, a batch LLM action, a tool"
version: "1.0.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: step1
    kind: tool
    intent: "Read"
    impl: step1
    schema: s1
    context_scope: { observe: [source.*] }
  - name: tag
    dependencies: [step1]
    run_mode: batch
    intent: "Tag"
    prompt: $bat.Tag
    schema: tags
    context_scope: { observe: [step1.id, step1.n] }
  - name: step3
    dependencies: [tag]
    kind: tool
    intent: "Count"
    impl: step3
    schema: s3
    context_scope: { observe: [step1.id, tag.tags] }
"""

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def step1(data: Any, *args: Any) -> dict:
    source = data["source"]
    return {"id": str(source["id"]), "n": int(source["n"])}


@udf_tool
def step3(data: Any, *args: Any) -> dict:
    return {"id": data["step1"]["id"], "n3": len(data["tag"]["tags"])}
"""

SCHEMAS = {
    "s1": "name: s1\nfields:\n  - {id: id, type: string, required: true}\n"
    "  - {id: n, type: integer, required: true}\n",
    "tags": "name: tags\nfields:\n  - id: tags\n    type: array\n    required: true\n"
    "    items: {type: string}\n",
    "s3": "name: s3\nfields:\n  - {id: id, type: string, required: true}\n"
    "  - {id: n3, type: integer, required: true}\n",
}

PROMPT = (
    "{prompt Tag}\nGive two tags for record {{ step1.id }} with n={{ step1.n }}.\n{end_prompt}\n"
)


def _tag_first(text: str) -> str:
    """The workflow with the batch action as its first stage, reading staging itself."""
    without_step1 = text.replace(
        """  - name: step1
    kind: tool
    intent: "Read"
    impl: step1
    schema: s1
    context_scope: { observe: [source.*] }
""",
        "",
    ).replace("    dependencies: [step1]\n    run_mode: batch", "    run_mode: batch")
    return without_step1.replace("step1.", "source.").replace(
        'data["step1"]["id"]', 'str(data["source"]["id"])'
    )


def _project(tmp_path: Path, shape: str = "tag_after_a_tool") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    for folder in ("agent_io/staging", "agent_config"):
        (workflow / folder).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "agent_actions.yml").write_text(
        "project_name: bat\ntool_path: [tools]\nschema_path: schema\n"
    )
    (root / "sandbox.yml").write_text("seed: 2\nbatch:\n  polls_until_complete: 3\n")
    first = shape == "tag_first"
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _tag_first(WORKFLOW_YML) if first else WORKFLOW_YML
    )
    (root / "tools" / WORKFLOW / "tools.py").write_text(_tag_first(TOOLS) if first else TOOLS)
    for name, text in SCHEMAS.items():
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(text)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_tag_first(PROMPT) if first else PROMPT)
    _SHAPES[root] = shape
    _stage(root, "a.json", [{"id": "a1", "n": 1}, {"id": "a2", "n": 2}])
    _stage(root, "b.json", [{"id": "b1", "n": 3}])
    return root


def _stage(root: Path, name: str, records) -> None:
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    (staging / name).write_text(json.dumps(records))


def _run(root: Path, *extra: str):
    result = run_agac(root, "run", "-a", WORKFLOW, "-u", "tools", "--sandbox", *extra)
    return result.returncode, " ".join((result.stdout + result.stderr).split())


_SHAPES: dict[Path, str] = {}


def _actions(root: Path) -> list[str]:
    return ["tag", "step3"] if _SHAPES[root] == "tag_first" else ["step1", "tag", "step3"]


def _field(root: Path, action: str, name: str) -> list:
    """*name* of every row the action stored, sorted: every row carries the first namespace."""
    namespace = "source" if _SHAPES[root] == "tag_first" else "step1"
    result = run_agac(
        root,
        "records",
        "-w",
        WORKFLOW,
        "--sandbox",
        "-A",
        action,
        "--field",
        f"content.{namespace}.{name}",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return sorted(json.loads(result.stdout), key=str)


def _ids(root: Path, action: str) -> list[str]:
    return [str(value) for value in _field(root, action, "id")]


def _held(root: Path, name: str = "id") -> dict[str, list]:
    return {action: _field(root, action, name) for action in _actions(root)}


def _collect(root: Path) -> list[int]:
    """Run again, as a person does, until the run is no longer paused.

    At most 12 runs: a change answered once the batch is collected sends a second batch.
    """
    codes = [_run(root)[0]]
    while codes[-1] == 4 and len(codes) < 12:
        codes.append(_run(root)[0])
    return codes


@pytest.fixture(params=["tag_after_a_tool", "tag_first"])
def paused(tmp_path, request):
    root = _project(tmp_path, request.param)
    code, output = _run(root)
    assert code == 4, output
    return root


class TestAStagedInputChangeWhileABatchIsOpen:
    def test_a_file_added_reaches_the_actions_after_the_batch(self, paused):
        _stage(paused, "c.json", [{"id": "c1", "n": 4}])

        codes = _collect(paused)

        assert codes[-1] == 0
        every = ["a1", "a2", "b1", "c1"]
        assert _held(paused) == {action: every for action in _actions(paused)}

    def test_a_file_removed_is_not_written_back_when_the_batch_is_collected(self, paused):
        (paused / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "b.json").unlink()

        codes = _collect(paused)

        assert codes[-1] == 0
        assert _held(paused) == {action: ["a1", "a2"] for action in _actions(paused)}

    def test_a_record_changed_or_added_in_a_file_is_answered(self, paused):
        _stage(paused, "b.json", [{"id": "b1", "n": 9}, {"id": "b2", "n": 5}])

        codes = _collect(paused)

        assert codes[-1] == 0
        assert _held(paused, "n") == {action: [1, 2, 5, 9] for action in _actions(paused)}

    def test_no_change_collects_the_batch_as_before(self, paused):
        codes = _collect(paused)

        assert codes[-1] == 0
        assert _ids(paused, "step3") == ["a1", "a2", "b1"]


class TestFreshWhileABatchIsOpen:
    def test_plain_fresh_is_refused(self, paused):
        code, output = _run(paused, "--fresh")

        assert code == 2, output
        assert "--fresh would drop the batch still open for tag" in output
        assert "--abandon-in-flight" in output
        assert _collect(paused)[-1] == 0
        assert _ids(paused, "step3") == ["a1", "a2", "b1"]

    def test_fresh_with_abandon_in_flight_drops_the_batch_and_starts_again(self, paused):
        code, output = _run(paused, "--fresh", "--abandon-in-flight")

        assert code == 4, output
        assert "--fresh: cleared stored results" in output

    def test_abandon_in_flight_without_fresh_is_refused(self, paused):
        code, output = _run(paused, "--abandon-in-flight")

        assert code == 2, output
        assert "--abandon-in-flight goes with --fresh" in output
