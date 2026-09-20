"""claim_source_guid_for_run: an in-memory, per-process claim, never persisted.

The identity-assignment step (staging) uses this to find the next free
occurrence when the same content is staged twice. It must never be backed by
`source_data`: a persisted check can't tell a still-live duplicate file apart
from this file's own row from before it was renamed, and would wrongly bump a
renamed file's identity on every re-stage (614).
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    db_path = tmp_path / "agent_io" / "test.db"
    backend = SQLiteBackend(str(db_path), "test_workflow")
    backend.initialize()
    yield backend
    backend.close()


class TestClaimingWithinOneBackend:
    def test_the_first_claim_succeeds(self, backend):
        assert backend.claim_source_guid_for_run("g1") is False

    def test_a_second_claim_of_the_same_guid_is_reported_taken(self, backend):
        backend.claim_source_guid_for_run("g1")
        assert backend.claim_source_guid_for_run("g1") is True

    def test_different_guids_do_not_collide(self, backend):
        assert backend.claim_source_guid_for_run("g1") is False
        assert backend.claim_source_guid_for_run("g2") is False


class TestClaimsDoNotPersist:
    def test_a_claim_is_not_written_to_source_data(self, backend):
        backend.claim_source_guid_for_run("g1")

        with backend._lock:
            cursor = backend.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM source_data")
            (count,) = cursor.fetchone()
        assert count == 0

    def test_a_fresh_backend_instance_does_not_see_a_prior_instance_claim(self, tmp_path):
        """A new process (a new backend instance over the same db file) starts
        with no memory of what an earlier run claimed — the guarantee that
        keeps a renamed or simply re-staged file from colliding with its own
        past self."""
        db_path = tmp_path / "agent_io" / "test.db"

        first = SQLiteBackend(str(db_path), "test_workflow")
        first.initialize()
        first.claim_source_guid_for_run("g1")
        first.close()

        second = SQLiteBackend(str(db_path), "test_workflow")
        second.initialize()
        try:
            assert second.claim_source_guid_for_run("g1") is False
        finally:
            second.close()
