"""A file staged while a batch is out reaches the action once that batch is collected."""

import json

from tests.integration.test_a_deeply_nested_record_runs_in_batch import (
    ACTION,
    WORKFLOW,
    _invoke,
    _project,
    _record_dispositions,
)


def _run_until_settled():
    for _ in range(4):
        result = _invoke("run", "-a", WORKFLOW)
        assert result.exit_code == 0, result.output
        if "run again" not in result.output:
            return


def test_a_file_staged_during_the_batch_is_answered_by_a_later_run(tmp_path, monkeypatch):
    root = _project(tmp_path, monkeypatch, 1)
    submitted = _invoke("run", "-a", WORKFLOW, "--fresh")
    assert submitted.exit_code == 0, submitted.output
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    staging.joinpath("more.json").write_text(
        json.dumps([{"page_id": "p9", "page_content": "page 9"}])
    )

    _run_until_settled()
    _run_until_settled()

    assert sorted(_record_dispositions(root).values()) == ["success"] * 3, ACTION
