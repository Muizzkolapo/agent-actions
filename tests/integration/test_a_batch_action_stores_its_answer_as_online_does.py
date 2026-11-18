"""A batch action stores its model's answer as the same action online does, through `agac run`.

Two things an action could do online and not in a batch. With `json_mode: false` it stored
the reply as text, where the batch stored whatever JSON the reply happened to quote. With
`json_mode: true` and no schema it ran, where the batch was refused before it started.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "answers_both_ways"
REPLY = "Here is a list: [1, 2, 3] done"

_CONFIG = """\
name: answers_both_ways
description: "One action with no schema"
version: "0.1.0"
defaults:
  json_mode: {json_mode}
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    prompt: $answers_both_ways.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""

_PROMPTS = """\
{prompt Summarize}
Summarise this page as JSON.
## PAGE
{{ source.page_content }}
{end_prompt}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "dbt models are SELECT statements."}])
    )
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    monkeypatch.chdir(root)
    # The in-process CLI does not read the project's .env.
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    return root


def _run(project, *, run_mode: str, json_mode: bool):
    """Run the workflow to its end in the given mode; a batch takes a second run to collect."""
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(_CONFIG.format(run_mode=run_mode, json_mode=str(json_mode).lower()))
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    if run_mode == "batch" and result.exit_code == 0:
        assert "run again" in result.output, "the batch did not pause on submission"
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])
    return result


def _stored(project) -> list[dict]:
    """What `summarize` stored under its own name, one entry per record."""
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return [
            row["content"]["summarize"] for row in backend.read_target("summarize", "pages.json")
        ]
    finally:
        backend.close()


@pytest.fixture
def model_writes_the_reply(monkeypatch):
    """The mock model writes REPLY, to an online call and on a batch line alike."""

    def online_reply(api_key, agent_config, prompt_config, context_data):
        return ResponseBuilder.wrap_non_json(REPLY, agent_config)

    answer = FakeDataGenerator.generate_openai_response.__func__

    def batch_reply(cls, custom_id, schema, prompt=None, attempt=1):
        response = answer(cls, custom_id, schema, prompt, attempt)
        response["choices"][0]["message"]["content"] = REPLY
        return response

    monkeypatch.setattr(AgacClient, "call_non_json", staticmethod(online_reply))
    monkeypatch.setattr(FakeDataGenerator, "generate_openai_response", classmethod(batch_reply))


def test_a_text_action_stores_the_reply_as_text_in_both_modes(project, model_writes_the_reply):
    online = _run(project, run_mode="online", json_mode=False)
    assert online.exit_code == 0, online.output
    stored_online = _stored(project)

    batch = _run(project, run_mode="batch", json_mode=False)
    assert batch.exit_code == 0, batch.output

    assert stored_online == [{"raw_response": REPLY}]
    assert _stored(project) == stored_online


def test_a_json_action_with_no_schema_runs_in_both_modes(project):
    online = _run(project, run_mode="online", json_mode=True)
    assert online.exit_code == 0, online.output
    assert len(_stored(project)) == 1

    batch = _run(project, run_mode="batch", json_mode=True)

    assert batch.exit_code == 0, batch.output
    assert "Schema is required" not in batch.output
    (stored,) = _stored(project)
    assert stored and "_parse_error" not in stored
