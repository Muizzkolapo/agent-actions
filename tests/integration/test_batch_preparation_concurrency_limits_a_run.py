"""`batch_preparation_concurrency` reaches the step of an `agac run`, and its batch actions take
turns.

Two batch actions and one online action read the same upstream in one step. With the
key at 1, no two batch preparations overlap, and the online action still runs (#1865).
"""

import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.exit_codes import EXIT_PAUSED
from agent_actions.cli.main import cli
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "prepare_in_turn"

_CONFIG = """\
name: prepare_in_turn
description: "Two batch actions and one online action in one step"
version: "0.1.0"
batch_preparation_concurrency: 1
defaults:
  json_mode: true
  granularity: Record
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: first
    intent: "Summarise"
    run_mode: batch
    prompt: $prepare_in_turn.Summarize
    schema: { summary: string }
    context_scope: { observe: [source.page_content] }
  - name: second
    intent: "Summarise"
    run_mode: batch
    prompt: $prepare_in_turn.Summarize
    schema: { summary: string }
    context_scope: { observe: [source.page_content] }
  - name: beside
    intent: "Summarise"
    run_mode: online
    prompt: $prepare_in_turn.Summarize
    schema: { summary: string }
    context_scope: { observe: [source.page_content] }
"""

_PROMPTS = """\
{prompt Summarize}
Summarise this page.
{{ source.page_content }}
{end_prompt}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    for name in ("one.json", "two.json"):
        staging.joinpath(name).write_text(
            json.dumps([{"page_id": f"{name}{i}", "page_content": f"page {i}"} for i in range(4)])
        )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    monkeypatch.chdir(root)
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    return root


def test_the_batch_actions_of_a_step_prepare_in_turn(project, monkeypatch):
    limits: list[object] = []
    spans: list[tuple[str, float, float]] = []
    lock = threading.Lock()

    run_level = ActionLevelOrchestrator._execute_parallel_actions

    async def noted_level(self, params):
        limits.append((params.batch_preparation_concurrency, sorted(params.batch_preparing)))
        return await run_level(self, params)

    prepare = BatchTaskPreparator.prepare_tasks

    def timed_prepare(self, agent_config, *args, **kwargs):
        started = time.perf_counter()
        # Long enough that two preparations allowed to run together would overlap.
        time.sleep(0.2)
        try:
            return prepare(self, agent_config, *args, **kwargs)
        finally:
            with lock:
                spans.append((agent_config["action_name"], started, time.perf_counter()))

    monkeypatch.setattr(ActionLevelOrchestrator, "_execute_parallel_actions", noted_level)
    monkeypatch.setattr(BatchTaskPreparator, "prepare_tasks", timed_prepare)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

    assert result.exit_code == EXIT_PAUSED, result.output
    assert limits == [(1, ["first", "second"])]
    assert sorted(name for name, _, _ in spans) == ["first", "first", "second", "second"]
    for name, start, end in spans:
        for other, other_start, other_end in spans:
            if other != name:
                assert end <= other_start or other_end <= start, spans
    assert "beside" in result.output


def test_a_batch_action_gives_its_turn_back_once_its_batch_is_sent(project, monkeypatch):
    """The turn covers preparing and sending a batch, not waiting for its results.

    The provider keeps every batch pending. The second batch action must still send its
    batch in the first pass; `--wait` then waits outside the actions, between passes.
    """
    from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
    from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
    from agent_actions.storage import get_storage_backend

    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "3600")
    sent: list[str] = []
    submit = AgacBatchClient._submit_to_provider_api

    def noted_submit(self, input_file, batch_name):
        sent.append(batch_name)
        return submit(self, input_file, batch_name)

    monkeypatch.setattr(AgacBatchClient, "_submit_to_provider_api", noted_submit)
    outcome: list[object] = []
    args = ["run", "-a", WORKFLOW, "--fresh", "--wait", "--poll", "1", "--wait-timeout", "2"]
    run = threading.Thread(
        target=lambda: outcome.append(CliRunner().invoke(cli, args)), daemon=True
    )
    run.start()
    run.join(60)

    assert not run.is_alive(), f"the run waited for a pending batch; sent so far: {sent}"
    (result,) = outcome
    assert result.exit_code == EXIT_PAUSED, result.output
    assert sorted(sent) == ["one.json", "one.json", "two.json", "two.json"], sent
    store_dir = project / "agent_workflow" / WORKFLOW
    backend = get_storage_backend(workflow_path=str(store_dir), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        for action in ("first", "second"):
            assert BatchRegistryManager(backend, action).has_uncollected_jobs(), action
    finally:
        backend.close()
