"""Retry selection bounds side effects as well as provider work."""

import json

from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    SECOND,
    WORKFLOW,
    _backend,
    _disposition,
    _fail,
    _record_ids,
    _stored_guids,
    chained,  # noqa: F401
    project,  # noqa: F401
)


def test_named_retry_preserves_other_failure_and_output(chained):  # noqa: F811
    selected, other = _record_ids(chained, SECOND)[:2]
    _fail(chained, selected, SECOND)
    _fail(chained, other, SECOND)
    backend = _backend(chained)
    try:
        before = backend.get_disposition(SECOND, record_id=other)
        output_before = {
            path: backend._read_target_raw(SECOND, path)
            for path in backend.list_target_files(SECOND)
        }
    finally:
        backend.close()

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
    assert _disposition(chained, selected, SECOND) == "success"
    backend = _backend(chained)
    try:
        assert backend.get_disposition(SECOND, record_id=other) == before
        for path, rows in output_before.items():
            unselected = [r for r in rows if r["source_guid"] != selected]
            assert [
                r for r in backend._read_target_raw(SECOND, path) if r["source_guid"] != selected
            ] == unselected
    finally:
        backend.close()


def test_retry_does_not_admit_new_staging_records_under_guard(project):  # noqa: F811
    selected = _record_ids(project)[0]
    before = _stored_guids(project)
    staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(staging.read_text().rstrip()[:-1] + ', {"page_content": "new"}]')
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace(
            "    impl: flatten_pages\n",
            "    impl: flatten_pages\n"
            '    guard: { condition: \'source.page_content != "new"\', on_false: "skip" }\n',
        )
    )
    _fail(project, selected)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
    assert _disposition(project, selected) == "success"
    assert _stored_guids(project) == before
    assert sorted(_record_ids(project)) == sorted(before)
    backend = _backend(project)
    try:
        assert len(backend.read_source("pages")) == len(before)
    finally:
        backend.close()


def test_retry_resolves_only_selected_file_past_file_limit(project):  # noqa: F811
    staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    second = staging / "z_pages.json"
    second.write_text(json.dumps([{"page_content": "second file"}]))
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    backend = _backend(project)
    try:
        selected = backend.read_target(ACTION, "z_pages.json")[0]["source_guid"]
        before = backend._read_target_raw(ACTION, "pages.json")
    finally:
        backend.close()
    _fail(project, selected)
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace("  - name: flatten\n", "  - name: flatten\n    file_limit: 1\n")
    )
    # An unrelated staged file must never be opened by this retry.
    (staging / "pages.json").write_text("not JSON")

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
    assert "Failed to process file pages.json" not in result.output
    assert _disposition(project, selected) == "success"
    backend = _backend(project)
    try:
        assert backend._read_target_raw(ACTION, "pages.json") == before
    finally:
        backend.close()


def test_retry_writes_no_node_level_disposition_for_a_file_it_never_opens(project):  # noqa: F811
    """The node-level half of the same property, where it can actually fail.

    A file whose records are all guard-filtered produces no output and only guard
    outcomes, so processing it writes a node-level `skipped` — the vacuous
    `only_guard_outcomes` that cascade-skips everything downstream. The original
    run writes one here; `agac retry` clears it, and a repair that never opens
    that file must not put it back. Break both the file walk and the source-save
    narrowing and it does.
    """
    staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    (staging / "pages.json").unlink()
    (staging / "a_pages.json").write_text(
        json.dumps([{"page_content": f"keep {i}"} for i in range(3)])
    )
    (staging / "b_pages.json").write_text(json.dumps([{"page_content": "drop me"}] * 2))
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace(
            "    impl: flatten_pages\n",
            "    impl: flatten_pages\n"
            '    guard: { condition: \'source.page_content != "drop me"\', on_false: "filter" }\n',
        )
    )
    assert CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"]).exit_code == 0
    backend = _backend(project)
    try:
        selected = backend.read_target(ACTION, "a_pages.json")[0]["source_guid"]
    finally:
        backend.close()
    assert _node_dispositions(project), "the fixture did not reach the state under test"
    _fail(project, selected)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", selected])

    assert result.exit_code == 0, result.output
    assert _disposition(project, selected) == "success"
    assert _node_dispositions(project) == []


def _node_dispositions(root, action=ACTION):
    backend = _backend(root)
    try:
        return [
            r for r in backend.get_disposition(action) if r["record_id"] == NODE_LEVEL_RECORD_ID
        ]
    finally:
        backend.close()
