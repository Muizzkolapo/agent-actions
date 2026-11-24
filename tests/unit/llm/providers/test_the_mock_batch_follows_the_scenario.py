"""The mock batch client follows the sandbox scenario as the online mock does.

At collect time each record's result line carries the scenario's fault until it heals,
leaves out a dropped result on its first submission only, breaks rules and pins fields,
and a judge's side call passes at ``judge.pass_rate``. A ``records`` match reads the
record's whole input, a field the prompt prints included. The batch of a named action
fails, and a batch is held for its first ``polls_until_complete`` status checks and until
``complete_after_seconds`` have passed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.config import sandbox
from agent_actions.expectations.judge import build_judge_prompt
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.batch_base import BatchTask
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.constants import RECORD_GUID_KEY

ACTIONS = {"extract": None, "vote_1": "vote", "vote_2": "vote"}
SCHEMA = {
    "type": "object",
    "properties": {"code": {"type": "string"}, "tone": {"type": "string"}},
    "required": ["code", "tone"],
}
CODE_RULE = {
    "expectations": [
        {
            "id": "code_shape",
            "type": "matches_regex",
            "field": "code",
            "params": {"pattern": "^[A-Z]{3}-[0-9]{2}$"},
        }
    ]
}


@pytest.fixture
def project(tmp_path):
    from agent_actions.config.paths import PathManager
    from agent_actions.utils import path_utils

    previous = path_utils._global_path_manager
    path_utils.set_path_manager(PathManager(project_root=tmp_path))
    yield tmp_path
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    AgacBatchClient._contracts_by_batch.clear()
    path_utils._global_path_manager = previous


def _config(action: str, **extra) -> dict:
    return {
        "name": action,
        "model_name": "agac-model",
        "json_mode": True,
        "compiled_schema": SCHEMA,
        # The prompt prints source.page_id, so the request's context block leaves it out.
        "prompt": "Label page {{ source.page_id }}.",
        **extra,
    }


def _submit(project: Path, client: AgacBatchClient, rows: list[dict], config: dict) -> str:
    tasks = client.prepare_tasks(rows, config)
    path = project / "input.jsonl"
    path.write_text("\n".join(json.dumps(task) for task in tasks))
    batch_id, _ = client._submit_to_provider_api(path, "input")
    return batch_id


def _rows(pages: list[str]) -> list[dict]:
    return [
        {
            "target_id": page,
            "content": {"source": {"page_id": page, "text": f"text of {page}"}},
            "prompt": f"Label page {page}.",
            RECORD_GUID_KEY: f"g-{page}",
        }
        for page in pages
    ]


def _collect(
    project: Path, scenario: str, pages: list[str], *, action="extract", **config
) -> tuple[list[dict], str]:
    """One submit and collect under *scenario*: a run of its own over the project's store."""
    (project / "sandbox.yml").write_text(scenario)
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(project, ACTIONS)
        store = SQLiteBackend.create(db_path=str(project / "wf.sandbox.db"), workflow_name="wf")
        store.initialize()
        sandbox.attach_store(store)
        client = AgacBatchClient()
        batch_id = _submit(project, client, _rows(pages), _config(action, **config))
        lines = client._fetch_raw_results(batch_id).decode().splitlines()
        summary = sandbox.scenario_summary()
    return [json.loads(line) for line in lines], summary


def _answers(lines: list[dict]) -> dict[str, dict]:
    return {
        line["custom_id"]: json.loads(line["response"]["body"]["choices"][0]["message"]["content"])
        for line in lines
    }


def test_a_scenario_error_is_the_record_s_failed_line_until_it_heals(project):
    scenario = "defaults:\n  errors: {rate: 1.0, kinds: [rate_limit], heal_on_attempt: 2}\n"

    first, summary = _collect(project, scenario, ["p1"])
    second, _ = _collect(project, scenario, ["p1"])

    assert first[0]["response"]["status_code"] == 429
    assert "1 errors" in summary
    assert second[0]["response"]["status_code"] == 200


def test_a_dropped_result_is_left_out_of_the_first_submission_only(project):
    first, summary = _collect(project, "batch: {drop_rate: 1.0}\n", ["p1", "p2"])
    second, _ = _collect(project, "batch: {drop_rate: 1.0}\n", ["p1", "p2"])

    assert first == []
    assert "2 batch results dropped" in summary
    assert [line["custom_id"] for line in second] == ["p1", "p2"]


def test_a_record_match_reads_a_field_the_prompt_prints(project):
    scenario = (
        "records:\n  - match: {source.page_id: p2}\n    actions: {extract: {error: refusal}}\n"
    )

    lines, summary = _collect(project, scenario, ["p1", "p2", "p3"])

    messages = {
        line["custom_id"]: line["response"]["body"]["choices"][0]["message"] for line in lines
    }
    assert messages["p2"]["refusal"] and messages["p2"]["content"] is None
    assert messages["p1"]["content"] and messages["p3"]["content"]
    assert "1 errors" in summary


def test_a_broken_rule_and_a_pinned_field_reach_the_result_line(project):
    scenario = (
        "actions:\n  extract:\n    break_rules: {rules: [matches_regex], rate: 1.0}\n"
        "    pin: {tone: stormy}\n"
    )

    lines, summary = _collect(project, scenario, ["p1", "p2"], expect=CODE_RULE)

    answers = _answers(lines)
    assert {answer["tone"] for answer in answers.values()} == {"stormy"}
    for answer in answers.values():
        code = answer["code"]
        assert not (len(code) == 6 and code[:3].isupper() and code[3] == "-"), code
    assert "2 rules broken" in summary


def test_the_honest_answer_meets_the_rule_the_scenario_breaks(project):
    lines, _ = _collect(project, "seed: 1\n", ["p1", "p2"], expect=CODE_RULE)

    for answer in _answers(lines).values():
        code = answer["code"]
        assert len(code) == 6 and code[:3].isupper() and code[3] == "-", code


def _judged(project: Path, scenario: str) -> list[bool]:
    (project / "sandbox.yml").write_text(scenario)
    rows = [
        {
            "target_id": f"j{n}",
            "prompt": build_judge_prompt("is calm", f"v {n}", None),
            "content": "",
        }
        for n in range(12)
    ]
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(project, ACTIONS)
        client = AgacBatchClient()
        config = {"name": "extract", "model_name": "agac-model", "json_mode": False}
        batch_id = _submit(project, client, rows, config)
        lines = client._fetch_raw_results(batch_id).decode().splitlines()
    return [
        json.loads(json.loads(line)["response"]["body"]["choices"][0]["message"]["content"])[
            "passed"
        ]
        for line in lines
    ]


@pytest.mark.parametrize(("rate", "verdicts"), [("1.0", {True}), ("0.0", {False})])
def test_a_batch_judge_passes_at_its_pass_rate(project, rate, verdicts):
    assert set(_judged(project, f"defaults:\n  judge: {{pass_rate: {rate}}}\n")) == verdicts


def test_a_batch_of_an_action_the_scenario_fails_reports_failed(project):
    (project / "sandbox.yml").write_text("batch: {fail: [vote]}\n")
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(project, ACTIONS)
        client = AgacBatchClient()
        failing = _submit(project, client, _rows(["p1"]), _config("vote_2"))
        passing = _submit(project, client, _rows(["p1"]), _config("extract"))

        assert client._fetch_status(failing) == "failed"
        assert client._fetch_status(passing) == "completed"


def _statuses(project: Path, scenario: str, checks: int) -> list[str]:
    (project / "sandbox.yml").write_text(scenario)
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(project, ACTIONS)
        client = AgacBatchClient()
        batch_id = _submit(project, client, _rows(["p1"]), _config("extract"))
        return [client._fetch_status(batch_id) for _ in range(checks)]


def test_a_batch_completes_at_its_first_status_check_by_default(project):
    assert _statuses(project, "seed: 1\n", 1) == ["completed"]


def test_polls_until_complete_alone_holds_the_batch_for_that_many_checks(project):
    statuses = _statuses(project, "batch: {polls_until_complete: 2}\n", 3)

    assert statuses == ["in_progress", "in_progress", "completed"]


def test_a_batch_waits_both_its_checks_and_its_seconds(project):
    statuses = _statuses(
        project, "batch: {polls_until_complete: 1, complete_after_seconds: 999}\n", 4
    )

    assert statuses == ["in_progress"] * 4


class _Recording(AgacBatchClient):
    def __init__(self) -> None:
        super().__init__()
        self.formatted: list[tuple[BatchTask, dict]] = []

    def format_task_for_provider(self, batch_task, schema=None):
        request = super().format_task_for_provider(batch_task, schema)
        self.formatted.append((batch_task, request))
        return request


def test_no_request_and_no_task_metadata_carries_the_record_s_guid(project):
    client = _Recording()

    client.prepare_tasks(_rows(["p1"]), _config("extract"))

    [(batch_task, request)] = client.formatted
    assert RECORD_GUID_KEY not in (batch_task.metadata or {})
    assert RECORD_GUID_KEY not in json.dumps(request)
