"""`on_empty` written in a workflow is what an empty answer does.

Every reader takes `on_empty` off the action's runtime config and falls back to
`warn`, so a key the expansion of the YAML does not carry there is a `warn` whatever
the author wrote. Driven through `agac run`, because the YAML is where it went
missing: a test that hands a strategy its config directly never sees the expansion.
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
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
TOOL_WORKFLOW = "tool_action"
LLM_WORKFLOW = "batch_field_rules"
BLANK = "BLANK"

# Its own file and name: a tool module is imported once per process, so rewriting the
# fixture's `flatten_pages` would leave an earlier test's import answering for it.
BLANK_TOOL = '''import json
from typing import Any

from agent_actions import udf_tool


@udf_tool
def flatten_unless_blank(data: Any, *args) -> list[dict]:
    """Nothing for a page marked blank, one record for any other."""
    if "BLANK" in json.dumps(data):
        return []
    return [{"summary": json.dumps(data)[:80], "exam_density": "low"}]
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Two pages per workflow, the second of which gets an empty answer."""
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    for workflow in (TOOL_WORKFLOW, LLM_WORKFLOW):
        config = _config(root, workflow)
        config.write_text(
            config.read_text()
            .replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
            .replace("impl: flatten_pages", "impl: flatten_unless_blank")
        )
        staging = root / "agent_workflow" / workflow / "agent_io" / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        staging.joinpath("pages.json").write_text(
            json.dumps(
                [
                    {"page_id": "p1", "page_content": "dbt models are SELECT statements."},
                    {"page_id": "p2", "page_content": BLANK},
                ]
            )
        )
    (root / "tools" / TOOL_WORKFLOW / "flatten_unless_blank.py").write_text(BLANK_TOOL)
    monkeypatch.chdir(root)
    # The in-process CLI does not read the project's .env, and the batch client asks.
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    return root


def _config(root, workflow):
    return root / "agent_workflow" / workflow / "agent_config" / f"{workflow}.yml"


def _on_empty(root, workflow, *, action=None, defaults=None, project_default=None):
    """Write `on_empty` on the workflow's one action, its defaults, or the project's."""
    config = _config(root, workflow)
    text = config.read_text()
    if defaults is not None:
        text = text.replace("defaults:\n", f"defaults:\n  on_empty: {defaults}\n", 1)
    if action is not None:
        text = text.rstrip("\n") + f"\n    on_empty: {action}\n"
    config.write_text(text)
    if project_default is not None:
        project = root / "agent_actions.yml"
        project.write_text(
            project.read_text().replace(
                "default_agent_config:\n",
                f"default_agent_config:\n  on_empty: {project_default}\n",
                1,
            )
        )


def _run(workflow):
    return CliRunner().invoke(cli, ["run", "-a", workflow, "--fresh"])


def _dispositions(root, workflow, action):
    """Each record's disposition, and the action's own under `__node__` if it has one."""
    paths = ProjectPathsFactory.create_project_paths(
        workflow, workflow, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=workflow)
    backend.initialize()
    try:
        return {
            row["record_id"]: (row["disposition"], row.get("reason") or "")
            for row in backend.get_disposition(action)
        }
    finally:
        backend.close()


def _records(root, workflow, action):
    return sorted(
        disposition
        for record_id, (disposition, _reason) in _dispositions(root, workflow, action).items()
        if record_id != "__node__"
    )


def _halted_on_empty(root, workflow, action):
    node = _dispositions(root, workflow, action).get("__node__")
    return node is not None and node[0] == "failed" and "on_empty=error" in node[1]


class TestOnEmptyOnTheAction:
    def test_error_fails_the_action(self, project):
        _on_empty(project, TOOL_WORKFLOW, action="error")

        result = _run(TOOL_WORKFLOW)

        assert result.exit_code != 0, result.output
        assert _halted_on_empty(project, TOOL_WORKFLOW, "flatten")

    def test_skip_stores_the_empty_record_as_passed_through_not_failed(self, project):
        _on_empty(project, TOOL_WORKFLOW, action="skip")

        result = _run(TOOL_WORKFLOW)

        assert result.exit_code == 0, result.output
        assert _records(project, TOOL_WORKFLOW, "flatten") == ["passthrough", "success"]

    def test_left_unset_an_empty_answer_fails_its_record_and_the_run_goes_on(self, project):
        """`warn` is the default, and an action that does not say keeps it."""
        result = _run(TOOL_WORKFLOW)

        assert result.exit_code == 0, result.output
        assert _records(project, TOOL_WORKFLOW, "flatten") == ["failed", "success"]


class TestOnEmptyInheritedFromADefault:
    def test_the_workflow_s_defaults_reach_the_action(self, project):
        """Every other key the expansion inherits can be written under `defaults:`."""
        _on_empty(project, TOOL_WORKFLOW, defaults="skip")

        result = _run(TOOL_WORKFLOW)

        assert result.exit_code == 0, result.output
        assert _records(project, TOOL_WORKFLOW, "flatten") == ["passthrough", "success"]

    def test_the_action_s_own_overrides_the_workflow_s_defaults(self, project):
        _on_empty(project, TOOL_WORKFLOW, defaults="error", action="skip")

        result = _run(TOOL_WORKFLOW)

        assert result.exit_code == 0, result.output
        assert _records(project, TOOL_WORKFLOW, "flatten") == ["passthrough", "success"]

    def test_the_project_s_default_reaches_the_action(self, project):
        _on_empty(project, TOOL_WORKFLOW, project_default="error")

        result = _run(TOOL_WORKFLOW)

        assert result.exit_code != 0, result.output
        assert _halted_on_empty(project, TOOL_WORKFLOW, "flatten")

    def test_the_action_s_own_overrides_the_project_s_default(self, project):
        """The project's `default_agent_config:` sits under the action, as for any key."""
        _on_empty(project, TOOL_WORKFLOW, project_default="error", action="skip")

        result = _run(TOOL_WORKFLOW)

        assert result.exit_code == 0, result.output
        assert _records(project, TOOL_WORKFLOW, "flatten") == ["passthrough", "success"]


class TestAnEmptyModelAnswer:
    """The model answering `{}` for the blank page, online and in a batch."""

    def test_error_fails_an_online_action(self, project, monkeypatch):
        answer = AgacClient.call_json

        def empty_for_the_blank_page(api_key, agent_config, prompt_config, context_data, schema):
            if BLANK in f"{prompt_config}{context_data}":
                return {}
            return answer(api_key, agent_config, prompt_config, context_data, schema)

        monkeypatch.setattr(AgacClient, "call_json", staticmethod(empty_for_the_blank_page))
        config = _config(project, LLM_WORKFLOW)
        config.write_text(config.read_text().replace("run_mode: batch", "run_mode: online"))
        _on_empty(project, LLM_WORKFLOW, action="error")

        result = _run(LLM_WORKFLOW)

        assert result.exit_code != 0, result.output
        assert _halted_on_empty(project, LLM_WORKFLOW, "summarize")

    def test_error_fails_a_batch_action_once_it_is_collected(self, project, monkeypatch):
        answer = FakeDataGenerator.generate_openai_response.__func__

        def empty_for_the_blank_page(cls, custom_id, schema, prompt=None, attempt=1):
            response = answer(cls, custom_id, schema, prompt, attempt)
            if BLANK in (prompt or ""):
                response["choices"][0]["message"]["content"] = "{}"
            return response

        monkeypatch.setattr(
            FakeDataGenerator, "generate_openai_response", classmethod(empty_for_the_blank_page)
        )
        _on_empty(project, LLM_WORKFLOW, action="error")

        submitted = _run(LLM_WORKFLOW)
        assert submitted.exit_code == 0, submitted.output
        assert "run again" in submitted.output, "the fixture did not pause on submission"

        collected = CliRunner().invoke(cli, ["run", "-a", LLM_WORKFLOW])

        assert collected.exit_code != 0, collected.output
        assert _halted_on_empty(project, LLM_WORKFLOW, "summarize")
