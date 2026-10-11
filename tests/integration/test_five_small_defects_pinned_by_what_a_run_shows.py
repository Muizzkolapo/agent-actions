"""Five small defects, each pinned by what its run or record shows.

1331  A record that fails before it is sent records its failure once in its state history.
1354  Pre-flight refuses a guard that names its own action.
1356  A HITL action with no `granularity` runs at FILE, as the docs say.
1296  The static check's hint for a prompt naming a non-upstream action names the dependency.
1374  An undefined bare name in a prompt is not reported as a namespace to observe.

Every project-level case is a real `agac run` through the CLI and the mock provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.strategies.online_llm import _build_prep_failed_result
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.record.envelope import RecordEnvelope, RecordState
from tests._support.agac_cli import run_agac
from tests.integration.test_an_action_reads_only_what_is_upstream_of_it import (
    CHAIN,
    _run,
    project,  # noqa: F401
)
from tests.integration.test_an_action_reads_only_what_is_upstream_of_it import (
    WORKFLOW as TOOL_WORKFLOW,
)


def _scratch_project(base: Path, workflow: str, config: str, rows: list[dict]) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / workflow
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
    )
    (directory / "agent_config" / f"{workflow}.yml").write_text(config)
    (directory / "agent_io" / "staging" / "rows.json").write_text(json.dumps(rows))
    return root


def _agac_run(root: Path, workflow: str, **env: str):
    return run_agac(
        root,
        "run",
        "-a",
        workflow,
        "--fresh",
        env={"OPENAI_API_KEY": "sk-not-used", **env},
    )


ROWS = [{"text": "one"}, {"text": "two"}]


# 1331 -------------------------------------------------------------------

ACTION = "ask"


def _failures(record, action=ACTION):
    return [
        (entry["from"], entry["to"])
        for entry in record.get("_state_history", [])
        if entry["action"] == action and entry["to"] == "failed"
    ]


def _collected(result):
    output, _ = ResultCollector.collect_results(
        [result], {}, ACTION, is_first_stage=False, storage_backend=None
    )
    (record,) = output
    return record


def test_an_online_prep_failure_is_recorded_once():
    result = _build_prep_failed_result(
        {"source_guid": "g1", "content": {"flatten": {}}},
        ProcessingContext(agent_config={}, agent_name=ACTION),
        "Template for 'ask' references undefined variables: summary",
    )

    record = _collected(result)

    assert _failures(record) == [(None, "failed")]
    assert record["_state"] == "failed"


def test_a_batch_prep_failure_is_recorded_once():
    """The tombstone is built from the context-map entry, which carries the transition
    preparation made (`active -> failed`) and no `_state` of its own."""
    entry = {"_state": "active"}
    RecordEnvelope.transition(entry, RecordState.FAILED, ACTION, "render error")
    tombstone = {"source_guid": "g1", "content": {}, "_state_history": entry["_state_history"]}
    result = ProcessingResult.failed(error="render error", source_guid="g1")
    result.data = [tombstone]

    record = _collected(result)

    assert _failures(record) == [("active", "failed")]
    assert record["_state"] == "failed"


def test_a_failure_of_another_action_is_not_taken_for_this_ones():
    """Only a failed entry this action wrote makes the stamp redundant."""
    earlier = {"_state": "active"}
    RecordEnvelope.transition(earlier, RecordState.FAILED, "flatten", "earlier failure")
    tombstone = {"source_guid": "g1", "content": {}, "_state_history": earlier["_state_history"]}
    result = ProcessingResult.failed(error="render error", source_guid="g1")
    result.data = [tombstone]

    record = _collected(result)

    assert _failures(record, "flatten") == [("active", "failed")]
    assert len(_failures(record, ACTION)) == 1


# 1354 -------------------------------------------------------------------

SELF_GUARD = "self_guard"


def _guard_config(condition: str) -> str:
    return f"""\
name: {SELF_GUARD}
description: "A guard on the action's own output"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: screen
    intent: "Screen"
    prompt: "Answer."
    schema: {{ approved: boolean, reason: string }}
    context_scope: {{ observe: [source.text] }}
  - name: decide
    dependencies: [screen]
    intent: "Decide"
    prompt: "Answer."
    schema: {{ approved: boolean }}
    guard: {{ condition: '{condition}', on_false: "filter" }}
    context_scope: {{ observe: [screen.approved, screen.reason] }}
  - name: next_action
    dependencies: [decide]
    intent: "Next"
    prompt: "Answer."
    schema: {{ done: boolean }}
    context_scope: {{ observe: [decide.approved] }}
"""


def _guard_run(base: Path, condition: str):
    root = _scratch_project(base, SELF_GUARD, _guard_config(condition), ROWS)
    return _agac_run(root, SELF_GUARD)


def test_a_guard_on_its_own_action_is_refused_before_any_record_is_sent(tmp_path):
    result = _guard_run(tmp_path, "decide.approved == true")

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "decide" in output and "guard" in output, output
    assert "reads only what is upstream" in output, output


def test_a_guard_on_an_upstream_field_still_runs(tmp_path):
    result = _guard_run(tmp_path, "screen.approved == true")

    assert result.returncode == 0, result.stdout + result.stderr


# 1356 -------------------------------------------------------------------

HITL = "hitl_granularity"


def _hitl_config(granularity_line: str) -> str:
    return f"""\
name: {HITL}
description: "A HITL action with no granularity"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: extract_data
    intent: "Extract"
    prompt: "Answer."
    schema: {{ summary: string }}
    context_scope: {{ observe: [source.text] }}
  - name: review_data
    kind: hitl
    dependencies: [extract_data]
    intent: "Human reviews extracted data before processing"
{granularity_line}    hitl:
      instructions: "Review the extracted data for accuracy"
    context_scope:
      observe:
        - extract_data.*
"""


def _hitl_run(base: Path, granularity_line: str = ""):
    root = _scratch_project(base, HITL, _hitl_config(granularity_line), ROWS)
    return _agac_run(root, HITL, AGAC_HITL_AUTO_APPROVE="true")


def test_a_hitl_action_with_no_granularity_runs(tmp_path):
    result = _hitl_run(tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "HITL actions require FILE granularity" not in output


def test_an_explicit_record_granularity_is_still_refused(tmp_path):
    result = _hitl_run(tmp_path, "    granularity: record\n")

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "HITL actions require FILE granularity" in output


# 1296 -------------------------------------------------------------------

LATE = """\
  - name: late
    dependencies: [flatten]
    intent: "late"
    prompt: "Note {{ flatten.summary }} and {{ final.summary }}"
    schema: tool_action_output
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


def _with_late(project, observe):  # noqa: F811
    config = project / "agent_workflow" / TOOL_WORKFLOW / "agent_config" / f"{TOOL_WORKFLOW}.yml"
    config.write_text(
        config.read_text().rstrip("\n")
        + "\n"
        + CHAIN
        + LATE.replace("[flatten.summary]", f"[{observe}]")
    )


def test_the_static_checks_hint_names_the_dependency_as_well_as_the_observe(project):  # noqa: F811
    _with_late(project, "flatten.summary")

    result = _run("--fresh")

    assert result.exit_code == 1, result.output
    assert "namespace 'final'" in result.output
    (hint,) = [line for line in result.output.splitlines() if "Hint:" in line]
    assert "context_scope.observe" in hint
    assert "dependencies" in hint, hint


# 1374 -------------------------------------------------------------------

CONTEXT = {"source": {"page_content": "text"}, "workflow": {"name": "wf"}}


def _warning_for(prompt: str) -> str:
    with patch("agent_actions.prompt.service.fire_event") as fired:
        with pytest.raises(AgentActionsError):
            PromptPreparationService._render_prompt_template(
                prompt, CONTEXT, agent_name="write", mode="online"
            )
    (event,) = [call.args[0] for call in fired.call_args_list if hasattr(call.args[0], "field_ref")]
    return event.message


def test_a_name_nothing_supplies_is_not_told_to_be_observed():
    message = _warning_for("{% if verbose %}Explain.{% endif %}")

    assert "'verbose'" in message
    assert "Add to context_scope.observe" not in message
    assert "nothing supplies" in message


def test_a_field_of_a_namespace_in_scope_is_told_to_be_qualified():
    message = _warning_for("Write about {{ page_content }}")

    assert "source.page_content" in message
    assert "Add to context_scope.observe" not in message
