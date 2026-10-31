"""An action answered again keeps no prompt trace from before; one left as it is keeps them.

``--rerun``, or an action's output gone missing, asks every record again, so the traces of
the run it replaces describe answers that no longer stand. They were left beside the new
ones, for the action and every reader reset with it, until retention pruned them. A config
edit alone asks nothing again, so the traces of the answers that stand stay. A retry, which
answers only what failed, keeps the traces of what it does not ask again.

Every run is an `agac run` or `agac retry` through the CLI, executor, store and mock
provider.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.providers.agac.client import AgacClient

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"
PUBLISHER = "publish"
OLD = "Summarise the page in one sentence"
NEW = "Summarise the page in five words"
PAGES = {
    "pages1.json": ["Page alpha.", "Page beta."],
    "pages2.json": ["Page gamma.", "Page delta."],
}
RECORDS = sum(len(pages) for pages in PAGES.values())
PUBLISH_ACTION = f"""  - name: {PUBLISHER}
    intent: "Publish"
    dependencies: [{ACTION}]
    schema: batch_field_rules_output
    prompt: $p.Publish
    context_scope: {{ observe: [{ACTION}.summary] }}
    expect: {{ repair: none }}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Four pages in two files, answered by the mock provider, and a reader."""
    from agent_actions.utils import path_utils

    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    config = _config(root)
    config.write_text(
        config.read_text()
        .replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        .rstrip("\n")
        + "\n"
        + PUBLISH_ACTION
    )
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging)
    staging.mkdir()
    for name, pages in PAGES.items():
        (staging / name).write_text(json.dumps([{"page_content": page} for page in pages]))
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return root


@pytest.fixture
def online(project):
    config = _config(project)
    config.write_text(config.read_text().replace("run_mode: batch", "run_mode: online"))
    return project


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _run(*args):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])
    assert result.exit_code == 0, result.output
    return result


def _run_to_completion(*args):
    """A batch action is submitted by one run and collected by the next."""
    for attempt in range(3):
        _run(*(args if attempt == 0 else ()))


def _backend(root):
    from agent_actions.config.project_paths import ProjectPathsFactory
    from agent_actions.storage import get_storage_backend

    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _traces(root, action):
    backend = _backend(root)
    try:
        return backend.get_prompt_traces(action)
    finally:
        backend.close()


def _edit_prompt(root):
    prompts = root / "prompt_store" / "p.md"
    text = prompts.read_text()
    assert OLD in text
    prompts.write_text(text.replace(OLD, NEW))


def _assert_one_run_of_traces(root, action):
    traces = _traces(root, action)
    assert len(traces) == RECORDS, [t["compiled_prompt"][:40] for t in traces]
    assert len({t["source_guid"] for t in traces}) == RECORDS
    assert len({t["run_id"] for t in traces}) == 1
    return traces


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_an_edit_keeps_the_traces_that_stand_until_a_rerun_leaves_only_the_new_ones(project, mode):
    if mode == "online":
        config = _config(project)
        config.write_text(config.read_text().replace("run_mode: batch", "run_mode: online"))
    _run_to_completion("--fresh")
    first_run = {t["run_id"] for t in _traces(project, PUBLISHER)}
    first_summaries = _assert_one_run_of_traces(project, ACTION)
    assert all(OLD in t["compiled_prompt"] for t in first_summaries)
    _edit_prompt(project)

    _run_to_completion()

    kept = _assert_one_run_of_traces(project, ACTION)
    assert {t["run_id"] for t in kept} == {t["run_id"] for t in first_summaries}
    assert all(OLD in t["compiled_prompt"] for t in kept)
    assert all(NEW not in t["compiled_prompt"] for t in kept)
    assert {t["run_id"] for t in _assert_one_run_of_traces(project, PUBLISHER)} == first_run

    _run_to_completion("--rerun", ACTION)

    summaries = _assert_one_run_of_traces(project, ACTION)
    assert all(NEW in t["compiled_prompt"] for t in summaries)
    assert all(OLD not in t["compiled_prompt"] for t in summaries)
    published = _assert_one_run_of_traces(project, PUBLISHER)
    assert {t["run_id"] for t in published}.isdisjoint(first_run)


def test_an_action_whose_output_is_gone_keeps_only_the_traces_of_its_new_answers(online):
    _run("--fresh")
    first_run = {t["run_id"] for t in _traces(online, ACTION)}
    backend = _backend(online)
    try:
        backend.delete_target(ACTION)
    finally:
        backend.close()

    _run()

    for action in (ACTION, PUBLISHER):
        traces = _assert_one_run_of_traces(online, action)
        assert {t["run_id"] for t in traces}.isdisjoint(first_run)


def test_a_retry_keeps_the_traces_of_the_records_it_does_not_ask_again(online, monkeypatch):
    answer = AgacClient.call_json
    refused = {"on": True}

    def beta_is_refused(api_key, agent_config, prompt_config, context_data, schema):
        if refused["on"] and "Page beta." in json.dumps([prompt_config, context_data], default=str):
            raise ValueError("the provider refused this page")
        return answer(api_key, agent_config, prompt_config, context_data, schema)

    monkeypatch.setattr(AgacClient, "call_json", staticmethod(beta_is_refused))
    CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    before = {t["source_guid"]: t["run_id"] for t in _traces(online, ACTION)}
    refused["on"] = False

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    after = _traces(online, ACTION)
    assert len({t["source_guid"] for t in after}) == RECORDS
    kept = [t for t in after if before.get(t["source_guid"]) == t["run_id"]]
    assert len({t["source_guid"] for t in kept}) >= RECORDS - 1
