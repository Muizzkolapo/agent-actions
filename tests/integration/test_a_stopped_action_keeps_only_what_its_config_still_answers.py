"""What a run stopped partway through an action finished is kept only while its config is
unchanged (1222).

The next run resets the action, and what that reset kept depended on the status the action
was left in alone. One interrupted, killed or stopped while collecting kept its finished
records even when its prompt or model had been edited since, and was then recorded as
complete under the new config. One stopped by an error kept nothing even when nothing had
changed, so every finished record was asked again, and paid for again.

Every run is an `agac run` through the CLI, executor, store and mock provider. Only the
fault that stops a run is stood in for, raised where the provider is called.
"""

import json
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.llm.providers.agac.client import AgacClient

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"
READER = "tally"
PAGES = {
    "pages1.json": ["Page alpha.", "Page beta."],
    "pages2.json": ["Page gamma.", "Page delta."],
}
EVERY_PAGE = sorted(page for pages in PAGES.values() for page in pages)
MODEL = "gpt-oss:120b-cloud"

READER_ACTION = f"""  - name: {READER}
    kind: tool
    dependencies: [{ACTION}]
    run_mode: online
    intent: "Tally"
    schema: tool_action_output
    impl: echo_summary
    context_scope: {{ observe: [{ACTION}.summary] }}
    expect: {{ repair: none }}
"""

PUBLISHER = "publish"
PUBLISH_ACTION = f"""  - name: {PUBLISHER}
    intent: "Publish"
    dependencies: [{ACTION}]
    schema: batch_field_rules_output
    prompt: $p.Publish
    context_scope: {{ observe: [{ACTION}.summary] }}
    expect: {{ repair: none }}
"""

ECHO_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def echo_summary(data: Any, *args) -> list[dict]:
    return [{"summary": (data or {})["summarize"]["summary"], "exam_density": "low"}]
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Four pages in two files, answered in batch by the mock provider."""
    from agent_actions.utils import path_utils

    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    config = _config(root)
    config.write_text(
        config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
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
    # A run installs a global path manager; left behind, it sends later tests' writes here.
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return root


@pytest.fixture
def online(project):
    config = _config(project)
    config.write_text(config.read_text().replace("run_mode: batch", "run_mode: online"))
    return project


class _Provider:
    """What the mock provider is asked online, and a fault raised at one of its calls."""

    def __init__(self, monkeypatch) -> None:
        self.asked: list[tuple[str, str]] = []
        self._fault: tuple[int, BaseException] | None = None
        answer = AgacClient.call_json

        def call_json(api_key, agent_config, prompt_config, context_data, schema):
            self.asked.append((_page_in(prompt_config, context_data), agent_config["model_name"]))
            if self._fault is not None and self._fault[0] == len(self.asked):
                raise self._fault[1]
            return answer(api_key, agent_config, prompt_config, context_data, schema)

        monkeypatch.setattr(AgacClient, "call_json", staticmethod(call_json))

    def stops(self, at_call: int, raising: BaseException) -> None:
        self.asked.clear()
        self._fault = (at_call, raising)

    def answers(self) -> None:
        self.asked.clear()
        self._fault = None

    def pages(self) -> list[str]:
        return sorted(page for page, _ in self.asked)


@pytest.fixture
def provider(monkeypatch):
    return _Provider(monkeypatch)


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _page_in(*sent) -> str:
    text = json.dumps(sent, default=str)
    (page,) = [page for page in EVERY_PAGE if page in text]
    return page


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _status(root, action=ACTION):
    status_file = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


def _edit_prompt(root):
    prompts = root / "prompt_store" / "p.md"
    text = prompts.read_text()
    edited = text.replace("Summarise the page in one sentence", "Summarise the page in five words")
    assert edited != text
    prompts.write_text(edited)


def _edit_model(root, model):
    config = _config(root)
    config.write_text(config.read_text().replace(f"model_name: {MODEL}", f"model_name: {model}"))


EDITS = pytest.mark.parametrize(
    ("edit", "model"),
    [
        pytest.param(_edit_prompt, MODEL, id="prompt"),
        pytest.param(
            lambda root: _edit_model(root, "other-model:1b"), "other-model:1b", id="model"
        ),
    ],
)


def _backend(root):
    from agent_actions.config.project_paths import ProjectPathsFactory
    from agent_actions.storage import get_storage_backend

    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _sent(root) -> dict[str, list[tuple[str, str]]]:
    """Each batch the mock provider was sent: its id, and the page and model of each task."""
    batches = {}
    for path in (root / ".agac" / "batch_state").glob("*.json"):
        tasks = json.loads(path.read_text())["tasks"]
        batches[path.stem] = sorted(
            (_page_in(task["prompt"]), task["model_config"]["model_name"]) for task in tasks
        )
    return batches


def _sent_since(root, before) -> list[tuple[str, str]]:
    return sorted(
        task for batch, tasks in _sent(root).items() if batch not in before for task in tasks
    )


@contextmanager
def _collecting_fails_on(file_name):
    collect = BatchProcessingService._process_single_batch_file

    def failing(self, **kwargs):
        if kwargs["file_name"] == file_name:
            raise RuntimeError("the provider dropped the connection")
        return collect(self, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(BatchProcessingService, "_process_single_batch_file", failing)
        yield


def _stop_collecting_after_the_first_file():
    """Submit both files, then collect the first and stop on the second."""
    assert _run("--fresh").exit_code == 0
    with _collecting_fails_on("pages2.json"):
        assert _run().exit_code != 0


def _stored_summaries(backend, action):
    summaries = {}
    for path in backend.list_target_files(action):
        for row in backend._read_target_raw(action, path):
            content = row.get("content") or {}
            summaries[row["source_guid"]] = (content.get(action) or {}).get("summary")
    return summaries


def _stored(root, action=ACTION):
    backend = _backend(root)
    try:
        return _stored_summaries(backend, action)
    finally:
        backend.close()


def _stored_rows(root, action=ACTION):
    backend = _backend(root)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend._read_target_raw(action, path)
        ]
    finally:
        backend.close()


def _still_holding(before, after):
    """The records whose stored answer is the one they held before."""
    return sorted(guid for guid, summary in after.items() if summary == before.get(guid))


@EDITS
def test_an_interrupted_action_asks_again_for_every_record_once_it_is_edited(
    online, provider, edit, model
):
    provider.stops(at_call=3, raising=KeyboardInterrupt())
    _run("--fresh")
    assert _status(online) == "interrupted"

    edit(online)
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == EVERY_PAGE, "answers given under the old config were kept"
    assert {asked_with for _, asked_with in provider.asked} == {model}


def test_an_interrupted_action_asks_only_for_what_it_had_not_finished(online, provider):
    provider.stops(at_call=3, raising=KeyboardInterrupt())
    _run("--fresh")

    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == ["Page delta.", "Page gamma."]


def test_an_action_stopped_by_an_error_does_not_ask_again_for_what_it_finished(online, provider):
    provider.stops(at_call=3, raising=ConfigurationError("the provider refused the key"))
    _run("--fresh")
    assert _status(online) == "failed"

    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == ["Page delta.", "Page gamma."]
    assert _status(online) == "completed"


@EDITS
def test_an_action_stopped_by_an_error_asks_again_for_every_record_once_it_is_edited(
    online, provider, edit, model
):
    provider.stops(at_call=3, raising=ConfigurationError("the provider refused the key"))
    _run("--fresh")

    edit(online)
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == EVERY_PAGE
    assert {asked_with for _, asked_with in provider.asked} == {model}


@pytest.mark.parametrize(
    "fault",
    [
        pytest.param(ConfigurationError("the provider refused the key"), id="error"),
        pytest.param(KeyboardInterrupt(), id="interrupt"),
    ],
)
def test_an_action_stopped_partway_through_a_file_after_an_edit_keeps_no_answer_from_before_it(
    online, provider, fault
):
    """The run after the edit answers the first page and stops on the second, before it
    writes their file, which still holds what the old prompt answered. The record that
    run finished must not be carried from that file, nor from the checkpoint, whose row
    lacks the lineage the stored one is given."""
    provider.answers()
    assert _run("--fresh").exit_code == 0
    before_the_edit = _stored(online)

    _edit_prompt(online)
    provider.stops(at_call=2, raising=fault)
    _run()
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    after = _stored(online)
    assert sorted(after) == sorted(before_the_edit)
    assert _still_holding(before_the_edit, after) == [], "an answer from before the edit"
    assert all(row.get("lineage") for row in _stored_rows(online))


def test_a_reader_stopped_by_an_error_after_its_source_was_edited_keeps_nothing_made_before_it(
    online,
):
    """The edit resets the reader with its source. The run after it stops the reader on
    its second record, partway through the first file, and goes on to write the second:
    the first file still holds rows made from the summaries the edit replaced."""
    config = _config(online)
    config.write_text(config.read_text().rstrip("\n") + "\n" + PUBLISH_ACTION)
    assert _run("--fresh").exit_code == 0
    before_the_edit = _stored(online, PUBLISHER)

    _edit_prompt(online)
    answer = AgacClient.call_json
    calls = []

    def refused_at_the_readers_second_record(api_key, agent_config, *args):
        calls.append(AgacClient._action_name(agent_config))
        if calls.count(PUBLISHER) == 2:
            raise ConfigurationError("the provider refused the key")
        return answer(api_key, agent_config, *args)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(AgacClient, "call_json", staticmethod(refused_at_the_readers_second_record))
        _run()
    assert _status(online, PUBLISHER) == "failed"
    result = _run()

    assert result.exit_code == 0, result.output
    after = _stored(online, PUBLISHER)
    assert sorted(after) == sorted(before_the_edit)
    assert _still_holding(before_the_edit, after) == [], "a row made from a replaced summary"


def test_a_record_the_reset_keeps_keeps_its_prompt_trace(online, provider):
    """The trace is where a stored answer's prompt is read back from."""
    provider.stops(at_call=3, raising=KeyboardInterrupt())
    _run("--fresh")

    provider.answers()
    assert _run().exit_code == 0

    backend = _backend(online)
    try:
        preview = backend.scan_data()["nodes"][ACTION]["preview"]
    finally:
        backend.close()
    assert len(preview) == len(EVERY_PAGE)
    assert [record.get("_trace") is not None for record in preview] == [True] * len(preview)


def test_a_collect_pass_stopped_by_an_error_does_not_send_what_it_collected_again(project):
    """A finished job stops its file being sent again only until it is collected, so the
    collected file is held back by its records alone."""
    _stop_collecting_after_the_first_file()

    before = _sent(project)
    _run()
    result = _run()

    assert result.exit_code == 0, result.output
    assert _sent_since(project, before) == []
    assert _status(project) == "completed"


def test_a_collect_pass_stopped_by_an_error_sends_everything_again_once_its_model_is_edited(
    project,
):
    """The second file's job is finished and waiting under the old model: collecting it
    would serve old answers under the new one."""
    _stop_collecting_after_the_first_file()
    assert _status(project) == "failed"

    _edit_model(project, "other-model:1b")
    before = _sent(project)
    _run()
    result = _run()

    assert result.exit_code == 0, result.output
    assert _sent_since(project, before) == [(page, "other-model:1b") for page in EVERY_PAGE]
    assert _status(project) == "completed"


def test_a_resumed_collect_that_fails_while_running_does_not_send_what_it_collected_again(
    project,
):
    """The reset after the first failure keeps the collected file; the one after the second
    must too, though the action failed while running and not while collecting."""
    _stop_collecting_after_the_first_file()

    def refused(*args, **kwargs):
        raise RuntimeError("the provider refused the request")

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(BatchSubmissionService, "submit_batch_job", refused)
        _run()
    assert _status(project) == "failed"

    before = _sent(project)
    _run()
    result = _run()

    assert result.exit_code == 0, result.output
    assert _sent_since(project, before) == []
    assert _status(project) == "completed"


def test_an_interrupted_retry_of_an_edited_action_leaves_the_edit_and_its_readers_to_the_next_run(
    online, provider
):
    """A retry answers only the records it names, and keeps the stamp it found so the next
    run still sees the edit. Stopped partway, that run must still apply the edit to every
    record, and to what reads them: the reader holds what it made from the old answers."""
    config = _config(online)
    config.write_text(config.read_text().rstrip("\n") + "\n" + READER_ACTION)
    (online / "tools" / WORKFLOW).mkdir(parents=True, exist_ok=True)
    (online / "tools" / WORKFLOW / "echo.py").write_text(ECHO_TOOL)

    empty = AgacClient.call_json

    def one_empty_answer(api_key, agent_config, prompt_config, context_data, schema):
        if "Page beta." in json.dumps([prompt_config, context_data], default=str):
            return [{}]
        return empty(api_key, agent_config, prompt_config, context_data, schema)

    provider.answers()
    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(AgacClient, "call_json", staticmethod(one_empty_answer))
        assert _run("--fresh").exit_code == 0
    assert _status(online) == "completed_with_failures"

    _edit_prompt(online)
    provider.stops(at_call=1, raising=KeyboardInterrupt())
    CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])
    assert _status(online) == "interrupted"

    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == EVERY_PAGE
    backend = _backend(online)
    try:
        answers = _stored_summaries(backend, ACTION)
        echoed = _stored_summaries(backend, READER)
    finally:
        backend.close()
    assert len(answers) == len(EVERY_PAGE)
    assert echoed == answers, "the reader holds what it made from answers that were replaced"


@pytest.mark.parametrize("retry_stops", [True, False], ids=["retry-interrupted", "retry-finished"])
def test_a_retry_of_an_edited_action_that_never_completed_leaves_the_edit_to_the_next_run(
    online, provider, retry_stops
):
    """No completion stamp holds this retry to the old config. The records it does not
    name were answered under what the interrupted run recorded as it started, and must
    still read so once the retry has run, or the next run carries them under the edit."""
    answer = AgacClient.call_json
    calls = []

    def beta_empty_then_interrupted(api_key, agent_config, prompt_config, context_data, schema):
        calls.append(_page_in(prompt_config, context_data))
        if len(calls) == 3:
            raise KeyboardInterrupt()
        if calls[-1] == "Page beta.":
            return [{}]
        return answer(api_key, agent_config, prompt_config, context_data, schema)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(AgacClient, "call_json", staticmethod(beta_empty_then_interrupted))
        _run("--fresh")
    assert _status(online) == "interrupted"

    _edit_prompt(online)
    if retry_stops:
        provider.stops(at_call=1, raising=KeyboardInterrupt())
    else:
        provider.answers()
    CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == EVERY_PAGE
