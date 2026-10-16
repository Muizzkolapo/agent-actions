"""A first-stage batch over a staged file in a subdirectory leaves no file on disk.

Submission wrote a placeholder for the file at its folder joined with its relative path
again, and collection removes one only at the name the file is stored under, so it stayed,
for a reader of the target folder to take for a batch still out.
"""

from tests.integration.test_a_batch_the_provider_refuses import (
    CLI_ACTION,
    WORKFLOW,
    _agac,
    _project,
    _stored_rows,
)


def test_no_file_is_left_in_the_target_folder_once_the_batch_is_collected(tmp_path):
    project = _project(tmp_path / "project", ("a",))
    io_dir = project / "agent_workflow" / WORKFLOW / "agent_io"
    (io_dir / "staging" / "sub").mkdir()
    (io_dir / "staging" / "a_pages.json").rename(io_dir / "staging" / "sub" / "page.json")

    assert _agac(project, "--fresh").status == "batch_submitted"
    collected = _agac(project)

    assert collected.status == "completed", collected.output
    assert [page for page, _ in _stored_rows(project)["sub/page.json"]] == ["a1", "a2"]
    assert list((io_dir / "target" / CLI_ACTION).rglob("*.json")) == []
