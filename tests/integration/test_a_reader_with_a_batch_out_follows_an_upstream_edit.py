"""A reader whose batch is really out when the action it reads is edited.

`summarize` and `publish` both run under `run_mode: batch` against the provider mock.
`publish` reads what `summarize` writes. The edit lands while `publish` has a batch
submitted and not yet collected: that batch was sent the four rows `summarize` held
before the edit.
"""

import json
import re

import pytest

from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_retry_selection_under_batch import (
    RECORDS,
    WORKFLOW,
    _agac,
    _backend,
    _project,
)

FIRST = "summarize"
READER = "publish"

READER_ACTION = """  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: batch_field_rules_output
    prompt: $p.Publish
    context_scope: { observe: [summarize.summary] }
    expect: { repair: none }
"""

ANCHOR = "    prompt: $p.Summarize\n"
# edit -> (what replaces the anchor, requests the provider is sent after the edit)
EDITS = {
    "guard": (
        ANCHOR
        + '    guard: { condition: \'source.page_content != "page 0"\', on_false: "filter" }\n',
        [RECORDS - 1, RECORDS - 1],
    ),
    "record_limit": (ANCHOR + "    record_limit: 3\n", [3, RECORDS]),
    "model": (ANCHOR + "    model_name: another-model\n", [RECORDS, RECORDS]),
}


def _config(project):
    return project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _statuses(project):
    found = list((project / "agent_workflow" / WORKFLOW).rglob("*status*.json"))
    assert len(found) == 1, found
    return {name: d.get("status") for name, d in json.loads(found[0].read_text()).items()}


def _rows(project, action):
    backend = _backend(project)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend._read_target_raw(action, path)
        ]
    finally:
        backend.close()


def _guids(project, action):
    return sorted(r["source_guid"] for r in _rows(project, action) if r.get("source_guid"))


def _run(project, *extra):
    code, output = _agac(project, "run", "-a", WORKFLOW, *extra)
    assert code == 0, output
    return output


def _run_to_the_end(project):
    transcript = [_run(project)]
    while "run again" in transcript[-1]:
        assert len(transcript) <= 6, "the workflow never stopped asking to be run again"
        transcript.append(_run(project))
    return "\n".join(transcript)


def _edit(project, edit):
    config = _config(project)
    assert ANCHOR in config.read_text()
    config.write_text(config.read_text().replace(ANCHOR, EDITS[edit][0], 1))


@pytest.fixture
def reader_has_a_batch_out(tmp_path):
    root = _project(tmp_path)
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(RECORDS)])
    )
    config = _config(root)
    config.write_text(config.read_text().rstrip("\n") + "\n" + READER_ACTION)

    assert "run again" in _run(root, "--fresh")
    assert "run again" in _run(root)
    assert _statuses(root) == {
        FIRST: ActionStatus.COMPLETED.value,
        READER: ActionStatus.BATCH_SUBMITTED.value,
    }
    assert len(_guids(root, FIRST)) == RECORDS
    assert _guids(root, READER) == []
    return root


@pytest.mark.parametrize("edit", sorted(EDITS))
def test_a_reader_with_a_batch_out_is_sent_what_the_edited_action_writes_now(
    reader_has_a_batch_out, edit
):
    """Counted at the provider: the batch already out is not what the reader ends on."""
    project = reader_has_a_batch_out
    _edit(project, edit)

    transcript = _run_to_the_end(project)

    assert _statuses(project) == {
        FIRST: ActionStatus.COMPLETED.value,
        READER: ActionStatus.COMPLETED.value,
    }, transcript
    sent = [int(n) for n in re.findall(r"submitted: (\d+) requests", transcript)]
    assert sent == EDITS[edit][1], transcript


def test_a_reader_with_a_batch_out_does_not_keep_the_row_the_new_guard_filters(
    reader_has_a_batch_out,
):
    project = reader_has_a_batch_out
    (filtered,) = [r["source_guid"] for r in _rows(project, FIRST) if '"page 0"' in json.dumps(r)]
    everything = _guids(project, FIRST)
    _edit(project, "guard")

    transcript = _run_to_the_end(project)

    assert _guids(project, READER) == sorted(set(everything) - {filtered}), transcript


def test_nothing_more_is_sent_or_collected_by_the_run_after(reader_has_a_batch_out):
    """The batch given up is still sitting complete at the provider."""
    project = reader_has_a_batch_out
    _edit(project, "guard")
    _run_to_the_end(project)
    held = _rows(project, READER)

    again = _run(project)

    assert "run again" not in again, again
    assert "submitted:" not in again, again
    assert _rows(project, READER) == held
