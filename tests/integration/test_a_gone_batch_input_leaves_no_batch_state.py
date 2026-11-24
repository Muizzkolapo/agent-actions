"""A batch action whose input file is gone forgets that file's batch state with its rows.

The walk deletes the file it stored for an input that is gone. Its context map, the inputs
it recorded and its registry entry go too; the other file's stay.
"""

import json
import sqlite3

from click.testing import CliRunner

from agent_actions.cli.exit_codes import EXIT_PAUSED, EXIT_SUCCESS
from agent_actions.cli.main import cli
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from tests.integration.test_retry_selection_under_batch import (
    ACTION,
    WORKFLOW,
    _backend,
    _cycle,
    _project,
)

PAGES = "pages.json"
OTHER = "other.json"


def _staging(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"


def _batch_state(root):
    """{file: the batch keys it holds} and the files the registry names."""
    backend = _backend(root)
    try:
        keys = [
            key
            for prefix in (f"batch_context:{ACTION}:", f"batch_inputs:{ACTION}:")
            for key in backend.list_metadata_prefix(prefix)
        ]
        held = {
            name: sorted(key for key in keys if key.split(":", 2)[2].startswith(name))
            for name in (PAGES, OTHER)
        }
        return held, sorted(BatchRegistryManager(backend, ACTION).get_all_jobs())
    finally:
        backend.close()


def test_a_gone_input_leaves_no_batch_state_and_the_other_file_keeps_its_own(tmp_path):
    root = _project(tmp_path)
    for name, prefix in ((PAGES, "p"), (OTHER, "o")):
        _staging(root).joinpath(name).write_text(
            json.dumps(
                [{"page_id": f"{prefix}{i}", "page_content": f"{name} {i}"} for i in (0, 1)]
            )
        )
    _cycle(root, "run", "-a", WORKFLOW, "--fresh", ends_with=EXIT_SUCCESS)
    held, registry = _batch_state(root)
    assert held[PAGES] and held[OTHER], held
    assert registry == [OTHER, PAGES]
    kept = held[PAGES]

    _staging(root).joinpath(OTHER).unlink()
    transcript = _cycle(root, "run", "-a", WORKFLOW, ends_with=EXIT_SUCCESS)

    assert f"'{ACTION}' has no input for {OTHER} any more" in " ".join(
        " ".join(transcript).split()
    )
    held, registry = _batch_state(root)
    assert held == {PAGES: kept, OTHER: []}
    assert registry == [PAGES]


def test_an_input_renamed_to_another_case_is_collected(tmp_path):
    """The gone pages.json takes nothing of Pages.json's batch state, so the next run that
    collects the batch sent for Pages.json finds its context map."""
    root = _project(tmp_path)
    _staging(root).joinpath(PAGES).write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in (0, 1)])
    )
    _cycle(root, "run", "-a", WORKFLOW, "--fresh", ends_with=EXIT_SUCCESS)

    _staging(root).joinpath(PAGES).rename(_staging(root) / "Pages.json")
    _cycle(root, "run", "-a", WORKFLOW, ends_with=EXIT_SUCCESS)

    backend = _backend(root)
    try:
        stored = {
            path: len(backend.read_target(ACTION, path))
            for path in backend.list_target_files(ACTION)
        }
    finally:
        backend.close()
    assert stored == {"Pages.json": 2}


TAG = "tag"

TAG_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def tag_density(data: Any, *args) -> list[dict]:
    return [{"summary": "tagged", "exam_density": "high"}]
"""

TAG_ACTION = f"""  - name: {TAG}
    kind: tool
    run_mode: online
    dependencies: [{ACTION}]
    intent: "Tag"
    schema: batch_field_rules_output
    impl: tag_density
    context_scope: {{ observe: [{ACTION}.summary] }}
    expect: {{ repair: none }}
"""


def _run_in_process(*extra):
    """One run driven to its end: each run that submits a batch is followed by one that
    collects it."""
    for _ in range(5):
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *extra])
        if "run again" not in result.output:
            return result
        assert result.exit_code == EXIT_PAUSED, result.output
        extra = ()
    raise AssertionError(result.output)


def _sources(root, action):
    """{stored file: the staged page each row came from}."""
    backend = _backend(root)
    try:
        return {
            path: sorted(
                r["content"]["source"]["page_content"] for r in backend.read_target(action, path)
            )
            for path in backend.list_target_files(action)
        }
    finally:
        backend.close()


def test_a_reader_gets_no_rows_of_a_gone_file_whose_batch_state_stays(tmp_path, monkeypatch):
    """The batch state of the gone file cannot be deleted, so it stays; its rows go all
    the same, and the action below holds nothing made from them."""
    from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager

    root = _project(tmp_path)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + TAG_ACTION)
    (root / "tools" / WORKFLOW).mkdir(parents=True, exist_ok=True)
    (root / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)
    for name in (PAGES, OTHER):
        _staging(root).joinpath(name).write_text(
            json.dumps([{"page_id": f"{name}{i}", "page_content": f"{name} {i}"} for i in (0, 1)])
        )
    monkeypatch.chdir(root)
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    assert _run_in_process("--fresh").exit_code == EXIT_SUCCESS
    assert sorted(_sources(root, TAG)) == [OTHER, PAGES]

    delete = RecoveryStateManager.delete

    def refuse_other(store, action_name, file_name):
        if file_name == OTHER:
            raise sqlite3.OperationalError("database is locked")
        return delete(store, action_name, file_name)

    monkeypatch.setattr(RecoveryStateManager, "delete", staticmethod(refuse_other))
    _staging(root).joinpath(OTHER).unlink()
    result = _run_in_process()

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _batch_state(root)[1] == [OTHER, PAGES]
    expected = {PAGES: [f"{PAGES} 0", f"{PAGES} 1"]}
    assert _sources(root, ACTION) == expected
    assert _sources(root, TAG) == expected
