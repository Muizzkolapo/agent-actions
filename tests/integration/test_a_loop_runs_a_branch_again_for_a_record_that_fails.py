"""A `- loop:` entry runs a branch again for each record whose check failed, up to N times.

`spec`, a tool, writes each record's topic and the try at which its check passes. The loop
`round` runs the branch `question_round` up to 3 times: `write`, an LLM action, writes a
question, and `check`, a tool, passes it once the record's try is reached. `check` reads
the previous iteration's check as the feedback input `prior`, which holds none in
iteration 1. `publish` reads the loop's name only. Every tool logs a line per call to
`calls.log`, so a test sees what ran. Each claim holds in both run modes: the LLM action
runs against the provider mock under `run_mode: online` and `run_mode: batch`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_PAUSED, EXIT_RECORD_FAILURES, EXIT_SUCCESS
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

WORKFLOW = "loop_flow"
RUN_MODES = pytest.mark.parametrize("run_mode", ["online", "batch"])
ENV = {"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
CALLS = "calls.log"
FAULT = "fault.json"

TOOLS = f"""import json
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


def _log(line: str) -> None:
    with open({CALLS!r}, "a") as calls:
        calls.write(line + "\\n")


@udf_tool
def make_spec(data: Any, *args) -> dict:
    source = data["source"]
    return {{"topic": source["topic"], "passes_at": source["passes_at"]}}


@udf_tool
def check_question(data: Any, *args) -> dict:
    spec = data.get("spec") or {{}}
    prior = data.get("prior") or {{}}
    tries = int(prior.get("tries") or 0) + 1
    fault = Path({FAULT!r})
    if fault.exists():
        stop = json.loads(fault.read_text())
        if stop["topic"] == spec.get("topic") and stop["try"] == tries:
            if stop.get("interrupt"):
                raise KeyboardInterrupt()
            raise RuntimeError("the check broke")
    _log("check:" + str(spec.get("topic")) + ":" + str(tries))
    passed = tries >= int(spec["passes_at"])
    return {{
        "passed": passed,
        "reasons": "" if passed else "too vague at try " + str(tries),
        "tries": tries,
        "question": (data.get("write") or {{}}).get("question"),
    }}


@udf_tool
def publish_item(data: Any, *args) -> dict:
    round_ = data.get("round") or {{}}
    _log("publish:" + str((data.get("spec") or {{}}).get("topic")))
    return {{"tries": round_.get("tries"), "passed": round_.get("passed")}}
"""

PROMPTS = """\
{prompt Write}
Write one exam question about: {{ spec.topic }}
{% if prior %}The last one failed: {{ prior.reasons }}{% endif %}
{end_prompt}
"""

BRANCH = """\
branch: question_round
description: Write a question, then check it
inputs:
  spec: the topic of the record
  prior: the check of the previous iteration
outputs: [check]
actions:
  - name: write
    intent: Write the question
    prompt: $loop_flow.Write
    schema: draft
    dependencies: [spec]
    context_scope: { observe: [spec.topic, prior.*] }
  - name: check
    kind: tool
    impl: check_question
    intent: Check the question
    schema: verdict
    dependencies: [write, spec]
    context_scope: { observe: [write.question, spec.passes_at, spec.topic, prior.*] }
"""

CONFIG = """\
name: loop_flow
description: "A loop of three over a write and a check"
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
  - name: spec
    kind: tool
    impl: make_spec
    intent: Read the topic
    schema: spec_out
    context_scope: {{ observe: [source.*] }}
  - loop: round
    include: question_round
    max_iterations: {max_iterations}
    inputs: {{ spec: spec }}
    feedback: {{ prior: check }}
    until: check.passed == true
    result: check
  - name: publish
    kind: tool
    impl: publish_item
    intent: Publish
    schema: published
    dependencies: [round]
    context_scope: {{ observe: [round.*, spec.topic] }}
"""

SCHEMAS = {
    "spec_out": "fields:\n  - {id: topic, type: string, required: true}\n  - {id: passes_at, type: integer, required: true}\n",
    "draft": "fields:\n  - {id: question, type: string, required: true}\n",
    "verdict": (
        "fields:\n  - {id: passed, type: boolean, required: true}\n  - {id: reasons, type: string, required: true}\n"
        "  - {id: tries, type: integer, required: true}\n  - {id: question, type: string, required: true}\n"
    ),
    "published": "fields:\n  - {id: tries, type: integer, required: true}\n  - {id: passed, type: boolean, required: true}\n",
}


def _project(base: Path, run_mode: str, passes_at: dict[str, int], max_iterations=3) -> Path:
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
    for name, text in SCHEMAS.items():
        (schemas / f"{name}.yml").write_text(f"name: {name}\n{text}")
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    (root / "branches" / "question_round.yml").write_text(BRANCH)
    (root / "tools" / WORKFLOW / "flow_tools.py").write_text(TOOLS)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        CONFIG.format(run_mode=run_mode, max_iterations=max_iterations)
    )
    (directory / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"topic": t, "passes_at": n} for t, n in passes_at.items()])
    )
    return root


def _agac(root: Path, *args: str) -> tuple[int, str]:
    result = run_agac(root, *args, "-a", WORKFLOW, env=ENV)
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _run_to_the_end(root: Path, *first: str, ends: int = EXIT_SUCCESS) -> str:
    """Run until the workflow stops asking to be run again; the last run exits *ends*."""
    code, output = _agac(root, "run", *first)
    transcript = [output]
    while code == EXIT_PAUSED:
        assert "run again" in transcript[-1], transcript[-1]
        assert len(transcript) <= 12, "the workflow never stopped asking to be run again"
        code, output = _agac(root, "run")
        transcript.append(output)
    assert code == ends, transcript[-1]
    assert "run again" not in transcript[-1], transcript[-1]
    return "\n".join(transcript)


def _backend(root: Path):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _rows(root: Path, action: str) -> list[dict]:
    backend = _backend(root)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _topics(root: Path, action: str) -> list[str]:
    return sorted(row["content"]["spec"]["topic"] for row in _rows(root, action))


def _calls(root: Path) -> list[str]:
    path = root / CALLS
    return path.read_text().split() if path.exists() else []


def _statuses(root: Path) -> dict[str, str]:
    status = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return {name: entry["status"] for name, entry in json.loads(status.read_text()).items()}


@RUN_MODES
def test_8_1_each_action_runs_twice_for_a_record_that_passes_in_iteration_2(tmp_path, run_mode):
    root = _project(tmp_path, run_mode, {"early": 1, "late": 2})

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert _topics(root, "round_iter1__write") == ["early", "late"], transcript
    assert _topics(root, "round_iter1__check") == ["early", "late"]
    assert _topics(root, "round_iter2__write") == ["late"]
    assert _topics(root, "round_iter2__check") == ["late"]
    assert _topics(root, "round_iter3__write") == []
    assert _topics(root, "round_iter3__check") == []
    checks = sorted(c for c in _calls(root) if c.startswith("check:"))
    assert checks == ["check:early:1", "check:late:1", "check:late:2"]


@pytest.fixture(params=["online", "batch"])
def three(tmp_path, request):
    root = _project(tmp_path, request.param, {"early": 1, "late": 2, "never": 9})
    return root, _run_to_the_end(root, "--fresh")


def _round(root: Path) -> dict[str, dict]:
    """The output of `round` by topic, for each record it holds an output of."""
    return {
        row["content"]["spec"]["topic"]: row["content"]["round"]
        for row in _rows(root, "round")
        if isinstance(row["content"].get("round"), dict)
    }


def _dispositions(root: Path, action: str) -> list[tuple[str, str | None]]:
    backend = _backend(root)
    try:
        return sorted(
            (row["disposition"], row.get("reason"))
            for row in backend.get_disposition(action, snapshots=False)
        )
    finally:
        backend.close()


def test_the_loop_name_holds_every_record_exactly_once(three):
    root, transcript = three

    topics = sorted(row["content"]["spec"]["topic"] for row in _rows(root, "round"))
    assert topics == ["early", "late", "never"], transcript
    assert sorted(c for c in _calls(root) if c.startswith("publish:")) == [
        "publish:early",
        "publish:late",
        "publish:never",
    ]


def test_the_loop_name_holds_the_result_of_the_iteration_that_passed(three):
    root, _ = three

    by_topic = _round(root)
    assert (by_topic["early"]["tries"], by_topic["early"]["passed"]) == (1, True)
    assert (by_topic["late"]["tries"], by_topic["late"]["passed"]) == (2, True)


def test_a_record_that_never_passes_holds_the_result_of_the_last_iteration(three):
    root, _ = three

    never = _round(root)["never"]
    assert (never["tries"], never["passed"]) == (3, False)
    assert never["reasons"] == "too vague at try 3"
    assert _topics(root, "round_iter3__check") == ["never"]


def test_a_record_that_passed_is_sent_elsewhere_and_never_reported_as_filtered(three):
    root, transcript = three

    assert not re.search(r"\b[1-9]\d* filtered", transcript), transcript
    assert _dispositions(root, "round_iter2__write") == [
        ("filtered", "sent_elsewhere"),
        ("success", None),
        ("success", None),
    ]
    assert _dispositions(root, "round_iter3__write") == [
        ("filtered", "sent_elsewhere"),
        ("success", None),
    ]


def test_8_2_a_stop_after_iteration_1_resumes_at_iteration_2_in_batch(tmp_path):
    """Each batch run stops once it has submitted a batch: the run that submits
    iteration 2's write has finished iteration 1, and no run after it repeats it."""
    root = _project(tmp_path, "batch", {"early": 1, "late": 2})
    code, output = _agac(root, "run", "--fresh")
    stopped_after_iteration_1 = None
    runs = 0
    while code == EXIT_PAUSED:
        assert "run again" in output, output
        runs += 1
        assert runs <= 12, output
        statuses = _statuses(root)
        if (
            stopped_after_iteration_1 is None
            and statuses.get("round_iter1__check") == "completed"
            and statuses.get("round_iter2__check") != "completed"
        ):
            stopped_after_iteration_1 = list(_calls(root))
        code, output = _agac(root, "run")
    assert code == 0, output

    assert stopped_after_iteration_1 is not None
    assert sorted(stopped_after_iteration_1) == ["check:early:1", "check:late:1"]
    checks = sorted(c for c in _calls(root) if c.startswith("check:"))
    assert checks == ["check:early:1", "check:late:1", "check:late:2"]
    assert _topics(root, "round_iter1__write") == ["early", "late"]
    assert _topics(root, "round_iter2__check") == ["late"]


def test_8_2_a_stop_inside_iteration_2_resumes_there_and_does_not_run_iteration_1_again(
    tmp_path,
):
    root = _project(tmp_path, "online", {"early": 1, "late": 2})
    (root / FAULT).write_text(json.dumps({"topic": "late", "try": 2, "interrupt": True}))
    code, output = _agac(root, "run", "--fresh")
    assert sorted(_calls(root)) == ["check:early:1", "check:late:1"], output
    assert _statuses(root).get("round_iter1__check") == "completed", output
    (root / FAULT).unlink()

    code, output = _agac(root, "run")

    assert code == 0, output
    assert "round_iter1__write 2 records in" not in output, output
    assert "round_iter1__check 2 records in" not in output, output
    checks = sorted(c for c in _calls(root) if c.startswith("check:"))
    assert checks == ["check:early:1", "check:late:1", "check:late:2"], output
    assert set(_statuses(root).values()) == {"completed"}, output
    assert _round(root)["late"]["tries"] == 2


@RUN_MODES
def test_retry_after_a_failure_inside_an_iteration_runs_that_iteration_on(tmp_path, run_mode):
    root = _project(tmp_path, run_mode, {"early": 1, "late": 2, "never": 9})
    (root / FAULT).write_text(json.dumps({"topic": "late", "try": 2}))
    transcript = _run_to_the_end(root, "--fresh", ends=EXIT_RECORD_FAILURES)
    assert sorted(_round(root)) == ["early", "never"], transcript
    (root / FAULT).unlink()

    code, output = _agac(root, "retry")
    while code == EXIT_PAUSED:
        assert "run again" in output, output
        code, output = _agac(root, "run")

    assert code == 0, output
    checks = sorted(c for c in _calls(root) if c.startswith("check:"))
    assert checks == [
        "check:early:1",
        "check:late:1",
        "check:late:2",
        "check:never:1",
        "check:never:2",
        "check:never:3",
    ], output
    assert _round(root)["late"]["tries"] == 2
    assert sorted(_round(root)) == ["early", "late", "never"]


def test_8_3_inspect_shows_the_loop_as_one_node_with_its_max_iterations(tmp_path):
    root = _project(tmp_path, "online", {"early": 1})

    code, output = _agac(root, "inspect")

    assert code == 0, output
    assert (
        "round loop ×3 max, until check.passed == true (branch question_round, result check)"
        in output
    ), output
    listed = output.split("Pre-flight")[0]
    assert "round_iter" not in listed, output
    assert "3 actions" in listed, output


def test_8_3_inspect_reports_no_null_warning_for_the_fields_of_the_loops_actions(tmp_path):
    root = _project(tmp_path, "online", {"early": 1})

    code, output = _agac(root, "inspect")

    assert code == 0, output
    assert "may be null at runtime" not in output, output
    assert "namespace as null" not in output, output
