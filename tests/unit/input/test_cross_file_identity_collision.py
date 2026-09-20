"""_give_repeats_their_own_identity: cross-file collisions within one run (614).

The same-file repeat-identity fix's occurrence counter reset for every file, so
identical content staged in two different files still collided on one guid.
This pins the fix at the level it actually operates: two files processed
sequentially against ONE shared backend (one run), and a fresh backend (a new
process) that must not remember a prior run's claims.
"""

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    _give_repeats_their_own_identity,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.id_generation import IDGenerator


def _backend(tmp_path, name="test.db"):
    backend = SQLiteBackend(str(tmp_path / "agent_io" / name), "test_workflow")
    backend.initialize()
    return backend


def test_a_second_file_sharing_content_with_the_first_gets_a_different_identity(tmp_path):
    backend = _backend(tmp_path)
    try:
        file_a = [{"source_guid": IDGenerator.derive_source_guid({"page_content": "shared"})}]
        file_b = [{"source_guid": IDGenerator.derive_source_guid({"page_content": "shared"})}]

        _give_repeats_their_own_identity(file_a, backend)
        _give_repeats_their_own_identity(file_b, backend)

        assert file_a[0]["source_guid"] != file_b[0]["source_guid"]
        assert "repeat_of_source_guid" not in file_a[0]
        assert file_b[0]["repeat_of_source_guid"] == file_a[0]["source_guid"]
    finally:
        backend.close()


def test_a_fresh_backend_does_not_remember_the_prior_ones_claims(tmp_path):
    """A retry or resume — a new process, re-deriving from scratch — must
    reproduce the same identity a file had before, not bump past it."""
    guid = IDGenerator.derive_source_guid({"page_content": "unique"})

    first_run = _backend(tmp_path)
    try:
        row = [{"source_guid": guid}]
        _give_repeats_their_own_identity(row, first_run)
        assert row[0]["source_guid"] == guid
    finally:
        first_run.close()

    second_run = _backend(tmp_path)
    try:
        row = [{"source_guid": guid}]
        _give_repeats_their_own_identity(row, second_run)
        assert row[0]["source_guid"] == guid, "identity moved across a fresh run"
        assert "repeat_of_source_guid" not in row[0]
    finally:
        second_run.close()
