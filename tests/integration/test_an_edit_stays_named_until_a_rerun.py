"""An edit stays named, and traceable, until a rerun answers every record under it.

An action can hold answers from two configs. Trace rows name each record's config, retries
included; a resumed or retried action keeps naming the edit, even once it is reverted; an
edit under a batch still out is named on collection; a reset under a file limit says the
files it skips keep older output. Every run goes through the CLI and the mock provider.
"""

import json

from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.providers.agac.client import AgacClient
from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    ACTION,
    EVERY_PAGE,
    MODEL,
    WORKFLOW,
    _backend,
    _edit_model,
    _page_in,
    _printed,
    _run,
    _status,
    _stored,
    online,  # noqa: F401 — fixture
    project,  # noqa: F401 — fixture
    provider,  # noqa: F401 — fixture
)

EDITED_MODEL = "other-model:1b"
STILL_NAMED = f"{ACTION} was edited since it completed (model)"
FILE_LIMIT = f"{ACTION} is re-running under a file limit of 1 after"


def _status_details(root):
    status_file = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[ACTION]


def _trace_models(root):
    """The model each trace row says its page was answered under, as {page: [models]}."""
    backend = _backend(root)
    try:
        traces = backend.get_prompt_traces(ACTION)
    finally:
        backend.close()
    models: dict[str, list[str]] = {}
    for row in traces:
        page = _page_in(row["compiled_prompt"])
        models.setdefault(page, []).append(json.loads(row["answered_under"])["model_name"])
    return {page: sorted(found) for page, found in models.items()}


def test_a_retried_record_is_traced_under_the_edit_while_the_stamp_names_the_old_config(
    online,  # noqa: F811
    monkeypatch,
):
    answer = AgacClient.call_json

    def beta_empty(api_key, agent_config, prompt_config, context_data, schema):
        if _page_in(prompt_config, context_data) == "Page beta.":
            return [{}]
        return answer(api_key, agent_config, prompt_config, context_data, schema)

    with monkeypatch.context() as patched:
        patched.setattr(AgacClient, "call_json", staticmethod(beta_empty))
        result = _run("--fresh")
    assert result.exit_code == 0, result.output
    assert _status(online) == "completed_with_failures"
    assert _trace_models(online) == {page: [MODEL] for page in EVERY_PAGE}

    _edit_model(online, EDITED_MODEL)
    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert _status_details(online)["answered_under"]["model_name"] == MODEL
    assert _trace_models(online) == {
        "Page alpha.": [MODEL],
        "Page beta.": sorted([MODEL, EDITED_MODEL]),
        "Page delta.": [MODEL],
        "Page gamma.": [MODEL],
    }


def test_a_resumed_action_names_the_edit_on_every_run_until_a_rerun(online, provider):  # noqa: F811
    provider.stops(at_call=3, raising=KeyboardInterrupt())
    _run("--fresh")
    assert _status(online) == "interrupted"
    _edit_model(online, EDITED_MODEL)
    provider.answers()

    result = _run()

    assert result.exit_code == 0, result.output
    assert sorted(provider.asked) == sorted(
        [("Page gamma.", EDITED_MODEL), ("Page delta.", EDITED_MODEL)]
    )
    assert len(_stored(online)) == len(EVERY_PAGE)

    for _ in range(2):
        provider.answers()
        result = _run()

        assert result.exit_code == 0, result.output
        assert STILL_NAMED in _printed(result)
        assert provider.asked == []

    result = _run("--rerun", ACTION)

    assert result.exit_code == 0, result.output
    assert provider.pages() == EVERY_PAGE
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert "was edited since" not in _printed(result)
    assert provider.asked == []


def test_an_action_stopped_before_it_answered_anything_names_no_edit_once_it_completes(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    provider.stops(at_call=1, raising=KeyboardInterrupt())
    _run("--fresh")
    assert _status(online) == "interrupted"
    assert _stored(online) == {}
    _edit_model(online, EDITED_MODEL)
    provider.answers()

    result = _run()

    assert result.exit_code == 0, result.output
    assert sorted(model for _, model in provider.asked) == [EDITED_MODEL] * len(EVERY_PAGE)
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert "was edited since" not in _printed(result)


def test_a_rerun_under_a_file_limit_says_the_files_it_skips_keep_older_output(online):  # noqa: F811
    assert _run("--fresh", "--file-limit", "1").exit_code == 0

    result = _run("--rerun", ACTION, "--file-limit", "1")

    assert result.exit_code == 0, result.output
    assert f"{FILE_LIMIT} --rerun: files the walk does not reach keep output" in _printed(result)


def test_a_rerun_with_no_file_limit_gives_no_such_warning(online):  # noqa: F811
    assert _run("--fresh").exit_code == 0

    result = _run("--rerun", ACTION)

    assert result.exit_code == 0, result.output
    assert "re-running under a file limit" not in _printed(result)


def test_an_edit_reset_by_a_new_file_limit_says_the_files_it_skips_keep_older_output(online):  # noqa: F811
    assert _run("--fresh").exit_code == 0
    _edit_model(online, EDITED_MODEL)

    result = _run("--file-limit", "1")

    assert result.exit_code == 0, result.output
    assert f"{FILE_LIMIT} an edit (model): files the walk does not reach" in _printed(result)
    assert STILL_NAMED not in _printed(result)


def test_an_action_stopped_before_it_stored_a_file_still_names_the_edit_it_resumed_under(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """The answer it kept is only a disposition: no file was stored before the stop."""
    provider.stops(at_call=2, raising=KeyboardInterrupt())
    _run("--fresh")
    assert _status(online) == "interrupted"
    assert _stored(online) == {}
    _edit_model(online, EDITED_MODEL)
    provider.answers()

    result = _run()

    assert result.exit_code == 0, result.output
    assert len(provider.asked) == len(EVERY_PAGE) - 1
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert STILL_NAMED in _printed(result)


def test_an_edit_reverted_after_a_resume_still_says_the_answers_come_from_two_configs(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    provider.stops(at_call=3, raising=KeyboardInterrupt())
    _run("--fresh")
    _edit_model(online, EDITED_MODEL)
    provider.answers()
    assert _run().exit_code == 0
    assert sorted(model for _, model in provider.asked) == [EDITED_MODEL, EDITED_MODEL]
    config = online / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().replace(EDITED_MODEL, MODEL))
    provider.answers()

    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.asked == []
    assert "was edited since" not in _printed(result)
    assert f"{ACTION} may hold answers given under more than one config" in _printed(result)

    result = _run("--rerun", ACTION)

    assert result.exit_code == 0, result.output
    assert provider.pages() == EVERY_PAGE
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert "more than one config" not in _printed(result)


def test_an_edit_while_the_batch_is_out_is_named_by_the_run_that_collects_it(project):  # noqa: F811
    result = _run("--fresh")
    assert result.exit_code == 0, result.output
    assert _status(project) == "batch_submitted"
    _edit_model(project, EDITED_MODEL)

    result = _run()

    assert result.exit_code == 0, result.output
    assert (
        f"{ACTION} was edited since its batch was sent (model): the batch is collected as it "
        "was sent"
    ) in _printed(result)
    assert _status(project) == "completed"
    assert len(_stored(project)) == len(EVERY_PAGE)

    result = _run()

    assert STILL_NAMED in _printed(result)


MIXED = f"{ACTION} may hold answers given under more than one config"


def _set_model(root, model):
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    text = config.read_text()
    for old in (MODEL, EDITED_MODEL):
        text = text.replace(f"model_name: {old}", f"model_name: {model}")
    config.write_text(text)


def test_an_edit_reverted_while_the_resumed_action_is_still_unfinished_is_still_named(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    provider.stops(at_call=2, raising=KeyboardInterrupt())
    _run("--fresh")
    _set_model(online, EDITED_MODEL)
    provider.stops(at_call=2, raising=KeyboardInterrupt())
    _run()
    assert provider.asked[0] == ("Page beta.", EDITED_MODEL)
    _set_model(online, MODEL)
    provider.answers()
    assert _run().exit_code == 0
    assert _status(online) == "completed"
    provider.answers()

    result = _run()

    assert result.exit_code == 0, result.output
    assert MIXED in _printed(result)


def test_a_reset_under_a_file_limit_after_an_edit_names_the_answers_it_left(online):  # noqa: F811
    assert _run("--fresh").exit_code == 0
    _edit_model(online, EDITED_MODEL)
    assert _run("--file-limit", "1").exit_code == 0

    result = _run("--file-limit", "1")

    assert result.exit_code == 0, result.output
    assert MIXED in _printed(result)


def test_a_reset_under_a_file_limit_with_no_edit_names_no_mix(online):  # noqa: F811
    assert _run("--fresh").exit_code == 0
    assert _run("--file-limit", "1").exit_code == 0

    result = _run("--file-limit", "1")

    assert result.exit_code == 0, result.output
    assert "more than one config" not in _printed(result)


def test_a_rerun_of_an_action_whose_batch_is_out_does_not_say_it_is_collected(project):  # noqa: F811
    assert _run("--fresh").exit_code == 0
    assert _status(project) == "batch_submitted"
    _edit_model(project, EDITED_MODEL)

    result = _run("--rerun", ACTION)

    assert result.exit_code == 0, result.output
    assert "collected as it was sent" not in _printed(result)
    assert f"--rerun: {ACTION}" in _printed(result)


def _flags(root):
    return _status_details(root).get("answers_under_more_than_one_config")


def test_a_rerun_under_a_file_limit_after_an_edit_leaves_the_action_marked_as_mixed(online):  # noqa: F811
    assert _run("--fresh").exit_code == 0
    _edit_model(online, EDITED_MODEL)
    assert _run("--rerun", ACTION, "--file-limit", "1").exit_code == 0
    assert _flags(online) is True

    result = _run("--file-limit", "1")

    assert result.exit_code == 0, result.output
    assert MIXED in _printed(result)

    assert _run("--rerun", ACTION, "--file-limit", "1").exit_code == 0
    assert _flags(online) is True, "a rerun under the limit dropped a mix the skipped file holds"


def test_a_rerun_under_a_file_limit_with_nothing_edited_marks_no_mix(online):  # noqa: F811
    assert _run("--fresh").exit_code == 0
    assert _run("--rerun", ACTION, "--file-limit", "1").exit_code == 0

    result = _run("--file-limit", "1")

    assert result.exit_code == 0, result.output
    assert _flags(online) is None
    assert "more than one config" not in _printed(result)


def test_a_retry_under_an_edit_then_reverted_still_names_the_mix(online, monkeypatch):  # noqa: F811
    answer = AgacClient.call_json

    def beta_empty(api_key, agent_config, prompt_config, context_data, schema):
        if _page_in(prompt_config, context_data) == "Page beta.":
            return [{}]
        return answer(api_key, agent_config, prompt_config, context_data, schema)

    with monkeypatch.context() as patched:
        patched.setattr(AgacClient, "call_json", staticmethod(beta_empty))
        assert _run("--fresh").exit_code == 0
    _set_model(online, EDITED_MODEL)
    assert CliRunner().invoke(cli, ["retry", "-a", WORKFLOW]).exit_code == 0
    _set_model(online, MODEL)

    result = _run()

    assert result.exit_code == 0, result.output
    assert "was edited since" not in _printed(result)
    assert MIXED in _printed(result)


def test_a_batch_sent_under_the_edit_is_not_said_to_be_sent_before_it(online, provider):  # noqa: F811
    provider.stops(at_call=3, raising=KeyboardInterrupt())
    _run("--fresh")
    _set_model(online, EDITED_MODEL)
    config = online / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().replace("run_mode: online", "run_mode: batch"))
    assert _run().exit_code == 0
    assert _status(online) == "batch_submitted"

    result = _run()

    assert result.exit_code == 0, result.output
    assert _status(online) == "completed"
    assert "edited since its batch was sent" not in _printed(result)
    assert len(_stored(online)) == len(EVERY_PAGE)


def test_a_rerun_of_an_edited_stopped_action_does_not_say_its_answers_stand(online, provider):  # noqa: F811
    provider.stops(at_call=3, raising=KeyboardInterrupt())
    _run("--fresh")
    _set_model(online, EDITED_MODEL)
    provider.answers()

    result = _run("--rerun", ACTION)

    assert result.exit_code == 0, result.output
    assert "edited since its last run started" not in _printed(result)
    assert provider.pages() == EVERY_PAGE
