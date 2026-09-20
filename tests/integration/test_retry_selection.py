"""Retry selection bounds side effects as well as provider work."""

import json

from click.testing import CliRunner

from agent_actions.cli.main import cli
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
