"""An edit stays named, and traceable, until a rerun answers every record under it.

An edit re-runs nothing, so an action can hold answers from two configs. Three things say
so. Each prompt trace row records the config it was answered under, under a retry too,
where the action's own stamp still names the earlier config. An action stopped partway
that resumes under an edit keeps its stamp at the config its kept answers were given
under, so every later run names the edit until ``--rerun``. And a reset under a file
limit says that the files the walk does not reach keep output from an earlier run.

Every run is an ``agac`` command through the CLI, executor, store and mock provider.
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
