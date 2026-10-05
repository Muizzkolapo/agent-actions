"""A file whose every record fails after an edit keeps no answer from before it (1283).

A run in which nothing of a file was answered and something failed does not write that
file, so whatever an earlier run stored for it stands. A reset relies on the re-run writing
each file again, so after an edit such a file still held the answers the edit replaced. The
action was recorded partly complete, with exit 0, over them; a reader reset with it ran on
them and was recorded complete; and no later plain run asked for them again.

Every run is an `agac run` through the CLI, executor, store and mock provider. Only the
provider's answers are stood in for, for the pages of one file: answers that do not parse,
or one a reader's tool raises on.
"""

import json
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    ACTION,
    PAGES,
    READER,
    READER_ACTION,
    WORKFLOW,
    _backend,
    _config,
    _edit_prompt,
    _page_in,
    _run,
    _status,
    _still_holding,
    _stored,
    online,  # noqa: F401
    project,  # noqa: F401
    provider,  # noqa: F401
)

FAILING = "pages1.json"
BREAKS_THE_READER = "Breaks the tally."

# Raises for one summary, so a reader can fail on every record of one file.
READER_IMPL = "tally_unless_it_breaks"
READER_TOOL = f"""from typing import Any

from agent_actions import udf_tool


@udf_tool
def {READER_IMPL}(data: Any, *args) -> list[dict]:
    summary = (data or {{}})["summarize"]["summary"]
    with open("handed.jsonl", "a") as handed:
        handed.write(__import__("json").dumps(summary) + "\\n")
    if summary == {BREAKS_THE_READER!r}:
        raise ValueError("the tally cannot read this summary")
    return [{{"summary": summary, "exam_density": "low"}}]
"""


def _with_a_reader(root):
    config = _config(root)
    reader = READER_ACTION.replace("echo_summary", READER_IMPL)
    config.write_text(config.read_text().rstrip("\n") + "\n" + reader)
    (root / "tools" / WORKFLOW).mkdir(parents=True, exist_ok=True)
    # Named for its tool: discovery imports by module name, and another test's `echo`
    # module would be served out of sys.modules in its place.
    (root / "tools" / WORKFLOW / f"{READER_IMPL}.py").write_text(READER_TOOL)


def _handed(root):
    handed = root / "handed.jsonl"
    return [json.loads(line) for line in handed.read_text().splitlines()] if handed.exists() else []


@contextmanager
def _answering_the_failing_file(answer):
    """The provider says *answer* for each page of the failing file, online."""
    asked = AgacClient.call_json

    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        if _page_in(prompt_config, context_data) in PAGES[FAILING]:
            return [answer]
        return asked(api_key, agent_config, prompt_config, context_data, schema)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(AgacClient, "call_json", staticmethod(call_json))
        yield


def _unparsed():
    return _answering_the_failing_file(
        {"raw_response": "not json", "_parse_error": "Failed to parse JSON from LLM response"}
    )


@contextmanager
def _batch_answers_unparsed():
    """The batch provider's answer for each page of the failing file does not parse."""
    generate = FakeDataGenerator.generate_openai_response.__func__

    def unparsed(cls, custom_id, schema, prompt=None, attempt=1):
        response = generate(cls, custom_id, schema, prompt, attempt)
        if any(page in (prompt or "") for page in PAGES[FAILING]):
            response["choices"][0]["message"]["content"] = "not json"
        return response

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(FakeDataGenerator, "generate_openai_response", classmethod(unparsed))
        yield


def test_a_file_whose_every_answer_fails_after_an_edit_keeps_no_answer_from_before_it(
    online,  # noqa: F811
):
    """The other file is answered, so the action completes partly, as it does on a first
    run; what it must not do is hold the summaries the edit replaced, or hand them on."""
    _with_a_reader(online)
    assert _run("--fresh").exit_code == 0
    before_the_edit = _stored(online)
    (online / "handed.jsonl").unlink()

    _edit_prompt(online)
    with _unparsed():
        result = _run()

    assert result.exit_code == 0, result.output
    assert _status(online) == "completed_with_failures"
    assert _still_holding(before_the_edit, _stored(online)) == [], "an answer from before the edit"
    assert _still_holding(before_the_edit, _stored(online, READER)) == [], (
        "a row made from a replaced summary"
    )
    assert not set(_handed(online)) & set(before_the_edit.values())


def test_a_reader_whose_every_record_of_a_file_fails_keeps_nothing_made_before_the_edit(
    online,  # noqa: F811
):
    """Its source answers that file again, and the reader's tool raises on both records."""
    _with_a_reader(online)
    assert _run("--fresh").exit_code == 0
    before_the_edit = _stored(online, READER)

    _edit_prompt(online)
    with _answering_the_failing_file({"summary": BREAKS_THE_READER, "exam_density": "low"}):
        result = _run()

    assert result.exit_code == 0, result.output
    assert _status(online, READER) == "completed_with_failures"
    assert _still_holding(before_the_edit, _stored(online, READER)) == [], (
        "a row made from a replaced summary"
    )


def test_a_batch_file_whose_every_answer_fails_after_an_edit_keeps_no_answer_from_before_it(
    project,  # noqa: F811
):
    assert _run("--fresh").exit_code == 0
    assert _run().exit_code == 0
    assert _status(project) == "completed"
    before_the_edit = _stored(project)

    _edit_prompt(project)
    with _batch_answers_unparsed():
        assert _run().exit_code == 0
        result = _run()

    assert result.exit_code == 0, result.output
    assert _status(project) == "completed_with_failures"
    assert _still_holding(before_the_edit, _stored(project)) == [], "an answer from before the edit"


def _stored_files(root, action):
    backend = _backend(root)
    try:
        return sorted(backend.list_target_files(action))
    finally:
        backend.close()


def test_a_first_run_whose_every_answer_for_a_file_fails_stores_nothing_for_it(
    online,  # noqa: F811
):
    """Nothing was stored for it, so nothing could be served from before."""
    _with_a_reader(online)
    with _unparsed():
        result = _run("--fresh")

    assert result.exit_code == 0, result.output
    assert _status(online) == "completed_with_failures"
    assert _stored_files(online, ACTION) == ["pages2.json"]
    assert _stored_files(online, READER) == ["pages2.json"]


def test_a_retry_answers_the_file_again_and_its_reader_with_it(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """The run stored that file's failures, so the next plain run asks nothing, and a retry
    asks for that file alone and leaves both actions holding its new answers."""
    _with_a_reader(online)
    assert _run("--fresh").exit_code == 0
    _edit_prompt(online)
    with _unparsed():
        assert _run().exit_code == 0

    provider.answers()
    assert _run().exit_code == 0
    assert provider.pages() == []
    retried = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

    assert retried.exit_code == 0, retried.output
    assert provider.pages() == sorted(PAGES[FAILING])
    answers = _stored(online)
    assert len(answers) == 4
    assert None not in answers.values()
    assert _stored(online, READER) == answers
