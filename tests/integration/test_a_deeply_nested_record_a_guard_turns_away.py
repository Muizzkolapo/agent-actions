"""A guard that turns away a record nested hundreds of levels deep leaves the run intact.

A record a guard filters or skips is not sent. Collection still builds its passthrough
or tombstone and snapshots the record, which used to copy it with `copy.deepcopy` and
fail the run at about 500 levels.
"""

import pytest

from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.integration.test_a_deeply_nested_record_runs_in_batch import (
    ACTION,
    WORKFLOW,
    _invoke,
    _project,
    _run_to_completion,
)

GUARDS = {
    "skip": "guard: { condition: 'source.page_content != \"page 0\"', on_false: skip }",
    "filter": "guard: { condition: 'source.page_content != \"page 0\"', on_false: filter }",
}


def _guarded_project(tmp_path, monkeypatch, behavior: str, depth: int):
    root = _project(tmp_path, monkeypatch, depth)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    text = config.read_text()
    anchor = "    expect: { repair: none }"
    assert text.count(anchor) == 1
    config.write_text(text.replace(anchor, f"    {GUARDS[behavior]}\n{anchor}"))
    return root


@pytest.mark.parametrize("behavior", ["skip", "filter"])
@pytest.mark.parametrize("depth", [600, 800])
def test_the_run_completes_and_the_other_record_is_answered(tmp_path, monkeypatch, behavior, depth):
    root = _guarded_project(tmp_path, monkeypatch, behavior, depth)

    ran = _run_to_completion()

    assert all(r.exit_code == 0 for r in ran), [r.output for r in ran]
    from agent_actions.config.project_paths import ProjectPathsFactory
    from agent_actions.storage import get_storage_backend

    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        held = [
            row["disposition"]
            for row in backend.get_disposition(ACTION)
            if row["record_id"] != NODE_LEVEL_RECORD_ID
        ]
    finally:
        backend.close()
    assert "success" in held
    assert "failed" not in held, held
    again = _invoke("run", "-a", WORKFLOW)
    assert again.exit_code == 0, again.output
