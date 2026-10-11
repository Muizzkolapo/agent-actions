"""A file the store fails to write fails its action, and the next run answers it (1265).

A failure confined to one input file costs only that file: the walk records it, goes on
with the others, and the action completes holding fewer records. A store that failed to
write one file of several was treated the same way. After an edit, the reset leaves each
file's rows in place until the run writes it again, so the action was recorded complete,
with exit 0, over the rows that file held from before the edit; its readers ran on them,
and nothing asked for them again. On a first run the file was simply never stored.

A batch collect pass took the failure the same way, and recorded the action partly
complete over that file's earlier rows.

Either way the run reported it first as a failed load of the file it was writing (1284).

Every run is an `agac run` through the CLI, executor, store and mock provider. Only the
store's failure is stood in for, raised where it writes the one target file.
"""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    ACTION,
    ECHO_TOOL,
    EVERY_PAGE,
    FILE_READER,
    PAGES,
    READER,
    READER_ACTION,
    WORKFLOW,
    _config,
    _edit_prompt,
    _run,
    _sent,
    _sent_since,
    _status,
    _still_holding,
    _stored,
    _stored_rows,
    _summaries_in,
    _with_a_file_reader,
    online,  # noqa: F401
    project,  # noqa: F401
    provider,  # noqa: F401
)

NOT_STORED = "pages1.json"
FAULTS = pytest.mark.parametrize(
    "fault",
    [
        pytest.param(sqlite3.OperationalError("disk I/O error"), id="database"),
        pytest.param(OSError(28, "No space left on device"), id="disk-full"),
    ],
)


@contextmanager
def _the_store_fails_to_write(action, relative_path, raising):
    write = SQLiteBackend.write_target

    def failing(self, action_name, path, *args, **kwargs):
        if (action_name, path) == (action, relative_path):
            raise raising
        return write(self, action_name, path, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(SQLiteBackend, "write_target", failing)
        yield


def _events(root):
    log = root / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _failures_naming_a_file(root):
    return [
        (event["event_type"], event["message"])
        for event in _events(root)
        if event["level"] == "error" and "file_path" in event["data"]
    ]


def _reported_as_a_failed_write(root, result, action, fault):
    assert result.exit_code == 1, result.output
    assert "Failed to load data" not in result.output
    assert "Failed to write" in result.output
    assert "D002" not in {event["code"] for event in _events(root)}
    failures = _failures_naming_a_file(root)
    assert [event_type for event_type, _ in failures] == ["FileWriteFailedEvent"]
    ((_, message),) = failures
    assert message.startswith("Failed to write "), message
    assert message.endswith(f"/target/{action}/{NOT_STORED}: {fault}"), message


def _with_a_reader(root):
    config = _config(root)
    config.write_text(config.read_text().rstrip("\n") + "\n" + READER_ACTION)
    (root / "tools" / WORKFLOW).mkdir(parents=True, exist_ok=True)
    (root / "tools" / WORKFLOW / "echo.py").write_text(ECHO_TOOL)


@FAULTS
def test_a_file_the_store_fails_to_write_after_an_edit_is_answered_again_by_the_next_run(
    online,  # noqa: F811
    provider,  # noqa: F811
    fault,
):
    """The file still holds what the prompt answered before the edit, and the file the
    store did write holds the new answers, so only the first is asked for again."""
    assert _run("--fresh").exit_code == 0
    before_the_edit = _stored(online)

    _edit_prompt(online)
    with _the_store_fails_to_write(ACTION, NOT_STORED, fault):
        failed = _run()
    assert failed.exit_code == 1, failed.output
    assert _status(online) == "failed"
    provider.answers()
    result = _run()

    assert result.exit_code == 0, result.output
    assert _status(online) == "completed"
    assert provider.pages() == sorted(PAGES[NOT_STORED])
    after = _stored(online)
    assert sorted(after) == sorted(before_the_edit)
    assert _still_holding(before_the_edit, after) == [], "an answer from before the edit"
    assert all(row.get("lineage") for row in _stored_rows(online))


@FAULTS
def test_a_file_the_store_fails_to_write_is_reported_as_a_failed_write_not_a_load(
    online,  # noqa: F811
    fault,
):
    """The writer reported through the loaders' failure event, so the run said at error
    level, in the terminal and in its log, that it failed to load the file it was writing."""
    with _the_store_fails_to_write(ACTION, NOT_STORED, fault):
        result = _run("--fresh")

    _reported_as_a_failed_write(online, result, ACTION, fault)


def test_a_file_a_downstream_action_fails_to_store_is_reported_as_a_failed_write(
    online,  # noqa: F811
):
    """An action reading another's output stores its file through the same writer, by
    another route than the first stage's, so it said the same."""
    _with_a_reader(online)
    fault = sqlite3.OperationalError("disk I/O error")
    with _the_store_fails_to_write(READER, NOT_STORED, fault):
        result = _run("--fresh")

    _reported_as_a_failed_write(online, result, READER, fault)


def test_a_file_a_batch_collect_pass_fails_to_store_is_reported_as_a_failed_write(
    project,  # noqa: F811
):
    """The collect pass stores a file through the same writer, so it said the same."""
    assert _run("--fresh").exit_code == 0
    fault = OSError(28, "No space left on device")
    with _the_store_fails_to_write(ACTION, NOT_STORED, fault):
        result = _run()

    _reported_as_a_failed_write(project, result, ACTION, fault)


def test_a_reader_of_an_action_whose_file_was_not_stored_keeps_nothing_made_before_the_edit(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """The edit resets the reader with its source. Run while the source still held its
    old answers for that file, the reader would make its rows from them."""
    _with_a_reader(online)
    assert _run("--fresh").exit_code == 0
    before_the_edit = _stored(online)

    _edit_prompt(online)
    with _the_store_fails_to_write(ACTION, NOT_STORED, sqlite3.OperationalError("disk I/O")):
        failed = _run()
    assert failed.exit_code == 1, failed.output
    assert _status(online, READER) == "skipped"
    result = _run()

    assert result.exit_code == 0, result.output
    answers = _stored(online)
    assert _still_holding(before_the_edit, answers) == [], "an answer from before the edit"
    assert _stored(online, READER) == answers


def test_a_reader_file_the_store_fails_to_write_after_its_source_was_edited_is_made_again(
    online,  # noqa: F811
):
    """A file tool leaves no checkpoint row; the file it did store keeps its records."""
    _with_a_file_reader(online)
    assert _run("--fresh").exit_code == 0
    before_the_edit = _stored(online, FILE_READER)

    _edit_prompt(online)
    with _the_store_fails_to_write(FILE_READER, NOT_STORED, OSError(28, "No space left")):
        failed = _run()
    assert failed.exit_code == 1, failed.output
    assert _status(online, FILE_READER) == "failed"
    handed = online / "handed.jsonl"
    handed.unlink()
    result = _run()

    assert result.exit_code == 0, result.output
    assert sorted(json.loads(line) for line in handed.read_text().splitlines()) == (
        _summaries_in(online, NOT_STORED)
    )
    after = _stored(online, FILE_READER)
    assert _still_holding(before_the_edit, after) == [], "a row made from a replaced summary"
    assert after == _stored(online)


def test_a_first_run_whose_store_fails_to_write_a_file_stores_it_on_the_next_run(
    online,  # noqa: F811
):
    with _the_store_fails_to_write(ACTION, NOT_STORED, sqlite3.OperationalError("disk I/O")):
        failed = _run("--fresh")
    assert failed.exit_code == 1, failed.output
    assert _status(online) == "failed"

    result = _run()

    assert result.exit_code == 0, result.output
    assert _status(online) == "completed"
    assert len(_stored(online)) == len(EVERY_PAGE)


def test_a_file_stored_on_the_run_after_its_store_failed_carries_its_lineage(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """The next run stores the file from its records' checkpoint rows without asking for
    them again, so those rows are enriched there, as the run that answered them would
    have."""
    with _the_store_fails_to_write(ACTION, NOT_STORED, sqlite3.OperationalError("disk I/O")):
        assert _run("--fresh").exit_code == 1
    provider.answers()

    assert _run().exit_code == 0
    assert provider.pages() == []
    assert all(row.get("lineage") for row in _stored_rows(online))


def test_a_batch_file_the_store_fails_to_collect_after_an_edit_is_collected_by_a_later_run(
    project,  # noqa: F811
):
    """The collect pass took the failure as that file's own, recorded the action partly
    complete over the file's rows from before the edit and exited 0, and no later run
    collected it. The edit's batch for the file is answered and waiting, so a later run
    collects it rather than sending the file again."""
    assert _run("--fresh").exit_code == 0
    assert _run().exit_code == 0
    assert _status(project) == "completed"
    before_the_edit = _stored(project)

    _edit_prompt(project)
    assert _run().exit_code == 0
    with _the_store_fails_to_write(ACTION, NOT_STORED, sqlite3.OperationalError("disk I/O")):
        failed = _run()
    assert failed.exit_code == 1, failed.output
    assert _status(project) == "failed"
    sent = _sent(project)
    _run()
    result = _run()

    assert result.exit_code == 0, result.output
    assert _status(project) == "completed"
    assert _sent_since(project, sent) == []
    after = _stored(project)
    assert sorted(after) == sorted(before_the_edit)
    assert _still_holding(before_the_edit, after) == [], "an answer from before the edit"
